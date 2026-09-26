# -*- coding: utf-8 -*-
"""推理：流程图里的「推理」盒子。

一次 /predict 做四件事：
    1. 取模型产物（registry）——没有就明确报错，提示先调 /train
    2. 校验输入（长度必须等于训练时的 input_len；**出现 NaN / Inf 直接拒收**）
    3. 按框架分流：tensorflow-keras → 类别+置信度；pytorch → 类别+置信度；adtk → 是否异常+异常占比
    4. 按外键顺序落库：InferenceTasks（挂 TrainingID 锚点）→ InferenceResults（每条样本一行）
       另外给每次调用留一条 ModelInvocations

输入校验这一条是刻意加严的：原数据管线会把越界切片补成整行 NaN（实测测试集里 10%），
那种样本喂进模型只会得到无意义的输出。与其静默产出垃圾，不如在入口就拒绝并说清原因。
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime
from pathlib import Path
import numpy as np
from . import datasets as ds
from . import tabular
from .config import config
from .db import DBError, database
from .figures import inference_figures
from .registry import load_artifact
class InvalidInput(ValueError):
    """输入不合法（长度不符、含 NaN/Inf、文件不可读等）——接口据此回 400。"""
# ------------------------------------------------------------------ 取输入
def _guard_path(raw_path: str) -> Path:
    """只允许读工作区（D:\\22project）内的文件，挡掉路径穿越。"""
    # ⚠️ 先归一化再解析：前端/脚本拼出来的是 Windows 风格的 `a\\b.csv`，
    #    在 Linux 上 `\\` 不是分隔符，直接 Path() 会得到"一个名字含反斜杠的文件"，
    #    于是明明存在的文件被报成"不存在"。详见 config.normalize_user_path 的说明。
    p = Path(config.normalize_user_path(raw_path))
    if not p.is_absolute():
        # 相对路径口径与 api.Train.post / _resolve_workspace_path 一致：先按工作区试，存在就用，
        # 否则再按项目目录试。两个基准都要试 —— /datasets 响应脱敏后前端拿到的是"相对工作区"
        # 的路径（如 testRestfulProject\1DCNN\0HP），只按 project_dir 拼会得到
        # testRestfulProject\testRestfulProject\1DCNN\0HP\... 从而误报 400。
        first = config.workspace_dir / p
        p = first if first.exists() else config.project_dir / p
    p = p.resolve()
    if config.workspace_dir.resolve() not in p.parents and p != config.workspace_dir.resolve():
        raise InvalidInput(f"出于安全考虑，只允许读取工作区内的文件：{config.workspace_dir}")
    if not p.is_file():
        raise InvalidInput(f"文件不存在：{p}")
    return p
def _read_signal(path: Path, column: str | None = None, sheet: str | int | None = None) -> tuple[np.ndarray, str]:
    """读一列信号。支持 .mat（CWRU 的 DE 通道）、.npy、以及表格文件（csv/txt/xlsx/xls）。"""
    suffix = path.suffix.lower()
    if suffix == ".mat":
        return ds.read_de_channel(path), "matlab"
    if suffix == ".npy":
        return np.asarray(np.load(path)).ravel().astype(float), "npy"
    if tabular.is_table(path):
        values = tabular.read_signal(path, column=column, sheet=sheet)
        return values, "tabular"
    raise InvalidInput(f"暂不支持的文件类型：{suffix}（支持 .mat / .npy / .csv / .txt / .xlsx / .xls）")
def _windows_from_signal(signal: np.ndarray, input_len: int, start_index: int = 0,
                         limit: int = 1) -> np.ndarray:
    """按**固定步长 = input_len**（即不重叠）切出待推理窗口，越界直接报错而不是补 NaN。

    与训练侧的差异（已知且有意保留）：训练按 `stride`（默认 150）**重叠**切窗、
    编号语义是"第几个训练窗"；这里按 input_len 不重叠切，编号是"从第 index 个窗起取 limit 个"。
    两侧窗口编号因此不能直接对齐，但对"看这段信号判成什么"这个用途没影响。
    """
    windows = []
    for i in range(start_index, start_index + limit):
        begin = i * input_len
        end = begin + input_len
        if end > signal.size:          # 宁可报错也不补 NaN：NaN 会一路传进模型，输出全是 nan
            raise InvalidInput(
                f"窗口 {i} 越界：需要信号长度 ≥ {end}，实际只有 {signal.size}。"
                f"（这正是原管线补 NaN 的地方，服务侧选择拒绝）")
        windows.append(signal[begin:end])
    return np.asarray(windows, dtype=float)
def _build_matrix(samples, path, input_len: int, index: int, limit: int,
                  column: str | None = None, sheet: str | int | None = None) -> tuple[np.ndarray, dict]:
    """把 samples / path 两种入参统一成 (n, input_len) 矩阵，并回带一份输入信息。

    samples 优先（浏览器/脚本直接送数组的场景）；否则按 path 读文件：
    路径先过 `_guard_path`（必须落在工作区内），再按后缀分流 .mat/.npy/表格。
    回带的 `info` 会写进 InferenceTasks 的 ResultSummary，用于事后追溯"这次喂的是哪个文件"。
    """
    info: dict = {"source": None}
    if samples is not None:
        arr = np.asarray(samples, dtype=float)
        if arr.ndim == 1:              # 一维 = 单个样本，补一维当成 (1, n)
            arr = arr.reshape(1, -1)
        if arr.ndim != 2:              # 三维及以上没有"每行一个样本"的语义，直接拒
            raise InvalidInput("samples 必须是二维数组（每行一个样本）或一维单样本")
        info["source"] = "inline_samples"
        return arr, info
    if not path:
        raise InvalidInput("必须提供 samples（内联数组）或 path（工作区内的 .mat/.csv/.npy/.xlsx）")
    file_path = _guard_path(path)
    signal, kind = _read_signal(file_path, column=column, sheet=sheet)
    info.update({"source": "path", "path": str(file_path), "format": kind,
                 "signal_points": int(signal.size), "window_index": index, "limit": limit,
                 "column": column, "sheet": sheet})
    return _windows_from_signal(signal, input_len, index, limit), info
def _validate(matrix: np.ndarray, input_len: int) -> None:
    """形状与数值的双重校验：长度不符、含 NaN/Inf、空样本三种情况都直接拒收。

    校验放在**标准化之前**，因为这几类问题都是输入侧的问题；
    标准化本身也可能算出 inf（scale 里有 0），那种情况由调用方自行留意。
    """
    if matrix.shape[1] != input_len:   # 长度必须与训练时的 input_len 完全一致，多一个点都不行
        raise InvalidInput(f"每个样本长度必须是 {input_len}，收到 {matrix.shape[1]}")
    if not np.all(np.isfinite(matrix)):
        # 只报前 5 行坏样本的行号，避免几百行 NaN 把报错信息撑爆
        bad = np.where(~np.isfinite(matrix).all(axis=1))[0].tolist()[:5]
        raise InvalidInput(f"样本里存在 NaN/Inf（行号 {bad} ...），拒绝推理。"
                           f"这类样本通常来自数据切片越界后的 NaN 填充。")
    if matrix.shape[0] == 0:           # 切窗后一个都没剩（例如 index 超出范围）
        raise InvalidInput("没有可推理的样本")
# ------------------------------------------------------------------ 三种框架
def _apply_scaler(artifact, matrix: np.ndarray) -> np.ndarray:
    """套用训练时保存的标准化参数。

    这一步不能省：模型是在 (x-μ)/σ 之后的分布上学的，若推理侧直接喂原始振动值，
    同一个模型会给出完全错误的类别（本服务第一次端到端验证时就踩了这个坑：
    测试集准确率 0.83 的模型，对原始信号窗口的预测全是错的）。
    """
    scaler_file = artifact.meta.get("scaler_file")
    # ⚠️ 下面两个 return 都是**静默跳过标准化**：meta 里没记 scaler_file（老产物/手工上传没带
    #    scaler.npz），或文件被删了。此时分类结果会系统性出错但接口不报错 ——
    #    换数据/换产物前，务必确认版本目录里 scaler.npz 还在。
    if not scaler_file:
        return matrix
    path = artifact.directory / scaler_file
    if not path.is_file():
        return matrix
    with np.load(path) as npz:          # scaler.npz 里就两个数组：训练集的均值与标准差
        mean, scale = npz["mean"], npz["scale"]
    return (matrix - mean) / scale      # 与训练时同一套 (x-μ)/σ，逐点对齐
def _predict_keras(artifact, matrix: np.ndarray, top_k: int) -> list[dict]:
    """tensorflow-keras 路线：喂 (n, length, 1)，输出 softmax 概率后取 top_k。"""
    import tensorflow.keras as keras
    model = keras.models.load_model(artifact.weights)   # .h5 与 .keras 都能读，所以这里无需分支
    scaled = _apply_scaler(artifact, matrix)            # 必须先标准化，原因见 _apply_scaler
    # 用「实际窗口长度」兜底：上传的模型可能没有 input_len，直接下标会 KeyError → 500
    length = int(artifact.meta.get("input_len") or matrix.shape[1])
    probs = model.predict(scaled.reshape(-1, length, 1), verbose=0)   # (n, length, 1)：通道在最后
    # 类别表缺失时退化成 class_0/class_1…（仍给出可读类别名，不至于整行空白）
    labels = artifact.meta.get("labels") or [f"class_{i}" for i in range(probs.shape[1])]
    return [_classification_row(i, probs[i], labels, top_k) for i in range(len(probs))]
def _torch_probs_from_callable(forward, scaled: np.ndarray, input_len: int) -> "np.ndarray":
    """把「可直接调用的 torch 模型」跑出概率矩阵 (n, num_classes)。

    自包含格式（torch.export / TorchScript）共用这一段：它们不需要任何架构代码，
    拿到就是可调用对象，差别只在"怎么拿到这个对象"。
    两处外部模型必定会遇到的不一致，这里都兜住：
      · **输入形状**：本项目的约定是 (n, 1, length)（通道在最前），但外部模型常见 (n, length)。
        依次试三种形状，能用哪种就用哪种；三种都不行就把三种的报错一起抛出去，便于定位。
      · **输出是 logits 还是概率**：本项目自己的模型前向返回 logits（softmax 在推理侧做），
        而别人导出的模型可能已经把 softmax 写进 forward 了。判据：若每行都在 [0,1]
        且行和≈1，就当概率直接用；否则当 logits 做 softmax。
        想固定下来就在产物 meta.json 里写 "output_activation": "none"（已是概率）或 "softmax"。
    """
    import torch
    n = scaled.shape[0]
    shapes = [(n, 1, input_len), (n, input_len), (n, input_len, 1)]
    errors = []
    out = None
    for shape in shapes:
        try:
            with torch.no_grad():
                out = forward(torch.tensor(scaled.reshape(*shape), dtype=torch.float32))
            break
        except Exception as exc:                       # noqa: BLE001
            errors.append(f"{shape}: {type(exc).__name__}: {str(exc)[:80]}")
    if out is None:
        raise InvalidInput("这个 pytorch 产物喂不进去：本平台按 (n, 1, length) / (n, length) / "
                           f"(n, length, 1) 三种形状都试过，全部失败 —— {'; '.join(errors)}")
    if isinstance(out, (tuple, list)):                 # 有的导出会返回 (logits, aux)
        out = out[0]
    probs = out.detach().cpu().numpy().astype(float)
    if probs.ndim == 1:                                # (n,) 当成单类，补成 (n,1)
        probs = probs.reshape(-1, 1)
    row_sum = probs.sum(axis=1)
    looks_like_probs = bool(np.all(probs >= 0) and np.all(probs <= 1) and np.allclose(row_sum, 1.0, atol=1e-3))
    if not looks_like_probs:
        e = np.exp(probs - probs.max(axis=1, keepdims=True))
        probs = e / e.sum(axis=1, keepdims=True)
    return probs
def _predict_exported(artifact, matrix: np.ndarray, top_k: int) -> list[dict]:
    """torch.export 产物（.pt2）：**自包含**，不需要任何架构代码 —— 外部 pytorch 模型的推荐入口。

    用户侧怎么产出（一行）：
        import torch; from torch.export import export, Dim
        ep = export(model.eval(), (torch.randn(2, 1, 848),), dynamic_shapes=({0: Dim("n")},))
        torch.export.save(ep, "model.pt2")
    ⚠️ 必须带 `dynamic_shapes`：否则导出时那个示例 batch 会被**烤死**，换个窗口数推理就报
       `Guard failed: x.size()[0] == 2`（实测踩过）。
    ⚠️ 输入长度会被固定成导出时的 length，这是符合本平台契约的 —— 推理永远用产物 meta 里的 input_len。
    """
    import torch
    model = torch.export.load(str(artifact.weights))
    return _exported_rows(artifact, matrix, top_k, model.module())
def _predict_torchscript(artifact, matrix: np.ndarray, top_k: int) -> list[dict]:
    """TorchScript 产物（torch.jit.trace/script + torch.jit.save）：同样自包含。

    ⚠️ torch 从 2.x 起明确警告：**Python 3.14+ 上 torch.jit 不受支持、可能失效**
       （本项目正是 3.14）。所以这条路留着是为了兼容已有的 TorchScript 文件，
       **新导出的模型建议用 torch.export（.pt2）**。
    """
    import torch
    model = torch.jit.load(str(artifact.weights), map_location="cpu")
    return _exported_rows(artifact, matrix, top_k, model)
def _exported_rows(artifact, matrix: np.ndarray, top_k: int, forward) -> list[dict]:
    """自包含 torch 模型的公共收尾：套 scaler → 前向 → 组行。"""
    input_len = int(artifact.meta.get("input_len") or matrix.shape[1])
    scaled = _apply_scaler(artifact, matrix)
    probs = _torch_probs_from_callable(forward, scaled, input_len)
    labels = artifact.meta.get("labels") or [f"class_{i}" for i in range(probs.shape[1])]
    return [_classification_row(i, probs[i], labels, top_k) for i in range(len(probs))]
def _predict_torch(artifact, matrix: np.ndarray, top_k: int) -> list[dict]:
    """**老式** pytorch 路线：按 meta 里的 num_classes/length 重建架构，再 load_state_dict。

    这条路只对"用本服务训练出来的" .pt 有效（脚本里的 build_model 必须存在、且结构同构）。
    ⚠️ 外部 pytorch 模型别走这里，请导出成自包含格式（.pt2 或 TorchScript）——
       走这条会因为键不匹配而失败。
    """
    import torch
    from .training import _import_project_module      # 懒导入，避免与 training 循环依赖
    # 复用训练侧同一个导入器：cwt_cnn 的模块名没法靠包路径导入，只能先补 sys.path 再 import
    mod = _import_project_module("cwt_cnn", "cwt_cnn_pytorch")
    input_len = int(artifact.meta.get("input_len") or matrix.shape[1])   # 缺 input_len 时按实际窗口长度
    # ⚠️ weights_only=True 是这条路唯一的"不执行上传者代码"闸门，别改回 False。
    #    实测我们自己的 payload {state_dict, length, num_classes} 在 True 下完全读得出来
    #    （int / dict / tensor 都在安全白名单里），原先写 False 的理由并不成立。
    try:
        payload = torch.load(artifact.weights, map_location="cpu", weights_only=True)
    except Exception as exc:
        # 读不了 = 包里带了自定义类。以前这会一路走到推理并**把上传者提供的代码跑起来**；
        # 现在明确拒绝，并给出可执行的出路（逃生舱仍是显式环境变量，不是默认行为）。
        if os.environ.get("MODEL_ALLOW_UNTRUSTED_PICKLE"):
            payload = torch.load(artifact.weights, map_location="cpu", weights_only=False)
        else:
            raise InvalidInput(
                f"这个 .pt 需要自定义类才能反序列化（{type(exc).__name__}: {str(exc)[:80]}）。"
                f"出于安全考虑本服务默认不会执行上传者提供的代码。两条出路："
                f"① 推荐 —— 导出成自包含格式：torch.export（.pt2）或 torch.jit.trace + torch.jit.save；"
                f"② 确认可信后设环境变量 MODEL_ALLOW_UNTRUSTED_PICKLE=1 再重启服务") from exc
    model = mod.build_model(num_classes=payload.get("num_classes") or artifact.meta.get("num_classes") or 10,
                           length=input_len)     # 结构必须与保存时同构，否则 load_state_dict 报键不匹配
    try:
        model.load_state_dict(payload["state_dict"])
    except Exception as exc:
        raise InvalidInput(
            f"这个 .pt 的 state_dict 与本项目的 cwt_cnn 架构不同构（{type(exc).__name__}: "
            f"{str(exc)[:120]}）。它是「只存权重、没有结构」的格式，推理时必须能重建出同一个网络；"
            f"外部模型请改用自包含格式：torch.export（.pt2）或 torch.jit.trace + torch.jit.save") from exc
    model.eval()                                 # 关掉 dropout / BN 的训练态行为
    scaled = _apply_scaler(artifact, matrix)
    x = torch.tensor(scaled.reshape(-1, 1, input_len), dtype=torch.float32)   # (n, 1, length)：通道在最前
    with torch.no_grad():                        # 推理不需要梯度，省内存也更快
        logits = model(x)
        probs = torch.softmax(logits, dim=1).numpy()     # logits → 概率，与 Keras 分支对齐
    labels = artifact.meta.get("labels") or [f"class_{i}" for i in range(probs.shape[1])]
    return [_classification_row(i, probs[i], labels, top_k) for i in range(len(probs))]
def _predict_adtk(artifact, matrix: np.ndarray, top_k: int) -> list[dict]:
    """adtk 路线：每个窗口算特征 → adtk 的 PCA 重构误差 → 与训练时标定的阈值比较。

    关键：`matrix` 的每一行是**一个窗口**（不是单个采样点）。adtk 的
    `PcaReconstructionError` 把 DataFrame 的**每一行**当成高维空间里的一个点，
    所以必须按行组装；训练侧共用同一套特征（`training.adtk_window_features`）避免走样。
    """
    import pickle
    import pandas as pd
    from .training import adtk_window_features          # 懒导入，避免与 training 循环依赖
    # 安全闸门：.pkl 是 pickle，反序列化 = 执行代码。上传接口刻意**不**反序列化上传的 .pkl，
    # 推理侧必须保持同一口径，否则等于给了"上传一个 pkl 就能在服务端执行代码"的入口。
    # 本机训练出来的产物 meta 里有 trusted=True；上传的一律 trusted=False。
    if artifact.meta.get("trusted", True) is False and not os.environ.get("MODEL_ALLOW_UNTRUSTED_PICKLE"):
        raise InvalidInput(
            f"产物 {artifact.meta.get('model') or artifact.name} 是**上传**的（不可信来源），"
            f"出于安全考虑不会反序列化它的 {Path(artifact.weights).name}；"
            f"要放行请设置环境变量 MODEL_ALLOW_UNTRUSTED_PICKLE=1 后重启服务")
    with open(artifact.weights, "rb") as fh:
        bundle = pickle.load(fh)
    # 判定产物格式：新格式必须同时带 feature_mode 与 transformer。
    # ⚠️ 这里**不再**保留"老格式还能跑"的兜底分支：老格式（点级 detect + 异常点占比阈值）
    #    在本服务里实测没有判别力（故障窗口的异常点占比反而低于正常基线，标定后全判正常），
    #    磁盘上唯一一份产物 adtk/v2 也已是新格式（feature_mode='stats' + PcaReconstructionError），
    #    那段代码事实上不可达。留着它的害处是：真有人塞进老 pkl 时，会按一套错误的阈值
    #    静默给出"正常/异常"，比直接报错危险得多 —— 所以改成明确拒收。
    if not (bundle.get("feature_mode") and bundle.get("transformer") is not None):
        raise InvalidInput(
            "这个 adtk 产物是老格式（点级 detect + 异常点占比），本服务已不再支持："
            "老格式实测没有判别力，请用当前版本重新训练 adtk 生成带 feature_mode/transformer 的产物")
    mode = str(bundle["feature_mode"])
    rate = float(bundle.get("sampling_rate") or 48000)
    features = matrix.astype(float) if mode == "raw" else np.asarray(
        [adtk_window_features(window, rate) for window in matrix])
    frame = pd.DataFrame(features, index=pd.date_range("2017-01-01", periods=features.shape[0], freq="s"))
    scores = np.asarray(bundle["transformer"].transform(frame), dtype=float).ravel()
    raw_threshold = bundle.get("threshold")
    if raw_threshold is None or float(raw_threshold) <= 0:      # 阈值缺失/为 0 → 会把所有窗口都判异常
        raise InvalidInput("产物里的 threshold 缺失或非法（<=0），请重新训练 adtk 生成完整产物")
    threshold = float(raw_threshold)
    base = float(bundle.get("score_median") or 0.0)
    rows = []
    for i, score in enumerate(scores):
        is_anomaly = bool(score > threshold)
        rows.append({
            "index": i,
            "is_anomaly": is_anomaly,
            "anomaly_score": round(float(score), 6),
            "predicted_class": 1 if is_anomaly else 0,
            "predicted_label": "异常" if is_anomaly else "正常",
            "predicted_category": "AnomalyDetection",
            "detail": {"detector": bundle.get("detector_name"),
                       "baseline": bundle.get("baseline_source"),
                       "feature_mode": mode,
                       "重构误差": round(float(score), 6),
                       "判定阈值": round(threshold, 6),
                       "正常分数中位": round(base, 6),
                       "相对正常倍数": round(float(score) / (base + 1e-12), 2)},
        })
    return rows
def _classification_row(i: int, prob_row: np.ndarray, labels: list, top_k: int) -> dict:
    """一行分类结果：取概率最高的类别，并附上前 top_k 的备选。"""
    order = np.argsort(prob_row)[::-1][:max(1, int(top_k))]     # 至少保留 1 个
    best = int(order[0])
    return {
        "index": i,
        "predicted_class": best,
        "predicted_label": labels[best] if best < len(labels) else f"class_{best}",
        "predicted_category": "Classification",
        "confidence": round(float(prob_row[best]), 6),
        "score": round(float(prob_row[best]), 6),
        "top_k": [{"class_id": int(c), "label": labels[c] if c < len(labels) else f"class_{c}",
                   "probability": round(float(prob_row[c]), 6)} for c in order],
        "detail": {"类别总数": len(labels), "第二名概率": round(float(prob_row[int(order[1])]), 6) if len(order) > 1 else None},
    }
_DISPATCH = {"tensorflow-keras": _predict_keras, "pytorch": _predict_torch,
             "pytorch-exported": _predict_exported, "pytorch-jit": _predict_torchscript,
             "adtk": _predict_adtk}
# ------------------------------------------------------------------ 落库
def _resolve_anchor(model_name: str, training_id: int | None) -> tuple[dict | None, int | None]:
    """确定 InferenceTasks 的外键锚点（TrainingID，NOT NULL）。

    两个来源：
      · 显式传了 `training_id` → 按 ID 查；**查不到直接报错**，不静默回退到"最近一次训练"
        （不然用户以为结果挂在指定的那次训练上，实际挂在别处）
      · 没传 → 取该模型**最近一次成功**的训练（`latest_training` 的 only_success 默认 True）：
        失败的训练没有可用权重，不能当锚点
    返回 (训练行, TrainingID)；返回的 ID 为 None 表示"没有可用的成功训练"。
    """
    from .training import db_model_name
    if training_id is not None:
        row = database.training_by_id(int(training_id))
        if row is None:
            raise DBError(f"TrainingID={training_id} 不存在")
        return row, int(training_id)
    row = database.latest_training(db_model_name(model_name))   # 默认只找 Status=成功 的行
    return row, (int(row["TrainingID"]) if row else None)
def _write_db(model_name: str, artifact, payload: dict, input_info: dict, predictions: list[dict],
              training_id: int | None, duration_ms: int, client_ip: str | None, request_params: dict,
              output_path: str | None = None) -> dict:
    """把一次推理写进三张表：InferenceTasks（1 行）+ InferenceResults（n 行）+ ModelInvocations（1 行）。

    这是"尽力而为"的写法：任何数据库异常都被收进返回值的 `written/error` 里，
    **不让推理请求因此失败**（推理本身已经算完了，结果也已经返回给调用方）。
    调用方/前端看 `db.written` 判断有没有落库，落库失败时 api 层还会补一个 `warning` 字段。
    """
    from .training import db_model_name
    try:
        # 外键锚点：InferenceTasks.TrainingID 是 NOT NULL，所以"这次推理基于哪一次训练"
        # 必须能查到 —— 拿不到成功训练记录就不写库并明确回报原因，绝不伪造一个 ID。
        # （_resolve_anchor 同时返回训练行与 TrainingID，这里只用得上 ID）
        _, anchor = _resolve_anchor(model_name, training_id)
        if anchor is None:
            return {"written": False, "dialect": database.dialect,
                    "error": f"库中没有 {model_name} 的成功训练记录，而 InferenceTasks.TrainingID 是 NOT NULL 外键；"
                             f"先调 /train 或显式传 training_id"}
        model_id = database.ensure_model(db_model_name(model_name))
        source_path = input_info.get("path")
        # 内联样本没有"数据集"这一概念，但 InferenceTasks.TargetDatasetID 是 NOT NULL，
        # 所以按模型登记一条 ADHOC 数据集，避免为了满足外键去伪造真实数据集。
        # 它是**复用**的（ensure_dataset 命中同名即返回），不会每次推理都新增一行。
        dataset_id = database.ensure_dataset(
            f"ADHOC-{model_name}", source=source_path or "内联数组(/predict samples)",
            sample_count=payload["count"], class_count=artifact.meta.get("num_classes"),
            data_path=source_path, description="推理时的临时输入登记")
        # 逐窗口组一行 InferenceResults。字段分三类：
        #   ① 分类模型共有：predicted_class / predicted_label / predicted_category / confidence / score
        #   ② 只有 adtk 才有：is_anomaly / anomaly_score（分类模型这两列落 NULL，反之亦然）
        #   ③ 溯源用：sample_index（窗口号）、actual_class（仅当输入是登记过的 CWRU 文件才填）
        rows = []
        for pred in predictions:
            # 先序列化再判断长度：直接按字符截（`[:500]`）会把 JSON 切成半截，落库就是坏数据
            snapshot = json.dumps({"top_k": pred.get("top_k", [])[:1]}, ensure_ascii=False)
            rows.append({
                "row_identifier": f"{Path(source_path).name if source_path else 'inline'}#{pred['index']}",
                "predicted_value": pred.get("confidence"),
                "anomaly_score": pred.get("anomaly_score"),
                "is_anomaly": pred.get("is_anomaly"),
                "predicted_category": pred.get("predicted_category"),
                "confidence": pred.get("confidence"),
                "feature_snapshot": snapshot if len(snapshot) <= 500 else json.dumps({"truncated": True}),
                "model_id": model_id,
                "sample_index": pred["index"],
                "predicted_class": pred.get("predicted_class"),
                "predicted_label": pred.get("predicted_label"),
                "score": pred.get("score"),
                "actual_class": pred.get("actual_class"),
                "detail": pred.get("detail"),
            })
        # 任务与结果**同一事务**提交：分两次提交会留下"有任务、没结果"的孤儿任务
        # （Status=成功、Progress=100，但明细点开是空的）
        task_id, written = database.insert_task_with_results({
            "training_id": anchor, "target_dataset_id": dataset_id,
            "task_name": f"predict-{model_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "task_type": artifact.meta.get("task", "classification"), "status": "成功",
            "inference_params": request_params,
            "result_summary": {"样本数": payload["count"], "模型": artifact.name,
                               "输入来源": input_info.get("source"), "锚点训练": anchor,
                               "预测分布": payload["summary"]},
            "model_id": model_id, "input_path": source_path, "output_path": output_path, "progress": 100,
            "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "completed": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, rows)
        database.insert_invocation(
            model_id=model_id, training_id=anchor, api_endpoint="/predict",
            request_params=request_params, response_result={"count": payload["count"], "summary": payload["summary"]},
            duration_ms=duration_ms, is_success=True, status_code=200,
            client_ip=client_ip, status="成功",
        )
        return {"written": True, "dialect": database.dialect, "InferenceTaskID": task_id,
                "results_written": written, "TrainingID": anchor, "DatasetID": dataset_id, "ModelID": model_id}
    except DBError as exc:
        return {"written": False, "dialect": database.dialect, "error": str(exc)}
    except Exception as exc:                                        # pragma: no cover
        return {"written": False, "dialect": database.dialect, "error": f"{type(exc).__name__}: {exc}"}
# ------------------------------------------------------------------ 统一入口
def predict(model: str | None = None, samples=None, path: str | None = None, index: int = 0,
            limit: int = 1, training_id: int | None = None,
            top_k: int = 3, write_db: bool = True, client_ip: str | None = None,
            column: str | None = None, sheet: str | int | None = None) -> dict:
    """推理入口：解析模型 → 取产物 → 切窗校验 → 分派引擎 → 落库，返回结果 + 落库回执。

    失败语义：输入非法抛 InvalidInput(→400)、产物缺失抛 FileNotFoundError(→409)，
    落库失败**不抛异常**而是在返回值里给 `db.written=False` + 原因（推理本身是成功的）。
    """
    from .training import normalize_model
    try:
        name = normalize_model(model)
    except ValueError:
        # 别名表里没有（1dcnn/cwt_cnn/adtk 之外的）名字 = 上传进来的模型，按原名当产物目录名用。
        # 这一步**不做白名单**是有意的：上传的模型必须能被推理；目录安全由 registry 的
        # `_model_dir()` 净化保证（拒绝路径分隔符与 ".."），不在这里重复拦。
        name = (model or "").strip()
        if not name:
            raise InvalidInput("必须提供 model")
    started = time.time()
    # 取产物：一个模型只有一个产物，没有版本可选。目录/权重缺失会抛 FileNotFoundError，
    # 由 api 层映射成 409 + "先调 /train"，而不是 500。
    artifact = load_artifact(name)
    # 切窗长度以产物里的 input_len 为准（训练多长、推理就必须多长）；
    # 早期上传的产物可能没写这个字段，退回 784 —— 下面 reshape 用的是同一个值，两处必须一致。
    input_len = int(artifact.meta.get("input_len") or 784)
    # 两种输入统一成 (n, input_len) 矩阵：samples（内联数组）优先，否则按 path 读文件再切窗
    matrix, input_info = _build_matrix(samples, path, input_len, int(index), int(limit),
                                       column=column, sheet=sheet)
    # 校验：列数必须等于 input_len；出现 NaN/Inf 一律拒收（否则会在网络里传播成 nan 结果）
    _validate(matrix, input_len)
    # 按**产物里记录的 framework** 分派引擎，而不是按模型名猜：
    #   tensorflow-keras → model.h5/.keras + scaler.npz → 类别 + 置信度 + top_k
    #   pytorch          → model.pt        + scaler.npz → 同上
    #   adtk             → detector.pkl（无监督）       → 是否异常 + 异常分数
    handler = _DISPATCH.get(artifact.framework)
    if handler is None:
        raise InvalidInput(f"产物框架 {artifact.framework} 暂不支持推理")
    predictions = handler(artifact, matrix, int(top_k))
    # 若输入来自登记过的数据集文件，顺便补上真实类别，便于直接看对错
    labels = artifact.meta.get("labels") or []
    actual = None
    if input_info.get("path"):
        stem = Path(input_info["path"]).name
        for row in ds.CWRU_0HP_CLASSES:
            if row[0] == stem:
                actual = row[1]
                break
    if actual is not None:
        for pred in predictions:
            pred["actual_class"] = actual
    if artifact.meta.get("task") == "classification":
        from collections import Counter
        counter = Counter(p["predicted_label"] for p in predictions)
        summary = dict(counter)
        if actual is not None:
            summary = {"真实类别": labels[actual] if actual < len(labels) else actual,
                       "预测": summary,
                       "是否全部命中": all(p["predicted_class"] == actual for p in predictions)}
    else:
        flagged = sum(1 for p in predictions if p.get("is_anomaly"))
        summary = {"异常样本": flagged, "正常样本": len(predictions) - flagged}
    payload = {
        "model": name,
        "framework": artifact.framework,
        "task": artifact.meta.get("task"),
        "input_len": input_len,
        "count": len(predictions),
        "input": input_info,
        "predictions": predictions,
        "summary": summary,
    }
    # ---- 出图：预测分布 + 窗口波形（失败不影响推理结果）----
    figure_result = inference_figures(name, payload, matrix)
    payload["figures"] = figure_result["figures"]
    payload["figures_dir"] = figure_result["dir"]
    if figure_result.get("error"):
        payload["figures_error"] = figure_result["error"]
    if write_db:
        payload["db"] = _write_db(name, artifact, payload, input_info, predictions, training_id,
                                  int((time.time() - started) * 1000), client_ip,
                                  {"model": name, "path": path,
                                   "samples": f"{matrix.shape[0]}x{matrix.shape[1]}" if samples is not None else None,
                                   "index": index, "limit": limit},
                                  output_path=figure_result["dir"])
    return payload

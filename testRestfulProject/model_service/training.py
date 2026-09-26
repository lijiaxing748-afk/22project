# -*- coding: utf-8 -*-
"""训练编排：算法模型1(1DCNN) / 算法模型2(cwt_cnn) / 算法模型3(adtk)。

设计原则：
  * **复用**原有代码里的模型结构与超参默认值，不另写一份网络（1DCNN 的 `mymodel()`、
    cwt_cnn 的 `MyModel` 都是直接 import 过来用），避免出现"两份实现逐渐跑偏"。
  * 框架（tensorflow / torch）**延迟导入**：Flask 启动时不加载几百 MB 的 TF，
    只有真的调 /train 才 import。
  * 训练完必须落盘（registry）+ 写库（Trainings），并把两边 id 回报给调用方。

写库顺序（外键依赖）：Datasets → Models → Trainings。
"""
from __future__ import annotations
import contextlib
import importlib
import json
import random
import sys
import traceback
from datetime import datetime
from pathlib import Path
import numpy as np
from . import datasets as ds
from . import tabular
from .config import config
from .db import DBError, database
from .figures import training_figures
from .registry import save_artifact
# 别名表：把用户可能写的各种叫法（英文缩写 / 中文「算法模型N」/ 框架名）统一落到同一个**内部键**上。
# 内部键同时是 data/models/<键>/ 的目录名与 _TRAINERS 的字典键，所以这张表的**值不能随便改**。
# ⚠️ 这里就是"模型名三套写法"的源头：接口别名 →(本表) 内部键 →(MODEL_META) 库表 Models 里的名字。
#    新增一个模型要同时改三处（ALIASES / MODEL_META / _TRAINERS），漏一处就变成"别名认得、但查不到库名"。
ALIASES = {
    "1dcnn": "1dcnn", "1d-cnn": "1dcnn", "cnn": "1dcnn", "算法模型1": "1dcnn", "模型1": "1dcnn",
    "cwt_cnn": "cwt_cnn", "cwt": "cwt_cnn", "pytorch": "cwt_cnn", "算法模型2": "cwt_cnn", "模型2": "cwt_cnn",
    "adtk": "adtk", "pcaad": "adtk", "异常检测": "adtk", "算法模型3": "adtk", "模型3": "adtk",
}
# 内部键 → 在 Models 表里的登记信息（db_name 与 sql/schema_mysql.sql 的种子数据保持一致）。
# db_name 是这个模型在库里的**正式名字**，description/type 是首次登记时写进去的元数据；
# type 只有 Classification / AnomalyDetection 两种取值（对应 schema 里的枚举），
# 训练落库时写进 Models.ModelType，api 也把整张表当 known_models 发给前端（推理分派不看这里）。
# ⚠️ db_name 必须与种子数据逐字一致（1DCNN 是全大写），否则库里会多出一个"看着同名、其实另一行"的模型。
MODEL_META = {
    "1dcnn": {"db_name": "1DCNN",
              "description": "一维卷积神经网络，CWRU 轴承振动信号 10 类故障分类。", "type": "Classification"},
    "cwt_cnn": {"db_name": "cwt_cnn",
                "description": "与 1DCNN 同任务的 PyTorch 实现，输出混淆矩阵。", "type": "Classification"},
    "adtk": {"db_name": "adtk",
             "description": "时序异常检测库（无监督），以正常轴承信号为基线做 PcaAD 重构误差检测。", "type": "AnomalyDetection"},
}
def db_model_name(name: str) -> str:
    """内部键（1dcnn）→ 库表 Models 里的名字（1DCNN，与 schema 种子数据一致）。

    为什么中间要多这一层换算：内部键是服务自己用的短名、还要当目录名，而库名是 sql/schema_mysql.sql
    种子数据定下的既有写法，两边都不宜为了对齐而改动，所以统一收在这个函数里换算。
    认不出的键**原样返回**：上传/自定义模型的名字不在别名表里，本来就该直接落库。
    ⚠️ 这是三套写法的第二跳：接口别名 --normalize_model--> 内部键 --db_model_name--> 库名；
    任何要走库的入口都必须跳完这两跳，否则就会出现"库里有行、但按内部键查不到"。
    """
    return MODEL_META.get(name, {}).get("db_name", name)
def normalize_model(name: str | None, default: str = "1dcnn") -> str:
    """把用户写的模型名（别名 / 大小写 / 中文）规范成内部键；不认识就抛 ValueError。

    先 strip().lower() 再查表，所以 'CWT_CNN'、' CNN ' 这类写法都能认出来。
    不给 name 时返回 default（/train 不指定模型就训 1dcnn，是既定默认行为）。
    ⚠️ 认不出来时直接抛 ValueError，**不退回默认值**——静默换成另一个模型去训练，用户从返回里看不出来。
    """
    if not name:
        return default
    key = str(name).strip().lower()
    if key not in ALIASES:
        raise ValueError(f"未知模型 {name!r}，可用：1dcnn / cwt_cnn / adtk")
    return ALIASES[key]
def _seed_everything(seed: int) -> None:
    """尽力而为的随机源对齐：python random 与 numpy 立刻设，TF / torch 只在**已导入**时才设。

    为什么要加"已导入"这个条件：本模块要求框架延迟导入（Flask 启动不许加载几百 MB 的 TF），
    为了设种子去 import tensorflow 等于把这条原则废掉；代价是"框架尚未导入就调用 = 那次没设上种子"，
    所以调用点都排在框架 import 之后（如 _train_cwt_cnn 在 import torch 之后、build_model 之前）。
    TF / torch 的调用都套了 suppress(Exception)：不同版本的 API 差异不该让训练整体崩掉。

    ⚠️ **没覆盖到**的随机源（要严格复现得自己补）：
      * PYTHONHASHSEED —— 必须在进程启动前由环境变量给定，运行时改不了，
        所以同一进程内 dict/set 的遍历顺序仍可能和别次不同；
      * Keras 自己那套随机源 —— 这里只设了 tf.random.set_seed，没调 keras.utils.set_random_seed；
        Keras 3（TF ≥ 2.16 默认自带）的 dropout / 权重初始化用的是它自己的生成器，不受 tf.random 管
        （Keras 2 老版本上 tf.random.set_seed 还能兜住，所以这条**随 TF 版本而变**，别当成永远成立）；
      * torch 的 cudnn 确定性 —— 只 manual_seed，没有 use_deterministic_algorithms()、
        也没关 cudnn.benchmark，GPU 上仍会非确定（本项目在 CPU 上跑，影响有限）。
    """
    random.seed(seed)
    np.random.seed(seed)
    if "tensorflow" in sys.modules:
        with contextlib.suppress(Exception):
            sys.modules["tensorflow"].random.set_seed(seed)
    if "torch" in sys.modules:
        with contextlib.suppress(Exception):
            sys.modules["torch"].manual_seed(seed)
def _log_path(model: str) -> Path:
    """这次训练的输出文件名（起止时间靠文件名区分，内容由 train() 重定向 stdout 写入）。

    ⚠️ 时间戳只精确到**秒**：同一秒内对同一个模型连开两次训练会算出同一个名字，
    后一次会把前一次的日志覆盖掉——排查"上一次为什么失败"时就只剩这一次的内容了。
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.log_dir / f"train-{model}-{stamp}.log"
def _import_project_module(dir_name: str, module_name: str):
    """把项目子目录塞进 sys.path 后导入模块。

    1DCNN.py 的文件名以数字开头，没法用 `import` 语句，只能走 importlib（这也是必须走 importlib 的原因）。
    插到 sys.path[0] 是为了让子目录里的模块名优先命中本项目的文件；
    ⚠️ 这是**进程级全局副作用**且只增不减：导入过的目录会一直留在 sys.path 里，
    子目录若有同名模块，后一次导入会直接命中 sys.modules 的缓存，拿到的是先导入的那个对象。
    """
    d = str(config.project_dir / dir_name)
    if d not in sys.path:
        sys.path.insert(0, d)
    return importlib.import_module(module_name)
# --------------------------------------------------------------- 数据源选择
def resolve_source(opts: dict) -> tuple[str, Path, str]:
    """决定这次训练用哪个数据源：返回 (登记名, 目录, 类型)。

    类型 `matlab` = CWRU 的 .mat（取 DE 通道）；`tabular` = Excel/CSV 表格
    （一个文件一个类别，文件名即标签，信号列可显式指定 signal_column）。
    未显式给 dataset_type 时按目录里有什么文件自动判断。
    """
    # ① 目录从哪来：显式 dataset_dir 优先（相对路径按 project_dir 拼，例如 "1DCNN/0HP"），
    #    没给就用内置的 CWRU-0HP。目录不存在就直接报错，不做"退回到默认目录"这种事。
    raw_dir = opts.get("dataset_dir")
    if raw_dir:
        # 归一化 Windows 分隔符：前端给的是 "1DCNN\\0HP" 这种写法，Linux 上不处理会找不到目录。
        directory = Path(config.normalize_user_path(raw_dir))
        if not directory.is_absolute():
            directory = config.project_dir / directory
    else:
        directory = config.dataset_dirs["CWRU-0HP"]
    if not directory.is_dir():
        raise FileNotFoundError(f"数据集目录不存在：{directory}")
    # ② 类型怎么定：显式 dataset_type 最优先；没给就"看目录里有什么"——
    #    ⚠️ 判定顺序是**先表格、后 .mat**：一个目录里同时有两种文件时会走表格路径，
    #    .mat 被静默忽略（往 1DCNN/0HP 里丢个 csv 就会踩到），所以两种数据源建议分目录放。
    kind = (opts.get("dataset_type") or "").lower()
    if kind not in ("matlab", "tabular"):
        if tabular.has_tables(directory):
            kind = "tabular"
        elif any(directory.glob("*.mat")):
            kind = "matlab"
        else:
            raise FileNotFoundError(f"{directory} 里既没有 .mat 也没有表格文件（csv/xlsx/xls）")
    # ③ 登记名（会写进 Datasets 表）：显式 dataset 优先，否则取目录名；内置目录用固定名，
    #    表格源补个 "(表格)" 后缀，方便在「数据集管理」页一眼区分两种来源
    name = opts.get("dataset") or (directory.name if raw_dir else "CWRU-0HP")
    if kind == "tabular" and not raw_dir:
        name = f"{name}(表格)"
    return name, directory, kind
def load_dataset(opts: dict, length: int, number: int, stride: int, rate: list) -> tuple[str, Path, str, dict]:
    """按数据源类型加载并切窗，两个数据源共用同一套切窗/标准化/划分。"""
    name, directory, kind = resolve_source(opts)
    # 两个数据源**共用**的切窗/标准化/划分参数——放在这里统一，等于保证"同一个模型换个
    # 数据源"时口径一致（rate 决定 train/valid/test 比例，seed 决定划分可复现）。
    # 两个"复刻旧脚本"的开关都在这里透传：
    #   strict=False   —— 越界窗口不跳过（本服务已统一为跳过，见 datasets._slice_windows）
    #   legacy_scaler  —— 标准化参数用"训练+测试一起 fit"（有统计量泄漏，只为复刻旧结果）
    common = dict(length=length, number=number, stride=stride, rate=rate,
                  normal=bool(opts.get("normal", True)), seed=int(opts.get("seed", 42)),
                  strict=bool(opts.get("strict", True)),
                  legacy_scaler=bool(opts.get("legacy_scaler", False)))
    if kind == "tabular":
        # 表格源多两个参数：signal_column（表内指定哪一列当振动信号）、sheet（xlsx 的工作表名）
        data = tabular.load_windows(directory, column=opts.get("signal_column"),
                                    sheet=opts.get("sheet"), **common)
    else:
        data = ds.load_windows(directory, **common)
    return name, directory, kind, data
# ============================================================ 算法模型1：1DCNN
def _train_1dcnn(opts: dict) -> dict:
    """按原脚本的网络结构训一个 TensorFlow/Keras 1DCNN。

    返回的 dict 是**训练结果描述**（指标、超参、类别表、saver 回调），不含模型对象；
    真正的落盘由 train() 拿 saver 去执行。这样落盘失败/成功都能统一处理。
    """
    length = int(opts.get("length", 784))
    number = int(opts.get("number", 600))
    stride = int(opts.get("stride", 150))
    rate = list(opts.get("rate") or [0.7, 0.15, 0.15])
    epochs = int(opts.get("epochs", 10))
    batch_size = int(opts.get("batch_size", 128))
    seed = int(opts.get("seed", 42))
    dataset_name, dataset_dir, dataset_kind, data = load_dataset(opts, length, number, stride, rate)
    mod = _import_project_module("1DCNN", "1DCNN")      # 复用原脚本的网络结构（同时把 TF 导进来）
    import tensorflow.keras as keras
    _seed_everything(seed)
    # 三个数据集从 (n, length) 变成 (n, length, 1)：Conv1D 要求最后一维是通道数，
    # 而振动信号只有 1 个通道。astype("float32") 与 Keras 默认精度对齐（用 float64 会慢近一倍）。
    x_train = data["X_train"].reshape(-1, length, 1).astype("float32")
    x_valid = data["X_valid"].reshape(-1, length, 1).astype("float32")
    x_test = data["X_test"].reshape(-1, length, 1).astype("float32")
    # 原脚本的网络输出层是硬编码的 Dense(10)（`1DCNN/1DCNN.py`），先挡住"类别数 > 10"，
    # 否则会训练到一半抛 "label value ... outside the valid range of [0, 10)" —— 那种报错
    # 完全看不出根因是网络结构写死的。类别数 < 10 可以正常跑（多出来的输出单元用不到）。
    if len(data["labels"]) > 10:
        raise ValueError(f"1DCNN 的输出层在原脚本里写死了 10 类（Dense(10)），"
                         f"而当前数据集有 {len(data['labels'])} 类；请改用 cwt_cnn，"
                         f"或把 1DCNN/1DCNN.py 的输出层改成按类别数动态生成")
    # 网络结构**直接复用原项目脚本**（importlib 导入 mod.mymodel），保证与既有实验结果同源；
    # 代价是它把输出层写死 10 类，所以上面那道守卫不能删。
    model = mod.mymodel(x_train)
    # 多分类标配：Adam + 稀疏类别交叉熵（标签是 0..9 的整数下标，不需要先做 one-hot）
    model.compile(optimizer=keras.optimizers.Adam(),
                  loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    # 训练：verbose=1 的进度条会写进本次的日志文件；validation_data 用切出来的 valid 集
    history = model.fit(x_train, data["y_train"], batch_size=batch_size, epochs=epochs,
                        verbose=1, validation_data=(x_valid, data["y_valid"]))
    # 评估用**测试集**（训练与验证都没碰过），结果记进 meta.metrics.test_accuracy/test_loss
    scores = model.evaluate(x_test, data["y_test"], verbose=0)
    y_pred = np.argmax(model.predict(x_test, verbose=0), axis=1)   # 取最大概率的下标当预测类别
    from sklearn.metrics import classification_report, confusion_matrix
    report = classification_report(data["y_test"], y_pred, digits=4, zero_division=0)
    per_class = classification_report(data["y_test"], y_pred, digits=4, zero_division=0, output_dict=True)
    confusion = confusion_matrix(data["y_test"], y_pred).tolist()   # 出混淆矩阵图用
    # 某类"测试窗口为 0"时必须显式回报：例如 IR014 只有 63788 点、180 个测试窗全被跳过，
    # accuracy 就只在剩下的类上算 —— 不报出来，指标就是静默虚高的。
    tested = set(np.asarray(data["y_test"]).tolist())
    untested_labels = [label for index, label in enumerate(data["labels"]) if index not in tested]
    def saver(target: Path) -> Path:
        """优先存 Keras 原生 .keras（zip）；若环境禁止在临时子目录里写文件导致
        PermissionError（受限沙箱常见），自动回退到 h5py 直写的 .h5。两种格式
        keras.models.load_model() 都能读，推理侧无需分支。

        注意：失败的 .keras 保存会留下「只有 config.json、没有权重」的半成品 zip，
        必须先删掉，否则它会被后续的权重查找误命中。
        """
        if data["scaler"] is not None:
            np.savez(target / "scaler.npz", mean=data["scaler"]["mean"], scale=data["scaler"]["scale"])
        path = target / "model.keras"
        try:
            model.save(path)
            return path
        except PermissionError:
            path.unlink(missing_ok=True)
            legacy = target / "model.h5"
            model.save(legacy)
            return legacy
    return {
        "framework": "tensorflow-keras",
        "task": "classification",
        "input_len": length,
        "num_classes": len(data["labels"]),
        "labels": data["labels"],
        "dataset_name": dataset_name,
        "dataset_path": str(dataset_dir),
        "dataset_stats": data["stats"],
        "params": {"epochs": epochs, "batch_size": batch_size, "length": length, "number": number,
                   "stride": stride, "rate": rate, "seed": seed,
                   "dataset_type": dataset_kind, "signal_column": opts.get("signal_column"),
                   "strict": bool(opts.get("strict", True)),
                   "legacy_scaler": bool(opts.get("legacy_scaler", False))},
        "metrics": {
            "test_accuracy": round(float(scores[1]), 6),
            "test_loss": round(float(scores[0]), 6),
            "val_accuracy": round(float(history.history["val_accuracy"][-1]), 6),
            "val_loss": round(float(history.history["val_loss"][-1]), 6),
            "history": {k: [round(float(v), 6) for v in vs] for k, vs in history.history.items()},
            "classification_report": report,
            "untested_labels": untested_labels,
            "note": (f"以下类别没有任何测试样本，未参与测试指标计算：{untested_labels}"
                     if untested_labels else None),
        },
        "per_class": {k: v for k, v in per_class.items() if k.isdigit()},
        "confusion": confusion,
        "scaler_file": "scaler.npz" if data["scaler"] is not None else None,
        "saver": saver,
    }
# ========================================================= 算法模型2：cwt_cnn
def _train_cwt_cnn(opts: dict) -> dict:
    """与 1DCNN 同任务的 PyTorch 实现，额外产出混淆矩阵所需的原始预测。

    网络结构与训练循环都来自 cwt_cnn/cwt_cnn_pytorch.py（build_model/train_model/evaluate），
    这里只负责把数据切窗、送进设备、收集指标。
    """
    # 超参默认值与 1DCNN 不同：number 只取 300（1DCNN 是 600），因为这边是**全批量**训练，
    # 一次把全部训练窗送进网络，窗数翻倍内存也翻倍；rate 也更偏向训练集（0.5/0.25/0.25）。
    length = int(opts.get("length", 784))
    number = int(opts.get("number", 300))
    stride = int(opts.get("stride", 150))
    rate = list(opts.get("rate") or [0.5, 0.25, 0.25])
    epochs = int(opts.get("epochs", 50))
    lr = float(opts.get("lr", 1e-3))
    seed = int(opts.get("seed", 42))
    # 数据源解析与切窗复用同一套（matlab/表格都支持），返回的 data 里已经切好 train/valid/test
    dataset_name, dataset_dir, dataset_kind, data = load_dataset(opts, length, number, stride, rate)
    mod = _import_project_module("cwt_cnn", "cwt_cnn_pytorch")   # 复用原项目的网络与训练循环
    import torch
    _seed_everything(seed)          # 必须在 build_model 之前调用，否则权重初值不可复现
    # 设备：有 GPU 就用（本项目在 CPU 上跑，50 轮约 25 秒）
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # ⚠️ 张量形状与 1DCNN **相反**：PyTorch 的 Conv1d 是"通道在前"，
    #    所以是 (n, 1, length) 而不是 Keras 的 (n, length, 1)。写反了能跑但准确率会崩。
    x_train = torch.tensor(data["X_train"].reshape(-1, 1, length), dtype=torch.float32).to(device)
    y_train = torch.tensor(data["y_train"].astype(np.int64), dtype=torch.long).to(device)
    x_test = torch.tensor(data["X_test"].reshape(-1, 1, length), dtype=torch.float32).to(device)
    y_test = torch.tensor(data["y_test"].astype(np.int64), dtype=torch.long).to(device)
    # 模型结构与训练循环都在原脚本里（build_model / train_model / evaluate），本函数只做编排；
    # 类别数是**动态传入**的（不像 1DCNN 那样写死 10），所以表格数据集类别数变化也能用。
    model = mod.build_model(num_classes=len(data["labels"]), length=length).to(device)
    # train_model 内部是"每个 epoch 一次全量梯度"（等价于 batch_size = 整批），
    # 所以 params 里 batch_size 记 0 —— 它是个约定值，表示"没用小批量"
    losses = mod.train_model(model, x_train, y_train, epochs=epochs, lr=lr, device=device)
    # 注意 X_valid 在这里**没有被使用**：它既不参与训练也不参与早停，
    # 因此 metrics 里 val_accuracy/val_loss 恒为 None（前端那两栏会显示"—"）
    accuracy, report = mod.evaluate(model, x_test, y_test, device=device)
    # 出一张混淆矩阵图需要原始预测；evaluate 只回文本报告，这里再取一次预测
    from sklearn.metrics import classification_report, confusion_matrix
    y_true_np = y_test.cpu().numpy()
    y_pred_np = mod.predict(model, x_test, device=device)
    per_class = classification_report(y_true_np, y_pred_np, digits=4, zero_division=0, output_dict=True)
    confusion = confusion_matrix(y_true_np, y_pred_np).tolist()
    def saver(target: Path) -> Path:
        """落盘回调（由 registry.save_artifact 调用）：先存标准化参数，再存网络权重。

        scaler 必须和权重放在同一个目录：推理侧要靠它把原始振动值换算到训练时的分布。
        """
        if data["scaler"] is not None:
            np.savez(target / "scaler.npz", mean=data["scaler"]["mean"], scale=data["scaler"]["scale"])
        path = target / "model.pt"
        torch.save({"state_dict": model.state_dict(), "length": length,
                    "num_classes": len(data["labels"])}, path)
        return path
    return {
        "framework": "pytorch",
        "task": "classification",
        "input_len": length,
        "num_classes": len(data["labels"]),
        "labels": data["labels"],
        "dataset_name": dataset_name,
        "dataset_path": str(dataset_dir),
        "dataset_stats": data["stats"],
        "params": {"epochs": epochs, "batch_size": 0, "length": length, "number": number,
                   "stride": stride, "rate": rate, "lr": lr, "seed": seed, "device": str(device),
                   "dataset_type": dataset_kind, "signal_column": opts.get("signal_column")},
        "metrics": {
            "test_accuracy": round(float(accuracy), 6),
            "test_loss": round(float(losses[-1]), 6),
            "val_accuracy": None,
            "val_loss": None,
            "history": {"loss": [round(float(v), 6) for v in losses]},
            "classification_report": report,
        },
        "per_class": {k: v for k, v in per_class.items() if k.isdigit()},
        "confusion": confusion,
        "scaler_file": "scaler.npz" if data["scaler"] is not None else None,
        "saver": saver,
    }
# =========================================================== 算法模型3：adtk
def adtk_slice_windows(signal: np.ndarray, length: int, number: int, stride: int) -> np.ndarray:
    """把一段长信号切成 (number, length) 的窗口矩阵（不够一个窗就停，不补零）。

    返回矩阵**行 = 一个窗口**，这正是 adtk 需要的形状：PcaAD 会把 DataFrame 的每一行当一个高维样本点，
    所以这里必须"一行一个窗"，而不是"一行一个采样点"（后者会让 PCA 退化成 1 维，见 _train_adtk 的说明）。
    ⚠️ 两个刻意取舍：窗不够长就 break（**不补零**——补零会造出虚假的"平稳段"，把正常基线算歪）；
    一个窗都切不出来时返回 shape=(0, length) 而非空列表，好让调用方直接看 shape[0] 判数量、不炸。
    stride < length 时相邻窗重叠、信息有重复，默认 stride=length（不重叠）。
    """
    windows = []
    for index in range(int(number)):
        start = index * int(stride)
        window = signal[start:start + int(length)]
        if window.size < int(length):
            break
        windows.append(np.asarray(window, dtype=float))
    return np.asarray(windows) if windows else np.zeros((0, int(length)), dtype=float)
def adtk_window_features(window: np.ndarray, sampling_rate: float, bands: int = 6) -> np.ndarray:
    """一个窗口 → 特征向量：时域 4 个统计量 + `bands` 个频带能量比。

    频带按 0..fs/2 等分（rfft 只取正频率，上界正好是奈奎斯特频率，换采样率也能用）；
    用**能量占比**而不是绝对能量，因为真正区分轴承故障的是"能量往高频搬"，与整体幅值大小无关。
    先减均值再算：不去直流的话，0Hz 分量会吃掉绝大部分能量，所有频带占比被压扁到看不出差别。
    ⚠️ 每个分母都加 1e-12：常值/掉线信号（幅值恒为 0）原本会算出 0/0=nan，nan 喂进 PCA 会污染整个拟合；
    加 eps 后至少得到一个有限值。最后一维是峰值因子 peak/rms —— 它对冲击（点蚀的典型表现）比 RMS 敏感。
    """
    x = np.asarray(window, dtype=float)
    x = x - x.mean()
    power = float(np.mean(x ** 2)) + 1e-12
    rms = float(np.sqrt(power))
    peak = float(np.max(np.abs(x))) + 1e-12
    kurtosis = float(np.mean(x ** 4) / power ** 2)
    skewness = float(np.mean(x ** 3) / power ** 1.5)
    spectrum = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(x.size, 1.0 / float(sampling_rate))
    edges = np.linspace(0.0, float(sampling_rate) / 2.0, int(bands) + 1)
    energy = np.array([spectrum[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in zip(edges[:-1], edges[1:])])
    energy = energy / (energy.sum() + 1e-12)
    return np.concatenate([[rms, kurtosis, skewness, peak / rms], energy])
def _train_adtk(opts: dict) -> dict:
    """无监督路线：把「正常」信号切成窗口，**窗口当样本**，fit adtk 的 PcaAD。

    踩过的坑（务必记住）：`PcaAD` 内部就是 `PcaReconstructionError(k)` + `InterQuartileRangeAD(c)`，
    它把 **DataFrame 的每一行**当成高维空间里的一个点。所以必须喂「窗口 × 特征」矩阵（行 = 窗口）。
    老代码喂的是「采样点 × 1 列」，PCA 退化成 1 维、重构误差恒为 0，
    判出来的"异常"跟故障毫无关系（实测故障窗口 0.026~0.103 < 正常 0.137，方向都是反的）。
    改成行 = 窗口之后：连续重构误差 AUC = 1.0000，adtk 自带的 IQR 判据就能做到 0% 误报 / 100% 命中。
    """
    import pickle
    import pandas as pd
    adtk_detector = importlib.import_module("adtk.detector")
    adtk_transformer = importlib.import_module("adtk.transformer")
    k = int(opts.get("k", 4))
    c = float(opts.get("c", 5.0))
    detector_name = str(opts.get("detector", "PcaAD"))
    feature_mode = str(opts.get("feature_mode", "stats")).lower()
    sampling_rate = float(opts.get("sampling_rate", 48000))
    length = int(opts.get("length", 784))
    number = int(opts.get("number", 600))
    stride = int(opts.get("stride", length))
    quantile = float(opts.get("threshold_quantile", 0.995))
    factor = float(opts.get("factor", 1.0))
    baseline_file = str(opts.get("baseline_file") or "normal_0_97.mat")
    if Path(baseline_file).name != baseline_file:        # 不许带路径分隔符，否则能读工作区外的文件
        raise ValueError(f"baseline_file 只能是文件名（不能带路径）：{baseline_file!r}")
    # 支持 dataset_dir：以前这里硬用 CWRU-0HP，用户在前端选了别的数据集也会被静默忽略
    dataset_dir = Path(opts.get("dataset_dir") or config.dataset_dirs["CWRU-0HP"])
    if dataset_dir.is_dir() and (dataset_dir / baseline_file).is_file():
        signal = ds.read_de_channel(dataset_dir / baseline_file)
        baseline_source = str(dataset_dir / baseline_file)
        dataset_name = opts.get("dataset") or "CWRU-0HP(normal基线)"
        dataset_path = str(dataset_dir)
    else:
        # 以前这里会"静默退回 adtk 自带的 cpu.csv"，结果是拿 CPU 电流数据训出一个
        # 号称轴承异常的模型；而且 cpu.csv 只有 1000 点、默认窗长 784 → 必然报"窗口太少"。
        # 现在直接报错，把数据来源问题暴露出来。
        raise ValueError(f"找不到基线文件 {dataset_dir / baseline_file}；"
                         f"adtk 需要一个「正常」样本文件当基线（默认 normal_0_97.mat）")
    signal = np.asarray(signal, dtype=float)[: int(opts.get("max_points", 400000))]
    windows = adtk_slice_windows(signal, length, number, stride)
    if windows.shape[0] < 20:
        raise ValueError(f"基线窗口太少（只有 {windows.shape[0]} 个）：检查 baseline_file={baseline_file}、"
                         f"length={length}、number={number} 与信号点数 {signal.size}")
    features = windows if feature_mode == "raw" else np.asarray(
        [adtk_window_features(window, sampling_rate) for window in windows])
    frame = pd.DataFrame(features, index=pd.date_range("2017-01-01", periods=features.shape[0], freq="s"))
    _seed_everything(int(opts.get("seed", 42)))
    # ---- 拟合与标定用**不同**的窗口：前 70% 拟合 PCA，后 30% 定阈值 ----
    # 以前是"在同一批窗口上既拟合、又取自己的分位数当阈值"，于是 baseline_false_positive_rate
    # 按构造必然 ≈ (1-quantile)，那是自证不是验证。留出一段没参与拟合的窗口，误报率才有意义。
    split = int(features.shape[0] * 0.7)
    if split < 20 or features.shape[0] - split < 5:          # 窗口太少就退回"全部拟合"
        split = features.shape[0]
    fit_frame, holdout_frame = frame.iloc[:split], frame.iloc[split:]
    calibrate_frame = holdout_frame if len(holdout_frame) else fit_frame
    # 原先这里还有一段"把 project_dir 插进 sys.path"的代码，其实完全是空转：
    # adtk 是 venv 里装的第三方包（不是项目子目录），上面 451 行就已经 import 成功了，
    # 而 main.py 启动时早已把 project_dir 追加进 sys.path。删掉不影响任何导入路径。
    detector_cls = getattr(adtk_detector, detector_name)
    detector = detector_cls(k=k, c=c) if detector_name == "PcaAD" else detector_cls()
    detector.fit(fit_frame)
    transformer = adtk_transformer.PcaReconstructionError(k=k)     # 连续分数 = PcaAD 的第一步
    transformer.fit(fit_frame)
    # ---- 阈值标定：分位数取自拟合窗口，误报率在**留出**窗口上算 ----
    fit_scores = np.asarray(transformer.transform(fit_frame), dtype=float).ravel()
    cal_scores = np.asarray(transformer.transform(calibrate_frame), dtype=float).ravel()
    threshold = float(np.quantile(fit_scores, quantile)) * factor
    false_positive = float((cal_scores > threshold).mean())
    try:
        adtk_flag_rate = float(np.asarray(detector.detect(calibrate_frame)).ravel().astype(bool).mean())
    except Exception:                                            # noqa: BLE001
        adtk_flag_rate = None
    def saver(target: Path) -> Path:
        """落盘回调：标准化参数 + 检测器/连续分数器 + 全部标定信息。

        阈值、拟合窗口数、基线来源都写进同一个 pkl：推理侧才能复现"当时是怎么判的"，
        而不是重新按当前数据猜一个阈值。
        """
        path = target / "detector.pkl"
        with open(path, "wb") as fh:
            pickle.dump({"detector": detector, "transformer": transformer, "detector_name": detector_name,
                         "feature_mode": feature_mode, "sampling_rate": sampling_rate, "bands": 6,
                         "feature_dim": int(features.shape[1]), "length": length, "number": number,
                         "stride": stride, "threshold": threshold, "threshold_quantile": quantile,
                         "factor": factor, "score_median": float(np.median(fit_scores)),
                         "fit_windows": int(split), "calibration_windows": int(len(calibrate_frame)),
                         "baseline_source": baseline_source, "baseline_windows": int(features.shape[0]),
                         "columns": list(frame.columns)}, fh)
        return path
    return {
        "framework": "adtk",
        "task": "anomaly_detection",
        "input_len": length,
        "num_classes": None,
        "labels": None,
        "dataset_name": dataset_name,
        "dataset_path": dataset_path,
        "dataset_stats": {"baseline_source": baseline_source, "baseline_points": int(signal.size),
                          "detector": detector_name, "k": k, "c": c, "feature_mode": feature_mode,
                          "feature_dim": int(features.shape[1]), "windows": int(features.shape[0]),
                          "threshold": threshold, "threshold_quantile": quantile, "factor": factor,
                          "baseline_false_positive_rate": false_positive,
                          "adtk_default_flag_rate": adtk_flag_rate},
        "params": {"detector": detector_name, "k": k, "c": c, "feature_mode": feature_mode,
                   "sampling_rate": sampling_rate, "length": length, "number": number, "stride": stride,
                   "threshold_quantile": quantile, "factor": factor, "baseline_file": baseline_file},
        "metrics": {"test_accuracy": None, "test_loss": None, "val_accuracy": None, "val_loss": None,
                    "history": {}, "classification_report": None,
                    "baseline_false_positive_rate": false_positive, "threshold": threshold,
                    "score_median": float(np.median(fit_scores)),
                    "note": "无监督模型，没有测试集准确率；推理返回 IsAnomaly + AnomalyScore（adtk 窗口重构误差）。"},
        "scaler_file": None,
        "saver": saver,
    }
# ================================================================== 统一入口
# 内部键 → 训练函数的分派表：键必须与 ALIASES 的值、data/models/<目录名> 三处严格一致（见文件头 ALIASES 的说明）
_TRAINERS = {"1dcnn": _train_1dcnn, "cwt_cnn": _train_cwt_cnn, "adtk": _train_adtk}
def train(model: str | None = None, options: dict | None = None) -> dict:
    """训练一个模型：跑训练 → 落盘产物 → 出图 → 按外键顺序写库，最后返回一份可读报告。

    四步走，任何一步失败都**不会**让接口静默成功：

        ① 建日志 + 劫持 stdout → 交给对应 trainer 去练（权重先留在内存）
        ② save_artifact 落盘：data/models/<名>/{权重, scaler.npz, meta.json}（**直接替换旧产物**）
        ③ 出图（失败只记 figures_error，不影响训练结论）
        ④ 写库 Datasets → Models → Trainings（连失败也写一行 Status=失败，便于追溯）

    注意 `/train` 是**同步阻塞**的：本函数返回时训练已经结束（1DCNN 10 轮约 15 秒）。
    """
    options = dict(options or {})
    name = normalize_model(model)
    started = datetime.now()
    log_path = _log_path(name)
    result: dict = {"model": name, "status": "失败", "started_at": started.isoformat(timespec="seconds"),
                    "log_file": str(log_path)}
    try:
        # ① 训练：把 stdout 重定向进日志文件。这样 Keras/PyTorch 的进度条与 trainer 里 print
        #    的中间信息全进 data/logs/train-<模型>-<时间戳>.log，出问题能完整回放，
        #    而不是只剩最后一行报错。代价：redirect_stdout 是**进程级**的，并发训练会串日志。
        with open(log_path, "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
            print(f"=== /train {name} 参数：{json.dumps(options, ensure_ascii=False, default=str)}\n")
            payload = _TRAINERS[name](options)      # 三个 trainer 之一，返回结构统一的 payload
        # ② 落盘：saver 是 trainer 塞进 payload 的回调，各框架保存方式不同（.h5/.pt/pickle），
        #    由 trainer 决定怎么写；这里只管"产物目录 + meta.json + 失败回滚"这套公共约定。
        #    lib 里的字段全是"产物自解释"所必需的：input_len 决定推理切多长的窗，
        #    labels 让模型文件能解释 0..9 对应哪种故障，dataset.stats 记录数据指纹。
        saver = payload.pop("saver")
        artifact = save_artifact(name, payload["framework"], saver, {
            "model": name,
            "framework": payload["framework"],
            "task": payload["task"],
            "input_len": payload["input_len"],
            "num_classes": payload["num_classes"],
            "labels": payload["labels"],
            "dataset": {"name": payload["dataset_name"], "path": payload["dataset_path"],
                        "stats": payload["dataset_stats"]},
            "params": payload["params"],
            "metrics": payload["metrics"],
            "confusion": payload.get("confusion"),          # 供 /models/<name> 与出图复用
            "scaler_file": payload.get("scaler_file"),
            "trained_at": started.isoformat(timespec="seconds"),
            "log_file": str(log_path),
            "trusted": True,                     # 本机训练出来的产物可信（推理侧会反序列化 .pkl）
            "provenance": "train",
        })
        # ---- 出图（失败不影响训练结果，只在响应里回报错误）----
        figure_result = training_figures(name, artifact.meta,
                                         {"confusion": payload.get("confusion"),
                                          "per_class": payload.get("per_class")})
        result.update({
            "status": "成功",
            "artifact": artifact.to_dict(),
            "metrics": payload["metrics"],
            "params": payload["params"],
            "dataset_stats": payload["dataset_stats"],
            "figures": figure_result["figures"],
            "figures_dir": figure_result["dir"],
        })
        if figure_result.get("error"):
            result["figures_error"] = figure_result["error"]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-2000:]
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("\n" + result["traceback"])
    completed = datetime.now()
    result["completed_at"] = completed.isoformat(timespec="seconds")
    result["duration_sec"] = round((completed - started).total_seconds(), 2)
    # ---- 写库：严格按外键顺序，DB 不可用时降级但显式回报 ----
    db_info: dict = {"written": False}
    artifact_dict = result.get("artifact") or {}
    stats = result.get("dataset_stats") or {}
    dataset_name = (artifact_dict.get("dataset") or {}).get("name") or options.get("dataset") or "CWRU-0HP"
    dataset_path = stats.get("dataset_dir") or (artifact_dict.get("dataset") or {}).get("path")
    try:
        dataset_id = database.ensure_dataset(
            dataset_name,
            source="Case Western Reserve University 轴承数据集" if "CWRU" in dataset_name else None,
            sample_count=stats.get("train_total"),
            class_count=artifact_dict.get("num_classes"),
            data_path=dataset_path,
            description="由 model_service 自动登记",
        )
        model_id = database.ensure_model(db_model_name(name), description=MODEL_META[name]["description"],
                                         model_type=MODEL_META[name]["type"])
        metrics = result.get("metrics") or {}
        training_id = database.insert_training(
            model_id=model_id,
            dataset_id=dataset_id,
            train_name=f"{name}-{started.strftime('%Y%m%d-%H%M%S')}",
            epochs=(result.get("params") or {}).get("epochs"),
            batch_size=(result.get("params") or {}).get("batch_size"),
            accuracy=metrics.get("test_accuracy"),
            loss=metrics.get("test_loss"),
            model_path=artifact_dict.get("weights"),
            status=result["status"],
            started=started.strftime("%Y-%m-%d %H:%M:%S"),
            completed=completed.strftime("%Y-%m-%d %H:%M:%S"),
            remark=json.dumps({
                "错误": result.get("error"),
                "跳过越界窗口": (result.get("dataset_stats") or {}).get("skipped_out_of_range_total"),
                "NaN窗口": (result.get("dataset_stats") or {}).get("nan_windows_total"),
                "日志": str(log_path),
                "图目录": result.get("figures_dir"),
            }, ensure_ascii=False),
        )
        db_info = {"written": True, "dialect": database.dialect,
                   "DatasetID": dataset_id, "ModelID": model_id, "TrainingID": training_id}
    except DBError as exc:
        db_info = {"written": False, "dialect": database.dialect, "error": str(exc)}
    except Exception as exc:                                       # pragma: no cover
        db_info = {"written": False, "dialect": database.dialect,
                   "error": f"{type(exc).__name__}: {exc}"}
    result["db"] = db_info
    return result

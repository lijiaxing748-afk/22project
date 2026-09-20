# -*- coding: utf-8 -*-
"""flask_restful 接口资源（流程图里的「Web访问」盒子）。

⚠️ 不要再往这里手抄一份路由表：这份清单曾经只列了 11 条、而 register_api 实际注册了 27 条，
   两边各自演化，最后连"哪些路由真的存在"都要靠读代码才知道。
   现在**唯一的权威清单是注册处 `register_api()`**，运行中的服务还可以直接看
   `GET /api`（ApiIndex）—— 它列的键与 register_api 一一对应，也是前端「接口索引」页的数据源。

按用途分四组（细节看各 Resource 的 docstring）：

    体检    GET  /health、/datasets、/system、/system/logs
    模型    GET  /models、/models/<name>、/models/<name>/overview、/models/<name>/references
            POST /models（登记）、POST /models/upload（上传）
            DELETE /models/<name>?scope=artifact|record
    发布    GET  /models/<name>/exports（发布历史）、POST 同路径（打包发布）
            GET  /models/<name>/exports/<包名>（下载）、DELETE 同路径（删除包）
    训练    POST /train、GET /trainings
    推理    POST /predict、GET /inference-tasks、GET /inference-tasks/<id>
    数据集  GET  /datasets/db、POST /datasets/db（登记）、POST /datasets/upload（上传）
            GET  /datasets/table（预览）、GET /datasets/signal（取一段信号画波形）
    图      GET  /figures、GET  /figures/<路径>、POST /system/maintenance（清空图库）

约定：任何失败都返回 {"error": ...} + 合适的状态码，并把细节写进 ModelInvocations（能写库时）。
"""
from __future__ import annotations
import json
import platform
import re
import sys
import traceback
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
# Response / redirect 已随零构建控制台（console.html + GET /ui）一起删掉，如无新用途别再 import
from flask import request, send_from_directory
from flask_restful import Resource
from . import datasets as ds
from . import exporter
from . import tabular
from .auth import log_operation, require_login, require_perm
from .config import config
from .db import DBError, database
from .figures import FIG_DIR, clear_figures, list_figures
from .inference import InvalidInput, predict
from .exporter import list_packages, resolve_package
from .registry import abort_artifact, begin_artifact, commit_artifact, delete_artifact, list_artifacts, load_artifact
from .training import MODEL_META, ALIASES, normalize_model, train
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")          # 训练日志里 Keras 进度条的转义序列
_PACKAGES = ("numpy", "pandas", "scikit-learn", "scipy", "matplotlib", "h5py", "flask",
             "flask-restful", "pymysql", "pyodbc", "tensorflow", "tf-nightly", "keras",
             "keras-nightly", "torch", "python-docx", "pywin32")
MAX_EPOCHS = 200          # 防止一条 HTTP 请求把服务占住几小时
MAX_LIMIT = 500           # 单次 /predict 最多多少窗口
# ---------------- 「这是不是一个模型」探测 ----------------
# 上传时不再要求用户填输入长度/类别数/类别标签：先按扩展名分类，再**打开文件看内容**，
# 判断它到底是不是权重文件，并尽量把 input_len / num_classes 猜出来。
WEIGHT_SUFFIXES = {
    ".h5": "tensorflow-keras", ".keras": "tensorflow-keras",
    ".pt": "pytorch", ".pth": "pytorch", ".pt2": "pytorch-exported",
    ".pkl": "adtk", ".pickle": "adtk",
}
# 上传文件夹时，这些扩展名之外的文件一律忽略（允许带上 scaler/meta/说明文件等附属文件）
KEEP_SUFFIXES = {".json", ".npz", ".npy", ".txt", ".yaml", ".yml", ".onnx", ".csv",
                 ".h5", ".keras", ".pt", ".pth", ".pt2", ".pkl", ".pickle"}
# PyTorch 的输出层一般叫这些名字，用来从 state_dict 里认出"最后一层"从而读出类别数
_HEAD_LAYER_RE = re.compile(r"(fc|classifier|linear|head|dense|out|output)\d*\.weight$")
def _keras_shapes(config: dict) -> tuple[int | None, int | None]:
    """从 Keras 的 model_config（dict）里挖出 input_len 与类别数（最后一个 Dense 的 units）。

    ⚠️ 形参名 `config` 遮蔽了模块级 `from .config import config`（全局配置对象）：
    本函数里的 config 一律指「Keras 导出的模型结构 dict」，不要当全局配置用。
    这是纯猜测逻辑，挖不到就返回 (None, None)、**绝不抛异常** —— 猜不出来只是少给用户
    一条提示，不该让上传/预览整个失败。
    """
    # 存档可能是 {"class_name": ..., "config": {...}} 外壳，也可能直接就是内层 config，两种都试
    conf = config.get("config", config) if isinstance(config, dict) else None
    if not isinstance(conf, dict):
        return None, None
    # layers 可能缺失或不是 list（手工改过的/非 Sequential 的存档），统一成 []，
    # 后面两个循环就不用再判类型了
    layers = conf.get("layers") if isinstance(conf.get("layers"), list) else []
    def first_dim(shape) -> int | None:
        """取形状里第一个有意义的维度。

        跳过 batch 维（shape[0]，训练时是 None）与 None/0 这类占位维度，
        所以 [None, 784, 1] 会返回 784 而不是 None。
        """
        if not isinstance(shape, list):
            return None
        # 只认正整数维度：字符串维度名（"channels" 之类）、None（未知的 batch 维）、0 全部过滤掉
        dims = [d for d in shape[1:] if isinstance(d, int) and d > 0]
        return int(dims[0]) if dims else None
    input_len = None
    # 逐层扫而不是只看第一层：导出后的 config 里输入形状挂在哪一层并不固定
    for layer in layers:                                   # 输入层：Keras2 用 batch_input_shape，Keras3 用 batch_shape
        lc = layer.get("config") if isinstance(layer, dict) else None
        if isinstance(lc, dict):
            # `or` 的语义正好是"左边没结果才退到右边"，所以 Keras2/Keras3 两个键可以顺手写一行；
            # 拿到就立刻 break，避免被后面某层的空形状覆盖成 None
            input_len = first_dim(lc.get("batch_input_shape")) or first_dim(lc.get("batch_shape"))
            if input_len:
                break
    if input_len is None:                                  # 顶层也可能直接挂形状
        input_len = first_dim(conf.get("batch_input_shape")) or first_dim(conf.get("batch_shape"))
    units = None
    # 类别数 = 输出层的神经元数。必须**从后往前**找第一个带 units 的层：
    # ⚠️ 不能直接取 layers[-1]，导出结构最后几层常常是 Activation/Dropout 这类没有 units 的层。
    # ⚠️ 该等式只在"最后一层是分类输出"时成立；回归头或嵌套子模型读出来的只是"最后一层的宽度"。
    for layer in reversed(layers):                         # 最后一个 Dense 的 units 就是类别数
        lc = layer.get("config") if isinstance(layer, dict) else None
        if isinstance(lc, dict) and isinstance(lc.get("units"), int) and lc["units"] > 0:
            units = int(lc["units"])
            break
    return input_len, units
def _exported_input_len(blob: bytes, names: list[str]) -> int | None:
    """从 torch.export（.pt2）产物里读回输入长度（窗口长度）。

    torch.export 的包里 `archive/data/sample_inputs/<名>` 存的是导出时的示例输入，
    用 `weights_only=True` 读它是安全的（里面只有张量，不会执行代码）。
    ⚠️ 它的结构是 `[args, kwargs]` 这种**嵌套**（实测读到 `[[Tensor(2,1,784)], {}]`），
       所以要递归找第一个"至少二维"的张量，只看一层会读不到。
    ⚠️ 读不出来就返回 None —— 调用方会退回"表单/meta 里的 input_len"，
       不该因为读不到一个提示值就把整个上传判失败。
       （TorchScript 就属于读不出来的那种：它的 traced_inputs 是空的/需要自定义类。）
    """
    import io
    import zipfile
    candidates = [n for n in names if n.startswith("archive/data/sample_inputs/")]
    if not candidates:
        return None
    try:
        import torch
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            raw = zf.read(candidates[0])
        obj = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    except Exception:
        return None
    def dig(node, depth=0):
        """递归找第一个 dim>=2 的张量，(n,1,length) 与 (n,length) 的最后一维都是 length。"""
        if depth > 5:
            return None
        if isinstance(node, torch.Tensor):
            return int(node.shape[-1]) if node.dim() >= 2 else None
        if isinstance(node, (list, tuple)):
            for item in node:
                found = dig(item, depth + 1)
                if found:
                    return found
        if isinstance(node, dict):
            for item in node.values():
                found = dig(item, depth + 1)
                if found:
                    return found
        return None
    return dig(obj)
def probe_weight(filename: str, blob: bytes) -> dict:
    """判断一个上传文件是不是模型权重，并尽量读出 input_len / num_classes。

    返回 {ok, framework, reason, input_len, num_classes}。判定规则（看内容，不只看后缀）：

      .h5      HDF5，且含 `model_weights` 组或 `model_config` 属性（Keras 存档）
      .keras   zip，且含 config.json / metadata.json（Keras 3 存档）
      .pt/.pth zip 且含 torch 的 data.pkl；能反序列化就顺手把类别数读出来
      .pkl     pickle（0x80 开头）——**不反序列化**，免得「上传即执行代码」
    """
    import io
    import zipfile
    suffix = Path(filename).suffix.lower()
    framework = WEIGHT_SUFFIXES.get(suffix)
    result = {"ok": False, "framework": framework, "reason": "", "input_len": None, "num_classes": None}
    # 第一关：扩展名。连后缀都不在支持列表里，就没必要打开文件了
    if framework is None:
        result["reason"] = f"扩展名 {suffix or '(无)'} 不是模型权重（支持 .h5/.keras/.pt/.pth/.pkl/.pickle）"
        return result
    if not blob:
        result["reason"] = "文件是空的（0 字节）"
        return result
    try:
        # ---------------- .h5 / .keras：两种 Keras 存档，用"文件头是不是 PK(zip)"区分 ----------------
        if suffix in (".h5", ".keras"):
            if blob[:2] == b"PK":                          # Keras 3 的 .keras 是一个 zip 包
                with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                    names = zf.namelist()
                    # 必须含 config.json（网络结构）或 metadata.json，否则就是个普通 zip
                    if "config.json" not in names and "metadata.json" not in names:
                        result["reason"] = f"压缩包里没有 config.json/metadata.json，不像 Keras 模型（含 {names[:5]}）"
                        return result
                    # ⚠️ config.json 要**按需读**：上面的判据是"config.json **或** metadata.json 有其一"，
                    #    但这里以前是无条件 `zf.read("config.json")` —— 于是只有 metadata.json 的包
                    #    会抛 KeyError，被外层 except 报成"不像有效模型文件"，与判据自相矛盾。
                    #    现在读不到就当"是模型、但猜不出结构"，返回 input_len/num_classes = None。
                    config = (json.loads(zf.read("config.json").decode("utf-8"))
                              if "config.json" in names else None)
                input_len, units = _keras_shapes(config) if config else (None, None)
                result.update(ok=True, input_len=input_len, num_classes=units,
                              reason=f"Keras 3 存档（zip，input_len={input_len}，类别数={units}）")
                return result
            # 不是 zip → 按 HDF5 处理（Keras 2 的 .h5）。
            # 关键：光能打开还不够，必须有 model_weights 组或 model_config 属性 ——
            # 否则随便一个 HDF5 数据文件都会被误判成"模型"
            import h5py
            with h5py.File(io.BytesIO(blob), "r") as handle:
                keys = list(handle.keys())
                raw_config = handle.attrs.get("model_config")
                if "model_weights" not in keys and raw_config is None:
                    result["reason"] = (f"HDF5 里既没有 model_weights 组也没有 model_config 属性"
                                        f"（顶层是 {keys[:5]}），不像 Keras 权重文件")
                    return result
                config = json.loads(raw_config) if raw_config is not None else None
            input_len, units = _keras_shapes(config) if config else (None, None)
            result.update(ok=True, input_len=input_len, num_classes=units,
                          reason=f"Keras HDF5（顶层 {keys[:5]}，input_len={input_len}，类别数={units}）")
            return result
        # ---------------- .pt / .pth / .pt2：torch 的三种 zip 容器，靠**包内条目**区分 ----------------
        # 为什么要分三种：本平台最早的 pytorch 路线是"重建架构 + load_state_dict"，
        # 那条路**只对用本服务训出来的模型有效**（外部模型结构不同就报键不匹配）。
        # 想让外部 pytorch 模型"上传就能用"，就必须是**自包含**格式 —— 结构跟着权重一起走：
        #   · .pt2（torch.export 产物）：torch 在 Python 3.14 上官方推荐的序列化方式，
        #     包里带 archive/data/weights/，加载不需要任何模型类
        #   · TorchScript（torch.jit.trace/script 产物）：包里带 code/，同样自包含
        #   · 老的 state_dict 包：只有张量、没有结构，仍然需要架构同构
        if suffix in (".pt", ".pth", ".pt2"):
            if blob[:2] != b"PK":
                result["reason"] = (f"不是 PyTorch 检查点（torch>=1.6 的 .pt 是 zip，应以 PK 开头；"
                                    f"实际开头 {blob[:4]!r}）")
                return result
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = zf.namelist()
            is_exported = any(name.startswith("archive/data/weights/") for name in names)
            # ⚠️ TorchScript 的条目是 `archive/code/__torch__/...`（前缀带 archive/），
            #    所以判据要用 "/code/" 而不是 startswith("code/")，否则漏判成老式 state_dict。
            is_torchscript = (not is_exported) and any("/code/" in name or name.endswith("/code")
                                                      for name in names)
            if is_exported or is_torchscript:
                kind = "torch.export 产物（.pt2）" if is_exported else "TorchScript"
                # 自包含格式：结构就在包里，不需要任何架构源码，加载后直接可调用
                result["framework"] = "pytorch-exported" if is_exported else "pytorch-jit"
                input_len = _exported_input_len(blob, names) if is_exported else None
                result.update(ok=True, input_len=input_len,
                              reason=f"{kind}（自包含，无需架构代码；input_len={input_len}，"
                                     f"类别数留到推理时按输出宽度定）")
                return result
            if not any(name.endswith("data.pkl") for name in names):
                result["reason"] = (f"zip 里既没有 torch 的 data.pkl、也没有 "
                                    f"archive/data/weights/（torch.export）或 code/（TorchScript）"
                                    f"（含 {names[:5]}），不像 PyTorch 模型")
                return result
            try:
                import torch
            except Exception as exc:                       # 本机没装 torch 也不该误判成"不是模型"
                result.update(ok=True, reason=f"PyTorch 检查点（本机无 torch，跳过参数解析：{exc}）")
                return result
            try:
                # ⚠️ 这里**必须** weights_only=True：它是 .pt 上传路径唯一的防代码执行闸门。
                #    （实测我们自己的 payload {state_dict, length, num_classes} 在
                #     weights_only=True 下完全读得出来 —— int/dict/tensor 都在安全白名单里，
                #     原先用 False 是没必要的。）
                obj = torch.load(io.BytesIO(blob), map_location="cpu", weights_only=True)
            except Exception as exc:
                # weights_only=True 读不了 = 包里带了自定义类（"存整个模型对象"那种）。
                # 以前这里 ok=True 放过去，等于推理时再决定 —— 而推理那边用的是
                # weights_only=False，**会把上传者提供的代码跑起来**。
                # 现在改成如实说明：能认出"这是个 torch 存档"，但本平台不会为它执行反序列化。
                result.update(ok=True, num_classes=None,
                              reason=f"PyTorch 存档，但需要自定义类才能读（{type(exc).__name__}）。"
                                     f"要让它**能推理**，请导出成自包含格式："
                                     f"torch.export（得到 .pt2）或 torch.jit.trace + torch.jit.save")
                return result
            state = obj.get("state_dict", obj) if isinstance(obj, dict) else obj
            shapes = [(k, tuple(v.shape)) for k, v in state.items()] if hasattr(state, "items") else []
            if not shapes:
                result["reason"] = "torch 文件里没有张量参数，不像模型权重"
                return result
            # 猜类别数：倒着找第一个"像分类头"的二维权重（fc/classifier/linear/head…），
            # 它的第 0 维 = 输出类别数；找不到就退而取最后一个二维权重
            head = next((s for k, s in reversed(shapes) if len(s) == 2 and _HEAD_LAYER_RE.search(k)), None)
            head = head or next((s for _, s in reversed(shapes) if len(s) == 2), None)
            result.update(ok=True, num_classes=int(head[0]) if head else None,
                          reason=f"PyTorch state_dict（{len(shapes)} 个张量，类别数={int(head[0]) if head else None}；"
                                 f"注意：这种格式没有结构，推理时按本项目的 cwt_cnn 架构重建，"
                                 f"外部模型若结构不同请改用 torch.export）")
            return result
        # ---------------- .pkl：只验 pickle 魔数，**绝不反序列化** ----------------
        # 反序列化 pickle = 执行文件里的任意代码，而这是"上传"来的文件；
        # 判断"是不是 pickle"只需要看头 1 个字节（协议 2+ 都以 0x80 开头）就够了。
        if blob[:1] != b"\x80":
            result["reason"] = f"不是 pickle 文件（.pkl 应以 0x80 开头，实际 {blob[:2]!r}）"
            return result
        result.update(ok=True, reason="pickle 序列化对象（adtk 检测器/传统模型；为安全起见不做反序列化校验）")
        return result
    except Exception as exc:
        # 坏文件、半截文件、权限问题都会落到这里。reason 会被前端逐条展示，所以要说人话。
        result["reason"] = f"读取失败，不像有效模型文件：{type(exc).__name__}: {exc}"
        return result
def _body() -> dict:
    """请求体 JSON；不是对象（或压根不是 JSON）时返回空 dict，避免调用方到处判 None。

    用 `silent=True` 是刻意的：前端有些请求是 form-data 或不带 body，
    这时不该直接 400，而应让接口用参数默认值继续跑。
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _log_train_result(name: str, result: dict) -> None:
    """把一次训练的结果记进操作日志。

    ⚠️ 训练**失败也必须记**（result=失败），和"只在成功时记录"的常规做法相反：
    训练是这个平台最重的操作，失败往往意味着数据/参数配错，恰恰是最需要追溯的情形。
    但失败不是"谁干了坏事"，所以 result 字段如实写"失败"，不写进 detail 的错误堆栈
    （异常详情已经在 Trainings 表和日志文件里了，重复塞一遍只会让日志表变胖）。

    整个函数不抛异常：log_operation 自己已经吞异常，这里再把取字段的部分包一层，
    防止 result 形状意外变化（比如 db 层改成返回非 dict）把训练接口打成 500。
    """
    try:
        status = str(result.get("status") or "")
        db = result.get("db") or {}
        detail = {
            "status": status,
            "epochs": result.get("epochs"),
            "duration_s": result.get("duration_s") or result.get("elapsed_s"),
            "db_written": db.get("written"),
            "warning": result.get("warning"),
        }
        # 训练失败时 result 里会有 error；截断后放进 message（db 层会再 _clip 到 500）
        message = str(result.get("error") or "")[:300] or None
        log_operation("run_training", target=name,
                      detail={k: v for k, v in detail.items() if v is not None},
                      result="成功" if status == "成功" else "失败",
                      message=message)
    except Exception:
        pass


def _int(value, default=None, name="参数"):
    """取整数参数：None 用默认值，转不动就抛 InvalidInput（接口据此回 400）。

    ⚠️ 调用方**不要**写成 `_int(x, 0, "y") or 0`：0 是 falsy，会把用户明确传的 0
    悄悄换成别的值 —— `/predict` 的 `limit=0` 曾因此绕过范围校验。
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise InvalidInput(f"{name} 必须是整数，收到 {value!r}")
def _sanitize_name(value: str, default: str) -> str:
    """名字 → **磁盘安全形式**：非法字符换成下划线，再去掉首尾的点与下划线，为空则用 default。

    允许中英文、数字、下划线、点、横线。⚠️ 本函数**从不抛异常**，所以"必须继续跑"的路径
    （回滚、上传落盘）用它；要求"非法就报错、不许静默改名"的路径（改模型名）用 `_safe_model_name()`。
    """
    return re.sub(r"[^\w\u4e00-\u9fa5.\-]+", "_", value).strip("._") or default
def _resolve_workspace_path(raw: str) -> Path:
    """把用户给的路径解析成**工作区内**的文件（`/datasets/table`、`/datasets/signal` 用它）。

    两级回退：相对路径先按工作区（D:\\22project）试，再按项目目录（testRestfulProject）试，
    所以 `data/datasets/x.csv` 与 `testRestfulProject/data/datasets/x.csv` 两种写法都能用。

    安全：候选路径必须满足 `relative_to(workspace)`，用的是 Path 语义而**不是字符串
    startswith** —— 否则 `D:\\22project_evil\\x` 这类同前缀目录会绕过检查（历史上真踩过）。
    最终找不到就抛 InvalidInput(400)，而不是把原始路径回显出去让人猜。
    """
    candidate = Path(raw)
    # 绝对路径只有一次机会；相对路径两个基准各试一次（工作区优先）
    tries = [candidate] if candidate.is_absolute() else \
        [config.workspace_dir / candidate, config.project_dir / candidate]
    for path in tries:
        resolved = path.resolve()
        try:
            resolved.relative_to(config.workspace_dir.resolve())    # 越界 → 换下一个候选
        except ValueError:
            continue
        if resolved.is_file():            # 目录不算命中，必须是指到文件
            return resolved
    raise InvalidInput(f"文件不存在或不在工作区内：{raw}")
class ApiIndex(Resource):
    """GET / 与 GET /api —— 接口索引，给人和「系统管理→接口索引」页看的自描述清单。

    ⚠️ 两个 URL 的内容**完全一样**，但实际能不能从 `/` 访问到，取决于是否托管了前端：
       · 没有前端产物（只部署后端）→ `/` 就是本接口，访问根路径看到接口清单，便于调试
       · 有前端产物（单端口部署）→ `/` 被 web.py 让给了前端首页，
         取接口清单请走 **`/api`**（就是这个类，内容一致）
       原因见 model_service/web.py 里 register_frontend() 的说明：
       交付时用户输 http://ip:8080/ 必须进系统，而不是看到一坨 JSON。
    """
    def get(self):
        # endpoints 由 _route_index() 从**注册表**生成，不再手抄：手抄那份已经漂过两次
        # （索引里留着早已删除的 /todos，同时漏掉 4 条真实存在的路由）。
        return {
            "service": "model_service",
            "flow": "Web访问 → 算法模型 → 训练 → 数据集 → 模型产物 → 推理 → (边缘设备)",
            "endpoints": _route_index(),
            # 别名表的 value 才是内部键：cnn / 算法模型1 / 模型1 等多个别名指向同一个键，所以先 set 去重
            "models": sorted(set(ALIASES.values())),
        }
class Health(Resource):
    """GET /health —— 服务 / 数据库 / 模型产物的体检，前端顶栏每 15 秒轮询它。

    刻意**不抛异常**：数据库连不上也算"服务还活着"，只在 database.ok 里标失败，
    否则顶栏会显示成"服务不可用"，让人误以为整个进程挂了。
    """
    def get(self):
        # 探测数据库用 ping()：它内部把异常吞成 {ok: False, error: ...}，
        # 所以库挂了这里也照样能返回 200，前端只需看 database.ok
        db_state = database.ping()
        artifacts = list_artifacts()
        return {
            "service": "ok",
            "config": config.describe(),
            "database": db_state,
            # models 列出"哪些模型已经有产物"：每个模型只有一个产物，所以就是名字清单
            "artifacts": {
                "count": len(artifacts),
                "models": [a.name for a in artifacts],
            },
            "figures": {"count": len(list_figures(limit=1000)), "dir": str(FIG_DIR)},
            # 写死的"已知问题"提示：告诉使用者本服务不排队、以及数据管线那个已修正的坑，
            # 免得看到一个慢接口就以为是卡死
            "warnings": [
                "本服务不做训练/推理排队，/train 是同步阻塞的（开发服务器已开 threaded）。",
                "数据管线已知问题：原脚本会把越界切片补成整行 NaN；服务侧改为拒绝并回报。",
            ],
        }
class ModelList(Resource):
    """GET /models —— 磁盘产物（artifacts）+ 库表登记（db_models）两份清单。

    两者故意不合并：产物可能还没登记（训练落盘后写库失败），登记也可能没有产物
    （只占位未训练），前端要能看出这种不一致。
    """
    def get(self):
        artifacts = list_artifacts()
        try:
            db_models = database.models_in_db()
        except DBError as exc:
            # ⚠️ 库查询失败时把 error 塞进列表，而不是返回 503：磁盘产物照样能列出来，
            # 前端只需在"库表"那一列标不可用，不至于因为库挂了就连产物都看不到
            db_models = [{"error": str(exc)}]
        return {
            "artifacts": [a.to_dict() for a in artifacts],
            "db_models": db_models,
            # 内置模型的元数据（内部键 → 描述/类型/db_name），给前端下拉框和说明文案用
            "known_models": {name: MODEL_META[name] for name in MODEL_META},
        }
class DatasetList(Resource):
    """数据集体检：内置 .mat 数据集 + data/datasets 下上传的表格数据集。"""
    def get(self):
        """把两类数据源都体检一遍。

        单个数据集出错只写进它自己的 error 字段，不让整页 500 —— 某个表格文件
        损坏不应该连带看不到其它数据集。
        """
        out = {}
        # 第一类：内置 .mat 数据集。config.dataset_dirs 是 {前端口径的数据集名: 真实目录}，
        # 遍历顺序无所谓——最后返回的是一个 {key: 体检结果} 映射，前端按 key 取，不依赖顺序
        for name, path in config.dataset_dirs.items():
            try:
                info = ds.describe_dataset(path)
                # 下面三个字段都是**给前端下拉框用**的元信息，缺一个前端就得自己猜：
                #   key          = 选中后回传给 /datasets/signal 的 dataset 参数（唯一标识）
                #   dataset_type = matlab / tabular，前端据此决定要不要显示"工作表/列"选择器
                #   dataset_dir  = 目录本身（出口脱敏会把它换成相对工作区的相对路径）
                info["dataset_type"] = "matlab"
                info["key"] = name
                out[name] = info
            except Exception as exc:
                # ⚠️ 单个数据集读失败也要占住自己的 key：前端列表里显示"这个数据集有问题"。
                # 直接跳过（少一行）最容易被误会成"数据集被删了"，整页 500 则连别的数据集都看不到
                out[name] = {"error": f"{type(exc).__name__}: {exc}", "dataset_dir": str(path),
                             "dataset_type": "matlab", "key": name}
        # 第二类：上传的表格数据集。⚠️ iterdir() 之前必须先判 is_dir()：
        # data/datasets 从没创建过或被人删掉时，iterdir() 会抛 FileNotFoundError 让整个 /datasets 挂掉；
        # 这里当成"还没有上传过数据集"，返回空列表继续往下走
        upload_root = sorted([p for p in config.upload_dir.iterdir() if p.is_dir()], key=lambda p: p.name) \
            if config.upload_dir.is_dir() else []          # 目录被删掉时不该 500，当成"没有上传数据集"
        for directory in upload_root:
            # key 前面加 "表格:" 前缀：用来和内置 .mat 的名字区分开，/datasets/signal 就是靠这个前缀
            # 认出"这是上传目录下的数据集"并去 data/datasets/<名> 找文件的
            key = f"表格:{directory.name}"
            try:
                # ⚠️ 这里读的是 tabular.describe_directory 的 **120 秒 TTL 缓存**结果：
                # 刚上传完文件如果这里显示不出来，不是文件没进去，而是缓存没清
                #（/datasets/upload 里那句 cache_clear() 就是为这个加的）
                info = tabular.describe_directory(directory)
            except Exception as exc:
                info = {"error": f"{type(exc).__name__}: {exc}", "files": []}
            # 无论体检成功还是失败，都补齐同样几个字段，前端不用到处判 key 在不在：
            # file_count / classes 缺失时给 0（空目录 = 0 个文件 0 个类别，比 null 好渲染）
            info.update({"key": key, "dataset_type": "tabular", "dataset_dir": str(directory),
                         "file_count": info.get("file_count", 0), "classes": info.get("classes", 0)})
            out[key] = info
        return out, 200
class DatasetUpload(Resource):
    """上传表格文件到 data/datasets/<数据集名>/（一个文件 = 一个类别）。"""
    MAX_MB = 80
    @require_perm("dataset:write")
    def post(self):
        """保存上传的表格文件，一个文件 = 一个类别（文件名即标签）。"""
        name = (request.form.get("name") or "").strip()
        files = _uploaded_files()
        if not files:
            return {"error": "没有收到文件（表单字段名用 file，可重复传多个）"}, 400
        if not name:
            name = Path(files[0].filename or "dataset").stem
        safe_name = _sanitize_name(name, "dataset")
        target = config.upload_dir / safe_name
        target.mkdir(parents=True, exist_ok=True)
        saved, skipped, overwritten = [], [], []
        for item in files:
            filename = Path(item.filename or "").name
            if not filename or Path(filename).suffix.lower() not in tabular.TABLE_SUFFIXES:
                skipped.append({"filename": filename,
                                "reason": f"不支持的扩展名，支持 {sorted(tabular.TABLE_SUFFIXES)}"})
                continue
            blob = item.read()
            if not blob:                                   # 0 字节文件会变成"空类别"，直接拒收
                skipped.append({"filename": filename, "reason": "空文件（0 字节）"})
                continue
            if len(blob) > self.MAX_MB * 1024 * 1024:
                skipped.append({"filename": filename, "reason": f"超过 {self.MAX_MB}MB"})
                continue
            destination = target / filename
            replaced = destination.is_file()               # 同名会被静默覆盖，这里至少回报出来
            destination.write_bytes(blob)
            if replaced:
                overwritten.append(filename)
            saved.append({"filename": filename, "size_kb": round(len(blob) / 1024, 1),
                          "path": str(destination), "label": tabular.label_from_filename(filename),
                          "replaced": replaced})
        # 体检结果有 120 秒 TTL 缓存：不清掉的话，响应里和列表页里都还是上传前的旧内容
        tabular.describe_directory.cache_clear()
        try:
            listing = tabular.describe_directory(target)
        except Exception as exc:
            listing = {"error": str(exc)}
        # ⚠️ 只在**有文件真的存下来**时记日志（saved 非空 = 返回 200）。
        #    全部被跳过时接口回 400、什么都没写，记一条"上传成功"是假账。
        #    overwritten 一定要进 detail：本平台约定"一个文件=一个类别"，覆盖等于换掉该类全部数据。
        if saved:
            log_operation("upload_dataset", target=safe_name,
                          detail={"files": [s["filename"] for s in saved],
                                  "size_kb": round(sum(s["size_kb"] for s in saved), 1),
                                  "overwritten": overwritten,
                                  "skipped": len(skipped)})
        return {"dataset": safe_name, "directory": str(target), "saved": saved,
                "skipped": skipped, "overwritten": overwritten,
                "hint": ("同名文件已被覆盖：本平台约定「一个文件 = 一个类别、文件名即标签」，"
                         "覆盖会直接换掉那个类别的全部数据" if overwritten else None),
                "listing": listing}, 200 if saved else 400
class TablePreview(Resource):
    """表格预览：列统计 + 前 N 行 + 推荐信号列（数据展示/数据集管理都用它）。"""
    def get(self):
        # path 必填：表格预览只认"工作区里的表格文件"，不接受把数据内联在请求里
        raw = request.args.get("path")
        if not raw:
            return {"error": "缺少 path 参数"}, 400
        # ⚠️ 用户给的路径必须先过 _resolve_workspace_path()，别自己拼 Path：
        # 它做两级回退（工作区优先、再试项目目录，所以 data/... 与 testRestfulProject/data/... 都能用），
        # 并用 relative_to(workspace) 判定越界——字符串 startswith 会被 D:\22project_evil 这类同前缀目录绕过
        try:
            path = _resolve_workspace_path(raw)
            # 扩展名白名单先行：不是 csv/xlsx/xls 就 400 说清楚，别等 pandas 抛一层看不懂的错再回 500
            # （is_table 只看后缀、不打开文件，放在 try 里纯粹是为了和下面共用同一个 except）
            if not tabular.is_table(path):
                return {"error": f"不是可预览的表格文件（支持 {sorted(tabular.TABLE_SUFFIXES)}）：{raw}"}, 400
            # rows = 预览多少行（前端表格默认显示 20 行）。⚠️ `or 20` 在 rows=0 时才生效——
            # 0 行预览没有意义，退成默认 20 可以接受；但 0 有语义的参数（如 /predict 的 limit）不能照抄这写法。
            data = tabular.preview(path, rows=_int(request.args.get("rows"), 20, "rows") or 20,
                                   sheet=request.args.get("sheet"), column=request.args.get("column"))
        except InvalidInput as exc:
            # ⚠️ 这一档必须排在 `except Exception` **之前**：InvalidInput 是 ValueError 子类，
            # 掉进兜底分支就变成 500，与其它接口"参数错→400"的口径不一致（?rows=abc 曾会这样）
            return {"error": str(exc)}, 400
        except Exception as exc:
            # 文件损坏/加密/列名对不上/不是数值列……统一算"这份表格读不出来"：500 但带上异常类型，便于定位
            return {"error": f"{type(exc).__name__}: {exc}"}, 500
        return data, 200
class Train(Resource):
    """POST /train —— 训练入口。**需要 train:run 权限**。

    这一层只做**参数校验与归一化**（模型名、epochs、rate、dataset_dir 的路径安全），
    真正的训练在 training.train() 里同步跑完，所以本接口耗时长、不能并发压。
    """
    @require_perm("train:run")
    def post(self):
        body = _body()
        try:
            name = normalize_model(body.get("model"))
            epochs = _int(body.get("epochs"), None, "epochs")
            if epochs is not None and not (1 <= epochs <= MAX_EPOCHS):
                raise InvalidInput(f"epochs 必须在 1..{MAX_EPOCHS} 之间")
            rate = body.get("rate")
            if rate is not None:                       # rate 不校验会一路炸到除零/空训练集（500）
                if not isinstance(rate, (list, tuple)) or len(rate) != 3:
                    raise InvalidInput("rate 必须是长度为 3 的数组，例如 [0.7,0.15,0.15]")
                try:
                    values = [float(x) for x in rate]
                except (TypeError, ValueError):
                    raise InvalidInput(f"rate 必须是数字数组，收到 {rate!r}")
                # 三项非负且和为 1：否则切出来的数据集大小算不对
                if any(x < 0 for x in values) or abs(sum(values) - 1.0) > 1e-6:
                    raise InvalidInput(f"rate 三项必须非负且和为 1，收到 {rate!r}")
                if values[1] + values[2] <= 0:
                    raise InvalidInput("rate[1]+rate[2] 必须大于 0（验证/测试集不能为空）")
                body["rate"] = values
            options = {k: v for k, v in body.items() if k not in ("model",)}
            for key in ("dataset_type", "dataset_dir", "signal_column", "sheet", "dataset"):
                if body.get(key) is not None:
                    options[key] = body[key]
            if body.get("dataset_dir"):
                candidate = Path(body["dataset_dir"])
                if candidate.is_absolute():
                    resolved = candidate.resolve()
                else:
                    # 相对路径口径与 `_resolve_workspace_path` 一致：先按工作区试，再按项目目录试。
                    # 这一步必须两边都试 —— 响应脱敏后前端拿到的是 "testRestfulProject\\1DCNN\\0HP"
                    # 这种"相对工作区"的路径，只按项目目录拼会得到 testRestfulProject\testRestfulProject\...
                    first = config.workspace_dir / candidate
                    resolved = (first if first.exists() else config.project_dir / candidate).resolve()
                # 用 relative_to 判断"在工作区内"：字符串 startswith 会被 D:\22project_evil
                # 这类同前缀目录绕过（inference._guard_path 也是这么做的，口径统一）
                try:
                    resolved.relative_to(config.workspace_dir.resolve())
                except ValueError:
                    raise InvalidInput("dataset_dir 必须在工作区内")
                options["dataset_dir"] = str(resolved)
            if epochs is not None:
                options["epochs"] = epochs
        except FileNotFoundError as exc:            # 数据目录不存在 / 目录里没有可用数据文件
            return {"error": str(exc),
                    "hint": "检查 dataset_dir 与 dataset_type；CWRU 默认目录是 1DCNN/0HP"}, 409
        except ValueError as exc:                   # 未知模型名、rate 不合法、表里没有数值列、基线文件缺失…
            # （含 InvalidInput —— 它是 ValueError 子类，两者都是"参数错 → 400 + 同一句话"，
            #   所以上面不需要再单独写一档 except InvalidInput）
            return {"error": str(exc)}, 400
        result = train(name, options)
        http = 200 if result["status"] == "成功" else 500
        if (result.get("db") or {}).get("written") is False:
            # 产物可能已经落盘、但库里没有 Trainings 行 —— 调用方必须知道，别只看 status
            result["warning"] = ("训练结果未写入数据库：" + str((result.get("db") or {}).get("error")))
        # ⚠️ POST /train 是**同步阻塞**的（创建即启动，训练完才返回），所以计划里
        #    "创建训练任务"和"启动训练"两行其实是**同一个接口**，不能记成两条日志，
        #    否则一次训练会产生两条几乎相同的记录，把日志表刷成两倍。
        # 这里按"训练完成"这个真实语义记一条，result（含准确率/耗时）落在 detail 里。
        _log_train_result(name, result)
        return result, http
class TrainingList(Resource):
    """GET /trainings?limit=N —— 最近训练记录（读库）。"""
    def get(self):
        return _recent_list("trainings", database.recent_trainings)
def _recent_list(key: str, fetch):
    """`GET /xxx?limit=N`（默认 20、上限 200）的"最近 N 条"读库接口，/trainings 与 /inference-tasks 共用。

    两个接口的方法体本来 12 行逐字重复，只差"取哪个 dict 键 / 调哪个 db 方法"。

    limit 语义：`_int()` 负责把缺参变默认 20（转不动则抛 InvalidInput），min(..., 200) 再夹上限，
    防止一次把整张表拉回来。
    ⚠️ 这里用的是 `_int(...) or 20` 这个 falsy 写法：limit=0 是 falsy，会被悄悄换成 20（不是 0 条）。
       对"最近 N 条"列表接口来说 0 条本来没意义，退成默认值与用户意图一致，所以这里可以接受；
       但同样的写法搬到 /predict 的 limit 上就是 bug（0 有语义），那边刻意不做 falsy 回退
       （见 Predict.post：`_int()` 取值 + 独立的范围校验）。两处写法不一致是**故意的**，别"统一风格"。
    ⚠️ 这里额外包了 try：`_int()` 转不动时会抛 InvalidInput（ValueError 子类），而 flask_restful 会把它
       变成 500（Flask 的 errorhandler 够不着，见 register_api 末尾）。?limit=abc 属于参数错，应当明确回 400。
    ⚠️ limit 最终由 db.py 用 f-string 拼进 `LIMIT {int(limit)}`：安全全靠 API 层保证它是"整数且 ≤200"，
       db 那边的 int() 只是最后一道兜底（拼接 SQL 的写法本身不该再扩散）。
    """
    try:
        limit = min(_int(request.args.get("limit"), 20, "limit") or 20, 200)
    except InvalidInput as exc:
        return {"error": str(exc)}, 400
    try:
        return {key: fetch(limit), "dialect": database.dialect}, 200
    except DBError as exc:
        # 读库失败 → 503 且带上 dialect：前端提示"数据库不可用"，而不是显示成"没有记录"
        return {"error": str(exc), "dialect": database.dialect}, 503
class TrainingList(Resource):
    """GET /trainings?limit=N —— 最近训练记录（读库）。"""
    def get(self):
        return _recent_list("trainings", database.recent_trainings)
def _log_failed_inference(name: str, exc: Exception, client_ip: str | None, body: dict) -> None:
    """推理失败时也写一条 `ModelInvocations`（is_success=0）。

    以前只有成功路径写调用日志（而且写在结果插入之后），输入校验被拒、模型缺产物这些
    更常见的失败反而零痕迹，排查时只剩 Flask 的 500 页面。

    注意**不能**为了写日志去 `ensure_model`：模型名打错就会凭空多出一行 Models 登记。
    只有"该模型已有训练记录"（能拿到 ModelID 满足外键）时才写。
    """
    # ⚠️ 这是函数内"懒导入"：本模块顶层其实已经 import 了 training，所以今天并不构成循环依赖，
    # 保持现状不影响行为（只有失败路径才会走到这里），别据此以为它跟 training 互相导入。
    from .training import db_model_name                     # 懒导入，避免与 training 循环依赖
    try:
        # name 先归一成 Models 表的正式名（用户可能传 1dcnn/中文别名）；
        # only_success=False 是刻意的：默认只认 Status='成功' 的训练行，若该模型唯一一次训练
        # 就是失败的，写日志的外键锚点会取不到，失败日志又变成零痕迹。
        row = database.latest_training(db_model_name(name), only_success=False)
        if not row:
            return
        # 状态码要和 Predict.post() 的异常分支逐一对应，否则日志里记 500、调用方收到 400，对不上账
        if isinstance(exc, FileNotFoundError):
            code = 409
        elif isinstance(exc, (InvalidInput, ValueError)):
            code = 400
        else:
            code = 500
        # ⚠️ request_params 必须剔除 samples：内联样本动辄几百 KB，整段塞进调用日志表会把库撑爆
        database.insert_invocation(
            model_id=int(row["ModelID"]), training_id=int(row["TrainingID"]), api_endpoint="/predict",
            request_params={k: v for k, v in body.items() if k != "samples"},
            response_result={"error": f"{type(exc).__name__}: {exc}"},
            duration_ms=None, is_success=False, status_code=code, client_ip=client_ip, status="失败")
    # 整段日志写入都是"尽力而为"：库连不上、表不存在、字段超长，统统只能吞掉。
    # 调用方 Predict 会在本函数返回后 re-raise 原始异常，日志里的二次异常绝不能把它盖掉。
    except Exception:                                        # 写日志失败绝不能盖掉原始异常
        pass
class Predict(Resource):
    """POST /predict —— 推理入口。**需要 predict:run 权限**。

    入参既可以是 samples（内联数组），也可以是 path（工作区内的文件）；
    成功返回结构化的 predictions + summary + figures + db 回执。
    """
    @require_perm("predict:run")
    def post(self):
        body = _body()
        try:
            # 推理允许"上传进来的模型名"（不在 1dcnn/cwt_cnn/adtk 别名表里），
            # 所以这里不做严格校验，交给 predict() 去解析产物目录。
            name = (body.get("model") or "").strip()
            if not name:
                raise InvalidInput("model 必填")
            # 写法要点：默认值交给 _int 的第二个参数（缺参就原样返回它），
            # **不能**写成 `_int(...) or 1` —— 0 是 falsy，会把用户明确传的 limit=0
            # 悄悄换成 1 放过去，于是绕过下面这条范围校验。
            limit = _int(body.get("limit"), 1, "limit")
            if not (1 <= limit <= MAX_LIMIT):
                raise InvalidInput(f"limit 必须在 1..{MAX_LIMIT} 之间")
            # index 必须 ≥0：负索引在 Python 切片里是"从尾部数"，会切出错位窗口却照样通过校验
            index = _int(body.get("index"), 0, "index")
            if index < 0:
                raise InvalidInput("index 不能为负数（窗口序号从 0 开始）")
            top_k = _int(body.get("top_k"), 3, "top_k")
            if not (1 <= top_k <= 50):
                raise InvalidInput("top_k 必须在 1..50 之间")
            try:
                payload = predict(
                    model=name,
                    samples=body.get("samples"),
                    path=body.get("path"),
                    index=index,
                    limit=limit,
                    training_id=_int(body.get("training_id"), None, "training_id"),
                    top_k=top_k,
                    write_db=bool(body.get("write_db", True)),
                    client_ip=request.remote_addr,
                    column=body.get("column"),
                    sheet=body.get("sheet"),
                )
            except Exception as exc:                 # 失败也要留一条调用记录，再原样抛出
                _log_failed_inference(name, exc, request.remote_addr, body)
                raise
        except FileNotFoundError as exc:
            return {"error": str(exc), "hint": "先调 POST /train 生成模型产物"}, 409
        except (DBError, ValueError) as exc:        # ValueError 已含 InvalidInput，不必单列一档
            return {"error": str(exc)}, 400
        except Exception as exc:                                   # pragma: no cover
            return {"error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-1500:]}, 500
        # 推理成功但落库失败时，必须让调用方看得见（以前是静默 200，只有前端自己去看 db.written）
        if (payload.get("db") or {}).get("written") is False:
            payload["warning"] = ("推理已完成，但结果未写入数据库："
                                  + str((payload.get("db") or {}).get("error")))
        return payload, 200
class InferenceTaskList(Resource):
    """GET /inference-tasks?limit=N —— 最近推理任务（读库）。"""
    def get(self):
        return _recent_list("tasks", database.recent_inference_tasks)
class InferenceTaskDetail(Resource):
    """GET /inference-tasks/<id> —— 单个任务 + 它的 InferenceResults 明细。"""
    def get(self, task_id):
        # ⚠️ 路由是 /inference-tasks/<int:task_id>：Werkzeug 的 int 转换器已经保证进来的是整数，
        # 非整数路径（/inference-tasks/abc）根本不会进这个方法，会直接 404。
        # 这里的 _int() 属于防御性统一写法（默认 None 时 DB 查不到自然走下面的 404）
        try:
            task = database.inference_task(_int(task_id, None, "task_id"))
        except DBError as exc:
            return {"error": str(exc)}, 503
        if task is None:
            return {"error": f"InferenceTaskID={task_id} 不存在"}, 404
        # db.inference_task() 一次把"任务头 + 该任务的全部 InferenceResults 明细"都查好了
        #（明细挂在返回值的 results 字段，按 ResultID 排序保证每次点开顺序一致）。
        # ⚠️ 明细**不分页**：一次推理如果写了上千个窗口，这个响应就是上千行；
        #    前端要自己分页/懒渲染，或者从源头限制一次写入的结果条数
        return task
# ------------------------------------------------------------ 模型名的"三套写法"
# 同一个模型在不同地方有三个名字，写错一个就会"找不到模型"或"建出重复行"：
#     1dcnn   ← 服务内部键（MODEL_META / _TRAINERS / 前端下拉的 value）
#     1DCNN   ← Models 表里的 ModelName（给人看、也写进 SQL 的正式名）
#     1dcnn   ← data/models/ 下的产物目录名（磁盘只认这个）
# 下面三个函数就是三套写法之间的换算器：凡是要"拿用户输入去查东西"，先过这里。
def _db_model_name(raw: str) -> str:
    """任意写法 → **Models 表里的正式名**（1dcnn / 1DCNN / cnn / 算法模型1 → 1DCNN）。

    `normalize_model` 只认别名表里那三个内置模型；上传进来的模型名不在表里，
    它会抛 ValueError，这时**原样返回** —— CRUD 场景本来就允许操作任意已登记的模型名。
    """
    from .training import db_model_name
    try:
        return db_model_name(normalize_model(raw))
    except ValueError:
        return raw
def _artifact_key(raw: str) -> str:
    """任意写法 → **产物目录名**（1DCNN → 1dcnn）。

    先换成正式名，再在 MODEL_META 里反查内部键；查不到（上传的模型）就退化成小写原名。
    注意返回的是**小写**键：磁盘目录就是小写，别拿它去写 Models 表。
    """
    name = _db_model_name(raw)
    return next((k for k, v in MODEL_META.items() if v["db_name"].lower() == name.lower()), name.lower())
def _safe_model_name(name: str) -> str:
    """模型名 → **磁盘安全形式**，非法字符**直接拒绝**而不是替换（改名用）。

    改名是有副作用的动作，静默把 `a/b` 变成 `a_b` 会让用户以为改成功了。
    同理不设默认名：清洗后为空就是"这个名字不能用"。
    """
    safe = _sanitize_name(name, "")
    if not safe:
        raise InvalidInput("模型名不合法（不能只有符号）")
    if safe != name:
        raise InvalidInput(f"模型名只能含中英文、数字、_ - .（收到 {name!r}）")
    return safe
def _rewrite_meta_model(directory: Path, model_name: str) -> None:
    """把 <目录>/meta.json 里的 `model` 字段改写成 model_name（改名与回滚共用）。

    ⚠️ 无条件改写，**不做** old→new 的相等判断：上传时写进 meta 的 model 大小写可能和目录名不一致
    （目录 1dcnn、meta 里写的 1DCNN），而 Windows 文件系统大小写不敏感，一比就"看起来相等"从而漏改，
    改名后 meta 里的模型名会永远停在老写法上。
    ⚠️ meta 损坏/非 JSON 直接跳过：改名是有副作用的长流程，为一个坏文件半途而废，
    会留下"目录搬了、meta 没改"这种更难解释的不一致。
    """
    meta_file = directory / "meta.json"
    try:
        payload = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(payload, dict):
        payload["model"] = model_name
        meta_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
def _rename_model(old: str, new: str) -> dict:
    """模型改名的**磁盘侧**动作：搬产物目录 + 改 meta.json + 改库里已存的路径。

    改名必须**同步四处**，少一处就出现"找得到一半、找不到另一半"的鬼状态：
      ① 产物目录      data/models/<老名> → data/models/<新名>
      ② 产物 meta     data/models/<新名>/meta.json 里的 model 字段
      ③ 库里的路径    Trainings.ModelPath / InferenceTasks.InputPath·OutputPath /
                      ModelDeployments.DeployedPath（实际由 db.rename_model_paths 按前缀 REPLACE）
      ④ Models 表行   ModelName（本函数**不管**，由调用方接着调 database.update_model(..., new_name=)）

    调用顺序（api 里就是这么用的）：先 _rename_model()，再 database.update_model(..., new_name=)；
    搬完目录后改库失败时用 _undo_rename() 搬回去，保证"库表"和"磁盘"不脱钩。
    **为什么先搬文件再改库**：搬目录是本地同盘 rename，几乎不会失败且失败原因一眼可见；
    而 update_model 要走网络+SQL（查重、外键、方言差异）。把易失败的放后面，失败时才有东西可回滚；
    反过来先改库的话，改库成功、搬目录失败，库里全是新路径、磁盘还是老目录，之后所有推理训练都 FileNotFoundError。
    """
    key = _artifact_key(old)                     # 真实目录名（1DCNN → 1dcnn）
    safe = _safe_model_name(new)
    old_dir, new_dir = config.model_dir / key, config.model_dir / safe
    moved = False                                # 真搬过目录才置位：没搬过就没什么可回滚的
    if old_dir.is_dir():
        # ⚠️ 用 exists() 而不是 is_dir()：同名位置被一个普通文件占着也照样不能搬，
        # 早点报错好过 Windows 上 rename 抛一个语焉不详的异常
        if new_dir.exists():
            raise InvalidInput(f"产物目录 data/models/{safe} 已存在，先删掉它或换个名字")
        old_dir.rename(new_dir)                  # 同一磁盘上的重命名，秒完成
        moved = True
        # 每个版本一个子目录（v1/v2/...），里面各有一份 meta.json，model 字段全部要跟着改
        _rewrite_meta_model(new_dir, safe)
    try:
        paths = database.rename_model_paths(key, safe)   # Trainings.ModelPath 等路径前缀
    except DBError:
        # 改库失败 → 把目录原样搬回去，宁可整体失败成一个"没改过名"的干净状态，
        # 也不能留下"库说新名、磁盘是老名"的脱钩（meta 与路径前缀由调用方的 _undo_rename 收尾）
        if moved:
            new_dir.rename(old_dir)
        raise
    # 返回值原样带在 PUT 响应里（改名与否、目录是否真的搬了、路径改了几行），供前端提示与排错
    return {"from": key, "to": safe, "artifact_dir_moved": moved,
            "artifact_dir": str(new_dir) if moved else None,
            "path_rows_updated": paths,
            "note": ("内置模型（1DCNN/cwt_cnn/adtk）改名后不能再按老名字训练——训练模板是硬编码的；"
                     "按新名字看档案/推理不受影响") if key in MODEL_META else None}
def _undo_rename(old: str, new: str) -> None:
    """update_model 失败时回滚 _rename_model 的副作用（目录 + meta + 路径）。

    这里是**回滚路径**，原则是"尽力恢复、绝不抛异常"：它是在异常处理里被调用的，
    再抛一个新异常会把真正的失败原因（改库为什么失败）彻底盖掉，且此时 _rename_model
    已经搬过目录，用户看到的现象会更乱。所以下面所有失败分支都是 return / pass。
    """
    key = _artifact_key(old)
    # ⚠️ 回滚路径不允许再抛异常（会盖掉"改库为什么失败"这个真正的错误），
    # 所以这里用不抛异常的 _sanitize_name（而不是会 raise 的 _safe_model_name），
    # 清洗不出来就退回原文照搬。
    safe = _sanitize_name(new, new)
    old_dir, new_dir = config.model_dir / key, config.model_dir / safe
    # 三个条件缺一不可：新目录得真的在、老目录不能已被别人占用（占用时宁可不动，避免把人家覆盖掉）、
    # 清洗后的名字确实和老名字不同（相同就没必要搬）
    if new_dir.is_dir() and not old_dir.exists() and safe != key:
        try:
            new_dir.rename(old_dir)
        except OSError:
            # 目录都搬不回去，后面改 meta/路径也没有意义，直接放弃整次回滚
            return
    # 与 _rename_model 对称：目录搬回老名后，各版本 meta 里的 model 也要写回老名
    _rewrite_meta_model(old_dir, key)
    # 路径前缀反向改回（rename_model_paths 是 REPLACE 前缀，反向调用即可复原）。
    # ⚠️ 这步和上面的目录搬回是相互独立的：能走到本函数，就说明 _rename_model 已经完整跑完
    # （它内部的 rename_model_paths 已经把库里路径改成新前缀了，否则会抛 DBError 而不是走到这），
    # 所以即使目录因为上面三个条件不满足而没搬回来，路径前缀也必须改回去。
    try:
        database.rename_model_paths(safe, key)
    except DBError:
        pass                                     # 回滚里的失败只能吞掉，别再抛出去盖住原始异常
class ArtifactDetail(Resource):
    """GET /models/<model_name> —— 查看某个模型产物的 meta.json；DELETE 见下。"""
    def get(self, model_name):
        """取产物档案。model_name 允许任意写法（1DCNN / 1dcnn / 上传名），先归一再查。"""
        # 先过 _artifact_key()：磁盘目录只认小写内部键，1DCNN / 上传名都得换算
        try:
            artifact = load_artifact(_artifact_key(model_name))
        except FileNotFoundError as exc:
            return {"error": str(exc)}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 400
        return artifact.to_dict()
    @require_perm("model:delete")
    def delete(self, model_name):
        """删除：?scope=artifact 删磁盘产物；?scope=record 删 Models 表登记行（带引用检查）。"""
        # 两种删除口径必须由调用方**显式选一个**：删的是磁盘产物，还是库表登记行？
        # 猜着删太危险（一个不可恢复、一个带外键引用检查），所以两个都没给就直接报错。
        # ⚠️ 以前是 `?version=vN` 删单个版本；产物已经拍平成"一个模型一份"，所以改成 scope。
        try:
            scope = (request.args.get("scope") or "").strip()
            if scope == "artifact":
                result = delete_artifact(_artifact_key(model_name))
                log_operation("delete_model", target=model_name, detail=result)
                return result, 200
            if scope == "record":
                force = request.args.get("force") in ("1", "true", "True")
                result = database.delete_model(_db_model_name(model_name), force=force)
                log_operation("delete_model_record", target=model_name,
                              detail={"force": force, **{k: v for k, v in result.items()
                                                         if k != "error"}})
                return result, 200
            raise InvalidInput("删除必须指定 ?scope=artifact（删磁盘产物）或 ?scope=record（删库表登记行）")
        except FileNotFoundError as exc:
            return {"error": str(exc)}, 404
        except DBError as exc:
            return {"error": str(exc)}, 409
        except ValueError as exc:                  # 含 InvalidInput（ValueError 子类）
            return {"error": str(exc)}, 400
    @require_perm("model:write")
    def put(self, model_name):
        """改 Models 表的登记信息：Description / ModelType / ApiEndpoint / Status / IsActive。

        带 `NewModelName`（或 `new_name`）时**连产物目录一起改名**：
        `data/models/<老名>` → `data/models/<新名>`，同时改产物 meta.json 里的 `model` 字段、
        以及 Trainings.ModelPath / InferenceTasks.InputPath 等已落库的路径前缀，
        避免出现"库表改名了、磁盘还是老目录"的脱钩状态。
        """
        body = _body()
        # ⚠️ old 走 _db_model_name()（库表口径，1DCNN）：库里存的是正式名，
        # 拿路径参数里的 1dcnn 直接去查会查不到行，改名就"成功"地改了个空。
        old = _db_model_name(model_name)
        # 兼容两种键名：前端 camel 风格的 NewModelName，和脚本里惯用的 new_name
        new_name = str(body.get("NewModelName") or body.get("new_name") or "").strip()
        rename = None
        try:
            # 名字没变（或没传）就只当普通的信息更新，不碰磁盘
            if new_name and new_name != old:
                # 查重放在搬目录之前：名字被占直接 409，别先动了磁盘才发现改不了
                if database.model_exists(new_name):
                    return {"error": f"模型名 {new_name} 已被占用，换一个"}, 409
                rename = _rename_model(old, new_name)
            try:
                result = database.update_model(old, body, new_name=new_name or None)
            except Exception:
                # 目录已经搬过去了、改库却失败 → 用 _undo_rename 把目录/meta/路径前缀搬回老名，
                # 再原样抛出，让下面的 except 翻译成正确的状态码
                if rename:
                    _undo_rename(old, new_name)           # 搬完目录但改库失败 → 原样搬回去
                raise
        except FileNotFoundError as exc:
            return {"error": str(exc)}, 404
        except DBError as exc:
            return {"error": str(exc)}, 409
        except ValueError as exc:                  # 含 InvalidInput（ValueError 子类）
            return {"error": str(exc)}, 400
        if rename:
            result["rename"] = rename
        # 改名要同时记下"从什么改成了什么"——只记新名字的话，拿旧名字反查日志会查不到。
        log_operation("update_model", target=new_name or old,
                      detail={"old_name": old, "new_name": new_name or None,
                              "renamed": bool(rename),
                              "fields": sorted(k for k in body if k not in ("NewModelName", "new_name"))})
        return result, 200
class ModelOverview(Resource):
    """一个模型的完整档案：登记信息 + 产物参数(meta) + 最近训练 + 引用统计。

    模型列表要同时显示「登记信息」与「模型参数」，并且选中某行要展开它自己的参数——
    分散在 4 个地方（Models 表 / Trainings 表 / 产物 meta.json / 引用关系），
    这里合并成一个响应，前端一次请求即可，不用自己拼。
    """
    def get(self, model_name):
        """一个模型的完整档案：登记 + 产物参数 + 最近训练 + 引用统计，一次请求给全。"""
        # name = 库表口径（Models.ModelName）；key = 磁盘口径（小写目录名）。
        # key 直接调 _artifact_key(model_name)：它内部就是"先 _db_model_name 再在 MODEL_META 反查"，
        # 与这里的 name 推导完全同源，原先就地内联只会多出一份要同步维护的副本。
        name = _db_model_name(model_name)
        key = _artifact_key(model_name)
        # ⚠️ 用 next(..., None) 而不是"查不到就 404"：允许"有产物但没登记"或"登记了还没训练"，
        # 档案页要能如实展示这种不一致（与 GET /models 刻意返回两份清单是同一个思路）。
        registration = next((r for r in database.models_in_db()
                             if str(r["ModelName"]).lower() == name.lower()), None)
        # ⚠️ list_artifacts() 会真的去遍历目录并读 meta.json，是磁盘 IO；一个模型只有一个产物，
        #    所以取第一条就是全部
        artifacts = list_artifacts(key)
        artifact = artifacts[0].to_dict() if artifacts else None
        params, metrics, labels, dataset, confusion = {}, {}, None, None, None
        if artifacts:
            meta = artifacts[0].meta
            params = meta.get("params") or {}
            metrics = meta.get("metrics") or {}
            labels = meta.get("labels")
            dataset = meta.get("dataset")
            confusion = meta.get("confusion")
        # 库层没有"按模型名查训练记录"的接口，只能拉最近 50 条再本地过滤，最后只留 5 条给前端
        trainings = [t for t in database.recent_trainings(50)
                     if str(t.get("ModelName", "")).lower() == name.lower()][:5]
        try:
            references = database.model_references(name)
        except DBError as exc:
            # 引用统计只是附带信息，库出错就降级成 error 字段，不能让整个档案页 500
            references = {"error": str(exc)}
        return {
            "model": name, "artifact_key": key,
            "registration": registration,
            "artifact": artifact,          # 该模型的唯一产物；还没有产物时是 None
            # ⚠️ metrics 里剔除 history（逐 epoch 的训练曲线），体积比其它指标大一个量级，
            # 曲线另有 /figures 的图片可看，档案页不需要它
            "params": params, "metrics": {k: v for k, v in metrics.items() if k != "history"},
            "labels": labels, "dataset": dataset, "confusion": confusion,
            "recent_trainings": trainings,
            "references": references,
        }, 200
class ModelUpload(Resource):
    """上传模型（文件夹，或者单个/多个文件）：落盘成 data/models/<模型名>/<版本>/ 并登记 Models 表。

    表单字段：`name`（模型名，必填）、`description`（可选）、`dataset`（可选），
    以及多个 `file`——浏览器既可以用 `<input type="file" webkitdirectory>` 选整个文件夹，
    也可以用普通 `<input type="file" multiple>` 选单个/多个文件，两条路走同一套逻辑
    （服务端按 basename 扁平化保存，丢掉相对路径）。

    **不再要求填 input_len / num_classes / labels**：
      1. 先按扩展名挑出权重候选，再用 probe_weight() 逐个做**内容探测**，判断"这是不是一个模型"；
         一个都不通过 → 400，并把每个文件被拒的原因一起返回（前端直接展示）；
      2. 通过的即权重文件，input_len / 类别数尽量从文件里读出来（Keras 解析 model_config，
         PyTorch 读最后一个全连接层的 weight 形状）；
      3. 文件夹里带 meta.json 就以它为准，只把缺失的 input_len/num_classes 补上。
    可选 scaler.npz；实在读不出 input_len 时 meta 里留 null，并在响应 warnings 里说明
    （推理侧按默认 784 处理，想固定就手动补 meta.json）。
    """
    MAX_MB = 500
    @require_perm("model:write")
    def post(self):
        """接收文件夹或若干文件，探测→落盘→登记 Models 表。

        四步：① 读进内存并分类 → ② 逐个内容探测、定权重 → ③ 落盘 + 写 meta.json → ④ 登记库 + 组装响应。
        ①③ 的逻辑分别收在 `_upload_blobs()` / `_upload_meta()` 里（本方法只留流程与错误映射）。
        """
        form = request.form
        name = (form.get("name") or "").strip()
        files = _uploaded_files()
        if not name:
            return {"error": "name（模型名）必填"}, 400
        if not files:
            return {"error": "没有收到文件（表单字段名用 file，可多选/整个文件夹）"}, 400
        safe = _sanitize_name(name, "model")
        # 1) 先把文件读进内存并分类，避免半途落盘
        blobs, skipped, candidates, scaler, meta_blob = _upload_blobs(
            files, KEEP_SUFFIXES, WEIGHT_SUFFIXES, self.MAX_MB)
        # 2) 判断"这是不是一个模型"：候选逐个做内容探测，第一个通过的当权重
        if not candidates:
            return {"error": "上传的内容里没有权重文件，不算模型（支持 .h5/.keras/.pt/.pth/.pkl/.pickle）",
                    "received": sorted(blobs), "skipped": skipped}, 400
        probed: list[dict] = []
        for filename, framework in candidates:
            info = probe_weight(filename, blobs[filename])
            probed.append({"filename": filename, "framework": info.get("framework") or framework,
                           "ok": info["ok"], "reason": info["reason"],
                           "input_len": info["input_len"], "num_classes": info["num_classes"]})
            if info["ok"]:
                # ⚠️ framework 必须**以探测结果为准**，不能再用后缀表猜的那个：
                #    `.pt` 底下其实有三种完全不同的 torch 格式（老式 state_dict / TorchScript /
                #    torch.export），后缀根本区分不了，只有打开包看内容才知道；
                #    而推理侧正是靠 framework 分派到对应的加载方式。用后缀表会把
                #    TorchScript 误标成 pytorch，于是推理时走到"重建架构"那条错路上去。
                weights, probe = (filename, info.get("framework") or framework), info
                break
        else:                       # 一个都没通过 → 不是模型（candidates 非空，所以只有"全不通过"会到这）
            return {"error": "上传的内容不是一个模型：没有任何文件通过权重校验",
                    "detail": probed, "skipped": skipped,
                    "hint": "支持 Keras 的 .h5/.keras（需含 model_weights 组或 config.json）、"
                            "PyTorch 的 .pt/.pth（torch 的 zip 检查点）、pickle 的 .pkl"}, 400
        # 2) 产物目录：一个模型一份，**重新上传 = 直接替换旧产物**（没有版本号可选）。
        #    先写进暂存目录，写完整了才换上去 —— 否则一次失败的上传会把上一份好产物毁掉。
        root, stage = begin_artifact(safe)
        replaced = (root / "meta.json").is_file()
        # 3) 落盘
        try:
            for filename, blob in blobs.items():
                (stage / filename).write_bytes(blob)
            # meta.json 只在这里写一次：用户带了就以他的为准，没带就按探测结果现造（_upload_meta 内部判断）
            meta, meta_generated = _upload_meta(form, safe, weights, probe, scaler, meta_blob)
            (stage / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            commit_artifact(root, stage)
        except Exception as exc:
            abort_artifact(stage)                  # 只清暂存，旧产物原封不动
            return {"error": f"落盘失败，已回滚：{type(exc).__name__}: {exc}"}, 500
        # 4) 登记 Models 表（同名就取用，不重复插）
        model_type = {"classification": "Classification", "anomaly_detection": "AnomalyDetection",
                      "regression": "Regression"}.get(str(meta.get("task") or "").lower(), meta.get("task"))
        db_error = None
        try:
            model_id = database.ensure_model(safe, description=form.get("description"),
                                             model_type=model_type, status="可运行")
        except DBError as exc:
            model_id, db_error = None, str(exc)
        warnings = []
        if replaced:
            warnings.append(f"这个模型之前已有产物，已被本次上传替换（旧产物不再保留）")
        if not meta.get("input_len"):
            warnings.append("没能自动识别输入长度（input_len），推理时按默认 784 处理；"
                            "想固定长度就在产物目录的 meta.json 里补一个 input_len")
        if meta.get("weights_file") and meta["weights_file"] != weights[0]:
            warnings.append(f"meta.json 声明的权重是 {meta['weights_file']}，探测选中的是 {weights[0]}（以 meta 为准）")
        # 记在 return 之前、**且只在成功路径上**（上面所有 4xx/5xx 分支都已 return 走了）。
        # replaced=True 说明这次上传覆盖了旧产物，写进 detail 便于事后追溯"谁把线上模型换掉了"。
        log_operation("upload_model", target=safe,
                      detail={"replaced": bool(replaced), "framework": meta.get("framework"),
                              "files": sorted(blobs), "size_kb": round(sum(len(v) for v in blobs.values()) / 1024, 1),
                              "db_written": db_error is None})
        return {
            "model": safe, "directory": str(root),
            "framework": meta.get("framework"), "weights": meta.get("weights_file") or weights[0],
            "input_len": meta.get("input_len"), "num_classes": meta.get("num_classes"),
            "labels": meta.get("labels"), "scaler": meta.get("scaler_file"),
            "meta_generated": meta_generated, "replaced": replaced,
            "probe": {"weights": weights[0], "framework": weights[1], "reason": probe.get("reason"),
                      "input_len": probe.get("input_len"), "num_classes": probe.get("num_classes")},
            "probed_files": probed,
            "saved": [{"filename": k, "size_kb": round(len(v) / 1024, 1)} for k, v in blobs.items()],
            "skipped": skipped, "warnings": warnings,
            "db": {"written": db_error is None, "ModelID": model_id, "ModelName": safe, "error": db_error},
            "hint": f"现在可以在「推理」里选 {safe}（输入长度 {meta.get('input_len') or '默认 784'}）",
        }, 201


def _uploaded_files():
    """multipart 里的文件列表：`file` 是主字段名，`files` 是同义旧写法（两个上传接口共用）。

    取不到就是空列表 —— 调用方据此回 400，不必自己判 None。
    """
    return request.files.getlist("file") or request.files.getlist("files")
def _upload_blobs(files, keep_suffix, weight_whitelist, max_mb):
    """把上传的文件读进内存并按用途分堆，返回 (blobs, skipped, candidates, scaler, meta_blob)。

    先按扩展名与大小筛一遍再 read()：整套流程是"先全部读进来、确认是模型、才落盘"，
    所以被忽略的文件既不占内存，也不该留下半个目录。
    """
    blobs: dict[str, bytes] = {}
    skipped: list[dict] = []
    candidates: list[tuple[str, str]] = []      # 权重候选：(文件名, 框架)，按上传顺序
    scaler = meta_blob = None
    for item in files:
        # 浏览器传文件夹时 filename 可能带 `子目录\文件`，统一削成纯文件名（顺带挡掉路径穿越）
        filename = Path((item.filename or "").replace("\\", "/")).name
        if not filename or filename.startswith("."):
            continue                            # 目录里的隐藏文件，静默忽略，不进 skipped
        suffix = Path(filename).suffix.lower()
        if suffix not in keep_suffix:
            skipped.append({"filename": filename, "reason": f"忽略非模型文件（{suffix or '无扩展名'}）"})
            continue
        blob = item.read()
        if len(blob) > max_mb * 1024 * 1024:
            skipped.append({"filename": filename, "reason": f"超过 {max_mb}MB"})
            continue
        blobs[filename] = blob
        if suffix in weight_whitelist:
            candidates.append((filename, weight_whitelist[suffix]))
        if filename == "scaler.npz":
            scaler = filename
        if filename == "meta.json":
            meta_blob = blob
    return blobs, skipped, candidates, scaler, meta_blob
def _upload_meta(form, safe, weights, probe, scaler, meta_blob):
    """决定落盘的 meta.json 内容，返回 (meta, generated)。

    用户带了 meta.json 就**以他的为准**（只补缺失项），没带就按探测结果现造一份；
    `generated` 回报"这份是我们生成的"，响应里的 meta_generated 用它。
    """
    if meta_blob:
        try:
            meta = json.loads(meta_blob.decode("utf-8"))
        except Exception:
            meta = None                         # 坏 JSON 当"没带"，退回自动生成，不让整个上传失败
        if isinstance(meta, dict):
            meta.setdefault("weights_file", weights[0])
            # ⚠️ 上传的 meta.json 是用户提供的，它自称 trusted 也不算数：强制标成不可信
            meta["trusted"] = False
            meta["provenance"] = "upload"
            for key in ("input_len", "num_classes"):   # meta 里缺的，用探测结果补齐
                if not meta.get(key) and probe.get(key):
                    meta[key] = probe[key]
            if scaler:
                meta.setdefault("scaler_file", scaler)
            return meta, False
    input_len = probe.get("input_len") or _int(form.get("input_len"), None, "input_len")
    num_classes = probe.get("num_classes") or _int(form.get("num_classes"), None, "num_classes")
    labels = [s.strip() for s in (form.get("labels") or "").split(",") if s.strip()]
    if not labels and num_classes == 10:       # CWRU 十类，标签直接给现成的
        labels = [label for _, _, label in sorted(ds.CWRU_0HP_CLASSES, key=lambda row: row[1])]
    return {
        "model": safe, "framework": weights[1],
        "task": "classification" if weights[1] != "adtk" else "anomaly_detection",
        "input_len": input_len, "num_classes": num_classes or (len(labels) or None),
        "labels": labels or None, "weights_file": weights[0],
        # scaler 只在收到名为 scaler.npz 的文件时才被置位（见 _upload_blobs），
        # 所以"没收到就是没有"——不需要再去磁盘上探一次
        "scaler_file": "scaler.npz" if scaler else None,
        "params": {"source": "uploaded"}, "metrics": {},
        "dataset": {"name": form.get("dataset") or None, "path": None, "stats": {}},
        "trained_at": None, "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "origin": "POST /models/upload",
        "trusted": False,                      # 上传的产物一律视为不可信：推理侧不会反序列化它的 .pkl
        "provenance": "upload",
        "probe": {"weights": weights[0], "framework": weights[1],
                  "input_len": probe.get("input_len"), "num_classes": probe.get("num_classes"),
                  "reason": probe.get("reason")},
    }, True
class ModelCreate(Resource):
    """POST /models —— 新增一条 Models 表登记（不训练，只是登记/占位）。"""
    @require_perm("model:write")
    def post(self):
        body = _body()
        # 两种键名都收：ModelName（库表风格，dvadmin 前端用）与 name（简化写法，脚本用）
        name = (body.get("ModelName") or body.get("name") or "").strip()
        if not name:
            return {"error": "ModelName 不能为空"}, 400
        # ⚠️ 这里**不做** _safe_model_name() 清洗：本接口只往 Models 表插一行、不碰磁盘，
        # 所以含 `/`、`..` 这种字符的名字也能登记成功；真正要拿名字当目录名的接口
        #（/models/upload、模型改名）才会做磁盘安全化并把非法字符拒掉。
        # 默认值写在参数里：ApiEndpoint 缺省 /predict、Status 缺省"未训练"（占位模型还没跑过训练）
        try:
            model_id = database.ensure_model(
                name, description=body.get("Description"), model_type=body.get("ModelType"),
                api_endpoint=body.get("ApiEndpoint") or "/predict", status=body.get("Status") or "未训练")
        except DBError as exc:
            # ⚠️ 注意 db.ensure_model() 是"有就取、没有就建"：**同名并不冲突**，它会直接返回已有的 ModelID，
            # 下面照样回 201（前端若想提示"已存在"，得自己拿 ModelID 去 /models 对账）。
            # 能走到这个 409 的是真正失败的情况：并发下两个请求同时插入撞唯一索引、字段超长、库不可用等
            return {"error": str(exc)}, 409
        # 201 Created，但"登记"不等于"有产物"：本接口不训练、不落盘
        #（要产物走 POST /models/upload 上传，或 POST /train 训练）
        return {"ModelID": model_id, "ModelName": name}, 201
class ModelReferences(Resource):
    """GET /models/<model_name>/references —— 删前引用体检：被哪些表引用了多少行。"""
    def get(self, model_name):
        # _db_model_name() 先归一（1dcnn / 中文别名 → Models 表里的正式名 1DCNN）：
        # 库里存的是正式名，拿磁盘口径的小写名去查会永远查不到行
        # 返回体形如 {ModelID, references: {表名: 引用行数}, total, deletable}：
        # deletable = (total == 0)，前端据此决定"删除"按钮能不能直接点，
        # 还是先提示"被 Trainings/InferenceTasks… 引用着"（引用不为 0 时删登记行会 409，
        # 必须带 ?force=true 才会连带清理，对应 ArtifactDetail.delete 的 ?scope=record&force=1）
        try:
            return database.model_references(_db_model_name(model_name)), 200
        except DBError as exc:
            # ⚠️ db 层遇到"这个名字不在 Models 表里"是抛 DBError 的，这里统一映射成 404：
            # 对调用方来说"模型不存在"属于资源不存在，不是服务故障
            return {"error": str(exc)}, 404


# ============================ 模型发布（导出下载） ============================
# 需求：把训练好的模型导出成文件供别人下载使用。
#
# ⚠️ 为什么不是"直接下载 data/models 里那个权重文件"：实测三种产物单独拿出去**全都用不了**
#    （1dcnn 缺 scaler.npz 就预测错、cwt_cnn 是 state_dict 缺结构就加载不出来、
#      adtk 的阈值是针对已标准化特征标定的）。所以发布物是**打包件**，
#    额外带上 README.md / requirements.txt / example_infer.py 三件套，
#    让"下载的人"真的能跑起来。打包细节见 exporter.py。
class ModelExportList(Resource):
    """GET /exports —— 全平台已发布的模型包清单（供「模型发布」独立页面）。

    与 `GET /models/<名>/exports` 的区别：那个是**单个模型**的发布历史，
    这个是**跨模型**的汇总页，一次把三样东西给全，前端一个请求就能渲染整页：

      1. 库里的发布记录（deployments）—— 权威档案：版本、来源训练、发布人、状态
      2. 磁盘上的包（packages）—— 事实：包还在不在、多大、什么时候生成
      3. 把两者**按模型分组**后的结果（groups）—— 前端直接按组渲染卡片

    ⚠️ 第 3 项是有意在后端算的：磁盘与库是两套数据源，"哪些包还在磁盘上"要拿
    DeployedPath 的文件名去对，这个匹配逻辑放在前端做会两边各写一份、还容易写错
    （Windows 反斜杠 vs POSIX 斜杠的坑）。所以后端算好再给。
    """
    def get(self):
        """全平台发布包汇总：按模型分组，标注每个包是否还在磁盘上。"""
        # ① 库记录。库挂了不该让整页 500 —— 磁盘上的包仍然可以列出来下载
        try:
            records = database.recent_deployments(limit=500)
            db_error = None
        except DBError as exc:
            records = []
            db_error = str(exc)

        # ② 磁盘包：逐个模型目录扫一遍，做成 {模型名: [包信息]}
        on_disk: dict[str, list[dict]] = {}
        for artifact in list_artifacts():
            on_disk[artifact.name] = list_packages(artifact.name)

        # ③ 按模型分组。分组以**库记录为主**，再补上"只在磁盘上、库里没有"的包
        groups: dict[str, dict] = {}

        def group_for(name: str) -> dict:
            """取（或建）一个模型的分组。**键用库表正式名**做规范化的显示名。"""
            if name not in groups:
                groups[name] = {"model": name, "deployments": [], "packages": [], "count": 0}
            return groups[name]

        for rec in records:
            name = rec.get("ModelName") or "（已删除的模型）"
            group_for(name)["deployments"].append(rec)

        # 把磁盘包归到分组里，并标出"库里有没有对应记录"
        recorded_names = {
            exporter_pkg_name(r) for r in records if r.get("DeployedPath")
        }
        for key, pkgs in on_disk.items():
            # 磁盘目录名是小写内部键（1dcnn），要换成库表正式名（1DCNN）才能与库记录并到一起。
            # 用 groups 里已有记录的模型名做匹配，匹配不上就用磁盘名（上传的模型可能没登记）
            display = next((g for g in groups if g.lower() == key.lower()), key)
            for pkg in pkgs:
                pkg = dict(pkg)
                pkg["recorded"] = pkg["package"] in recorded_names
                group_for(display)["packages"].append(pkg)

        for group in groups.values():
            # 库里标记为「已导出」且磁盘上确实存在的包，才算"可下载"
            group["downloadable"] = sum(
                1 for p in group["packages"] if p["recorded"])
            group["count"] = len(group["deployments"])
            group["packages"].sort(key=lambda p: p["created_at"], reverse=True)
            group["deployments"].sort(key=lambda r: r.get("DeploymentID") or 0, reverse=True)
            group["has_artifact"] = group["model"] in on_disk or any(
                g.lower() == group["model"].lower() for g in on_disk)

        total_pkgs = sum(len(p) for p in on_disk.values())
        payload = {
            "groups": sorted(groups.values(), key=lambda g: g["model"].lower()),
            "total": {
                "models": len(groups),
                "records": len(records),
                "packages_on_disk": total_pkgs,
                "size_kb": round(sum(
                    p["size_kb"] for pkgs in on_disk.values() for p in pkgs), 1),
            },
            "export_dir": "data/exports",
        }
        if db_error:
            payload["db_error"] = db_error
        return payload, 200


def exporter_pkg_name(record: dict) -> str:
    """从发布记录的 DeployedPath 里取出包文件名（只取最后一段）。

    ⚠️ 必须只取文件名：库里存的是**已脱敏的相对路径**，而磁盘上拿到的是绝对路径，
    两边前缀写法不一定一致；文件名为 `1dcnn-v1-20260917-184935.zip`，用它对齐最稳。
    """
    raw = str(record.get("DeployedPath") or "")
    return raw.replace("\\", "/").rstrip("/").split("/")[-1]


class ModelExport(Resource):
    """GET /models/<model_name>/exports —— 该模型的发布历史；POST —— 打包发布。"""
    def get(self, model_name):
        """列出该模型已发布的包：磁盘上的 zip（真实文件）+ 库里的发布记录。

        ⚠️ 两个来源都要给：磁盘是"包还在不在"的事实，库是"当初谁发布、来源哪次训练"的档案。
        只给一边都不完整——用户删过包而库记录还在，或反过来。
        """
        name = _db_model_name(model_name)
        try:
            key = _artifact_key(model_name)
        except ValueError as exc:
            return {"error": str(exc)}, 400
        try:
            records = database.recent_deployments(model_name=name, limit=200)
        except DBError as exc:
            records = []
            db_hint = str(exc)
        else:
            db_hint = None
        payload = {
            "model": name,
            "artifact_key": key,
            # 磁盘上的真实包（按文件名倒序）
            "packages": list_packages(key),
            # 库里的发布流水
            "deployments": records,
            "download_base": f"/models/{name}/exports",
        }
        if db_hint:
            # 库连不上不该让整个页面 500：磁盘上的包仍然可以列出来下载
            payload["db_error"] = db_hint
        return payload, 200

    @require_perm("export:run")
    def post(self, model_name):
        """打包发布：生成 zip → 写 ModelDeployments → 返回下载地址。

        请求体（都可选）：
            training_id  来源训练；不传则取该模型最近一次**成功**的训练
            version      版本号；不传则按已发布数量自动递增（v1/v2/…）
            description  备注，写进 Remark
            deployed_by  发布人
        """
        body = _body()
        name = _db_model_name(model_name)
        try:
            key = _artifact_key(model_name)
        except ValueError as exc:
            return {"error": str(exc)}, 400

        # ① 拿产物。没有产物就没有可发布的东西 → 404，并明确指出下一步做什么
        try:
            artifact = load_artifact(key)
        except FileNotFoundError as exc:
            return {"error": str(exc), "hint": "先在「模型管理」里训练或上传该模型，再来发布"}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 400

        # ② 定位 ModelID：发布记录要挂到 Models 行上（外键非空）
        try:
            registration = next((r for r in database.models_in_db()
                                 if str(r["ModelName"]).lower() == name.lower()), None)
        except DBError as exc:
            return {"error": str(exc), "dialect": database.dialect}, 503
        if registration is None:
            return {"error": f"模型 {name} 还没有在 Models 表登记，无法记录发布信息"}, 409
        model_id = int(registration["ModelID"])

        # ③ 来源训练。ModelDeployments.TrainingID 在 schema 里是 **NOT NULL 外键**，
        #    所以这里必须给出一个 TrainingID，不能留空。三步兜底：
        #      ① 请求显式给的 training_id（存在性校验，查不到就 400）；
        #      ② 该模型最近一次**成功**的训练（推理侧也是这个口径）；
        #      ③ 连成功记录都没有（产物来自上传、或历次训练全失败但磁盘上有产物）——
        #         退到该模型**最近一次任意状态**的训练，并在响应里如实提示"来源训练是失败的"。
        #    ⚠️ 为什么不对 ③ 直接报错：实测 adtk 这个模型 14 条训练记录**全部是失败**，
        #       但它磁盘上有可用的 detector.pkl（早期人工放进去的）。此时"不让发布"是错的——
        #       用户手里明明有一个能用的产物，我们却因为"查不到成功训练"而拒绝导出。
        #       所以兜底放行，但把真相写进 warnings，不假装它是成功训练来的。
        training = None
        training_warning = None
        try:
            requested_id = _int(body.get("training_id"), None, "training_id")
            if requested_id is not None:
                training = database.training_by_id(requested_id)
                if training is None:
                    return {"error": f"训练记录 TrainingID={requested_id} 不存在"}, 404
            else:
                training = database.latest_training(name, only_success=True)
                if training is None:
                    # 没有成功的训练：退到最近一次任意状态的，并明确告诉用户这是降级
                    training = database.latest_training(name, only_success=False)
                    if training is not None:
                        training_warning = (
                            f"{name} 没有成功的训练记录，发布记录挂到了最近一次"
                            f"「{training.get('Status')}」的训练（TrainingID={training['TrainingID']}）；"
                            f"请确认磁盘上的产物确实是你想发布的那个")
        except InvalidInput as exc:
            return {"error": str(exc)}, 400
        except DBError:
            training = None
        source_training_id = int(training["TrainingID"]) if training else None
        # TrainingID 非空是 schema 的硬约束：走到这里还是 None，说明连一条训练记录都没有
        # （模型是上传进来的、从未训练过）。这种情况**不能**在 ModelDeployments 里记发布——
        # 与其让它撞外键报 1452 那个难懂的错，不如在这里说清楚
        if source_training_id is None:
            return {
                "error": f"{name} 没有任何训练记录，无法写发布记录"
                         f"（ModelDeployments.TrainingID 是非空外键）",
                "hint": "先在「模型管理」里训练一次该模型，让 Trainings 表里有记录，再来发布",
            }, 409

        # ④ 版本号：显式给的优先，否则按已成功发布的数量递增
        try:
            version = str(body.get("version") or "").strip()
            if not version:
                version = exporter.next_version(key, database.count_deployments(model_id))
        except DBError as exc:
            return {"error": str(exc), "dialect": database.dialect}, 503

        # ⑤ 打包。失败也要留一条 DeployStatus='失败' 的记录（与 Trainings"失败也写一行"同口径），
        #    否则"发布失败了"这件事在库里没有任何痕迹
        device_id = None
        try:
            device_id = database.local_device_id()
        except DBError as exc:
            return {"error": str(exc)}, 409
        try:
            result = exporter.export_artifact(
                key, artifact, version, training=training, source_training_id=source_training_id,
                description=str(body.get("description") or "").strip() or None)
        except exporter.ExportError as exc:
            _record_failed_export(model_id, source_training_id, device_id, version, str(exc), body)
            return {"error": str(exc)}, 400
        except Exception as exc:                                   # noqa: BLE001
            _record_failed_export(model_id, source_training_id, device_id, version, repr(exc), body)
            return {"error": f"打包失败：{type(exc).__name__}: {exc}"}, 500

        # ⑥ 写发布记录。库写不进去就**先删掉刚打好的包**——否则磁盘上会留下一个
        #    "有文件、无记录"的孤儿包，用户以为发布成功了，实际库里查不到
        download_url = f"/models/{name}/exports/{result.package.name}"
        try:
            deployment_id = database.insert_deployment(
                model_id, source_training_id, device_id,
                version=version, version_alias="latest", environment="test",
                deployed_path=str(result.package), deploy_url=download_url,
                runtime_params={
                    "format": "native", "contents": [c["filename"] for c in result.contents],
                    "input_len": artifact.meta.get("input_len"),
                    "framework": artifact.framework,
                    "artifact_key": key,
                },
                deploy_status="已导出",
                deployed_by=str(body.get("deployed_by") or "model_service"),
                remark=str(body.get("description") or "").strip() or None)
        except DBError as exc:
            exporter.delete_package(key, result.package.name)
            return {"error": f"发布记录写入失败，已撤销本次导出：{exc}",
                    "dialect": database.dialect}, 503

        payload = result.to_dict()
        # ⚠️ download_url 必须用**库表正式名**（1DCNN），不能直接回包名拼接的那份：
        #    路由参数 next 请求要能原样传回来，用正式名最稳
        payload["download_url"] = download_url
        payload["deployment"] = {"DeploymentID": deployment_id, "Version": version,
                                 "VersionAlias": "latest", "DeployStatus": "已导出"}
        payload["source_training"] = {"TrainingID": source_training_id,
                                      "TrainName": training.get("TrainName") if training else None,
                                      "Status": training.get("Status") if training else None}
        if training_warning:
            payload["warnings"].append(training_warning)
        payload["hint"] = "下载后解压，先看 README.md；example_infer.py 可直接运行验证"
        log_operation("publish_model", target=name,
                      detail={"package": result.package.name, "version": version,
                              "training_id": source_training_id,
                              "size_kb": payload.get("size_kb")})
        return payload, 201


def _record_failed_export(model_id, training_id, device_id, version, error, body) -> None:
    """打包失败时补一条失败记录。**绝不能反过来把主流程带崩**，所以整个吞掉异常。

    ⚠️ training_id 可能为 None（走到"打包"这步之前训练已解析成功，所以正常不会），
    但这里是纯记录用途，宁可少写一条也不要再抛异常把 500 的成因盖掉。
    """
    if training_id is None:
        return
    try:
        database.insert_deployment(
            model_id, training_id, device_id, version=version, version_alias=None,
            environment="test", deploy_status="失败", error_message=error,
            deployed_by=str(body.get("deployed_by") or "model_service"))
    except Exception:                                              # noqa: BLE001
        pass


class ModelExportPackage(Resource):
    """GET /models/<model_name>/exports/<package> —— 下载发布包；DELETE —— 删除包。

    ⚠️ 路由注册顺序：本类必须排在 `/models/<model_name>` 之前。否则
    `/models/1DCNN/exports` 会被 ArtifactDetail 当成 model_name 吃掉（同一个坑见 _ROUTES 顶部注释）。
    """
    @require_login
    def get(self, model_name, package):
        """下载发布包。文件以附件形式返回，浏览器直接触发下载而不是打开。

        ⚠️ 这里只需要 require_login（不要求 export:run）：浏览和取用别人做好的
        模型包是**读**操作，现场操作员也该能下载。
        令牌从 `?token=` 来——浏览器 <a href> 带不了自定义请求头，见 auth._extract_token()。
        """
        try:
            key = _artifact_key(model_name)
            path = exporter.resolve_package(key, package)
        except exporter.ExportError as exc:
            return {"error": str(exc)}, 400
        except FileNotFoundError as exc:
            return {"error": str(exc)}, 404
        # send_from_directory 自带 Content-Length / ETag / Range，还能白拿 conditional 协商；
        # as_attachment=True 触发下载，download_name 显式给中文安全的名字
        return send_from_directory(
            str(path.parent), path.name, as_attachment=True, download_name=path.name,
            conditional=True)

    @require_perm("export:delete")
    def delete(self, model_name, package):
        """删除一个发布包（只删磁盘文件 + 把记录标成「已删除」，**不删库记录**）。

        保留记录是有意的：包没了，但"曾经发布过 v1"是历史事实，删记录会断掉审计链。
        """
        try:
            key = _artifact_key(model_name)
            result = exporter.delete_package(key, package)
        except exporter.ExportError as exc:
            return {"error": str(exc)}, 400
        except FileNotFoundError as exc:
            return {"error": str(exc)}, 404
        try:
            result["records_marked"] = database.mark_deployment_deleted(package)
        except DBError as exc:
            # 文件已经删了，这一步只是标记失败——如实回报，但不改状态码
            result["records_marked"] = 0
            result["db_error"] = str(exc)
        log_operation("unpublish_model", target=_db_model_name(model_name),
                      detail={"package": package, "records_marked": result.get("records_marked")})
        return result, 200


class ModelExportInspect(Resource):
    """GET /models/<model_name>/exports/<package>/inspect —— 看包里的目录结构。

    单独一个路径而不是给 ModelExportPackage.get 加查询参数（如 ?inspect=1）：
    查询参数看不见、也容易被忘，而"下载"和"看内容"是两件不同的事，各自一个 URL
    更直白；再说下载那条走的是 send_from_directory，混进分支反而别扭。
    """
    def get(self, model_name, package):
        """列出一个发布包 zip 里的文件（只读中央目录，不解压）。"""
        try:
            key = _artifact_key(model_name)
            return exporter.inspect_package(key, package), 200
        except exporter.ExportError as exc:
            return {"error": str(exc)}, 400
        except FileNotFoundError as exc:
            return {"error": str(exc)}, 404


class FigureList(Resource):
    """GET /figures —— 列出已生成的图（训练曲线/混淆矩阵/预测分布等）。"""
    def get(self):
        # 先按大 limit 取回来再按 model 过滤，避免"过滤后不足 limit 条"这种别扭语义
        # ⚠️ `_int()` 转不动会抛 InvalidInput（ValueError 子类），而项目没有全局异常处理器，
        #    不接住 ?limit=abc 就会变成 500；这里包一层回 400，`or 60` 的 falsy 语义保持原样。
        try:
            limit = min(_int(request.args.get("limit"), 60, "limit") or 60, 500)
        except InvalidInput as exc:
            return {"error": str(exc)}, 400
        model = request.args.get("model")
        # ⚠️ list_figures 内部是"按 mtime 倒序遍历 + 到 limit 就 break"，先截断后过滤会漏：
        # 某个模型的图可能排在 500 名之后，所以这里固定取满 500 再筛。
        # 代价是 >500 张图时只看得到最新的 500 张（图库大了要换成按目录筛选）
        items = list_figures(limit=500)
        if model:
            # 两种命中写法都要支持：file 是相对 FIG_DIR 的路径，可能与 model 同级（"1dcnn/x.png"），
            # 也可能嵌在子目录里（"runs/1dcnn/x.png"）
            items = [i for i in items if i["file"].startswith(f"{model}/") or f"/{model}/" in i["file"]]
        return {"count": len(items[:limit]), "figures": items[:limit],
                "hint": "图片可直接用返回的 url 在浏览器打开（GET /figures/<路径>）"}
class FigureFile(Resource):
    """GET /figures/<路径> —— 直接返回 PNG 文件（conditional=True 支持 304 缓存协商）。"""
    def get(self, relpath):
        # 直接把 PNG 交给 Flask 发文件：不用自己 open/read，还能白拿 Content-Length、ETag、
        # Range 这些头。conditional=True 让它处理 If-None-Match/If-Modified-Since → 命中时回 304，
        # 前端反复切页不再重复下载整张图。
        # ⚠️ relpath 直接来自 URL，穿越防护靠 send_from_directory 自己做的 safe_join
        # （规范化后若逃出 FIG_DIR 会抛 NotFound），所以别改成 Path(FIG_DIR / relpath).read_bytes() 那种写法
        return send_from_directory(FIG_DIR, relpath, conditional=True)
# class Console(Resource)（GET /ui，零构建单页控制台）已整类删除：它每次请求读盘吐 console.html，
# 与 Vue 前端功能重叠，属于第二套 UI。删除后 /ui 不再注册路由 → 返回 404。
# 备注：当初路径选 /ui 而不是 /console，是因为 Flask debug=True 时 Werkzeug 调试器独占 /console。
# 说明：原先这里还有一个 `class Root`，作用是让 `GET /` 返回与 `GET /api` 完全一样的索引
# （`return ApiIndex().get()`）。它已删除 —— flask_restful 一个资源可以挂多个 URL，
# 在 _ROUTES 里把 ApiIndex 同时注册到 "/" 与 "/api" 即可，少一个只为转发而存在的类。
# ============================ 数据集管理 / 数据展示 ============================
class DatasetDb(Resource):
    """GET/POST /datasets/db —— Datasets 表的登记记录：读 + 登记。"""
    def get(self):
        """列登记记录，顺带把 8 张表的行数一并返回（前端「库表登记」页要用）。"""
        # 一次请求给两样东西：Datasets 的登记行 + 各表行数（「库表登记」页要一起显示）
        try:
            return {"datasets": database.datasets_in_db(), "dialect": database.dialect,
                    "counts": database.table_counts()}, 200
        except DBError as exc:
            # ⚠️ 库连不上给 503 而不是 500，并且照样带上 dialect：前端要能显示"配的是 MySQL、但连不上"，
            # 而不是一个什么都不带的 500 —— 这类故障排查全靠这一句话
            return {"error": str(exc), "dialect": database.dialect}, 503
    @require_perm("dataset:write")
    def post(self):
        """登记一个数据集（同名则沿用已有行，响应里的 already_existed 标明是哪种）。"""
        body = _body()
        name = (body.get("name") or "").strip()
        if not name:
            return {"error": "name 不能为空"}, 400        # 登记是**幂等**的：同名数据集由 register_dataset 决定复用已有行，所以成功有两种状态码——
        # 201 = 新建，200 = 复用了已有行（响应里的 already_existed 就是判据，前端据此提示"已存在"）
        try:
            result = database.register_dataset(
                name=name, source=body.get("source"),
                class_count=_int(body.get("class_count"), None, "class_count"),
                sample_count=_int(body.get("sample_count"), None, "sample_count"),
                data_path=body.get("data_path"), description=body.get("description"))
        except DBError as exc:
            return {"error": str(exc), "dialect": database.dialect}, 503
        result["dialect"] = database.dialect
        # 登记是幂等的（同名复用已有行），两种成功要区分开：already_existed=True 说明
        # 这次并没有真的新建，日志里记成"登记"而不是"新建"，免得审计时以为多了一个数据集。
        log_operation("register_dataset", target=name,
                      detail={"already_existed": bool(result.get("already_existed")),
                              "class_count": body.get("class_count"),
                              "sample_count": body.get("sample_count"),
                              "source": body.get("source")})
        return result, 200 if result["already_existed"] else 201
class DatasetSignal(Resource):
    """取一段原始信号（降采样成数值数组），供「数据展示」画波形。

    既支持内置 .mat（CWRU DE 通道），也支持表格文件（.csv/.xlsx/.xls，可指定 column/sheet）。
    """
    def get(self):
        """取一段原始信号（已降采样成 points 个数值）。"""
        # 入参分工：dataset 决定"去哪个目录找"、file 决定"取哪个文件"、points/start 决定"取哪一段"
        dataset = request.args.get("dataset") or ""
        filename = request.args.get("file")
        if not filename:
            return {"error": "缺少 file 参数（数据集文件名）"}, 400
        # 采样点数两头都要夹：上万个点浏览器画不动，几十个点又看不出波形，所以夹在 200..4000。
        # ⚠️ 这里用了 `or 1500`（0/None 都会退到默认值）——points=0 本来就没意义，退默认可接受；
        # 但**别把这个写法照抄到 limit 那种 0 有语义的参数上**（Predict.post 里就专门避开了这个坑）
        # ⚠️ 这两个 _int 必须包在 try 里：转不动会抛 InvalidInput，而 flask_restful 会把它变成
        #    500 {"message": "Internal Server Error"}（Flask 的 errorhandler 够不着，见 register_api 末尾）。
        #    别处的参数错都回 400，这里漏包就会变成同一份 API 两种口径（?points=abc 曾经就是 500）。
        try:
            points = min(max(_int(request.args.get("points"), 1500, "points") or 1500, 200), 4000)
            # start 是"从第几个采样点开始取"，负数会让 Python 从尾部数（切出错位窗口），所以夹到 ≥0
            start = max(_int(request.args.get("start"), 0, "start"), 0)
        except InvalidInput as exc:
            return {"error": str(exc)}, 400
        column = request.args.get("column")
        sheet = request.args.get("sheet")
        # 1) 目录来自 dataset 键（内置 CWRU / 上传的表格数据集）
        directory = None
        if dataset in config.dataset_dirs:
            # 内置 .mat：键就是 CWRU_0HP 这类名字
            directory = config.dataset_dirs[dataset]
        elif dataset.startswith("表格:"):
            # 上传的表格集：列表页(DatasetList)回的 key 是 "表格:<目录名>"，这里切掉前缀还原成真实目录名
            directory = config.upload_dir / dataset.split(":", 1)[1]
        elif dataset:
            # 兜底：兼容直接传裸目录名的老调用（按 data/datasets/<名> 找）
            directory = config.upload_dir / dataset
        if directory is not None:
            try:
                # 数据集目录必须落在工作区内：否则 dataset=..\..\..\x 能读到工作区外的文件
                # （原来的写法只校验了"逃逸之后的目录"，等于没校验）
                directory.resolve().relative_to(config.workspace_dir.resolve())
            except ValueError:
                return {"error": f"非法的 dataset 参数：{dataset!r}（越出工作区）"}, 400
            # 先用 Path(filename).name 把 `..\..\secret.csv` 这类相对路径削成纯文件名（第一道），
            # 拼完再 resolve + 二次 relative_to(directory) 校验（第二道）——两道都得留：
            # 只靠 name 挡不住绝对路径，只靠 relative_to 又挡不住"目录本身就被指到工作区外"
            path = (directory / Path(filename).name).resolve()
            try:
                path.relative_to(directory.resolve())
            except ValueError:
                return {"error": f"文件不在该数据集目录内：{filename}"}, 400
        else:                                   # 2) 直接给工作区内的相对/绝对路径
            # dataset 为空：当成"给我工作区里的某个路径"，交给公共解析器（自带穿越防护与两级回退）
            try:
                path = _resolve_workspace_path(filename)
            except InvalidInput as exc:
                return {"error": str(exc)}, 400
        if not path.is_file():
            # 404 且只回报文件名：这里本来就没打算把绝对路径告诉调用方（响应出口还有一层脱敏兜底）
            return {"error": f"文件不存在：{path.name}"}, 404
        try:
            if tabular.is_table(path):
                # 表格：一列就是一段信号（column/sheet 由前端下拉选），标签直接用文件名推
                signal = tabular.read_signal(path, column=column, sheet=sheet)
                label = tabular.label_from_filename(path.name)
                class_id = None
                kind = "tabular"
            else:
                # .mat：读 CWRU 的 DE 通道，再拿文件名去 10 类表反查类别 ID
                # （反查不到就只保留 guess_label 的猜测标签、class_id 留 None，这不算错误）
                signal = ds.read_de_channel(path)
                # 拿文件名去 10 类表反查类别 ID；反查不到就只保留 guess_label 的猜测标签、
                # class_id 留 None，这不算错误
                hit = next((row for row in ds.CWRU_0HP_CLASSES if row[0] == path.name), None)
                label, class_id, kind = (hit[2], hit[1], "matlab") if hit else (ds.guess_label(path.name), None, "matlab")
        except Exception as exc:
            # 文件损坏、列名对不上、不是数值列……统一算"读不出来"：给 500 但带上原始异常类型，便于定位
            return {"error": f"读取信号失败：{type(exc).__name__}: {exc}"}, 500
        # 降采样分两步：stride = 总长//目标点数，保证"等间隔抽到的点数 ≥ points"，
        # 再 [:points] 截断成正好 points 个——比精确算步长再处理边界小数简单得多
        segment = signal[start:]
        stride = max(1, segment.size // points)
        values = segment[::stride][:points]
        # min/max/mean/std 都按**降采样后**的 values 算（不是整段原始信号）：前端画的正是这些点，
        # 统计口径必须和图一致，否则会出现"波形看着很平、均值却很大"。round 到 5 位是给 JSON 瘦身
        return {
            "dataset": dataset or None, "file": path.name, "file_path": str(path),
            "dataset_type": kind, "label": label, "class_id": class_id, "column": column, "sheet": sheet,
            "samples_in_file": int(signal.size), "start": start, "stride": stride,
            "points": int(values.size),
            "min": round(float(values.min()), 5), "max": round(float(values.max()), 5),
            "mean": round(float(values.mean()), 5), "std": round(float(values.std()), 5),
            "values": [round(float(v), 5) for v in values],
        }, 200
# ================================ 系统管理 ================================
class SystemInfo(Resource):
    """GET /system —— 运行信息：Python/平台、关键依赖版本、路径、库表行数、产物/图/日志 占用。"""
    def get(self):
        # 内部小工具：某个包读不到版本不能让整个 /system 500 —— 没安装算 None（前端显示"未安装"），
        # 其它异常退化成"读取失败"（安装元数据损坏之类，属于"知道有问题但不致命"）
        def dist_version(name):
            """查已安装包的版本；没装返回 None（前端显示"未安装"）。"""
            try:
                return version(name)
            except PackageNotFoundError:
                return None
            except Exception:                                            # pragma: no cover
                return "读取失败"
        # 三块"占用统计"：产物 / 图 / 日志。产物只算权重文件的大小（meta、scaler 都是小文件，
        # 而 a.weights 才是"这个模型有多大"的答案）；图和日志则是目录里所有文件的字节数之和
        artifacts = list_artifacts()
        figure_items = list_figures(limit=1000)
        logs = list(config.log_dir.glob("*.log"))
        # ⚠️ 只有数据库这一块允许"失败也继续"：ok=False 与 error 一起回，/system 页面照样能看到
        # 路径、依赖版本、产物占用——排查"库为什么连不上"时恰恰最需要这些，不能因为库挂了整页空白
        try:
            counts, db_ok = database.table_counts(), True
        except DBError as exc:
            counts, db_ok = {"error": str(exc)}, False
        return {
            # 这是"本机自检"页，runtime/packages/paths 给的就是真实环境值；路径的脱敏在响应出口
            # 由 _install_path_mask() 统一兜（绝对路径会被换成 <工作区>/<本机> 之类的占位符）
            "runtime": {"python": sys.version.split()[0], "executable": sys.executable,
                        "platform": platform.platform(), "machine": platform.machine()},
            "packages": {name: dist_version(name) for name in _PACKAGES},
            "paths": config.describe(),
            "database": {"dialect": database.dialect, "ok": db_ok, "counts": counts,
                         "bootstrap": database.last_bootstrap},
            "artifacts": {"count": len(artifacts),
                          "items": [{"model": a.name, "framework": a.framework,
                                     "weights": str(a.weights),
                                     "size_kb": round(a.weights.stat().st_size / 1024, 1)} for a in artifacts]},
            "figures": {"count": len(figure_items),
                        "total_kb": round(sum(f["size_kb"] for f in figure_items), 1), "dir": str(FIG_DIR)},
            "logs": {"count": len(logs),
                     "total_kb": round(sum(p.stat().st_size for p in logs) / 1024, 1),
                     "dir": str(config.log_dir)},
        }, 200
class SystemLogs(Resource):
    """GET /system/logs —— 训练日志文件列表（按修改时间倒序）。"""
    def get(self):
        # 倒序 = 最近写的日志排最前，前端下拉默认就落在"最近一次训练"上
        files = sorted(config.log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        # 只 stat 不读内容：日志动辄几十 MB，列表页只需要名字/大小/时间，读进来纯属浪费内存
        return {"dir": str(config.log_dir), "count": len(files), "logs": [
            {"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1),
             "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
            for p in files]}, 200
class SystemLogFile(Resource):
    """GET /system/logs/<name>?tail=N —— 看某个日志的尾部 N 行。"""
    def get(self, name):
        # 只接受纯文件名：挡掉 `../` 之类的路径，否则能读到日志目录之外的文件
        if Path(name).name != name:
            return {"error": "非法日志名"}, 400
        path = config.log_dir / name
        if not path.is_file():
            return {"error": f"日志不存在：{name}"}, 404
        # 尾部行数夹在 10..3000：1 行查不出问题，把整个日志丢给浏览器又会卡死
        tail = min(max(_int(request.args.get("tail"), 300, "tail") or 300, 10), 3000)
        # Keras 进度条写进日志的 ANSI 转义序列在浏览器里是乱码，这里统一剥掉。
        # ⚠️ errors="replace" 不能省：日志里混进 GBK 输出或二进制碎片时，严格解码会抛
        # UnicodeDecodeError 把整个接口打成 500；rstrip() 顺手吃掉 Windows 的 \r，否则前端显示空行
        lines = [_ANSI.sub("", ln).rstrip()
                 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
        return {"name": name, "size_kb": round(path.stat().st_size / 1024, 1),
                "total_lines": len(lines), "returned": len(lines[-tail:]), "lines": lines[-tail:]}, 200
class Maintenance(Resource):
    """POST /system/maintenance —— 维护操作（危险，前端红按钮 + 二次确认）。"""
    def post(self):
        # ⚠️ 白名单式分发：只有下面**显式写出来**的 target 才会被执行，绝不按字符串去拼函数名。
        # 新增维护动作时必须同时改这里的 if 和返回里的 supported 列表，
        # 否则前端会拿到"支持这个动作、却回 400"的矛盾提示
        target = (_body().get("target") or "").strip()
        if target == "figures":
            # 目前唯一的动作：清空图库（只删 data/figures 下的 png，不动模型产物、不动库表）
            return clear_figures(), 200
        # 白名单式：只认已知的 target，别的明确报错并回可选值
        return {"error": f"不支持的维护目标：{target!r}", "supported": ["figures"]}, 400
# ------------------------------------------------------------------ 路由表
# 这张表是**唯一的注册清单**，同时也是 GET /（= GET /api，「接口索引」页）的数据源。
# 加一条路由 = 在下面加一行：注册与索引不可能再脱钩。原先两边各写一份手抄清单，实际已经漂过两次
# —— 索引里挂着早已删除的 /todos，同时漏掉 4 条真实存在的路由。
#
# ⚠️ 顺序有讲究，别按"好看"重排：
#   · `/models` 出现两次是**故意的**：ModelList 只实现 GET、ModelCreate 只实现 POST，
#     flask-restful 按 HTTP 方法分发，两者不冲突（同一路径同一方法被两个资源类实现属未定义行为，
#     以后再加同 URL 的资源类，先确认方法不重叠）。
#   · 含变量段的 `/models/<model_name>` 与静态段 `/models/upload`、`/models/<model_name>/references`
#     混在一起时，更具体的静态规则必须先命中，否则 `/models/upload` 会被当成 model_name='upload'
#     丢给 ArtifactDetail（上传接口直接 404/400）。改这里的路径写法（例如把 <model_name> 换成
#     <path:...>）之后，务必实测 `/models/upload` 仍走 ModelUpload。
#   · ApiIndex 一次挂两个 URL（"/" 与 "/api"）：根路径原本有个只为转发而存在的 Root 类，已删除。
#   · ApiIndex 的 ("/", "/api") 是**一次 add_resource 挂两个 URL**：根路径原本有个只为转发而
#     存在的 Root 类，已删除。⚠️ 不能拆成两次 add_resource —— flask_restful 用"类名小写"当
#     endpoint，第二个同名 endpoint 会直接 AssertionError: View function mapping is overwriting
#     an existing endpoint function。
_ROUTES = (
    (ApiIndex, ("/", "/api")),
    (Health, ("/health",)),
    (ModelList, ("/models",)),
    (DatasetList, ("/datasets",)),
    (Train, ("/train",)),
    (TrainingList, ("/trainings",)),
    (Predict, ("/predict",)),
    (InferenceTaskList, ("/inference-tasks",)),
    (InferenceTaskDetail, ("/inference-tasks/<int:task_id>",)),
    (ArtifactDetail, ("/models/<model_name>",)),
    (ModelCreate, ("/models",)),
    (ModelUpload, ("/models/upload",)),
    (ModelReferences, ("/models/<model_name>/references",)),
    (ModelOverview, ("/models/<model_name>/overview",)),
    # ⚠️ 两条 exports 路由都必须排在 (ArtifactDetail, "/models/<model_name>") **之前**：
    #    否则 `/models/1DCNN/exports` 会被 ArtifactDetail 当成 model_name 吃掉（同一坑见上方注释）。
    #    `/models/<model_name>/exports` 比 `/models/<model_name>` 更具体，flask-restful 按
    #    注册顺序匹配，先注册的先命中。
    (ModelExport, ("/models/<model_name>/exports",)),
    (ModelExportPackage, ("/models/<model_name>/exports/<package>",)),
    # ⚠️ inspect 必须排在 `/exports/<package>` 之后但在 ArtifactDetail 之前：它更长、
    #    更具体，flask-restful 按注册顺序匹配，先注册的先命中。
    (ModelExportInspect, ("/models/<model_name>/exports/<package>/inspect",)),
    (ModelExportList, ("/exports",)),
    (FigureList, ("/figures",)),
    (FigureFile, ("/figures/<path:relpath>",)),
    (DatasetDb, ("/datasets/db",)),
    (DatasetSignal, ("/datasets/signal",)),
    (DatasetUpload, ("/datasets/upload",)),
    (TablePreview, ("/datasets/table",)),
    (SystemInfo, ("/system",)),
    (SystemLogs, ("/system/logs",)),
    (SystemLogFile, ("/system/logs/<name>",)),
    (Maintenance, ("/system/maintenance",)),
)
# 原先还注册过两条，已随"零调用"清理一起删除，别再往索引里补：
#   Console → "/ui"（零构建控制台，前端已改为纯 Vue 页面）
#   DatasetRecord → "/datasets/db/<int:dataset_id>"（单条登记行的查/改/删，前端只声明过
#     updateDataset/deleteDataset 却没有任何页面调用；登记的写入仍在 POST /datasets/db）
# GET /（及 /api）的索引里，各条路由的路径形态：把 Flask 的转换器写法换成更易读的占位符。
# 只影响「接口索引」页的显示，不参与路由匹配。
_PATH_DISPLAY = {"<int:task_id>": "<id>", "<path:relpath>": "<路径>", "<model_name>": "<model>",
                 "<name>": "<名>", "<package>": "<包名>"}


def api_root_segments() -> frozenset[str]:
    """所有业务接口路径的**第一段**（`/models/...` → `models`）。

    ⚠️ 用途只有一个：给 web.py 的 SPA 兜底路由判断"这个请求到底是不是接口"。
    背景：SPA 兜底 `/<path:path>` 会接住所有没注册的路径，
    于是一个**拼错接口名**的请求（比如 `/models/nope/nope`）会拿到一坨 HTML，
    前端 axios 报 "Unexpected token <"，排查时容易往语法错误上跑偏。
    有了这个集合就能识别出"第一段是已知资源名 → 这是接口，不是前端路由"，
    从而如实回 JSON 404。

    ⚠️ 从 `_ROUTES` **现算**而不是手写常量：手写那份一定会漂
    （加接口时忘了同步，于是新接口的 404 又变回 HTML）。
    ⚠️ 排除 `/` —— 它的第一段是空串，混进来会让所有路径都被当成接口。
    """
    segs = set()
    for _resource, paths in _ROUTES:
        for p in paths:
            first = p.strip("/").split("/")[0]
            if first and not first.startswith("<"):
                segs.add(first)
    return frozenset(segs)


def _route_index() -> dict[str, str]:
    """路径 → 用途说明，直接取各 Resource 的 docstring 首行（不再手抄一份）。

    同一个路径被两个资源类实现时（只有 `/models`：GET 与 POST）把两句话拼起来。
    """
    out: dict[str, str] = {}
    for resource, paths in _ROUTES:
        # docstring 首行往往自带 "GET /health —— " 前缀，而 UI 的「接口」列已经单独显示了路径，去掉它
        desc = (resource.__doc__ or "").strip().splitlines()[0]
        desc = re.sub(r"^(?:GET|POST|PUT|DELETE|GET/POST|GET/PUT/DELETE|GET/POST/PUT/DELETE)\s+\S+\s*——\s*", "", desc)
        desc = desc.replace("**", "").rstrip("。")     # 去掉行内强调标记与句末句号，拼接时更干净
        for path in paths:
            show = path
            for flask_form, readable in _PATH_DISPLAY.items():
                show = show.replace(flask_form, readable)
            out[show] = f"{out[show]}；{desc}" if show in out else desc
    return out
def register_api(api) -> None:
    """把 _ROUTES 里的资源挂到 flask_restful.Api 上（由 main.py 调用）。"""
    for resource, paths in _ROUTES:
        api.add_resource(resource, *paths)
    # ⚠️ 收尾必须调用它：脱敏挂在 app.after_request 上，跟资源注册顺序无关，
    # 但放在这里能保证"谁用 register_api 谁就自动带上出口脱敏"——漏挂一次，所有响应都在裸奔真实路径。
    # 注意这里传的是 flask_restful.Api 对象本身（_install_path_mask 内部自己取 api.app）
    _install_path_mask(api)          # 出口脱敏：响应里不再出现本机真实目录
    # ⚠️ 别试图用 @app.errorhandler(InvalidInput) 把各方法里的 try/except 收成一处：flask_restful
    # 先接管异常（Api.error_router → handle_error），非 HTTPException 一律变成 500，够不到 Flask。
    # 它只在 PROPAGATE_EXCEPTIONS 为真（debug/testing 打开）时才漏过去 —— 那会让同一份代码在
    # debug 与非 debug 下表现不同，比多写几行 try/except 危险。所以"参数错 → 400"就显式写在各方法里。
# ============================================ 响应脱敏：不把本机真实目录暴露给前端
# 只认"盘符 + 冒号 + 分隔符"（C:\ / d:/）：单字母能对上真实盘符，又能避开 http:// 这种多字母 scheme
_DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
def mask_private_paths(payload, workspace: str = "", home: str = ""):
    """递归把响应里的绝对路径换成"工作区内的相对路径"。

    路径散落在 30 多个字段里（`directory` / `weights` / `dataset.path` / `log_file` /
    `figures_dir` / `input_path` / `output_path` / 报错信息里的路径 …），逐个改必然漏，
    所以在**响应出口**统一兜一遍：

        D:\\22project\\testRestfulProject\\data\\models\\1dcnn\\v1
            → testRestfulProject\\data\\models\\1dcnn\\v1
        C:\\Users\\<用户名>\\...   → <用户目录>\\...
        E:\\其它盘\\...           → <本机>\\...

    注意只影响**显示**：前端要回传的路径（如 `dataset_dir`）变成"相对工作区"后，
    后端用 `project_dir / 相对路径` 仍能解析，训练/推理链路不受影响。
    """
    def fix(text: str) -> str:
        """把一段文本里出现的本机绝对路径换成占位符标签。"""
        # 整串正好等于工作区/用户目录时单独处理：走下面的前缀替换会得到空字符串，
        # 前端会显示成一个空字段（看起来像"没数据"），不如明确给个占位标签
        if workspace and text == workspace:
            return "<工作区>"
        if home and text == home:
            return "<用户目录>"
        # 先工作区、后用户目录：工作区命中的目标是"换成相对工作区的相对路径"（前端要回传这个口径，
        # 所以 label 是空串），用户目录只是兜底遮蔽成 <用户目录>——工作区放前面才不会被兜底规则先吃掉。
        # 且 \\ 与 / 两种分隔符都要试：同一个路径在不同接口里两种写法都存在；
        # 最后那个不带分隔符的 replace 兜"裸目录名"（文本正好以目录名结尾、后面没有分隔符的情况）
        for raw, label in ((workspace, ""), (home, "<用户目录>")):
            if raw:
                text = text.replace(raw + "\\", label).replace(raw + "/", label).replace(raw, label)
        # 工作区之外的其它盘符统一换成 <本机>/，保留目录结构（只藏机器信息，不丢可读性）。
        # 用 lambda 而不是字符串模板：替换串以反斜杠结尾会让 re.sub 抛 "bad escape (end of pattern)"
        return _DRIVE_RE.sub(lambda _match: "<本机>/", text)
    def walk(node):
        """递归遍历 JSON 结构，对每个字符串套 fix()；容器原样重建，其它类型不动。"""
        # 容器一律**重建**而不是就地改：响应对象可能还被别处引用，就地改会连带污染原数据；
        # tuple 也重建为 list —— JSON 序列化出来本来都是数组，形状不变。数字/布尔/None 原样放行
        if isinstance(node, str):
            return fix(node)
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, (list, tuple)):
            return [walk(item) for item in node]
        return node
    return walk(payload)
def _install_path_mask(api) -> None:
    """给 Flask app 挂一个 after_request：只处理 JSON 响应，图片/日志/SSE 原样放行。"""
    # flask_restful.Api 把 Flask app 挂在 .app 上；取不到（例如测试里塞了个假 api）就直接跳过，
    # 不要为了脱敏把注册流程搞崩
    app = getattr(api, "app", None)
    if app is None:                                              # pragma: no cover
        return
    # 这两个前缀在注册时算一次就够：after_request 每次响应都会跑，别在里面重复做 Path.home()
    workspace, home = str(config.workspace_dir), str(Path.home())
    @app.after_request
    def _mask_response(response):                                # noqa: ANN001
        """出口统一兜一遍脱敏，避免逐个字段改还漏掉。"""
        # ⚠️ 只碰 JSON 和 text/*，其它一律原样放行：
        #   · /figures/<路径> 返回的是 PNG 二进制，get_data(as_text=True) 会把字节解码坏（图片直接花掉）；
        #   · text/event-stream 是流式响应（SSE），set_data() 会把"流"截断成一次性响应。
        # 放在**出口**做而不是逐个字段改，是因为路径散落在 30 多个字段里
        # （directory/weights/dataset.path/log_file/input_path/报错信息……），逐个改必然漏
        mimetype = response.mimetype or ""

        # ⚠️⚠️ 必须跳过"文件直通"响应（direct_passthrough）——这是加静态托管时踩到的坑：
        #    send_from_directory() 返回的不是内存里的字符串，而是一个**打开的文件句柄**
        #    （werkzeug 的 FileWrapper），且 direct_passthrough=True。
        #    对这种响应调 get_data() 会直接抛：
        #        RuntimeError: Attempted implicit sequence conversion but the
        #        response object is in direct passthrough mode.
        #    后果不只是"某个接口坏掉"——**托管进来的每一个前端页面都会 500**：
        #    首页 index.html 是 text/html，正好落进下面 elif 那个分支。
        #    也就是说没有这一行，单端口托管等于完全不可用。
        #    判断用 direct_passthrough 而不是 is_streamed：后者对生成器也返回 True，
        #    而生成器响应是**可以**安全读的，用 is_streamed 会把该脱敏的漏掉。
        if response.direct_passthrough:
            return response

        if mimetype == "application/json":
            try:
                payload = json.loads(response.get_data(as_text=True) or "null")
            except Exception:                                    # 不是合法 JSON 就别动它
                # 解析不了（自拼的 JSON 片段、空 body）就原样放行：宁可漏一次脱敏，也不能把响应改坏
                return response
            # ensure_ascii=False 保住中文；重新 set_data 后 Content-Length 由 Flask 自己重算
            response.set_data(json.dumps(mask_private_paths(payload, workspace, home), ensure_ascii=False))
        elif mimetype.startswith("text/") and mimetype != "text/event-stream":
            # 日志尾部（/system/logs/<名>）里也有绝对路径，一起脱敏
            response.set_data(mask_private_paths(response.get_data(as_text=True), workspace, home))
        # ⚠️ 每个分支都必须返回 response：after_request 返回 None 会让后续处理拿到 None 响应直接崩
        return response

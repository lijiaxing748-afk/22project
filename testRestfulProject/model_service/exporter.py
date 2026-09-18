# -*- coding: utf-8 -*-
"""模型发布（导出下载）：把一个训练产物打成**自解释的 zip**，供别人拿去用。

为什么不能只导出权重文件 —— 实测 data/models/ 下的三种产物，单独拿出去**全都用不了**：

    1dcnn    model.keras 1243KB + scaler.npz   → 缺 scaler.npz 则振幅没归一化，预测结果是错的
    cwt_cnn  model.pt     398KB + scaler.npz   → model.pt 存的是 state_dict，没有网络结构就加载不出来
    adtk     detector.pkl    3KB               → pkl 里的阈值是针对**已标准化特征**标定的，缺变换参数就判错

所以"发布"的重点不在"导出一个文件"，而在**让外人真的能把这个模型跑起来**。据此，zip 里除了
权重本身，还必须带上三件套（都是本模块**现生成**的，不属于训练产物）：

    README.md         把 meta.json 翻译成人话：输入多长、标签什么顺序、为什么必须带 scaler
    requirements.txt  依赖与**运行环境里的真实版本**，避免照着装却装错版本
    example_infer.py  复制粘贴就能跑的最小示例，把"能不能用"从口头说明变成可执行验证

产物布局（一个训练产物一个包，互不覆盖，见 ModelDeployments.TrainingID）：

    data/exports/<模型名>/<模型名>-<版本>-<时间戳>.zip

⚠️ 路径脱敏必须在这里手动做一次：api.mask_private_paths() 挂在 app.after_request 上，
   那是**响应出口**；而本模块是把 meta.json 写进 zip **文件**，根本不经过响应出口。
   漏了不会报错，只会静默把开发机的目录结构发给下载者。
"""
from __future__ import annotations
import importlib.metadata
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import config
from .registry import Artifact

# 各框架需要额外附带的"结构/说明"文件。
#
# ⚠️ **只有 pytorch 需要**，keras 不需要 —— 这是实测出来的结论，别想当然地对齐：
#    · PyTorch：training.py 存的是
#          torch.save({"state_dict": model.state_dict(), ...})
#      只有权重张量。网络结构来自项目里的 cwt_cnn/cwt_cnn_pytorch.py 的 build_model()，
#      外人手里没有那个文件，torch.load 出来的 state_dict 根本无处可挂。
#    · Keras：.keras 是 zip，实测内含 config.json（class_name=Functional，带全部 layers
#      定义），**结构自带**，load_model() 直接就能重建。再附一份 1DCNN.py 是噪音，
#      而且那份脚本还会把 tensorflow 拖进 import 链，对使用者是负担。
#
# 所以这里刻意**不给 tensorflow-keras 配条目**。若哪天换成"只存权重"的保存方式，
# 再往这里加条目即可。
#
# ⚠️ **必须连同项目内的兄弟模块一起打包**，否则打出来的包根本 import 不过去 ——
#    这是实测踩到的坑：cwt_cnn_pytorch.py 第 23 行有 `import preprocess`，
#    而 preprocess.py 就在同一个目录里。只发 cwt_cnn_pytorch.py 的话，外人一执行就
#    `ModuleNotFoundError: No module named 'preprocess'`（本机的 venv 里能 import 成功，
#    是因为 training.py 的 _import_project_module() 把 cwt_cnn/ 插进了 sys.path，
#    这个便利**在别人的机器上不存在**）。
#
# 键是 registry.Artifact.framework 的取值；值是 (源目录, [(源文件名, 包内文件名), ...])。
_ARCH_FILES = {
    "pytorch": ("cwt_cnn", [
        ("cwt_cnn_pytorch.py", "model_arch.py"),
        # preprocess 是 model_arch 的项目内依赖（import preprocess），必须跟着走
        ("preprocess.py", "preprocess.py"),
    ]),
}

# adtk 模型的 detector.pkl 里存的是 **adtk 库自己的类实例**
# （实测：adtk.detector._detector_hd.PcaAD、adtk.transformer._transformer_hd.PcaReconstructionError），
# 而 adtk/ 是本项目自带的目录、**pip 里装不到**（实测 venv/Lib/site-packages 下没有 adtk，
# 所以 build_requirements 也读不到它的版本号）。
# 别人解压后 pickle.load 会因为解析不到这两个类而 ModuleNotFoundError，
# 所以必须把 adtk 包一起打进 zip。
#
# 只带"能被 import 链真正载入的"那部分：实测反序列化 pkl 会载入 20 个 adtk.* 模块、
# 对应下面 6 个子包 + 5 个顶层模块，共 19 个 .py。
# 刻意**不带**的（占了 adtk/ 一半以上体积，且与加载无关）：
#   · adtk/tests/      —— 17 个测试文件，127 KB
#   · adtk/dataset/    —— 15 个示例 csv，adtk 的演示数据
#   · adtk/data/       —— 只有 _data.py 被 import，data/ 下的 csv 不需要
_ADTK_PKG = "adtk"
_ADTK_INCLUDE = (
    # 顶层模块（不带 __init__.py：adtk/ 是 namespace package，本来就没有）
    ("_base.py",), ("_utils.py",), ("_detector_base.py",), ("_transformer_base.py",),
    ("_aggregator_base.py",),
    # 子包（每个都必须带 __init__.py，否则不是包）
    ("aggregator", "__init__.py"), ("aggregator", "_aggregator.py"),
    ("data", "__init__.py"), ("data", "_data.py"),
    ("detector", "__init__.py"), ("detector", "_detector_1d.py"), ("detector", "_detector_hd.py"),
    ("metrics", "__init__.py"), ("metrics", "_metrics.py"),
    ("pipe", "__init__.py"), ("pipe", "_pipe.py"),
    ("transformer", "__init__.py"), ("transformer", "_transformer_1d.py"),
    ("transformer", "_transformer_hd.py"),
)


def _add_adtk_package(zf: "zipfile.ZipFile", contents: list[dict], warnings: list[str]) -> None:
    """把 adtk 包按需裁进 zip 的 `adtk/` 目录下。

    ⚠️ 不打包整个 adtk/：那会把 tests/（17 个文件 127 KB）和 dataset/（15 个示例 csv）
    一起塞进去，包体积翻几倍，而它们对"加载 detector.pkl"一点用都没有。
    这里按实测出来的 import 链白名单复制（见 _ADTK_INCLUDE）。
    """
    root = config.project_dir / _ADTK_PKG
    if not root.is_dir():
        warnings.append(f"⚠️ 找不到 adtk 包（{_ADTK_PKG}/），本包缺少检测器依赖，"
                        f"外人 pickle.load 会失败")
        return
    missing = []
    added = 0
    for parts in _ADTK_INCLUDE:
        src = root.joinpath(*parts)
        if not src.is_file():
            missing.append("/".join(parts))
            continue
        # zip 内路径统一用正斜杠，且保持 adtk/xxx 的包结构 —— 解压后才能直接 import adtk
        arcname = f"{_ADTK_PKG}/" + "/".join(parts)
        zf.write(src, arcname)
        contents.append({"filename": arcname, "size_kb": round(src.stat().st_size / 1024, 1)})
        added += 1
    if missing:
        warnings.append(f"⚠️ adtk 包缺少这些文件：{', '.join(missing)}；本包可能不完整")
    if added:
        warnings.append(
            f"已附带 adtk 运行库（{added} 个文件）到包内 adtk/ 目录 —— "
            f"detector.pkl 里存的是 adtk 的类实例，没有这个目录 pickle.load 会失败。"
            f"解压后请在**包的根目录**下运行 example_infer.py，不要移动 adtk/")

# 除了权重之外，产物目录里这些文件也要一起打包（有则带）
_EXTRA_ARTIFACT_FILES = ("scaler.npz",)

# 打包时忽略的产物目录内文件：meta.json 会重新生成（脱敏后），不要原样带
_SKIP_FROM_ARTIFACT = {"meta.json"}

# requirements.txt 里按框架声明哪些包（版本在生成时从当前环境读，不写死）
_REQUIRED_PACKAGES = {
    "tensorflow-keras": ["tensorflow", "keras", "numpy"],
    "pytorch": ["torch", "numpy"],
    "adtk": ["adtk", "pandas", "numpy", "scikit-learn"],
}


class ExportError(RuntimeError):
    """发布打包失败（上层据此回 409/500 并写入 ModelDeployments.ErrorMessage）。"""


@dataclass
class ExportResult:
    """一次发布的产出：包文件 + 内容清单 + 需要提醒使用者的话。"""
    model: str
    version: str
    package: Path                                  # zip 的绝对路径
    contents: list[dict] = field(default_factory=list)   # [{filename, size_kb}]
    warnings: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        """包体大小（KB）。打包后包一定存在，取不到就报错而不是编个 0。"""
        return round(self.package.stat().st_size / 1024, 1)

    def to_dict(self) -> dict:
        """给接口用的字段（download_url 由 api 层拼，这里只管磁盘事实）。"""
        return {
            "model": self.model,
            "version": self.version,
            "package": self.package.name,
            "size_kb": self.size_kb,
            "contents": self.contents,
            "warnings": self.warnings,
        }


# ------------------------------------------------------------------ 版本与目录
def next_version(model: str, existing: int) -> str:
    """算下一个版本号：该模型已有 N 个发布包 → v(N+1)。

    registry.py 已经去掉了"版本目录层"（一个模型只有一个产物），所以版本号不能从磁盘推，
    只能由**发布次数**推——调用方传 ModelDeployments 里该模型的行数。
    """
    return f"v{int(existing) + 1}"


def export_dir(model: str) -> Path:
    """某个模型的发布包目录 data/exports/<模型名>/（不存在则建）。"""
    safe = _safe_component(model)
    directory = config.export_dir / safe
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe_component(name: str) -> str:
    """净化会拼进路径的片段（模型名、版本号、包名）。

    ⚠️ 不能省这一步：模型名既来自别名表，也可能来自"上传的任意模型名"，而它会被拼成路径。
    与 registry._model_dir() 同一套规则，但这里必须**独立再挡一次**——发布包目录在
    data/exports 下，跟 data/models 是两棵树，不能指望那边的校验顺带保护这边。
    """
    clean = str(name or "").strip()
    if not clean or ".." in clean or "/" in clean or "\\" in clean:
        raise ExportError(f"非法的名字 {name!r}：不能含路径分隔符或 ..")
    if not re.match(r"^[\w\u4e00-\u9fa5.\-]+$", clean):
        raise ExportError(f"非法的名字 {name!r}：只允许中英文、数字、_ - .")
    if clean.startswith("."):
        raise ExportError(f"非法的名字 {name!r}：不能以点开头")
    return clean


def resolve_package(model: str, package_name: str) -> Path:
    """把 URL 里的包名解析成磁盘路径，并**二次确认**它没逃出该模型的发布目录。

    ⚠️ package_name 直接来自 URL。只靠 _safe_component 挡不住所有写法（比如
    编码过的分隔符），所以按 delete_artifact() 的老办法：resolve 之后比对父目录。
    """
    directory = export_dir(model).resolve()
    candidate = (directory / _safe_component(package_name)).resolve()
    if candidate.parent != directory or not candidate.is_file():
        raise FileNotFoundError(f"发布包不存在：{package_name}")
    return candidate


def list_packages(model: str) -> list[dict]:
    """列出某个模型已发布的包（按文件名倒序 = 时间倒序），附带大小与时间。"""
    directory = config.export_dir / _safe_component(model)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.zip"), reverse=True):
        stat = path.stat()
        out.append({
            "package": path.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return out


def inspect_package(model: str, package_name: str) -> dict:
    """看一个发布包**里面有什么**：列出 zip 内条目，不解压、不落盘。

    给「模型发布」页的「看内容」用：让人在下载前就知道包里有模型、meta.json、
    README.md、example_infer.py 这些，而不是拿到一个文件名就下载。

    ⚠️ 用 ZipFile.namelist() 只读中央目录，不读文件内容 —— 包可能上百 MB，
    逐个解压出来看结构纯属浪费。所以这里也不报告"解压后大小"。
    """
    import zipfile

    path = resolve_package(model, package_name)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    files = [{"path": n, "dir": n.endswith("/")} for n in sorted(names) if not n.endswith("/")]
    return {
        "package": package_name,
        "model": model,
        "size_kb": round(path.stat().st_size / 1024, 1),
        "created_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "files": files,
        # 关键文件名给前端做「有没有 README / 例子」的提示，省得前端自己扒字符串
        "has_readme": any(n.lower() == "readme.md" for n in names),
        "has_example": any(n.lower() == "example_infer.py" for n in names),
    }


def delete_package(model: str, package_name: str) -> dict:
    """删除一个发布包（只删 zip，不动库记录——记录的清理由 api 层决定）。"""
    path = resolve_package(model, package_name)
    size_kb = round(path.stat().st_size / 1024, 1)
    path.unlink()
    return {"deleted": package_name, "freed_kb": size_kb}


# ------------------------------------------------------------------ 脱敏
_DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")


def _mask_paths(payload):
    """把结构里的本机绝对路径改成相对写法。

    ⚠️ 这是 api.mask_private_paths() 的**必要重复实现**，不是冗余：那边挂在
    app.after_request（响应出口）上，而这里是把 meta 写进 **zip 文件**，不经过响应出口。
    逻辑保持与那边一致（工作区 → 相对路径；其它盘符 → <本机>/），但**不复用它的函数**——
    那个函数属于 api 层的响应处理，exporter 反过来 import api 会绕成循环依赖。

    meta.json 里真实存在这些字段：dataset.path、dataset.stats.baseline_source、log_file。
    """
    workspace = str(config.workspace_dir)
    home = str(Path.home())

    def fix(text: str) -> str:
        if workspace and text == workspace:
            return "<工作区>"
        if home and text == home:
            return "<用户目录>"
        for raw, label in ((workspace, ""), (home, "<用户目录>")):
            if raw:
                text = text.replace(raw + "\\", label).replace(raw + "/", label).replace(raw, label)
        return _DRIVE_RE.sub(lambda _m: "<本机>/", text)

    def walk(node):
        if isinstance(node, str):
            return fix(node)
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [walk(i) for i in node]
        return node

    return walk(payload)


# ------------------------------------------------------------------ 三件套生成
def _pkg_version(name: str) -> str | None:
    """读当前环境里某个包的真实版本；没装就返回 None（不编造版本号）。"""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def build_requirements(framework: str) -> str:
    """生成 requirements.txt。

    ⚠️ 版本号必须从**运行环境**读，不能写死：写死的话以后升级了环境，
    包里写的还是旧版本，外人照着装反而装出一个不匹配的组合。
    """
    wanted = _REQUIRED_PACKAGES.get(framework) or ["numpy"]
    lines = [
        "# 由「模型管理平台」自动生成：加载本包所需的 Python 依赖。",
        "# 版本取自打包时的运行环境，按需调整。",
        "# 安装：pip install -r requirements.txt",
        "",
    ]
    for pkg in wanted:
        version = _pkg_version(pkg)
        # 装了的带版本锁，没装（或读不到）的就只写包名，让 pip 自己挑——
        # 编一个版本号出来比不写更糟，别人会照着装失败
        lines.append(f"{pkg}=={version}" if version else pkg)
    return "\n".join(lines) + "\n"


def build_readme(model: str, artifact: Artifact, training: dict | None,
                 version: str, source_training_id: int | None) -> str:
    """生成 README.md —— 把 meta.json 翻译成"人话"。

    这些字段必须出现在 README 里，否则外人拿到权重无法正确使用：
      · input_len  —— 不给就没法把原始振动信号切成模型要的窗长
      · labels     —— 不给则 0..9 这些数字无从解释成具体故障
      · scaler     —— 不说清楚就有人跳过标准化，预测结果会**静默错误**
    """
    meta = artifact.meta or {}
    labels = meta.get("labels") or []
    task = meta.get("task") or "classification"
    framework = artifact.framework
    has_scaler = (artifact.directory / "scaler.npz").is_file()

    lines = [
        f"# {model} 模型使用说明",
        "",
        f"> 由「模型管理平台」自动生成 · 发布版本 **{version}** · 框架 `{framework}`",
        "",
        "## 这是什么模型",
        "",
        f"- **模型名**：{model}",
        f"- **框架**：{framework}",
        f"- **任务类型**：{'时序异常检测（无监督）' if task == 'anomaly_detection' else '故障分类（有监督）'}",
        f"- **权重文件**：`{artifact.weights.name}`",
    ]
    if source_training_id:
        lines.append(f"- **来源训练**：TrainingID = {source_training_id}"
                     + (f"（{training.get('TrainName')}）" if training and training.get("TrainName") else ""))
    if training:
        if training.get("Accuracy") is not None:
            lines.append(f"- **测试集准确率**：{training['Accuracy']}")
        if training.get("Loss") is not None:
            lines.append(f"- **训练损失**：{training['Loss']}")

    lines += ["", "## 用之前必须知道的参数", ""]

    input_len = meta.get("input_len")
    lines.append(f"- **输入长度（input_len）**：`{input_len if input_len else '未记录，请按训练时配置'}`")
    if input_len:
        lines.append(f"  - 模型接受**一维**信号，每条样本必须是 **{input_len}** 个点；")
        lines.append(f"  - 原始长信号请按该长度滑窗切分（窗口长度 = {input_len}）。")

    num_classes = meta.get("num_classes")
    if task != "anomaly_detection":
        lines.append(f"- **类别数**：`{num_classes or '—'}`")
    if labels:
        lines += ["- **标签顺序（输出下标 → 故障类型）**：", ""]
        lines += ["  | 下标 | 类型 |", "  | --- | --- |"]
        lines += [f"  | {i} | {label} |" for i, label in enumerate(labels)]
        lines.append("")

    if has_scaler:
        lines += [
            "## ⚠️ 必须一起使用 scaler.npz",
            "",
            "`scaler.npz` 里是**训练时用的标准化参数**（`mean` / `scale`）。推理前必须先用它把原始信号",
            "换算到训练时的分布，否则输入尺度和训练时不一致，**预测结果会静默错误**",
            "（不报错，但准确率大幅下降）。",
            "",
            "```python",
            "import numpy as np",
            "sc = np.load('scaler.npz')",
            "x = (x_raw - sc['mean']) / sc['scale']",
            "```",
            "",
        ]

    if task == "anomaly_detection":
        lines += [
            "## 判定方式（异常检测）",
            "",
            "本模型是无监督异常检测，**没有类别标签**。它输出一个异常分数，",
            "与 `detector.pkl` 内部已标定的阈值比较后得到「正常 / 异常」：",
            "",
            "- 分数与阈值都在反序列化后的对象里，见 `example_infer.py`；",
            "- 阈值是在**训练时那批正常数据**上按分位数标定的，换数据分布需要重新标定。",
            "",
            "### ⚠️ 为什么包里有一个 adtk/ 目录",
            "",
            "`detector.pkl` 里存的是 **adtk 库自己的类实例**（`PcaAD`、`PcaReconstructionError`），",
            "而 adtk 不是 pip 上的包，所以本包**自带了一份精简的 adtk 运行库**。",
            "",
            "- 解压后请在**包的根目录**下运行 `example_infer.py`；",
            "- **不要删除或移动 `adtk/` 目录**，否则 `pickle.load` 会报 `ModuleNotFoundError`；",
            "- 该目录只含加载检测器所必需的模块（不含测试与示例数据），可以随包一起分发。",
            "",
            "另外，检测器的判定需要先把窗口转成**统计特征**（参数都在 `detector.pkl` 里：",
            "`sampling_rate` / `feature_mode` / `bands`），不能直接喂原始振动信号。",
            "",
        ]

    lines += [
        "## 怎么用",
        "",
        "1. 安装依赖：`pip install -r requirements.txt`",
        "2. 直接跑示例：`python example_infer.py`",
        "3. 接入自己的代码：参照 `example_infer.py`，注意上面的 input_len 与 scaler",
        "",
    ]
    if "model_arch.py" in _framework_extras(framework):
        lines += [
            "## ⚠️ 关于 model_arch.py",
            "",
            f"`{framework}` 的权重文件里**只有权重、没有网络结构**，所以本包额外附带了",
            "`model_arch.py`（网络结构定义）。加载时必须**先建模型、再灌权重**：",
            "",
            "```python",
            "from model_arch import build_model        # 网络结构在这里",
            "model = build_model(...)                  # 先按同样参数建出结构",
            "model.load_state_dict(torch.load('model.pt')['state_dict'])",
            "```",
            "",
            "⚠️ `model_arch.py` 内部还会 import 同目录下的其它项目文件（如 `preprocess.py`），",
            "**这些文件必须和它放在同一个目录里，一个都不能删**，否则一执行就报",
            "`ModuleNotFoundError`。",
            "",
        ]

    lines += [
        "## 包里有什么",
        "",
        "| 文件 | 说明 |",
        "| --- | --- |",
    ]
    for item in _pack_descriptions(artifact, framework):
        lines.append(f"| `{item[0]}` | {item[1]} |")
    lines += [
        "",
        "---",
        "",
        "本包由「模型管理平台」的发布功能生成。`meta.json` 保留了完整原始元数据",
        "（训练超参、数据集指纹、指标），需要更多细节可查阅它。",
        "",
    ]
    return "\n".join(lines)


def _artifact_files(artifact: Artifact) -> list[dict]:
    """产物目录里将要打包的文件清单（权重 + scaler 等），返回 [{filename, size_kb}]。"""
    out = []

    def add(path: Path, name: str | None = None):
        if path.is_file():
            out.append({"filename": name or path.name, "size_kb": round(path.stat().st_size / 1024, 1)})

    add(artifact.weights)
    for extra in _EXTRA_ARTIFACT_FILES:
        add(artifact.directory / extra)
    return out


def _framework_extras(framework: str) -> set[str]:
    """该框架需要附带哪些额外文件（zip 内文件名）。"""
    spec = _ARCH_FILES.get(framework)
    return {dest for _src, dest in spec[1]} if spec else set()


def _pack_descriptions(artifact: Artifact, framework: str) -> list[tuple[str, str]]:
    """`包里有什么` 表格的行：文件名 → 说明。"""
    rows: list[tuple[str, str]] = []
    for item in _artifact_files(artifact):
        name = item["filename"]
        if name == "scaler.npz":
            rows.append((name, "标准化参数，**推理前必须使用**（见上文）"))
        else:
            rows.append((name, "模型权重"))
    for name in sorted(_framework_extras(framework)):
        if name == "model_arch.py":
            rows.append((name, "网络结构定义，**加载权重时必需**"))
        else:
            # 结构文件的项目内依赖（如 preprocess.py）：别人删了同样会 import 失败
            rows.append((name, "网络结构的依赖模块，**不能删**"))
    rows += [
        ("meta.json", "完整元数据（训练超参、数据集指纹、指标）"),
        ("README.md", "本文件"),
        ("requirements.txt", "Python 依赖"),
        ("example_infer.py", "最小可运行示例"),
    ]
    if framework == "adtk":
        rows.append(("adtk/", "精简版 adtk 运行库，**加载检测器必需，不能删**"))
    return rows


def build_example_infer(model: str, artifact: Artifact, training: dict | None) -> str:
    """生成 example_infer.py —— 复制粘贴就能跑的最小示例。

    按框架分三套模板。这不是"锦上添花"：老师的需求是"供别人使用"，
    而"别人能不能真的跑起来"只有一段可执行代码能证明。
    """
    meta = artifact.meta or {}
    input_len = meta.get("input_len") or 784
    num_classes = meta.get("num_classes") or 10
    framework = artifact.framework
    has_scaler = (artifact.directory / "scaler.npz").is_file()
    header = [
        '"""',
        f"{model} 推理示例 —— 由「模型管理平台」自动生成。",
        "",
        "用法：pip install -r requirements.txt && python example_infer.py",
        '"""',
        "import numpy as np",
        "",
        f"INPUT_LEN = {input_len}",
    ]
    if has_scaler:
        header += [
            "",
            "# ⚠️ 训练时用了标准化，推理必须复用同一套参数，否则预测结果会静默错误",
            "SCALER = np.load('scaler.npz')",
            "",
            "",
            "def normalize(x):",
            "    return (x - SCALER['mean']) / SCALER['scale']",
        ]

    if framework == "tensorflow-keras":
        body = [
            "",
            "",
            "def load_model():",
            "    import tensorflow as tf",
            f"    return tf.keras.models.load_model('{artifact.weights.name}')",
            "",
            "",
            "def main():",
            "    model = load_model()",
            f"    # 造一条 {input_len} 点的假信号；换成你自己的数据即可",
            f"    x = np.random.randn({input_len}).astype('float32')",
        ]
        if has_scaler:
            body.append("    x = normalize(x)")
        body += [
            "    x = x.reshape(1, INPUT_LEN, 1)          # (batch, length, channels)",
            "    proba = model.predict(x, verbose=0)[0]",
            "    index = int(np.argmax(proba))",
            f"    labels = {meta.get('labels') or []}",
            "    name = labels[index] if labels else str(index)",
            "    print(f'预测类别: {index} ({name})  置信度: {proba[index]:.4f}')",
            "    print('各类别概率:', np.round(proba, 4).tolist())",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
        ]
    elif framework == "pytorch":
        body = [
            "",
            "",
            "def load_model():",
            "    import torch",
            "    # ⚠️ 权重文件里只有 state_dict，没有网络结构 —— 结构在 model_arch.py 里",
            "    from model_arch import build_model",
            f"    model = build_model(num_classes={num_classes}, length=INPUT_LEN)",
            f"    ckpt = torch.load('{artifact.weights.name}', map_location='cpu')",
            "    model.load_state_dict(ckpt['state_dict'])",
            "    model.eval()",
            "    return model",
            "",
            "",
            "def main():",
            "    import torch",
            "    model = load_model()",
            f"    x = np.random.randn({input_len}).astype('float32')",
        ]
        if has_scaler:
            body.append("    x = normalize(x)")
        body += [
            "    tensor = torch.from_numpy(x).float().reshape(1, 1, INPUT_LEN)",
            "    with torch.no_grad():",
            "        logits = model(tensor)",
            "        proba = torch.softmax(logits, dim=1)[0].numpy()",
            "    index = int(np.argmax(proba))",
            f"    labels = {meta.get('labels') or []}",
            "    name = labels[index] if labels else str(index)",
            "    print(f'预测类别: {index} ({name})  置信度: {proba[index]:.4f}')",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
        ]
    else:                                    # adtk / 未知框架：按无监督检测器给
        body = [
            "import pickle",
            "import pandas as pd",
            "",
            "",
            "def main():",
            f"    with open('{artifact.weights.name}', 'rb') as fh:",
            "        bundle = pickle.load(fh)",
            "    # ⚠️ 反序列化会用到包内 adtk/ 目录里的类，所以必须在**包的根目录**下运行，",
            "    #    并且不要移动/删除 adtk/ 目录。",
            "    print('检测器      :', bundle.get('detector_name'))",
            "    print('判定阈值    :', bundle.get('threshold'))",
            "    print('输入长度    :', bundle.get('length'))",
            "    print('采样率      :', bundle.get('sampling_rate'))",
            "    print('特征模式    :', bundle.get('feature_mode'))",
            "    print('特征维度    :', bundle.get('feature_dim'))",
            "    print('训练用列    :', bundle.get('columns'))",
            "",
            f"    x = np.random.randn({input_len}).astype('float32')",
            "    # ⚠️ 检测器是在**已标准化的统计特征**上标定的，不能直接喂原始信号：",
            "    #    需要先用 bundle 里的参数（sampling_rate/bands/feature_mode）",
            "    #    把窗口转成统计特征，再交给 transformer/detector 算异常分数。",
            "    #    完整流程可参考平台后端的 model_service/inference.py（_predict_adtk）。",
            "    print()",
            "    print('已成功加载检测器。要真正判定，请按上面提示组装特征后调用：')",
            "    print('    score = bundle[\"detector\"].score(feature_frame)')",
            "    print('    is_anomaly = score > bundle[\"threshold\"]')",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
        ]
    return "\n".join(header + body) + "\n"


# ------------------------------------------------------------------ 打包主流程
def export_artifact(model: str, artifact: Artifact, version: str,
                    training: dict | None = None, source_training_id: int | None = None,
                    description: str | None = None) -> ExportResult:
    """把一个产物打成 zip，返回 ExportResult（**不写数据库**，库由调用方写）。

    暂存后原子替换：zip 先写到 .staging-<时间戳> 目录里再搬正，避免留下半个坏包被下载到
    （与 registry.begin_artifact/commit_artifact 同一思路，但那份是给产物目录用的，
    这里作用在 data/exports 上，所以另写一份而不复用）。
    """
    safe = _safe_component(model)
    directory = export_dir(safe)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    package_name = f"{safe}-{_safe_component(version)}-{stamp}.zip"

    stage = directory / f".staging-{stamp}-{datetime.now().strftime('%f')}"
    stage.mkdir()
    warnings: list[str] = []
    contents: list[dict] = []
    try:
        staged_zip = stage / package_name
        with zipfile.ZipFile(staged_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # ① 权重 + scaler 等产物文件（原样复制，不做格式转换 —— 决策 B）
            for path, name in _collect_artifact_files(artifact):
                zf.write(path, name)
                contents.append({"filename": name, "size_kb": round(path.stat().st_size / 1024, 1)})

            # ② meta.json：**脱敏后重新生成**，不直接复制磁盘上那份
            meta = _mask_paths(dict(artifact.meta or {}))
            meta["export"] = {
                "version": version,
                "packaged_at": datetime.now().isoformat(timespec="seconds"),
                "source_training_id": source_training_id,
                "description": description,
                "platform": "模型管理平台",
            }
            blob = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr("meta.json", blob)
            contents.append({"filename": "meta.json", "size_kb": round(len(blob) / 1024, 1)})

            # ③ 网络结构文件（决策 C）：pytorch 不带它就永远加载不出来。
            #    ⚠️ 连同项目内的兄弟模块一起发（见 _ARCH_FILES 的说明）：只发主文件的话，
            #    外人执行会 ModuleNotFoundError —— 本机能 import 是因为 sys.path 被改过。
            spec = _ARCH_FILES.get(artifact.framework)
            if spec:
                src_dir, files = spec
                missing = []
                for src_name, dest_name in files:
                    src = config.project_dir / src_dir / src_name
                    if not src.is_file():
                        missing.append(src_name)
                        continue
                    zf.write(src, dest_name)
                    contents.append({"filename": dest_name, "size_kb": round(src.stat().st_size / 1024, 1)})
                if missing:
                    # 缺文件是**必须让用户知道**的降级，否则包看起来正常却根本跑不起来
                    warnings.append(
                        f"⚠️ 找不到 {'/'.join(missing)}（{src_dir}/ 下），本包不完整，"
                        f"外人可能无法加载 {artifact.weights.name}")
                else:
                    warnings.append(
                        f"{safe} 的权重文件里只有权重、没有网络结构，已附带 "
                        f"{', '.join(d for _s, d in files)}（来自 {src_dir}/）；"
                        f"加载时必须先建模型再 load_state_dict")

            # ⑤ adtk 包（只有 adtk 框架需要）：detector.pkl 里是 adtk 的类实例，
            #    没有这个目录 pickle.load 直接失败。见 _add_adtk_package 的说明
            if artifact.framework == "adtk":
                _add_adtk_package(zf, contents, warnings)

            # ⑥ 三件套（现生成）
            for name, text in (
                ("README.md", build_readme(safe, artifact, training, version, source_training_id)),
                ("requirements.txt", build_requirements(artifact.framework)),
                ("example_infer.py", build_example_infer(safe, artifact, training)),
            ):
                zf.writestr(name, text.encode("utf-8"))
                contents.append({"filename": name, "size_kb": round(len(text.encode("utf-8")) / 1024, 1)})

        staged_zip.rename(directory / package_name)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)         # 失败只清暂存，已发布的老包不受影响
        raise
    else:
        shutil.rmtree(stage, ignore_errors=True)

    if not (artifact.directory / "scaler.npz").is_file() and artifact.framework != "adtk":
        # 分类模型没有 scaler 不是错误（训练时可能没开标准化），但值得提一句
        warnings.append(f"{safe} 的产物里没有 scaler.npz，"
                        f"如果训练时用了标准化，这个包无法复现原结果")

    return ExportResult(model=safe, version=version, package=directory / package_name,
                        contents=contents, warnings=warnings)


def _collect_artifact_files(artifact: Artifact):
    """产物目录里要打进包的文件：权重在前，其余按白名单。

    白名单而不是"目录下全部文件"是有意的：产物目录里可能躺着训练产生的中间文件
    （日志、图、临时件），全打进去会让包体积和内容都失控。
    meta.json 排除在外 —— 它由 export_artifact 脱敏后重新生成。
    """
    out = [(artifact.weights, artifact.weights.name)]
    for extra in _EXTRA_ARTIFACT_FILES:
        path = artifact.directory / extra
        if path.is_file() and path.name not in _SKIP_FROM_ARTIFACT and path != artifact.weights:
            out.append((path, path.name))
    return out

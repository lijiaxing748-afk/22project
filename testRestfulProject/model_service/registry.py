# -*- coding: utf-8 -*-
"""模型产物（流程图里的「Pxl模型」盒子）。

原来两个训练脚本跑完就把模型丢在内存里，没有 model.save / torch.save，
所以「Pxl模型」这个盒子在磁盘上根本不存在，Trainings.ModelPath 也无值可填。
本模块定义一套极简的产物约定 —— **一个模型只有一个产物目录，没有版本号**：

    data/models/<模型名>/model.keras      ← Keras 原生格式
    data/models/<模型名>/model.pt         ← PyTorch state_dict
    data/models/<模型名>/detector.pkl     ← 无监督检测器（adtk 的 PcaAD）
    data/models/<模型名>/scaler.npz       ← 训练期标准化参数（推理必须复用）
    data/models/<模型名>/meta.json        ← 输入长度、类别表、指标、超参、数据集指纹

meta.json 一定要带类别表：否则模型文件本身无法解释 0..9 到底对应哪种故障。

⚠️ 为什么去掉了 v1/v2 版本层：本项目只用**最新**产物，而版本号要一路渗进接口
（?version= 参数）、前端（版本列）、图片目录（figures/<名>/vN/）与文档，
每处都得同步、每处都能写错；实际使用中从来没有人真的去挑一个旧版本推理。
重新训练 = 直接替换该模型的产物目录。旧的多版本目录由
`_archive_legacy_versions()` 一次性搬去 data/archive/model_versions/（不删）。
"""
from __future__ import annotations
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from .config import config
_WEIGHT_NAMES = ("model.keras", "model.pt", "detector.pkl", "model.h5")
# 模型名允许的字符：中英文、数字、下划线、点、横线（见 _model_dir 的安全说明）
_MODEL_NAME_RE = re.compile(r"^[\w\u4e00-\u9fa5.\-]+$")
@dataclass
class Artifact:
    """一个已落盘的模型产物：**定位信息**（目录 / 权重文件）+ **自解释信息**（框架 / meta）。

    它不是"模型对象"，只是磁盘上那堆文件的**句柄**——推理时按 `weights` 加载、
    按 `framework` 决定用哪个引擎、按 `meta["input_len"]` 决定切多长的窗。
    """
    name: str                 # 模型名（同时也是 data/models 下的目录名，如 1dcnn）
    directory: Path           # 产物目录的绝对路径 data/models/<名>/
    weights: Path             # 权重文件绝对路径（model.h5 / model.pt / detector.pkl）
    framework: str            # tensorflow-keras / pytorch / adtk —— 推理分派靠它
    meta: dict = field(default_factory=dict)   # meta.json 的完整内容（见模块头）
    def to_dict(self) -> dict:
        """挑出给接口/前端用的字段（meta 里的原始 dict 太大，不透传）。

        只挑这些字段是有意为之：`/models` 会一次列出所有模型，
        把整份 meta（含 history 曲线、classification_report 文本）塞进去会让响应膨胀几十倍。
        """
        return {
            "model": self.name,
            "framework": self.framework,
            "weights": str(self.weights),
            "directory": str(self.directory),
            "input_len": self.meta.get("input_len"),
            "num_classes": self.meta.get("num_classes"),
            "labels": self.meta.get("labels"),
            "metrics": self.meta.get("metrics"),
            "params": self.meta.get("params"),
            "dataset": self.meta.get("dataset"),
            "created_at": self.meta.get("created_at"),
        }
def _model_dir(name: str) -> Path:
    """模型名 → 产物目录。**必须净化**。

    模型名既可能来自别名表，也可能来自"上传的任意模型名"，而它会被直接拼进路径。
    不净化的话 `../../x` 能读到工作区外的目录，推理时还会对这些文件做反序列化 ——
    等于给了一个任意文件读取 / 任意代码执行的入口。
    只允许中英文、数字、下划线、点、横线，且不含 `..`。
    """
    clean = str(name or "").strip()
    if not clean or ".." in clean or not _MODEL_NAME_RE.match(clean):
        raise ValueError(f"非法的模型名 {name!r}：只允许中英文、数字、_ - .，且不能含路径分隔符")
    if clean.startswith("."):
        # 以点开头会和暂存目录 `.staging-*` 撞名，也会藏成隐藏目录
        raise ValueError(f"非法的模型名 {name!r}：不能以点开头")
    return config.model_dir / clean
def _read_meta(directory: Path) -> dict:
    """读 meta.json；缺失或内容坏掉都返回空 dict，让调用方走默认分支而不是崩掉。"""
    meta_path = directory / "meta.json"
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
def _find_weights(directory: Path) -> Path | None:
    """找权重文件。

    优先用 meta.json 里登记的 weights_file——因为发生过「.keras 保存失败但留下
    只含 config.json 的半成品 zip，被固定顺序误当成权重」的事故；
    其次按约定顺序找，并且忽略 0 字节的空壳。
    """
    recorded = _read_meta(directory).get("weights_file")
    if recorded:
        candidate = directory / recorded
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    for name in _WEIGHT_NAMES:
        p = directory / name
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None
def begin_artifact(name: str) -> tuple[Path, Path]:
    """开始写一个产物：返回 (产物目录, 暂存目录)。

    为什么要暂存：产物是"一个模型一份"，重新训练/重新上传都要替换旧的，而**写文件失败是常事**
    （磁盘满、.keras 半成品、上传中途断）。直接往产物目录里写，失败时就会把上一份好产物毁掉；
    所以新内容一律先写进 `.staging-<时间戳>/`，写完整了再搬上来。
    配套：成功 → `commit_artifact()`；失败 → `abort_artifact()`（只删暂存，旧产物原封不动）。
    """
    root = _model_dir(name)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f".staging-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    stage.mkdir()
    return root, stage
def commit_artifact(root: Path, stage: Path) -> None:
    """把暂存目录里的文件搬进产物目录，并清掉旧产物。

    ⚠️ 调用这一刻起旧的产物就被删了，所以只能在新内容**已经完整写好**之后调。
    用 rename 而不是 copy：同一磁盘上的重命名是原子的，不会留下半个文件。
    """
    for old in root.iterdir():
        if old == stage:
            continue
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    for item in stage.iterdir():
        item.rename(root / item.name)
    stage.rmdir()
def abort_artifact(stage: Path) -> None:
    """放弃这次写入：只删暂存目录，**旧产物不受影响**。"""
    shutil.rmtree(stage, ignore_errors=True)
def save_artifact(name: str, framework: str, saver, meta: dict) -> Artifact:
    """落盘一个模型产物，返回可用的 Artifact。**重新训练会直接替换该模型的旧产物。**

    saver: 调用方提供的回调，签名 `saver(target_dir: Path) -> Path`，负责把权重写进
    给定目录并返回权重文件路径（各框架的存法不同，所以由 trainer 自己决定）。

    整个落盘是"要么全有要么全无"的单元，靠 begin/commit/abort 这套暂存目录实现：
      ① 权重与 meta 先写进暂存目录；
      ② 全部写成功后才清掉旧产物、把暂存文件搬上来；
      ③ 中途任何异常都只删暂存目录 —— 旧产物原封不动，也不会留下
         "只有 scaler 没有权重"的半成品被后续查找误命中。
    """
    root, stage = begin_artifact(name)
    try:
        # ① 先让 saver 写权重（Keras 的 .keras / PyTorch 的 .pt / adtk 的 pickle 都在这步）
        weights = Path(saver(stage))
        # ② meta 是产物的"说明书"：模型名/框架 + 权重文件名，再合并 trainer 给的业务字段
        #    （input_len、labels、metrics、params、dataset 指纹…）。权重文件名必须记下来，
        #    否则后面只能靠固定顺序猜哪个文件是权重（踩过 .keras 半成品被误命中的坑）。
        meta = {
            **meta,
            "model": name,
            "framework": framework,
            "weights_file": weights.name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        (stage / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        # ③ 到这一步新产物已经完整躺在暂存目录里了，才动手换掉旧的
        commit_artifact(root, stage)
    except Exception:
        abort_artifact(stage)
        raise
    return Artifact(name=name, directory=root, weights=root / weights.name, framework=framework, meta=meta)
def load_artifact(name: str) -> Artifact:
    """按名字取产物（本项目一个模型只有一个产物，没有版本可选）。

    抛错语义（上层据此回 404/409，不要吞）：
      - 模型目录不存在 / 没有权重 → FileNotFoundError("先调 /train")
    """
    directory = _model_dir(name)
    if not directory.is_dir():
        raise FileNotFoundError(f"还没有任何 {name} 的模型产物，先调 /train")
    weights = _find_weights(directory)
    if weights is None:
        raise FileNotFoundError(f"还没有任何 {name} 的模型产物，先调 /train")
    # meta 缺失也放行（framework 退化成 unknown），让"权重存在但没有说明书"的产物还能被看到，
    # 而不是在这里直接崩掉——真正需要 input_len/labels 的地方自己会报错。
    meta = _read_meta(directory)
    return Artifact(name=name, directory=directory, weights=weights,
                    framework=meta.get("framework", "unknown"), meta=meta)
def list_artifacts(name: str | None = None) -> list[Artifact]:
    """列出已落盘的产物；name 为空时列出全部模型（每个模型最多一条）。"""
    if not config.model_dir.is_dir():
        return []
    if name:
        names = [name]
    else:
        # ⚠️ 跳过 .staging-* ：那是 save_artifact 正在写、还没搬上来的暂存目录，
        #    以及任何隐藏目录（以点开头的一律不当模型看）
        names = sorted(p.name for p in config.model_dir.iterdir()
                       if p.is_dir() and not p.name.startswith("."))
    out: list[Artifact] = []
    for model_name in names:
        directory = _model_dir(model_name)
        if not directory.is_dir():
            continue
        weights = _find_weights(directory)
        if weights is None:
            continue
        meta = _read_meta(directory)
        out.append(Artifact(name=model_name, directory=directory, weights=weights,
                            framework=meta.get("framework", "unknown"), meta=meta))
    return out
def delete_artifact(name: str) -> dict:
    """删除某个模型的产物目录（危险操作，由 DELETE /models/<名>?scope=artifact 触发）。

    只删 data/models/<模型名> 这一层，且删除前把路径 resolve 后二次确认父目录，
    避免误删到别处。
    """
    directory = _model_dir(name).resolve()
    if directory.parent != config.model_dir.resolve():
        raise ValueError("拒绝删除模型目录以外的路径")
    if not directory.is_dir():
        raise FileNotFoundError(f"还没有任何 {name} 的模型产物")
    files = [p for p in directory.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    shutil.rmtree(directory)
    return {"deleted": name, "files": len(files), "freed_kb": round(size / 1024, 1)}
def archive_legacy_versions() -> dict:
    """把旧布局（data/models/<名>/vN/）搬成新布局（data/models/<名>/），旧版本归档。

    一次性迁移，可重复执行（已经是新布局的目录会被跳过）：
      · 若 <名>/ 下有 vN 子目录：把**编号最大**的那个的内容搬上来当唯一产物，
        其余 vN 目录整个搬到 data/archive/model_versions/<名>/ 下（**不删**）。
      · 归档位置放在 model_dir **之外**，避免它自己被当成一个模型列出来。
      · 混合态（根目录已有扁平产物、同时残留 vN）只归档 vN，**不动**扁平产物 —— 见下面的守卫。
    """
    moved, archived = [], []
    if not config.model_dir.is_dir():
        return {"migrated": moved, "archived": archived}
    archive_root = config.model_dir.parent / "archive" / "model_versions"

    def _archive(old, name: str) -> None:
        """把一个旧版本目录整个搬到归档区（目标已存在就先删，保持"最后一份为准"）。"""
        dest = archive_root / name / old.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        old.rename(dest)
        archived.append(f"{name}/{old.name}")

    for root in sorted(p for p in config.model_dir.iterdir()
                       if p.is_dir() and not p.name.startswith(".")):
        versions = sorted((d for d in root.iterdir() if d.is_dir() and re.match(r"^v\d+$", d.name)),
                          key=lambda d: int(d.name[1:]))
        if not versions:
            continue                                  # 已经是新布局
        # ⚠️⚠️ 混合态守卫：根目录下**已经有文件** ⇒ 这台机器早就完成过扁平化，
        #    剩下的 vN 只是没清干净的遗留。此时绝不能执行"把编号最大的 vN 搬上来"：
        #      · Linux/macOS 上 Path.rename 对已存在的目标是**静默覆盖** —— 会拿一个
        #        更旧的 v2 盖掉更新的扁平产物，而且不报任何错（数据静默回退）；
        #      · Windows 上 os.rename 会抛 FileExistsError，整个迁移直接崩。
        #    实测 data/models/adtk 就是这个形态：扁平产物 trained_at=2026-09-15，
        #    残留 v1/v2 分别是 09-13 20:12 / 20:52 —— 跑一次旧逻辑就把 09-15 的换掉了。
        #    所以混合态只归档，扁平产物原样保留。
        if any(item.is_file() for item in root.iterdir()):
            for old in versions:
                _archive(old, root.name)
            continue
        keep, drop = versions[-1], versions[:-1]
        for old in drop:
            _archive(old, root.name)
        for item in list(keep.iterdir()):
            item.rename(root / item.name)
        keep.rmdir()
        moved.append(root.name)
    return {"migrated": moved, "archived": archived}

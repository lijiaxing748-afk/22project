# -*- coding: utf-8 -*-
"""出图：把训练与推理的结果落成 PNG（无头、不弹窗）。

为什么单独一个模块：
  * 原有把图"表现出来"的地方只有 `plt.show()`（1DCNN.py 的准确率/损失曲线、
    cwt_cnn 的混淆矩阵、adtk 的时序图），进程退出图就没了，也没法在接口里返回；
  * 这里统一用 Agg 后端 + `savefig` 落盘，Flask 跑在无显示环境也能出图，
    图放在 data/figures/<模型>/ 下，可通过 GET /figures/<路径> 直接看。

⚠️ 为什么必须走**无头后端**（Agg，见 `_pyplot()`）：
   服务器上没有显示器。matplotlib 默认后端会去找显示服务并尝试弹窗，后果是
   "连不上就抛异常 / 连得上就弹个窗口把进程挂住"，两种在服务端都是事故。
   Agg 是纯文件渲染，只往磁盘写 PNG，不需要任何显示环境 —— 这也是本模块能
   被 Flask 请求线程直接调用的前提。

⚠️ 图是**磁盘产物**而不是内存对象：
   早期版本图只存在内存里（甚至只 `plt.show()` 弹一下），进程一退出、函数一返回
   图就没了，既没法返回给接口、也没法事后复查；现在每张图都写进
   `data/figures/<模型>/<版本>/`，服务重启后仍能通过 GET /figures/<相对路径> 打开
   （代价是要自己管磁盘，见文件末尾的 `clear_figures()`）。

生成内容：
  训练后  training_curves.png（准确率/损失）、confusion_matrix.png（混淆矩阵）、
          per_class_metrics.png（每类 P/R/F1）
  推理后  prediction_distribution.png（预测分布）、predicted_windows.png（窗口波形 + 预测标签）

出图失败一律不影响训练/推理主流程：两个入口函数内部整段 try，异常转成 error 文本返回；
调用方（training.py / inference.py）只是把它记进结果的 `figures_error` 字段，
绝不因为"图没画出来"就让训练或推理本身判为失败 —— 图只是结论的补充说明，不是结论本身。
"""
from __future__ import annotations
import os
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from .config import config, match_dir_case_insensitive
# ⚠️ 缓存目录必须在**第一次 import matplotlib 之前**通过环境变量指定（之后改无效）：
# matplotlib 默认把字体缓存写到用户目录，受限环境（沙箱 / 只读 HOME）下不可写会报警甚至失败；
# 统一挪到项目内 data/.cache/matplotlib，缓存也就跟着项目一起清理。
# 后端（Agg）则在 `_pyplot()` 里设置 —— 同样要求早于 pyplot 的导入。
os.environ.setdefault("MPLCONFIGDIR", str(config.data_dir / ".cache" / "matplotlib"))
FIG_DIR = config.data_dir / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def _model_fig_dir(model: str) -> Path:
    """某个模型的图库目录 `data/figures/<模型键>/`（**只解析，不建目录**）。

    ⚠️ 大小写兜底：见 `config.match_dir_case_insensitive` —— 历史数据里可能存着 `MyModel` 这种
    大小写混合的目录名，而调用方一律用小写产物键来找；不兜底的话在 Linux 上会"图库看起来是空的"。
    出图时下层会自己 mkdir，所以这里不需要（也不应该）建目录。
    """
    exact = FIG_DIR / model
    if exact.exists():
        return exact
    found = match_dir_case_insensitive(FIG_DIR, model)
    return found if found is not None else exact
_CJK_FONTS = ["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC", "Source Han Sans SC"]
_plt = None
def _pyplot():
    """懒加载 matplotlib 并配好全局样式（只做一次）。返回 pyplot 模块。"""
    global _plt
    if _plt is None:
        import matplotlib
        # ⚠️ 必须在 `import matplotlib.pyplot` **之前**切换后端：pyplot 一旦被导入就把
        # 后端定死，之后再 use() 轻则告警、重则无效，于是又回到"弹窗/连显示服务"的老路。
        matplotlib.use("Agg")                      # 无头：服务器上没有显示器，只写文件
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        # ⚠️ 中文字体必须**显式指定**（SimHei / Microsoft YaHei 等）：matplotlib 自带的
        # DejaVu Sans 没有汉字字形，缺字形时它**不报错**，只是把每个汉字画成一个方框
        # （"豆腐块"），很容易被误当成前端/编码问题去查。
        # 而且只能挂系统里**真的存在**的字体：硬写一个不存在的名字，同样会静默回落成方框。
        available = {f.name for f in font_manager.fontManager.ttflist}
        cjk = [f for f in _CJK_FONTS if f in available]
        plt.rcParams["font.sans-serif"] = cjk + ["DejaVu Sans"]  # 退路：至少让数字/英文正常
        plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示（中文字体里 − 常缺字形）
        plt.rcParams["figure.facecolor"] = "white"
        plt.rcParams["savefig.facecolor"] = "white"
        plt.rcParams["axes.grid"] = True
        plt.rcParams["grid.alpha"] = 0.3
        _plt = plt
    return _plt
def _short_labels(labels: list[str]) -> list[str]:
    """把长标签压成适合当坐标轴的两行短名：滚动体故障-0.007in -> 滚动体\\n0.007in"""
    out = []
    for lab in labels:
        text = str(lab)
        if text == "正常":
            out.append("正常")
            continue
        parts = text.split("-")
        kind = parts[0].replace("故障", "")
        detail = parts[1] if len(parts) > 1 else ""
        detail = detail.replace("@6点钟", "@6").replace("in", "")
        out.append(f"{kind}\n{detail}" if detail else kind)
    return out
def _save(fig, path: Path) -> dict:
    """落盘一张图并关掉它（不 close 会累积内存），返回带可直接访问 url 的条目。

    ⚠️ 必须 `close(fig)`：pyplot 会把所有 figure 挂在全局状态里，一个训练请求画三张图、
    多来几次就把内存吃满；图已经写进磁盘，内存里那份没有保留价值。
    url 用 `/figures/<相对路径>` 且统一正斜杠 —— 它是直接给前端 `<img src>` 用的，
    Windows 的 `\\` 在 URL 里是非法字符。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", dpi=120)
    _pyplot().close(fig)
    rel = path.relative_to(FIG_DIR).as_posix()      # 统一成正斜杠，前端当 URL 用
    return {"name": path.name, "path": str(path), "url": f"/figures/{rel}",
            "size_kb": round(path.stat().st_size / 1024, 1)}
# ------------------------------------------------------------------ 训练期出图
def training_figures(model: str, meta: dict, extra: dict | None = None) -> dict:
    """生成训练期三张图，返回 {"figures": [...], "dir": ..., "error": ...}

    契约：**本函数不抛异常**（整段 try），失败时把错误塞进 error 返回。
    调用方只把 error 记成 `figures_error`，训练是否成功完全由指标决定 ——
    ⚠️ 出图依赖字体、matplotlib、磁盘权限等一堆训练用不到的东西，不该让它们左右结论。
    """
    extra = extra or {}
    target = _model_fig_dir(model)
    figures: list[dict] = []
    try:
        plt = _pyplot()
        metrics = meta.get("metrics") or {}
        history = metrics.get("history") or {}
        labels = meta.get("labels") or []
        # ① 训练曲线
        epochs = range(1, max((len(v) for v in history.values()), default=0) + 1)
        if epochs:
            fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
            pairs = [("accuracy", "val_accuracy", "准确率", axes[0]),
                     ("loss", "val_loss", "损失值", axes[1])]
            for key, val_key, title, ax in pairs:
                if key in history:
                    ax.plot(epochs, history[key], "-.", color="#c0392b", label=f"训练集{title}")
                if val_key in history:
                    ax.plot(epochs, history[val_key], "b-.", label=f"验证集{title}")
                ax.set_title(f"训练集与验证集{title}曲线")
                ax.set_xlabel("训练轮次")
                ax.set_ylabel(title)
                ax.legend()
            fig.suptitle(f"{meta.get('model', model)} · 训练曲线 "
                         f"(epochs={len(list(epochs))})", fontsize=13)
            figures.append(_save(fig, target / "training_curves.png"))
        # ② 混淆矩阵
        confusion = extra.get("confusion")
        if confusion and labels:
            import numpy as np
            mat = np.asarray(confusion, dtype=int)
            short = _short_labels(labels)
            fig, ax = plt.subplots(figsize=(8.6, 7.2))
            im = ax.imshow(mat, cmap="Blues")
            fig.colorbar(im, ax=ax, fraction=0.046)
            ax.set_xticks(range(len(short)), short, rotation=45, ha="right", fontsize=8)
            ax.set_yticks(range(len(short)), short, fontsize=8)
            ax.set_xlabel("预测类别")
            ax.set_ylabel("真实类别")
            ax.set_title(f"{meta.get('model', model)} · 混淆矩阵"
                         f"（测试集 {int(mat.sum())} 个窗口，准确率 "
                         f"{metrics.get('test_accuracy')}）", fontsize=12)
            threshold = mat.max() / 2 if mat.size else 0
            for i in range(mat.shape[0]):
                for j in range(mat.shape[1]):
                    if mat[i, j]:
                        ax.text(j, i, str(mat[i, j]), ha="center", va="center", fontsize=7,
                                color="white" if mat[i, j] > threshold else "#333333")
            ax.grid(False)
            figures.append(_save(fig, target / "confusion_matrix.png"))
        # ③ 每类 P/R/F1
        per_class = extra.get("per_class") or {}
        if per_class and labels:
            short = _short_labels(labels)
            cols = [c for c in ("precision", "recall", "f1-score") if any(
                c in per_class.get(str(i), {}) for i in range(len(labels)))]
            if cols:
                import numpy as np
                x = np.arange(len(labels))
                width = 0.8 / len(cols)
                fig, ax = plt.subplots(figsize=(11, 4.6))
                for k, col in enumerate(cols):
                    values = [float(per_class.get(str(i), {}).get(col, 0) or 0) for i in range(len(labels))]
                    ax.bar(x + k * width, values, width, label=col)
                ax.set_xticks(x + width * (len(cols) - 1) / 2, short, rotation=45, ha="right", fontsize=8)
                ax.set_ylim(0, 1.05)
                ax.set_ylabel("得分")
                ax.set_title(f"{meta.get('model', model)} · 各类别精确率/召回率/F1")
                ax.legend()
                figures.append(_save(fig, target / "per_class_metrics.png"))
        return {"figures": figures, "dir": str(target), "error": None}
    except Exception as exc:                                     # pragma: no cover
        return {"figures": figures, "dir": str(target),
                "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-800:]}
# ------------------------------------------------------------------ 推理期出图
def inference_figures(model: str, payload: dict, matrix=None) -> dict:
    """生成推理期两张图：预测分布 + 预测窗口波形（最多 6 个窗口）。

    与训练期同样**不抛异常**，失败只写进 error（调用方记 `figures_error`）。
    落盘目录额外带 `predict-<时间戳>` 一层：同一份模型会被反复推理，
    每次都覆盖同名文件的话，历史留痕就没了。
    """
    target = _model_fig_dir(model) / f"predict-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    figures: list[dict] = []
    try:
        plt = _pyplot()
        predictions = payload.get("predictions") or []
        task = payload.get("task")          # ② 里靠它区分"分类窗口标题"和"异常窗口标题"
        # ① 预测分布
        # ⚠️ 这里**不能**按 task 分支：分类与异常检测的预测标签都在 p["predicted_label"] 里，
        #    两支代码一字不差。历史上这里写成 if task == "classification" 并在分支内
        #    `from collections import Counter`，于是 Counter 变成函数局部名 —— 非分类任务
        #    （adtk 的 anomaly_detection）走 else 支时局部名未绑定，必抛 UnboundLocalError，
        #    被外层整段 try 吞成 figures_error：adtk 推理永远拿不到这张分布图。
        #    现在 import 提到模块级、分支合并，两条任务类型走同一行。
        counter = Counter(p["predicted_label"] for p in predictions)
        if counter:
            keys = list(counter)
            values = [counter[k] for k in keys]
            colors = ["#27ae60" if k in ("正常",) else "#c0392b" for k in keys]
            fig, ax = plt.subplots(figsize=(max(6, 0.9 * len(keys) + 3), 4.2))
            bars = ax.bar(range(len(keys)), values, color=colors, width=0.6)
            ax.bar_label(bars)
            ax.set_xticks(range(len(keys)), keys, rotation=30, ha="right", fontsize=9)
            ax.set_ylabel("窗口数")
            ax.set_title(f"{model} · 本次推理 {payload.get('count')} 个窗口的预测分布")
            figures.append(_save(fig, target / "prediction_distribution.png"))
        # ② 预测窗口波形
        if matrix is not None:
            import numpy as np
            matrix = np.asarray(matrix)
            show = min(6, len(matrix))
            cols = 2
            rows = (show + cols - 1) // cols
            fig, axes = plt.subplots(rows, cols, figsize=(12, 2.0 * rows), squeeze=False)
            for i in range(show):
                ax = axes[i // cols][i % cols]
                pred = predictions[i]
                signal = matrix[i]
                ax.plot(range(len(signal)), signal, lw=0.7, color="#2c3e50")
                if task == "classification":
                    title = f"窗口{pred['index']} → {pred['predicted_label']} ({pred['confidence']:.3f})"
                    if pred.get("actual_class") is not None:
                        hit = pred["predicted_class"] == pred["actual_class"]
                        # 注意：✓/✗ 这类符号在雅黑/宋体里没有字形，会渲染成方框，所以用中文标注
                        title += "  命中" if hit else "  未命中"
                        ax.set_facecolor("#eafaf1" if hit else "#fdedec")
                else:
                    # ⚠️ 措辞过时（保留原话以免前端/截图对不上）：
                    # "异常点占比"是**老格式产物**的说法 —— 那时 anomaly_score 取的是
                    # 点级 detect 中被标记点的比例（flags.mean()），确实是"占比"；
                    # 但新格式产物（PcaAD transform）里同一个字段存的是**重构误差**
                    # （越大越异常，inference.py 的 detail 里就叫"重构误差"），不是百分比。
                    # 所以图上这个数字只当"异常分数"看，别解读成"异常点占多少百分比"。
                    title = (f"窗口{pred['index']} → {pred['predicted_label']}"
                             f"（异常点占比 {pred['anomaly_score']:.3f}）")
                    ax.set_facecolor("#fdedec" if pred["is_anomaly"] else "#eafaf1")
                ax.set_title(title, fontsize=9)
                ax.set_xlabel("采样点", fontsize=8)
                ax.set_ylabel("幅值", fontsize=8)
                ax.tick_params(labelsize=7)
                ax.grid(alpha=0.2)
            for j in range(show, rows * cols):
                axes[j // cols][j % cols].axis("off")
            fig.suptitle(f"{model} · 预测窗口原始信号（绿底=命中/正常，红底=未命中/异常）"
                         f"\n{str(payload.get('input', {}).get('path') or '内联数组')}", fontsize=11)
            fig.tight_layout()
            figures.append(_save(fig, target / "predicted_windows.png"))
        return {"figures": figures, "dir": str(target), "error": None}
    except Exception as exc:                                     # pragma: no cover
        return {"figures": figures, "dir": str(target),
                "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-800:]}
def list_figures(limit: int = 200) -> list[dict]:
    """列出已生成的图，供 GET /figures 用。"""
    out = []
    for path in sorted(FIG_DIR.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        rel = path.relative_to(FIG_DIR).as_posix()
        out.append({"file": rel, "url": f"/figures/{rel}",
                    "size_kb": round(path.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
        if len(out) >= limit:
            break
    return out
def delete_figure(relpath: str) -> dict:
    """删除图库里**单张**图（前端「图库」页每张图上的删除按钮）。返回删掉的文件与释放空间。

    ⚠️ **路径穿越防护必须自己做**：relpath 直接来自 URL。`GET /figures/<路径>` 那边靠
       `send_from_directory` 的 safe_join 兜住了，但那是"读"；这里是"删文件"，
       一旦 `../../db.env` 这种路径被放进来，后果不可逆。做法是 resolve() 后要求它
       仍在 FIG_DIR 之内 —— 用 `relative_to()` 判，逃出去会抛 ValueError。
       不要改成字符串 startswith 那种判断：`FIG_DIR + "_backup"` 也能骗过它。

    ⚠️ **只允许删 .png**：这个目录按约定只放图，但"按传入路径删任意文件"这件事本身
       太危险，限定后缀能把误传路径时的破坏面收窄到"最多删掉一张图"。

    ⚠️ 删空目录但**不动 FIG_DIR 本身**：训练/推理会各建一层子目录
       （`<模型>/` 与 `<模型>/predict-<时间戳>/`），图删光后目录留着只是垃圾；
       但 FIG_DIR 是模块级创建、被多处引用，删掉它会让后续出图多一次 mkdir 的竞态。
    """
    root = FIG_DIR.resolve()
    target = (FIG_DIR / relpath).resolve()
    try:
        rel = target.relative_to(root)
    except ValueError:
        raise FileNotFoundError("路径不合法：超出了图库目录")
    if target.suffix.lower() != ".png":
        raise FileNotFoundError("只能删除图库里的 PNG 图")
    if not target.is_file():
        raise FileNotFoundError(f"图不存在：{relpath}")
    size = target.stat().st_size
    target.unlink()
    # 往上逐级删**空**目录，直到 FIG_DIR 为止（rmdir 碰见非空会抛 OSError，就此收手）
    parent = target.parent
    while parent != root and root in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return {"deleted": rel.as_posix(), "freed_kb": round(size / 1024, 1)}


def clear_figures() -> dict:
    """清空图库（危险操作，由系统的「维护」触发）。目录本身保留。"""
    removed = 0
    freed = 0
    for path in list(FIG_DIR.rglob("*.png")):
        freed += path.stat().st_size
        path.unlink(missing_ok=True)
        removed += 1
    for directory in sorted([p for p in FIG_DIR.rglob("*") if p.is_dir()],
                            key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()                       # 只删空目录
        except OSError:
            pass
    return {"removed": removed, "freed_kb": round(freed / 1024, 1), "dir": str(FIG_DIR)}

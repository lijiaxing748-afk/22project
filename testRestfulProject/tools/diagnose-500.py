#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""训练 / 推理 500 排查工具 —— 在实验室电脑上运行。

背景：页面能开、数据集列表（GET）正常，但提交训练/推理（POST）就 500。
      GET 只读数据库，POST 要**真的去加载数据文件和模型产物**，所以问题
      几乎一定在"文件层面"——最常见的就是**改了文件名**。

这个脚本不依赖 Flask、不连数据库，只做三件事：
  1. 检查 CWRU 数据集的 10 个 .mat 文件名是否和代码里的登记表**逐字一致**
  2. 检查每个 .mat 内部是否真的有含 "DE" 的通道（改名无关，但顺手查）
  3. 检查三个模型的产物文件是否齐全、能否被读取

用法（在 testRestfulProject 目录下）：
    venv\\Scripts\\python.exe tools\\diagnose-500.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

SEP = "=" * 66


def title(t: str) -> None:
    print()
    print(SEP)
    print(f"  {t}")
    print(SEP)


# ----------------------------------------------------------------------
# 1) 数据集文件名核对
# ----------------------------------------------------------------------
def check_dataset() -> bool:
    title("1. CWRU 数据集文件名核对（改名问题的重点）")

    from model_service.datasets import CWRU_0HP_CLASSES

    data_dir = PROJECT / "1DCNN" / "0HP"
    print(f"  目录: {data_dir}")
    if not data_dir.is_dir():
        print(f"  [错误] 目录不存在！训练必然 500。")
        return False

    expected = [name for name, _, _ in CWRU_0HP_CLASSES]
    on_disk = sorted(p.name for p in data_dir.glob("*.mat"))

    print(f"  代码要求 {len(expected)} 个文件，磁盘上有 {len(on_disk)} 个 .mat")
    print()

    missing = [n for n in expected if n not in on_disk]
    extra = [n for n in on_disk if n not in expected]

    ok = True
    print("  --- 登记表逐个核对 ---")
    for name, cid, label in CWRU_0HP_CLASSES:
        exists = (data_dir / name).is_file()
        flag = "OK  " if exists else "缺失"
        if not exists:
            ok = False
        print(f"   [{flag}] 类别{cid:>2}  {name:<34} {label}")

    if missing:
        print()
        print(f"  [错误] 有 {len(missing)} 个登记文件在磁盘上找不到：")
        for n in missing:
            print(f"         {n}")
        # 尝试给出"是不是被改名了"的猜测
        print()
        print("  猜测你改成了哪个名字（按相似度）：")
        for m in missing:
            guess = _closest(m, extra) if extra else None
            if guess:
                print(f"         {m}\n           -> 磁盘上像是: {guess}")

    if extra:
        print()
        print(f"  [警告] 磁盘上有 {len(extra)} 个文件**不在登记表里**：")
        for n in extra:
            print(f"         {n}")
        print()
        print("  说明：这些文件会被当成「未登记类别」，各自单独一类，")
        print("        类别号从 10 开始递增。这**不会**直接导致 500，")
        print("        但会让模型多出莫名其妙的类别、指标无法解释。")

    return ok


def _closest(target: str, candidates: list[str]) -> str | None:
    """粗略找最像的那个文件名（只看字符集合与长度，够用就行）。"""
    def score(s: str) -> float:
        # 越长公共前缀 + 字符出现次数越接近，分越高
        common = sum(min(target.count(c), s.count(c)) for c in set(target + s))
        return common / max(len(target), len(s))

    best = max(candidates, key=score)
    return best if score(best) > 0.6 else None


# ----------------------------------------------------------------------
# 2) .mat 内部通道
# ----------------------------------------------------------------------
def check_mat_channels() -> bool:
    title("2. .mat 内部的 DE 通道检查")
    data_dir = PROJECT / "1DCNN" / "0HP"
    if not data_dir.is_dir():
        print("  [跳过] 目录不存在")
        return False

    try:
        from scipy.io import loadmat
    except ImportError as exc:
        print(f"  [错误] 无法 import scipy: {exc}")
        return False

    ok = True
    for p in sorted(data_dir.glob("*.mat")):
        try:
            mat = loadmat(str(p))
            de_keys = [k for k in mat if "DE" in k and not k.startswith("__")]
            if de_keys:
                n = mat[de_keys[0]].size
                print(f"   [OK  ]  {p.name:<34} {de_keys[0]:<16} {n:>8} 点")
            else:
                keys = [k for k in mat if not k.startswith("__")]
                print(f"   [错误]  {p.name:<34} 找不到含 'DE' 的通道！实际变量: {keys[:5]}")
                ok = False
        except Exception as exc:
            print(f"   [错误]  {p.name:<34} 读取失败: {type(exc).__name__}: {exc}")
            ok = False
    return ok


# ----------------------------------------------------------------------
# 3) 模型产物
# ----------------------------------------------------------------------
def check_artifacts() -> bool:
    title("3. 模型产物检查")
    models_dir = PROJECT / "data" / "models"
    if not models_dir.is_dir():
        print(f"  [错误] 目录不存在: {models_dir}")
        return False

    ok = True
    for name in sorted(p.name for p in models_dir.iterdir() if p.is_dir()):
        mdir = models_dir / name
        # 产物有两种布局：直接摊在模型目录下（当前布局），或放在 v1/v2 版本子目录里。
        # 必须两种都看，否则会误报"0 个版本"。
        files = sorted(p.name for p in mdir.iterdir() if p.is_file())
        subdirs = sorted(p.name for p in mdir.iterdir() if p.is_dir())

        if files:
            print(f"\n  --- {name} ---")
            print(f"   [直接布局] {files}")
            weights = _pick_weights(mdir)
            if weights:
                size = weights.stat().st_size
                if size > 0:
                    print(f"   [OK]   权重 {weights.name}  {size/1024:.0f} KB")
                else:
                    print(f"   [错误] 权重 {weights.name} 是 0 字节（保存失败留下的空壳）")
                    ok = False
            else:
                print(f"   [错误] 找不到权重文件！meta 声称 "
                      f"{_read_meta_weights(mdir)!r}，目录里实际只有 {files}")
                ok = False
        for sub in subdirs:
            sdir = mdir / sub
            sfiles = sorted(p.name for p in sdir.iterdir() if p.is_file())
            print(f"\n  --- {name}/{sub} ---")
            print(f"   {sfiles}")
            weights = _pick_weights(sdir)
            if weights and weights.stat().st_size > 0:
                print(f"   [OK]   权重 {weights.name}  {weights.stat().st_size/1024:.0f} KB")
            elif not sfiles:
                print(f"   [错误] 空目录")
                ok = False
        if not files and not subdirs:
            print(f"\n  --- {name} ---")
            print(f"   [错误] 空目录，推理必然 409/500")
            ok = False
    return ok


def _read_meta_weights(directory: Path) -> str | None:
    import json
    p = directory / "meta.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("weights_file")
    except Exception:
        return None


def _pick_weights(directory: Path) -> Path | None:
    """复刻 registry._find_weights 的逻辑：先看 meta 登记的，再按约定名找。"""
    order = ["model.keras", "model.h5", "model.pt", "model.pt2", "detector.pkl",
             "model.pth", "weights.pt", "model.joblib"]
    recorded = _read_meta_weights(directory)
    if recorded:
        cand = directory / recorded
        if cand.is_file() and cand.stat().st_size > 0:
            return cand
    for n in order:
        p = directory / n
        if p.is_file() and p.stat().st_size > 0:
            return p
    # 兜底：列目录找任意疑似权重
    for p in directory.iterdir():
        if p.is_file() and p.suffix in (".keras", ".h5", ".pt", ".pt2", ".pkl", ".pth", ".npz"):
            if p.stat().st_size > 0:
                return p
    return None


# ----------------------------------------------------------------------
# 4) 真实跑一次最小推理
# ----------------------------------------------------------------------
def try_real_predict() -> None:
    title("4. 真实调用一次推理（直接看真正的报错）")
    print("  这一步最重要：它绕开 HTTP，直接把 traceback 打出来。\n")
    try:
        from model_service.inference import predict
    except Exception as exc:
        print(f"  [错误] 连 inference 模块都 import 不了：{type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return

    mat = PROJECT / "1DCNN" / "0HP" / "48k_Drive_End_IR007_0_109.mat"
    cases = [
        ("adtk",    {"model": "adtk"}),
        ("1dcnn",   {"model": "1dcnn"}),
        ("cwt_cnn", {"model": "cwt_cnn"}),
    ]
    for label, kwargs in cases:
        print(f"  === 试 {label} ===")
        try:
            out = predict(path=str(mat) if mat.is_file() else None,
                          index=0, limit=1, write_db=False, **kwargs)
            summary = out.get("summary") if isinstance(out, dict) else None
            print(f"   [OK]  推理成功，summary={summary}\n")
        except Exception as exc:
            print(f"   [失败] {type(exc).__name__}: {exc}")
            import traceback
            tb = traceback.format_exc()
            print("   ---- traceback ----")
            for line in tb.strip().split("\n")[-18:]:
                print(f"   {line}")
            print()


def main() -> int:
    print(SEP)
    print("  训练 / 推理 500 排查")
    print(f"  项目目录: {PROJECT}")
    print(SEP)

    results = {}
    try:
        results["数据集文件名"] = check_dataset()
    except Exception as exc:
        print(f"  [错误] 检查数据集时崩溃: {type(exc).__name__}: {exc}")
        results["数据集文件名"] = False

    try:
        results["DE 通道"] = check_mat_channels()
    except Exception as exc:
        print(f"  [错误] 检查通道时崩溃: {type(exc).__name__}: {exc}")
        results["DE 通道"] = False

    try:
        results["模型产物"] = check_artifacts()
    except Exception as exc:
        print(f"  [错误] 检查产物时崩溃: {type(exc).__name__}: {exc}")
        results["模型产物"] = False

    try_real_predict()

    title("结论")
    for k, v in results.items():
        print(f"  {'[OK]  ' if v else '[有问题]'} {k}")
    print()
    if not all(results.values()):
        print("  上面标 [有问题] 的项目就是 500 的原因。")
        print("  最常见的是数据集文件名被改过 —— 见第 1 节的 [错误] 行。")
    else:
        print("  文件层面全部正常，请把第 4 节打印的 traceback 发出来进一步定位。")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

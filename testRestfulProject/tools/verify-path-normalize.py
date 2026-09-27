# -*- coding: utf-8 -*-
"""验证路径归一化与数据集目录解析：Windows 风格路径在任何平台上都能被正确解析。

背景（两条教训，都在这一个文件里验）：
  ① 前端拼路径用 `\\`，Windows 上 Path() 认；Linux 上 `\\` 只是普通字符，
     导致"文件明明在却报不存在"。
  ② ⚠️ **盘符相关的期望值依平台而异**：Windows 上 `D:\\x` 本身就是绝对路径，
     去掉盘符会把它降级成相对路径，调用方再拼一次项目根就成了
     `...\\testRestfulProject\\22project\\testRestfulProject\\1DCNN\\0HP` —— 目录不存在、
     训练直接 500（2026-09-27 实测踩到）。Linux 上没有盘符概念，只能丢掉。
     所以下面用 `os.name` 区分期望值，而不是断言一个"与平台无关"的错答案。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_service.config import (  # noqa: E402
    config, normalize_user_path, dataset_dir_candidates)

FAIL = 0


def check(name, got, want):
    global FAIL
    ok = (got == want)
    if not ok:
        FAIL += 1
    print(f"  [{'OK' if ok else '失败'}] {name}")
    if not ok:
        print(f"       输入期望: {want!r}")
        print(f"       实际得到: {got!r}")


def main():
    global FAIL
    print("=" * 64)
    print("  normalize_user_path —— Windows 路径 → 当前平台可解析形式")
    print("=" * 64)

    # ⚠️ 盘符相关期望值**依平台而异**，见文件头 ②。
    nt = (os.name == "nt")
    cases = [
        # (说明, 输入, 期望)
        ("反斜杠相对路径（前端最常发的格式）",
         "1DCNN\\0HP\\x.csv", "1DCNN/0HP/x.csv"),
        ("已是正斜杠：保持原样",
         "1DCNN/0HP/x.csv", "1DCNN/0HP/x.csv"),
        ("混合分隔符",
         "1DCNN\\0HP/sub/x.csv", "1DCNN/0HP/sub/x.csv"),
        ("中文目录名（我们的数据集就是中文）",
         "DEMO-轴承表格数据\\信号.csv", "DEMO-轴承表格数据/信号.csv"),
        ("Windows 绝对路径 D:\\...（Windows 上必须**保持绝对**）",
         "D:\\22project\\frontend\\dist",
         "D:/22project/frontend/dist" if nt else "22project/frontend/dist"),
        ("Windows 绝对路径小写盘符",
         "c:\\x\\y.csv", "c:/x/y.csv" if nt else "x/y.csv"),
        ("盘符 + 正斜杠",
         "D:/22project/x.csv", "D:/22project/x.csv" if nt else "22project/x.csv"),
        ("相对工作区写法（响应脱敏后的典型值）",
         "testRestfulProject\\1DCNN\\0HP", "testRestfulProject/1DCNN/0HP"),
        ("空字符串",
         "", ""),
        ("纯空白",
         "   ", ""),
        ("None", None, ""),
        ("前后空白要 strip",
         "  a\\b.csv  ", "a/b.csv"),
        ("单个文件名",
         "x.csv", "x.csv"),
        ("只有盘符（Windows 上仍是绝对的根，Linux 上退化成空）",
         "D:", "D:" if nt else ""),
        ("UNC 风格 \\\\server\\share → //server/share（双斜杠保留，UNC 语义）",
         "\\\\server\\share\\f.csv", "//server/share/f.csv"),
    ]

    for desc, raw, want in cases:
        check(desc, normalize_user_path(raw), want)

    print()
    print("--- 两种调用方式必须等价（模块函数 / Config 实例方法）---")
    for desc, raw, want in cases:
        via_instance = config.normalize_user_path(raw)
        if via_instance != want:
            check(f"[实例调用] {desc}", via_instance, want)
    # 实例调用全部通过时补一条汇总，避免上面循环没输出显得"没测"
    all_same = all(config.normalize_user_path(r) == w for _, r, w in cases)
    check("config.normalize_user_path（实例）与模块函数结果一致", all_same, True)

    print()
    print("=" * 64)
    print("  dataset_dir_candidates —— 数据集的六种写法都要能落到同一个真实目录")
    print("=" * 64)

    real = config.project_dir / "1DCNN" / "0HP"
    forms = [
        ("绝对写法", str(real)),
        ("反斜杠绝对写法", str(real).replace("/", "\\")),
        ("相对项目根", "1DCNN/0HP"),
        ("反斜杠相对", "1DCNN\\0HP"),
        ("相对工作区", "testRestfulProject/1DCNN/0HP"),
        ("盘符 + 相对（脱敏后/旧库里的典型值）",
         "D:/22project/testRestfulProject/1DCNN/0HP"),
    ]
    for desc, raw in forms:
        candidates = dataset_dir_candidates(raw)
        hit = next((c for c in candidates if c.is_dir()), None)
        check(f"{desc} → 首个存在的候选 = 真实目录",
              hit is not None and Path(hit).resolve() == real.resolve(), True)
    check("空输入 → 空候选", dataset_dir_candidates("") == [], True)
    check("候选里包含「原样」这一项（绝对路径优先）",
          str(real) in [str(c) for c in dataset_dir_candidates(str(real))], True)

    print()
    print("=" * 64)
    print("  真实文件解析验证（在临时目录里造中文+多级路径）")
    print("=" * 64)

    import tempfile
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix="pathnorm-"))
    try:
        deep = tmp / "DEMO-轴承表格数据"
        deep.mkdir(parents=True)
        target = deep / "信号.csv"
        target.write_text("a\n1\n", encoding="utf-8")

        # 模拟前端发来的 Windows 风格串（相对于 tmp）
        raw = "DEMO-轴承表格数据\\信号.csv"
        norm = normalize_user_path(raw)
        resolved = (tmp / norm).resolve()
        check("Windows 风格串归一化后能指向真实文件",
              resolved.is_file(), True)
        print(f"       归一化: {norm!r}")
        print(f"       解析到: {resolved}")

        # 对照：不归一化会怎样
        # ⚠️ 这个对照**只在非 Windows 上成立**：Windows 的 Path 本来就认 `\`，
        #    不归一化也能找到。在 Linux 上它找不到 —— 那正是线上故障现象。
        #    所以按平台给不同的期望值，否则在 Windows 开发机上跑测试会"假失败"。
        naive = (tmp / Path(raw)).resolve()
        if sys.platform == "win32":
            check("（对照）Windows 上不归一化也找得到 —— 所以此 bug 开发机测不出来",
                  naive.is_file(), True)
        else:
            check("（对照）Linux 上不归一化就找不到 —— 这正是线上故障现象",
                  naive.is_file(), False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(f"失败 {FAIL} 项")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

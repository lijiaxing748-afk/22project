# -*- coding: utf-8 -*-
"""验证 config.normalize_user_path()：Windows 风格路径在 Linux 上也能解析。

背景：前端拼路径用 `\\`，Windows 上 Path() 认；Linux 上 `\\` 只是普通字符，
      导致"文件明明在却报不存在"。这个测试在 Windows 上同样可跑，
      断言的是**归一化结果**（与平台无关），从而能在开发机上提前发现问题。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_service.config import config, normalize_user_path  # noqa: E402

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
        ("Windows 绝对路径 D:\\...",
         "D:\\22project\\frontend\\dist", "22project/frontend/dist"),
        ("Windows 绝对路径小写盘符",
         "c:\\x\\y.csv", "x/y.csv"),
        ("盘符 + 正斜杠",
         "D:/22project/x.csv", "22project/x.csv"),
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
        ("只有盘符（退化成空）",
         "D:", ""),
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

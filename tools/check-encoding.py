#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""编码约定检查（UTF-8 有/无 BOM）—— 交付前一跑，避免"看不见的编码坑"。

规则（本项目约定）：
  · `.ps1`（Windows PowerShell 脚本）→ **必须带 UTF-8 BOM**
      原因：Windows PowerShell 5.1 读没有 BOM 的 .ps1 时按**系统 ANSI（中文机器是 GBK）**解码，
      脚本里的中文会变成乱码，甚至语句被拆错。仓库里原有的 01~06-*.ps1 / elevate.ps1 都带 BOM，就是这个原因。
  · 其它文本文件（.py/.md/.vue/.ts/.sql/.bat/.sh/.json/...）→ **必须 UTF-8 无 BOM**
      原因：BOM 会被当成内容。踩过的坑：db.env 带 BOM 时第一行变成 "\ufeffMODEL_DB_DIALECT"，
      键名多一个不可见字符 → 整行配置读不到；.bat 带 BOM 会让 cmd 第一行报错。
      （应用侧已做防御：db.env 与建表 .sql 用 utf-8-sig 读，能吃掉 BOM；但文件本身仍应无 BOM。）
  · 所有文本文件都必须能按 UTF-8 解码（出现 GBK/ANSI 文件要报出来）。
  · 换行：`.bat/.cmd/.ps1` 必须 **CRLF**（cmd 对 LF 的批处理会解析错乱），`.sh/.bash` 必须 **LF**
    （CRLF 的 shell 脚本在 Linux 上报 /bin/bash^M: bad interpreter）。仓库用 .gitattributes 钉住。

用法：
    testRestfulProject\\venv\\Scripts\\python.exe tools\\check-encoding.py [项目根目录，默认自动定位]

退出码：0 = 全部符合；1 = 有不合规文件（会逐条列出，并给出可复制的修复命令）。
"""
from __future__ import annotations

import sys
from pathlib import Path

BOM = b"\xef\xbb\xbf"
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".cache", ".idea", ".vscode",
             ".pytest_cache", "venv", ".venv", "venv-py312"}
SKIP_PREFIX_DIRS = ("venv-py", "venv-backup", "venv_")
TEXT_SUFFIXES = {
    ".py", ".pyi", ".md", ".txt", ".html", ".htm", ".css", ".scss", ".js", ".cjs", ".mjs",
    ".ts", ".tsx", ".vue", ".json", ".sql", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".psm1",
    ".yml", ".yaml", ".ini", ".cfg", ".toml", ".env", ".example", ".gitattributes", ".gitignore",
}
TEXT_NAMES = {"db.env", "db.env.example", "requirements.txt", ".gitignore", ".gitattributes",
              ".editorconfig", "Dockerfile", "Makefile", "LICENSE"}

# 换行约定：值 = 该类型**必须**是哪种换行（None/缺省 = 不检查）
#   · .bat/.cmd 必须 CRLF：cmd.exe 对 LF 的批处理解析会错乱（goto/标签/括号块尤甚 —— 实测踩过，
#     uninstall.bat 的 goto 与括号块整段失效，报出一堆"中文片段不是命令"）；
#   · .sh/.bash 必须 LF：CRLF 的 shell 脚本在 Linux 上会报 /bin/bash^M: bad interpreter；
#   · .ps1 用 CRLF（Windows 习惯，PowerShell 两种都能读）。
EOL_RULES = {".bat": "crlf", ".cmd": "crlf", ".ps1": "crlf", ".sh": "lf", ".bash": "lf"}


def is_text(path: Path) -> bool:
    if path.name in TEXT_NAMES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith(SKIP_PREFIX_DIRS) for part in parts[:-1]):
            continue
        if is_text(p):
            yield p


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    problems: list[str] = []
    n_ps1 = n_other = 0

    for p in sorted(iter_files(root)):
        rel = p.relative_to(root).as_posix()
        try:
            data = p.read_bytes()
        except OSError as exc:
            problems.append(f"{rel}：读不了（{exc}）")
            continue
        has_bom = data.startswith(BOM)
        if p.suffix.lower() in (".ps1", ".psm1"):
            n_ps1 += 1
            if not has_bom:
                problems.append(
                    f"{rel}：.ps1 **缺 UTF-8 BOM** —— Windows PowerShell 5.1 会按 GBK 读，中文乱码。\n"
                    f"        修：在文件开头加 BOM（EF BB BF），或用 PowerShell 7（pwsh）执行")
        else:
            n_other += 1
            if has_bom:
                problems.append(
                    f"{rel}：不应带 BOM（BOM 会被当成文件内容）。\n"
                    f"        修：去掉开头三字节 EF BB BF（Python 里用 encoding='utf-8-sig' 读入、'utf-8' 写出）")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{rel}：不是 UTF-8（{exc}）—— 可能是 GBK/ANSI，请转成 UTF-8")

        # 换行检查（2026-09-28 加）：.bat/.cmd 必须 CRLF，否则 cmd.exe 解析会错乱；
        # shell 脚本必须 LF，否则 Linux 上报 "/bin/bash^M: bad interpreter"。
        want = EOL_RULES.get(p.suffix.lower())
        if want and b"\n" in data:
            crlf = data.count(b"\r\n")
            bare_lf = data.count(b"\n") - crlf
            if want == "crlf" and bare_lf > 0:
                who = "cmd.exe 读 .bat/.cmd 会解析错乱（带 goto/标签/括号块时整段失效，实测踩过）" if p.suffix.lower() in (".bat", ".cmd") \
                      else "Windows 脚本按惯例用 CRLF（PowerShell 两种都能读，但保持一致更好）"
                problems.append(
                    f"{rel}：应为 CRLF 换行，但有 {bare_lf} 处裸 LF —— {who}。\n"
                    f"        修：把行尾统一成 CRLF（仓库已用 .gitattributes 钉住 eol=crlf）")
            if want == "lf" and crlf > 0:
                problems.append(
                    f"{rel}：应为 LF 换行，但有 {crlf} 处 CRLF —— Linux 上执行会报 bad interpreter: /bin/bash^M。\n"
                    f"        修：把行尾统一成 LF（.gitattributes 已钉住 *.sh eol=lf）")

    print(f"检查目录：{root}")
    print(f"  文本文件：{n_ps1 + n_other} 个（其中 .ps1 {n_ps1} 个；.ps1 须带 BOM，其余须无 BOM）")
    print("  换行约定：.bat/.cmd/.ps1 = CRLF，.sh/.bash = LF")
    if not problems:
        print("  ✅ 全部符合约定（编码、BOM、换行都正确）")
        return 0
    print(f"  ❌ 发现 {len(problems)} 处不合规：")
    for item in problems:
        print(f"     - {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

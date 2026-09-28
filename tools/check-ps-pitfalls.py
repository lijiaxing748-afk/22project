#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PowerShell 脚本体检（Windows PowerShell 5.1 的坑）—— 带 --fix 可自动补一行加固。

背景：2026-09-28 交付现场连续踩到同一类问题，写进文档也做成工具，免得以后再犯。

  坑 1（本次真正的根因）：脚本里写 `$ErrorActionPreference = 'Stop'`，同时又调用原生命令
        （mysql.exe / pip / sc.exe / schtasks / nssm …）。原生命令往 **stderr** 写东西时
        （例如 mysql 的 `ERROR 1045 Access denied`），5.1 会生成 NativeCommandError；
        在 Stop 下这是**终止性错误** → 脚本直接被杀掉。
        现场表现：探测 MySQL 账号只试了第一个候选（root+空口令）就退出，后面能成功的候选根本没机会试。
        规则：**调用原生命令的脚本不要用 Stop**（用 Continue + 显式 Die/exit 判断返回值）；
              或者把每个原生命令的 stderr 用 `2>&1` 收下来。

  坑 2：给原生命令传**带内嵌双引号**的参数（典型：SQL 里 `CONCAT(@@port, " ", @@version)`）
        在 5.1 下会在引号处被拆成两条参数，mysql 把后半截当**库名**：
        `ERROR 1044 ... Access denied ... to database ', @@version)'`。
        规则：不要给原生命令传带双引号的参数，改成多条简单命令。

  坑 3：把带 BOM 的文件读成字符串再写回时，若没去掉首字符 U+FEFF 又写 BOM → **双 BOM**；
        PowerShell 于是在脚本级 `param` 前看到一个多余字符，把参数块当表达式解析，报
        `The assignment expression is not valid`。
        规则：脚本级 `param(` 必须是第一条语句（前面只能有注释/[CmdletBinding()]）；
              BOM/换行另见 tools/check-encoding.py。

用法：
    testRestfulProject\\venv\\Scripts\\python.exe tools\\check-ps-pitfalls.py        # 只体检
    testRestfulProject\\venv\\Scripts\\python.exe tools\\check-ps-pitfalls.py --fix  # 自动补加固行

退出码：0 = 无错误级问题；1 = 有错误级问题。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".venv", "venv", ".cache"}
SKIP_PREFIX = ("venv-",)

# 判定"调用原生命令"的关键词（够用即可，宁可漏也不误报成错误级）
NATIVE_RE = re.compile(r"(\$Mysql|\$mysqld|\$mysqlClient|mysql\.exe|\bpip\b|sc\.exe|schtasks|nssm|taskkill|"
                       r"where\.exe|net\.exe|robocopy|xcopy|icacls|takeown|openfiles)")
EAP_RE = re.compile(r"^\s*\$ErrorActionPreference\s*=\s*'([^']+)'", re.M)
TOP_PARAM_RE = re.compile(r"^param\s*\(", re.M)          # ⚠️ 只认**脚本级**（顶格）的 param
QUOTED_ARG_RE = re.compile(r"""-\w+\s+'[^']*"[^']*'""")   # 例如 -e 'SELECT ... " " ...'
FIX_LINE = ("if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) "
            "{ $PSNativeCommandUseErrorActionPreference = $false }")


def iter_ps1(root: Path):
    for p in sorted(root.rglob("*.ps1")):
        parts = p.relative_to(root).parts[:-1]
        if any(part in SKIP_DIRS or part.startswith(SKIP_PREFIX) for part in parts):
            continue
        yield p


def apply_fix(text: str) -> tuple[str, bool]:
    """只做一件事：在已有的 `$ErrorActionPreference = ...` 之后补一行 PS7 兼容开关。

    ⚠️ 刻意**不**插入完整的 EAP 块、**不**改 EAP 的值、**不**碰 param —— 上一版工具乱插，
       把加固块插进了函数体，害得 apply-update.ps1 解析失败（教训）。
    """
    if "PSNativeCommandUseErrorActionPreference" in text:
        return text, False
    m = EAP_RE.search(text)
    if not m:
        return text, False
    end = text.find("\n", m.start())
    if end < 0:
        end = len(text)
    fixed = (text[:end + 1] + FIX_LINE + "\n" + text[end + 1:])
    return fixed, True


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parent.parent
    do_fix = "--fix" in sys.argv

    errors, notices, fixed = [], [], []
    n = 0
    for p in iter_ps1(root):
        n += 1
        rel = p.relative_to(root).as_posix()
        raw = p.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig", errors="replace")

        if do_fix:
            new_text, changed = apply_fix(text.replace("\r\n", "\n"))
            if changed:
                p.write_bytes((b"\xef\xbb\xbf" if has_bom else b"") + new_text.replace("\n", "\r\n").encode("utf-8"))
                fixed.append(rel)
                text = new_text
                raw = p.read_bytes()
                has_bom = raw.startswith(b"\xef\xbb\xbf")

        # ---- 错误级 ----
        # ① 双 BOM / 脚本级 param 之前有可执行语句
        if has_bom and raw[3:].decode("utf-8", errors="replace").startswith("\ufeff"):
            errors.append(f"{rel}：开头有**两个 BOM** → PowerShell 会把参数块当表达式解析"
                          f"（The assignment expression is not valid）；用 tools/check-encoding.py 也能查")
        m = TOP_PARAM_RE.search(text)
        if m:
            for i, line in enumerate(text[:m.start()].split("\n")):
                s = line.strip()
                if s and not s.startswith("#") and not s.startswith("["):
                    errors.append(f"{rel}:{i+1}：脚本级 `param(` 之前出现可执行语句 → 参数块解析会失败")
                    break

        # ② Stop + 原生命令 = 本次根因
        eaps = EAP_RE.findall(text)
        uses_native = bool(NATIVE_RE.search(text))
        if uses_native and any(v.lower() == "stop" for v in eaps):
            errors.append(f"{rel}：设了 `$ErrorActionPreference = 'Stop'` 又调用原生命令 → 原生命令的 stderr "
                          f"（如 mysql 的 ERROR 1045）会变成**终止性错误**，5.1 下直接把脚本杀掉（现场踩过）。\n"
                          f"        修：改成 Continue 并用 Die/退出码显式判断，或给原生命令加 `2>&1` 收下输出")

        # ---- 提示级 ----
        for i, line in enumerate(text.split("\n")):
            s = line.strip()
            if s.startswith("#"):
                continue
            if NATIVE_RE.search(s) and QUOTED_ARG_RE.search(s):
                notices.append(f"{rel}:{i+1}：原生命令参数里有**内嵌双引号** → 5.1 下可能被拆参：{s[:80]}")
        if "2>$null" in text:
            notices.append(f"{rel}：用了 `2>$null`（5.1 下仍可能生成 NativeCommandError；建议 `2>&1` 收下再判断）")
        if uses_native and not any(v.lower() in ("continue", "silentlycontinue") for v in eaps):
            notices.append(f"{rel}：调用原生命令但 EAP 不是 Continue（当前 {eaps or ['未设']}）")

    print(f"检查目录：{root}")
    print(f"  .ps1 文件：{n} 个" + (f"；本次自动补加固行 {len(fixed)} 个：{', '.join(fixed)}" if fixed else ""))
    if errors:
        print(f"  ❌ 错误 {len(errors)} 条（必须修）：")
        for e in errors:
            print(f"     - {e}")
    if notices:
        print(f"  ⚠️ 提示 {len(notices)} 条（人工确认）：")
        for e in notices:
            print(f"     - {e}")
    if not errors and not notices:
        print("  ✅ 无问题（param 位置、EAP、原生命令参数、BOM 都正常）")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查 tensorflow / torch 的 .pyd/.dll 依赖了哪些**系统级** DLL。

用来回答"是不是缺 VC++ 运行库"这个问题 —— 如果依赖表里出现
msvcp140.dll / vcruntime140.dll / vcruntime140_1.dll，
那确实需要 VC++ Redistributable；如果只是 api-ms-win-crt-*（UCRT），
那是 Windows 10+ 自带的，不用装任何东西。

用法：
    venv\\Scripts\\python.exe tools\\check-dll-deps.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"


def pe_imports(path: Path) -> list[str]:
    """极简 PE 导入表解析，只取被导入的 DLL 名字。"""
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return []
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return []
    coff = e_lfanew + 4
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    pe32p = magic == 0x20B
    dd = opt + (112 if pe32p else 96)

    sections = []
    sec_off = opt + opt_size
    for i in range(nsec):
        off = sec_off + i * 40
        va, vsz = struct.unpack_from("<II", data, off + 12)
        raw, rsz = struct.unpack_from("<II", data, off + 20)
        sections.append((va, max(vsz, rsz), raw))

    def rva2off(rva: int):
        for va, vsz, raw in sections:
            if va <= rva < va + vsz:
                return rva - va + raw
        return None

    try:
        imp_rva = struct.unpack_from("<I", data, dd + 8)[0]
    except struct.error:
        return []
    if not imp_rva:
        return []
    off = rva2off(imp_rva)
    if off is None:
        return []

    names = []
    while off + 20 <= len(data):
        ent = data[off:off + 20]
        if ent == b"\0" * 20:
            break
        name_rva = struct.unpack_from("<I", ent, 12)[0]
        if not name_rva:
            break
        no = rva2off(name_rva)
        if no is None or no >= len(data):
            break
        end = data.find(b"\0", no)
        names.append(data[no:end].decode("ascii", "replace"))
        off += 20
    return names


VCRUNTIME = ("msvcp", "vcruntime", "concrt", "vccorlib")


def classify(dll: str) -> str:
    low = dll.lower()
    if low.startswith(VCRUNTIME):
        return "VC++ 运行库（需要 Redistributable）"
    if low.startswith("api-ms-win-crt"):
        return "UCRT（Win10+ 自带，无需安装）"
    if low.startswith(("kernel32", "user32", "advapi32", "ws2_32", "ole32",
                       "shell32", "bcrypt", "crypt32", "psapi", "secur32")):
        return "Windows 系统 DLL（自带）"
    return "其它"


def scan(pkg: str) -> None:
    root = SITE / pkg
    print("=" * 70)
    print(f"  {pkg}")
    print("=" * 70)
    if not root.is_dir():
        print(f"  [跳过] 未安装: {root}")
        print()
        return

    bins = sorted(list(root.rglob("*.pyd")) + list(root.rglob("*.dll")))
    print(f"  二进制文件: {len(bins)} 个\n")

    need_vc: set[str] = set()
    ucrt: set[str] = set()
    other: set[str] = set()
    for b in bins:
        try:
            for d in pe_imports(b):
                low = d.lower()
                if low.startswith(VCRUNTIME):
                    need_vc.add(d)
                elif low.startswith("api-ms-win-crt"):
                    ucrt.add(d)
                elif low.endswith(".dll") and not low.startswith(("kernel32", "user32",
                                                                  "advapi32", "ws2_32",
                                                                  "ole32", "shell32",
                                                                  "bcrypt", "crypt32",
                                                                  "psapi", "secur32",
                                                                  "ntdll", "rpcrt4",
                                                                  "api-ms-win")):
                    other.add(d)
        except Exception:
            pass

    if need_vc:
        print("  ⚠️ 直接依赖 VC++ 运行库：")
        for d in sorted(need_vc):
            print(f"       {d}")
        print("     -> 目标机器需要装 Microsoft Visual C++ Redistributable (x64)")
    else:
        print("  ✅ 没有直接依赖 msvcp/vcruntime（VC++ Redistributable）")

    if ucrt:
        print(f"\n  UCRT（{len(ucrt)} 个，Win10+ 自带，不用管）")
    if other:
        print(f"\n  其它非系统 DLL（可能是包内自带的）：")
        for d in sorted(other)[:10]:
            print(f"       {d}")
    print()


if __name__ == "__main__":
    print()
    print(f"  扫描目录: {SITE}")
    for p in ("tensorflow", "torch"):
        scan(p)

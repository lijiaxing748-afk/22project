#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证"缺 VC++ 运行库"到底会怎么崩 —— 用真实的 LoadLibrary 试。

为什么要这么试：Windows 上 import tensorflow 失败有很多种表现，
    - 缺 VC++ 运行库 -> ImportError: DLL load failed while importing _pywrap_tensorflow_internal
    - 缺 python312.dll -> 同一种报错，但原因完全不同
只有真的去看"哪些依赖解析不了"才能区分。

用法：
    venv\\Scripts\\python.exe tools\\check-vcruntime.py
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

# 必须先让 tf 的目录进 DLL 搜索路径，否则我们自己也会误报
SITE = Path(__file__).resolve().parent.parent / "venv" / "Lib" / "site-packages"
TF = SITE / "tensorflow"
TORCH = SITE / "torch"
for p in (TF, TF / "python", TORCH / "lib"):
    if p.is_dir():
        os.add_dll_directory(str(p))


REQUIRED = [
    ("msvcp140.dll",              "VC++ 2015-2022 运行库 (msvcp140)"),
    ("vcruntime140.dll",          "VC++ 运行库 (vcruntime140)"),
    ("vcruntime140_1.dll",        "VC++ 运行库 (vcruntime140_1) —— VS2019 16.3+ 才有"),
    ("vcruntime140_threads.dll",  "VC++ 运行库 (vcruntime140_threads) —— VS2022 17.10+ 才有"),
    ("msvcp140_atomic_wait.dll",  "VC++ 运行库 (msvcp140_atomic_wait)"),
    ("concrt140.dll",             "VC++ 并发运行库（部分包会要）"),
]

print("=" * 70)
print("  1. 逐个检查 VC++ 运行库 DLL 能否被加载")
print("=" * 70)
missing = []
for name, desc in REQUIRED:
    try:
        ctypes.WinDLL(name)                       # 按系统搜索路径加载
        verdict = "OK"
    except OSError as exc:
        verdict = f"缺失 ({exc.winerror if hasattr(exc, 'winerror') else '?'})"
        missing.append((name, desc))
    flag = "  " if verdict == "OK" else "!!"
    print(f" {flag} {name:<30} {verdict:<14} {desc}")

print()
print("=" * 70)
print("  2. 直接尝试加载 tensorflow 的核心 DLL")
print("=" * 70)


def try_load(path: Path) -> None:
    if not path.is_file():
        print(f"    [跳过] 文件不存在: {path.name}")
        return
    try:
        ctypes.WinDLL(str(path))
        print(f"    [OK]   {path.name}")
    except OSError as exc:
        print(f"    [失败] {path.name}")
        print(f"           {exc}")
        # 把具体的"找不到哪个依赖"挖出来
        err = getattr(exc, "winerror", None)
        if err == 126:
            print("           winerror=126 = 找不到指定的模块（通常是缺依赖的 DLL）")


for cand in [
    TF / "python" / "_pywrap_tensorflow_internal.pyd",
    TF / "python" / "_pywrap_tensorflow_common.dll",
    TORCH / "lib" / "torch_cpu.dll",
    TORCH / "lib" / "c10.dll",
]:
    try_load(cand)

print()
print("=" * 70)
print("  3. 真实 import 测试")
print("=" * 70)
for mod in ("tensorflow", "torch", "sklearn", "numpy", "scipy"):
    try:
        m = __import__(mod)
        print(f"    [OK]   import {mod:<12} {getattr(m, '__version__', '?')}")
    except BaseException as exc:
        print(f"    [失败] import {mod:<12} {type(exc).__name__}: {exc}")

print()
print("=" * 70)
print("  结论")
print("=" * 70)
if missing:
    print("  ❌ 缺少以下 VC++ 运行库组件：")
    for name, desc in missing:
        print(f"       {name}   ({desc})")
    print()
    print("  处理：在目标机器上安装 vc_redist.x64.exe（离线包 01-安装程序/ 里已备）")
    print("       安装后**重启**终端，再试。")
else:
    print("  ✅ VC++ 运行库齐全，tensorflow / torch 的底层依赖没有问题。")
    print("     如果 import 仍然失败，问题不在 VC++ 运行库。")

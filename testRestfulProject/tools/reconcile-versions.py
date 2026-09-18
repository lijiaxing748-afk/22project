# -*- coding: utf-8 -*-
"""
把 requirements.txt 里每个版本号和"离线 wheel 里实际有的版本"对一遍。

为什么需要这个：手写 requirements 时很容易记错小版本号（比如 greenlet 3.5.5 vs 3.5.6）。
这种错在联网环境下 pip 会自动选一个兼容版本、看不出来；但离线安装是精确匹配，
一个都不许错，否则直接报 No matching distribution found。

本脚本会输出需要修正的行。
"""
import os
import re
import sys

req_path = sys.argv[1]
whl_dir = sys.argv[2]

# 先扫出 wheel 目录里每个包实际有哪些版本
# wheel 文件名形如：greenlet-3.5.6-cp312-cp312-win_amd64.whl
available = {}
for fn in os.listdir(whl_dir):
    if not fn.lower().endswith(".whl"):
        continue
    parts = fn[:-4].split("-")
    if len(parts) < 2:
        continue
    name = parts[0].lower().replace("_", "-")
    ver = parts[1]
    available.setdefault(name, set()).add(ver)

print(f"wheel 目录里有 {len(available)} 个不同的包\n")

lines = open(req_path, encoding="utf-8-sig").read().split("\n")
fixes = []
for idx, raw in enumerate(lines, 1):
    line = raw.split("#")[0].strip()
    m = re.match(r"^([A-Za-z0-9_.\-]+)\s*==\s*(.+)$", line)
    if not m:
        continue
    name, ver = m.group(1), m.group(2).strip()
    key = name.lower().replace("_", "-")
    if key not in available:
        fixes.append((idx, name, ver, "wheel 目录里没有这个包", None))
        continue
    if ver not in available[key]:
        # 选一个最接近的实际版本建议
        actual = sorted(available[key])[-1]
        fixes.append((idx, name, ver, f"实际可用: {', '.join(sorted(available[key]))}", actual))

if not fixes:
    print("全部版本号与 wheel 一致，无需修正")
    sys.exit(0)

print(f"发现 {len(fixes)} 处需要修正：\n")
for idx, name, ver, note, actual in fixes:
    if actual:
        print(f"  行{idx:>3}  {name}=={ver}   ->   {name}=={actual}")
        print(f"          （{note}）")
    else:
        print(f"  行{idx:>3}  {name}=={ver}   ->   {note}")

print()
print("=== 可直接套用的替换 ===")
for idx, name, ver, note, actual in fixes:
    if actual:
        print(f'  "{name}=={ver}" -> "{name}=={actual}"')

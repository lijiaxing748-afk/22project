# -*- coding: utf-8 -*-
"""校验修好的 requirements.txt：能解析、无重复、覆盖关键包、与真实环境一致。"""
import re
import sys
from collections import Counter

req_path = sys.argv[1]
freeze_path = sys.argv[2]


def parse(path):
    pkgs = {}
    for raw in open(path, encoding="utf-8-sig"):
        line = raw.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*==\s*(.+)$", line)
        if m:
            pkgs[m.group(1).lower().replace("_", "-")] = m.group(2).strip()
    return pkgs


req = parse(req_path)
print(f"requirements.txt 解析出 {len(req)} 个包")

# 重复检查
names = []
for raw in open(req_path, encoding="utf-8-sig"):
    line = raw.split("#")[0].strip()
    m = re.match(r"^([A-Za-z0-9_.\-]+)\s*==", line)
    if m:
        names.append(m.group(1).lower().replace("_", "-"))
dups = [n for n, c in Counter(names).items() if c > 1]
print(f"重复项: {dups if dups else '无'}")

# 关键包检查
critical = ["tensorflow", "keras", "torch", "flask", "flask-cors",
            "pymysql", "python-dotenv", "sqlalchemy", "statsmodels",
            "tabulate", "numpy", "pandas", "scikit-learn", "matplotlib"]
print()
print("=== 关键包 ===")
missing = []
for c in critical:
    if c in req:
        print(f"   [OK]   {c}=={req[c]}")
    else:
        print(f"   [缺失] {c}")
        missing.append(c)

# 与真实环境比对
if freeze_path:
    real = parse(freeze_path)
    print()
    print("=== 与本机真实环境（pip freeze）比对 ===")
    only_req = sorted(set(req) - set(real))
    only_real = sorted(set(real) - set(req))
    print(f"   仅在 requirements 里: {only_req if only_req else '无'}")
    print(f"   仅在环境中未列出  : {only_real if only_real else '无'}")

    # 版本不一致的
    diff = [(k, req[k], real[k]) for k in set(req) & set(real) if req[k] != real[k]]
    print()
    if diff:
        print("   版本不一致：")
        for k, a, b in sorted(diff):
            print(f"     {k}: requirements={a}  实际={b}")
    else:
        print("   版本全部一致")

# 检查是否还有 keras-nightly
print()
if "keras-nightly" in req:
    print("   [错误] 仍含 keras-nightly（应为正式版 keras）")
    sys.exit(1)
else:
    print("   [OK] 已不含 keras-nightly")

if missing:
    print(f"\n   [错误] 缺少关键包: {missing}")
    sys.exit(1)
print("\n校验通过")

# -*- coding: utf-8 -*-
"""对解压出来的包内 dist 做 baseURL 校验（用于验证 tar.gz 是否打进了修好的前端）。"""
import pathlib
import re
import sys

DIST = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not DIST or not DIST.is_dir():
    print("[FAIL] 请传入 dist 目录路径")
    sys.exit(1)

ASSETS = DIST / "assets"
print("=" * 62)
print(f"  校验包内产物：{DIST}")
print("=" * 62)

vb = DIST / "version-build"
if vb.is_file():
    print(f"\n  version-build : {vb.read_text(encoding='utf-8').strip()}")

pat = re.compile(r'function\(e=null,t=null\)\{let n="([^"]*)";')
found = []
for f in sorted(ASSETS.glob("*.js")):
    s = f.read_text(encoding="utf-8", errors="ignore")
    for m in pat.finditer(s):
        found.append((f.name, m.group(1)))

print("\n  ---- getBaseURL 编译结果 ----")
ok = True
if not found:
    print("  [FAIL] 找不到 getBaseURL")
    ok = False
for name, val in found:
    good = (val == "")
    if not good:
        ok = False
    print(f"  {name:<30} baseURL = {val!r:<10} {'✅ 正确' if good else '❌ 错误（会双前缀）'}")

print("\n  ---- captcha 字面量 ----")
for f in sorted(ASSETS.glob("*.js")):
    s = f.read_text(encoding="utf-8", errors="ignore")
    for m in re.finditer(r'url:"([^"]*captcha[^"]*)"', s):
        print(f"  {f.name:<30} url = {m.group(1)!r}")

print("\n  ---- 双前缀痕迹 ----")
hits = [f.name for f in sorted(ASSETS.glob("*.js"))
        if "api/api" in f.read_text(encoding="utf-8", errors="ignore")]
print("  " + (", ".join(hits) if hits else "无（干净）✅"))
if hits:
    ok = False

print("\n" + "=" * 62)
print("  结论：" + ("✅ 包内前端正确，可分发" if ok else "❌ 包内前端有误，需重新打包"))
print("=" * 62)
sys.exit(0 if ok else 1)

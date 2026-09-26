# -*- coding: utf-8 -*-
"""校验前端 dist 里 axios baseURL 的实际编译值。

背景：/api/captcha/ 在浏览器里变成 /api/api/captcha/，根因是打包时
VITE_API_URL 不是空字符串（.env.production 里是 '/api'）。
本脚本直接从产物中反查 getBaseURL 编译后的返回值，避免"看着源码是对的、
实际打包用了别的 mode"这种误判。
"""
import pathlib
import re
import sys

DIST = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "22project" / "dist"
ASSETS = DIST / "assets"

if not ASSETS.is_dir():
    print(f"[FAIL] 找不到产物目录：{ASSETS}")
    sys.exit(1)

print("=" * 62)
print("  校验前端产物 axios baseURL")
print("=" * 62)

# 1) 找 version-build
vb = DIST / "version-build"
if vb.is_file():
    print(f"\n  version-build : {vb.read_text(encoding='utf-8').strip()}")

# 2) 反查 getBaseURL：编译后形如  X=function(e=null,t=null){let n="<值>";return ...}
#    注意压缩后变量名可能是 zb / Yt 等，所以只按结构匹配。
pat = re.compile(r'function\(e=null,t=null\)\{let n="([^"]*)";')

found = []
for f in sorted(ASSETS.glob("*.js")):
    try:
        s = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for m in pat.finditer(s):
        found.append((f.name, m.group(1)))

print("\n  ---- getBaseURL 编译结果 ----")
if not found:
    print("  [!] 没匹配到 getBaseURL 结构，改用宽松扫描")
    # 宽松：找 let n=""; 后紧跟 replace(/\/$/,"")
    loose = re.compile(r'let n="([^"]*)";return t&&')
    for f in sorted(ASSETS.glob("*.js")):
        s = f.read_text(encoding="utf-8", errors="ignore")
        for m in loose.finditer(s):
            found.append((f.name, m.group(1)))

if not found:
    print("  [FAIL] 完全找不到 baseURL 常量，产物结构可能变了")
    sys.exit(1)

ok = True
for name, val in found:
    if val == "":
        verdict = "正确（空字符串，请求直接打同源）"
    else:
        verdict = f"错误！会叠成 '{val}{val}/xxx' 双前缀"
        ok = False
    print(f"  {name:<34} baseURL = {val!r:<10} {verdict}")

# 3) 顺带查 api 分片里 captcha 字面量
print("\n  ---- 接口字面量（应为单 /api 前缀）----")
for f in sorted(ASSETS.glob("*.js")):
    s = f.read_text(encoding="utf-8", errors="ignore")
    if "captcha" in s:
        for m in re.finditer(r'url:"([^"]*captcha[^"]*)"', s):
            print(f"  {f.name:<34} url = {m.group(1)!r}")

# 4) 查双前缀痕迹
print("\n  ---- 双前缀痕迹 api/api ----")
hits = []
for f in sorted(ASSETS.glob("*.js")):
    s = f.read_text(encoding="utf-8", errors="ignore")
    if "api/api" in s:
        hits.append(f.name)
print("  " + (", ".join(hits) if hits else "无（干净）"))
if hits:
    ok = False

print("\n" + "=" * 62)
print("  结论：" + ("通过，可以打包" if ok else "不通过，需用 build:singleport 重新构建"))
print("=" * 62)
sys.exit(0 if ok else 1)

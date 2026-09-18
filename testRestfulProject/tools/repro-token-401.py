# -*- coding: utf-8 -*-
"""复现：登录拿 token → 用该 token 访问 user_info，看是否被判"登录已失效"。

这个脚本严格模拟 curl 的行为（同一个 token、同一个进程外的 HTTP 请求），
并把**响应体原样打出来**，用于确认"是不是跨进程/跨请求才失效"。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

BASE = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else 5000}"

print(f"目标: {BASE}\n")

# 1. 登录
r = requests.post(f"{BASE}/api/login/",
                  json={"username": "admin", "password": "Admin@2026"}, timeout=20)
print(f"[1] POST /api/login/  -> HTTP {r.status_code}")
body = r.json()
print(f"    code={body.get('code')}  msg={body.get('msg')}")
tok = (body.get("data") or {}).get("access")
if not tok:
    print("    !! 没拿到 token，后续无法进行")
    sys.exit(1)
print(f"    token = {tok[:45]}...")
print(f"    token 段数 = {len(tok.split('.'))}  (itsdangerous 是 3 段)")

# 2. 用 Bearer 访问 user_info（模拟 curl）
print()
r2 = requests.get(f"{BASE}/api/system/user/user_info/",
                  headers={"Authorization": f"Bearer {tok}"}, timeout=20)
print(f"[2] GET /api/system/user/user_info/  (Authorization: Bearer <token>)")
print(f"    -> HTTP {r2.status_code}   {r2.text[:220]}")

# 3. 换用 dvadmin 风格的裸 token 头
print()
r3 = requests.get(f"{BASE}/api/system/user/user_info/",
                  headers={"token": tok}, timeout=20)
print(f"[3] 同一 token 放 `token` 头")
print(f"    -> HTTP {r3.status_code}   {r3.text[:220]}")

# 4. 换 ?token= 方式
print()
r4 = requests.get(f"{BASE}/api/system/user/user_info/",
                  params={"token": tok}, timeout=20)
print(f"[4] 同一 token 放 ?token= 查询串")
print(f"    -> HTTP {r4.status_code}   {r4.text[:220]}")

# 5. 不带任何凭证（对照组，应该也是 401/4000）
print()
r5 = requests.get(f"{BASE}/api/system/user/user_info/", timeout=20)
print(f"[5] 完全不带凭证（对照组）")
print(f"    -> HTTP {r5.status_code}   {r5.text[:220]}")

# 6. /health 看服务端自报的鉴权配置
print()
try:
    h = requests.get(f"{BASE}/health", timeout=20).json()
    d = h.get("data") or h
    print(f"[6] /health 里的 auth 配置: {json.dumps(d.get('config', {}).get('auth', d.get('auth')), ensure_ascii=False)}")
    print(f"    env_file = {(d.get('config') or {}).get('env_file')}")
except Exception as e:  # noqa: BLE001
    print(f"[6] /health 读取失败: {e}")

print("\n判读：")
print("  如果 [2][3][4] 全部 4000 而 [5] 也是 4000，说明服务端**根本没认出这个 token**；")
print("  如果 [2]/[3] 成功而 [4] 失败，是取值方式问题，不是密钥问题。")

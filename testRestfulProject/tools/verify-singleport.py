# -*- coding: utf-8 -*-
"""单端口托管验收：确认"一个端口跑完整站"真的成立。

跑法： venv\\Scripts\\python.exe tools\\verify-singleport.py

它检查三件最容易出错的事：
  1. 前端路由（/platform/model 这种**并不存在的文件**）能不能返回 index.html
     —— 这是 SPA 兜底的核心，答错就是"按 F5 白屏"
  2. 业务接口有没有被 SPA 兜底吃掉（必须仍是 JSON，不能变成 HTML）
  3. API 的 404 有没有如实回 404（不能伪装成 200 的 HTML）
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from main import app  # noqa: E402
from model_service.web import _dist_dir  # noqa: E402
c = app.test_client()
fails = []


def ck(label, cond, extra=""):
    if not cond:
        fails.append(label)
    print(f"  [{'OK ' if cond else 'BAD'}] {label:<52} {extra}")


def is_html(resp):
    return "text/html" in (resp.headers.get("Content-Type") or "")


def is_json(resp):
    return "application/json" in (resp.headers.get("Content-Type") or "")


print("=== 0. 前端产物是否被找到 ===")
dist = _dist_dir()
print(f"    产物目录: {dist}")
ck("找到 dist 且含 index.html", dist is not None and (dist / "index.html").is_file())

print()
print("=== 1. 首页与静态资源 ===")
r = c.get("/")
ck("/ 返回 HTML（前端首页，不是 JSON 接口清单）",
   r.status_code == 200 and is_html(r), f"-> {r.status_code}, {r.mimetype}")
ck("index.html 明确不缓存",
   "no-cache" in (r.headers.get("Cache-Control") or "") or "no-store" in (r.headers.get("Cache-Control") or ""),
   f"-> {r.headers.get('Cache-Control')}")

body = r.get_data(as_text=True)
import re  # noqa: E402
m = re.search(r'src="(/assets/[^"]+\.js)"', body)
if m:
    asset = m.group(1)
    r2 = c.get(asset)
    ck(f"assets 能被取到 ({asset[:34]}…)", r2.status_code == 200, f"-> {r2.status_code}")
    ck("assets 长缓存（带 hash 可放心缓存）",
       "max-age=31536000" in (r2.headers.get("Cache-Control") or ""),
       f"-> {r2.headers.get('Cache-Control')}")
else:
    ck("index.html 里能找到 /assets/*.js 引用", False, f"-> {body[:120]}")

print()
print("=== 2. SPA 兜底：前端路由必须回 index.html（F5 刷新不能白屏）===")
# 这四条都是 Vue Router 的路径，**服务器上不存在对应文件**
for p in ("/home", "/login", "/platform/model", "/platform/publish", "/platform/visual"):
    r = c.get(p)
    ok = r.status_code == 200 and is_html(r) and "<div id=" in r.get_data(as_text=True)
    ck(f"GET {p} -> index.html", ok, f"-> {r.status_code}, html={is_html(r)}")

print()
print("=== 3. 业务接口没有被兜底吃掉（必须是 JSON）===")
for p in ("/health", "/models", "/datasets", "/api"):
    r = c.get(p)
    ck(f"GET {p} 仍是 JSON", r.status_code == 200 and is_json(r),
       f"-> {r.status_code}, json={is_json(r)}")

print()
print("=== 3b. 接口清单已挪到 /api（/ 让给前端首页）===")
r = c.get("/api")
idx = r.get_json() or {}
ck("/api 是接口索引", "endpoints" in idx, f"-> keys={list(idx)[:4]}")
ck("路由表里 / 只剩一条（前端首页）",
   sum(1 for rl in app.url_map.iter_rules() if str(rl) == "/") == 1)
ck("/ 与 /api 是不同 endpoint",
   app.url_map.bind("localhost").match("/")[0] != app.url_map.bind("localhost").match("/api")[0],
   f"-> /: {app.url_map.bind('localhost').match('/')[0]}, /api: {app.url_map.bind('localhost').match('/api')[0]}")

print()
print("=== 4. API 的 404 如实回 404（不能伪装成 200 的 HTML）===")
for p in ("/models/nope/nope", "/api/definitely-not-a-route", "/health/extra/deep"):
    r = c.get(p)
    # 三类都可以是 404；关键是**不能是 200 的 index.html**
    ok = not (r.status_code == 200 and is_html(r))
    ck(f"GET {p} 未被 SPA 兜底", ok, f"-> {r.status_code}, html={is_html(r)}")

print()
print("=== 5. 目录穿越防护 ===")
for p in ("/../db.env", "/..%2fdb.env", "/assets/../../db.env"):
    r = c.get(p)
    leaked = "MODEL_DB" in r.get_data(as_text=True)
    ck(f"{p} 未泄露 db.env", not leaked, f"-> {r.status_code}")

print()
print("=== 6. 鉴权在单端口下依然生效 ===")
r = c.post("/train", json={"model": "1dcnn"})
ck("未登录 POST /train 仍 401", r.status_code == 401, f"-> {r.status_code}")
r = c.get("/models/1DCNN/exports/x.zip")
ck("未登录下载仍 401", r.status_code == 401, f"-> {r.status_code}")
r = c.get("/api/system/user/user_info/")
ck("未登录 user_info 仍被拒", (r.get_json() or {}).get("code") == 4000)

print()
print("=" * 68)
print("  失败项:", fails if fails else "无 —— 全部通过")
sys.exit(1 if fails else 0)

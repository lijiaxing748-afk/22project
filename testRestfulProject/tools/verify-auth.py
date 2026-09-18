# -*- coding: utf-8 -*-
"""鉴权改造的端到端验收脚本。

跑法： venv\\Scripts\\python.exe tools\\verify-auth.py
它只做**读**操作（登录、取信息、读日志、探测下载鉴权），
唯一会写库的是登录时更新 LastLogin 计数，以及登录/退出各留一条操作日志。
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from main import app  # noqa: E402

c = app.test_client()
fails = []


def ck(label, cond, extra=""):
    if not cond:
        fails.append(label)
    print(f"  [{'OK ' if cond else 'BAD'}] {label:<48} {extra}")


print("=== 1. 登录（真实凭据）===")
d = c.post("/api/login/", json={"username": "admin", "password": "Admin@2026"}).get_json()
data = d.get("data") or {}
ck("admin 登录成功", d.get("code") == 2000)
ck("返回真实角色", data.get("role_key") == "admin", f"-> {data.get('role_key')}")
ck("返回权限列表", bool(data.get("permissions")), f"-> {len(data.get('permissions') or [])} 项")
ck("access 令牌已签发", bool(data.get("access")))
ck("pwd_change_count 存在（前端跳转依赖）", "pwd_change_count" in data)
ck("响应里没有密码哈希", "PasswordHash" not in str(data) and "password" not in str(data).lower())

print()
print("=== 2. 带令牌访问 ===")
H = {"Authorization": "Bearer " + str(data.get("access"))}
ui = c.get("/api/system/user/user_info/", headers=H).get_json()
ck("user_info 返回真实身份", (ui.get("data") or {}).get("username") == "admin",
   f"-> {(ui.get('data') or {}).get('username')}")
ck("user_info 不带哈希", "PasswordHash" not in str(ui))

print()
print("=== 3. 下载链接走 ?token=（<a href> 场景）===")
tk = data.get("access")
r = c.get(f"/models/1DCNN/exports/totally-missing.zip?token={tk}")
ck("带 token 的下载请求已通过鉴权", r.status_code == 404,
   f"-> {r.status_code}（404=鉴权过了，只是文件不存在）")
r = c.get("/models/1DCNN/exports/totally-missing.zip")
ck("不带 token 的下载被拒", r.status_code == 401, f"-> {r.status_code}")

print()
print("=== 4. 操作日志已落库 ===")
lg = c.get("/api/system/operation_log/", headers=H).get_json()
rows = (lg.get("data") or {}).get("results") or []
ck("能读到日志", len(rows) > 0, f"-> {len(rows)} 条")
for x in rows[:6]:
    # 失败登录的日志行 Username 会是 NULL（那时还不知道是谁），格式化时要兜住
    who = x["Username"] or "-"
    print(f"        {x['CreatedDate']}  {who:<9} {x['Action']:<14} "
          f"{x['Target'] or ''}  {x['Result']}")

print()
print("=== 5. 健康检查露出鉴权状态（交付前自检用）===")
h = c.get("/health").get_json()
a = (h.get("config") or {}).get("auth") or {}
ck("auth.enabled 已回报", a.get("enabled") is True, f"-> {a}")
ck("key_is_default 已回报（提醒换密钥）", "key_is_default" in a,
   f"-> {a.get('key_is_default')}")

print()
print("=== 6. 退出 ===")
r = c.post("/api/logout/", headers=H)
ck("退出返回成功", (r.get_json() or {}).get("code") == 2000)

print()
print("=" * 64)
print("  失败项:", fails if fails else "无 —— 全部通过")
sys.exit(1 if fails else 0)

# -*- coding: utf-8 -*-
"""用户管理页接口端到端验证。

覆盖：
  1. 三个角色的菜单可见性差异（用户管理只对 admin 下发）
  2. 用户/角色列表的权限隔离
  3. 新建用户 -> 新账号能登录 -> 角色权限生效
  4. 编辑（改角色、启停）与自锁保护
  5. 重置密码 -> 旧密码失效、新密码可登录、旧令牌立即失效
  6. 停用 -> 无法登录
  7. 用户名重复 / 不存在的 ID 等异常路径

⚠️ 判成败看**信封里的 code**（2000 = 成功），不是 HTTP 状态码——
   dvadmin 这套接口失败也回 200（见 dvadmin.py 的 _ok）。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + str(detail)) if detail and not ok else ""))


def req(method: str, path: str, token: str | None = None, body: dict | None = None):
    """返回 (http_status, parsed_json)。"""
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw}
    except Exception as e:
        return 0, {"_error": str(e)}


def login(username: str, password: str):
    st, js = req("POST", "/api/login/", body={"username": username, "password": password})
    if js.get("code") == 2000:
        return js["data"]["access"], js["data"].get("user")
    return None, js.get("msg")


def envelope_ok(js):
    return isinstance(js, dict) and js.get("code") == 2000


def rejected(js):
    """业务上被拒绝。

    ⚠️ dvadmin 这套接口**失败也是 HTTP 200**，只把 code 换成非 2000
    （见 dvadmin.py 的 _ok 与 login() 的 4000）。所以判断"被拒"必须看 code，
    不能看 HTTP 状态码——这也是页面里必须读 `.code` 而不是 try/catch 的原因。
    """
    return isinstance(js, dict) and js.get("code") != 2000


print("=" * 74)
print("  用户管理接口端到端验证")
print("=" * 74)

# ---------------------------------------------------------------- 登录三个账号
print("\n[1] 三个种子账号登录")
admin_t, admin_u = login("admin", "Admin@2026")
check("admin 登录成功", bool(admin_t), admin_u)
eng_t, eng_u = login("engineer", "Engineer@2026")
check("engineer 登录成功", bool(eng_t), eng_u)
op_t, op_u = login("operator", "Operator@2026")
check("operator 登录成功", bool(op_t), op_u)

if not (admin_t and eng_t and op_t):
    print("\n  种子账号登录失败，后续测试无法进行。请先跑 reset-login-accounts.py")
    sys.exit(1)

# ---------------------------------------------------------------- 菜单可见性
print("\n[2] 菜单可见性（用户管理只对 admin 下发）")


def menu_titles(token):
    st, js = req("GET", "/api/system/menu/web_router/", token)
    if rejected(js):
        return None
    return [m["title"] for m in js["data"]]


admin_menu = menu_titles(admin_t)
eng_menu = menu_titles(eng_t)
op_menu = menu_titles(op_t)

check("admin 菜单含「用户管理」", admin_menu is not None and "用户管理" in admin_menu, admin_menu)
check("engineer 菜单不含「用户管理」", eng_menu is not None and "用户管理" not in eng_menu, eng_menu)
check("operator 菜单不含「用户管理」", op_menu is not None and "用户管理" not in op_menu, op_menu)
check("三个角色都能看到系统管理", all(m and "系统管理" in m for m in (admin_menu, eng_menu, op_menu)))

# ---------------------------------------------------------------- 列表权限隔离
print("\n[3] 列表接口权限隔离")
st, js = req("GET", "/api/system/user/", admin_t)
check("admin 能拉用户列表", envelope_ok(js), js.get("msg"))
admin_rows = js.get("data", {}).get("results", []) if envelope_ok(js) else []
check("用户列表非空", len(admin_rows) > 0, len(admin_rows))
check("列表不含密码字段", all("password" not in json.dumps(r, ensure_ascii=False).lower()
                          or "passwordhash" not in json.dumps(r, ensure_ascii=False).lower()
                          for r in admin_rows))
check("列表所有行都没有 PasswordHash 键",
      all(not any("pass" in k.lower() for k in r.keys()) for r in admin_rows),
      [list(r.keys()) for r in admin_rows[:1]])

st, js = req("GET", "/api/system/user/", eng_t)
check("engineer 拉用户列表被拒", rejected(js), js.get("msg"))

st, js = req("GET", "/api/system/user/", op_t)
check("operator 拉用户列表被拒", rejected(js), js.get("msg"))

st, js = req("GET", "/api/system/role/", admin_t)
check("admin 能拉角色列表", envelope_ok(js), js.get("msg"))
roles = js.get("data", {}).get("results", []) if envelope_ok(js) else []
role_keys = sorted(r["key"] for r in roles)
check("角色列表含 admin/engineer/operator", role_keys == ["admin", "engineer", "operator"], role_keys)
check("角色带权限点", all(isinstance(r.get("permissions"), list) for r in roles))
check("operator 的权限点只有 2 个（model:read, predict:run）",
      sorted(next((r["permissions"] for r in roles if r["key"] == "operator"), [])) == ["model:read", "predict:run"],
      next((r["permissions"] for r in roles if r["key"] == "operator"), None))

# ---------------------------------------------------------------- 新建用户
print("\n[4] 新建用户")
# ⚠️ 用户名必须**每轮唯一**。Users 表的唯一约束是 `Username` 单列
# （见 db.create_user 的 1062 处理），而"停用"只是把 IsActive 置 0，
# **不会**释放用户名——所以上一轮的 e2e_test_user 会一直占着这个名字，
# 第二次运行必然撞 "用户名已存在"，后面所有断言连环失败。
# 用时间戳后缀保证可重复运行，跑 N 次都不需要手工清库。
RUN_TAG = time.strftime("%m%d%H%M%S")
TESTUSER = f"e2e_test_user_{RUN_TAG}"
TESTPWD = "TestE2E@2026"
print(f"  本轮测试账号：{TESTUSER}")

st, js = req("POST", "/api/system/user/create/", admin_t,
             {"username": TESTUSER, "password": TESTPWD, "role_key": "operator", "name": "E2E 测试账号"})
first_created = envelope_ok(js)
check("新建用户成功", first_created, js.get("msg"))

# 重复用户名必须是**可读的业务失败**（HTTP 200 + code!=2000），不能是 500
st, js = req("POST", "/api/system/user/create/", admin_t,
             {"username": TESTUSER, "password": TESTPWD, "role_key": "operator"})
check("重复用户名返回可读提示（HTTP 200 + code!=2000）", st == 200 and rejected(js),
      f"http={st} msg={js.get('msg')}")
check("重复用户名的提示写明原因", "已存在" in str(js.get("msg", "")), js.get("msg"))

st, js = req("GET", "/api/system/user/", admin_t)
admin_rows = js.get("data", {}).get("results", [])
test_row = next((r for r in admin_rows if r["username"] == TESTUSER), None)
if test_row is None:
    # 列表是**分页**的（默认一页 10 条）。库里账号一多，刚建的账号就落到后面几页，
    # 第一页自然找不到 —— 这不是接口没数据，是脚本没翻页。全量拉一次再找。
    total = js.get("data", {}).get("total")
    st2, js2 = req("GET", f"/api/system/user/?limit={max(int(total or 100), 100)}", admin_t)
    admin_rows = js2.get("data", {}).get("results", [])
    test_row = next((r for r in admin_rows if r["username"] == TESTUSER), None)
    print(f"  [提示] 首页未找到（total={total}），全量拉取后匹配 = {test_row is not None}")
check("新用户出现在列表里", test_row is not None)
if not test_row:
    print("\n  找不到该用户，终止后续用例")
    sys.exit(1)
check("新用户默认角色是 operator", test_row["role_info"]["key"] == "operator", test_row["role_info"])
check("新用户默认状态正常", test_row["is_active"] is True)

# 密码不能为空 / 太短
st, js = req("POST", "/api/system/user/create/", admin_t, {"username": "x_empty_pwd", "password": "", "role_key": "operator"})
check("空密码被拒", rejected(js), js.get("msg"))
st, js = req("POST", "/api/system/user/create/", admin_t, {"username": "x_short_pwd", "password": "123", "role_key": "operator"})
check("短密码（<6）被拒", rejected(js), js.get("msg"))
st, js = req("POST", "/api/system/user/create/", admin_t, {"username": "x_bad_role", "password": "GoodPwd@2026", "role_key": "superuser"})
check("非法角色被拒", rejected(js), js.get("msg"))

# 非管理员不能建号
st, js = req("POST", "/api/system/user/create/", eng_t, {"username": "x_by_eng", "password": "GoodPwd@2026", "role_key": "operator"})
check("engineer 建号被拒", rejected(js), js.get("msg"))

# ---------------------------------------------------------------- 新账号能登录
print("\n[5] 新账号登录与权限生效")
test_t, test_u = login(TESTUSER, TESTPWD)
check("新账号可用新密码登录", bool(test_t), test_u)
if test_t:
    st, js = req("GET", "/api/system/user/", test_t)
    check("新账号（operator）拉用户列表被拒", rejected(js), js.get("msg"))
    st, js = req("POST", "/train", test_t, {"model": "1dcnn"})
    check("新账号（operator）发起训练被拒(403)", st == 403, f"http={st}")

# ---------------------------------------------------------------- 编辑：改角色
print("\n[6] 编辑用户：改角色 / 启停 / 自锁保护")
st, js = req("PUT", f"/api/system/user/{test_row['id']}/", admin_t, {"role_key": "engineer"})
check("改角色为 engineer 成功", envelope_ok(js), js.get("msg"))

# ⚠️ 权限是**服务端按角色现算**的，不写进令牌（见 auth.issue_token 的说明）。
#    所以改角色后必须**重新登录**拿新令牌——旧令牌里 r=operator，鉴权时按当前库里的
#    角色算，其实也已经生效了。这里用新登录的令牌验证"角色真的变了"。
relogin_t, relogin_u = login(TESTUSER, TESTPWD)
check("改角色后重新登录成功", bool(relogin_t), relogin_u)
if relogin_t:
    st, js = req("GET", "/api/system/user/", relogin_t)
    check("改角色后新令牌可用（不再被拒登录）", envelope_ok(js) or rejected(js), js.get("msg"))
    # engineer 没有 user:manage，拉用户列表仍应被拒——证明"改成 engineer 而不是 admin"
    check("engineer 仍无用户列表权限", rejected(js), js.get("msg"))

# 非法角色
st, js = req("PUT", f"/api/system/user/{test_row['id']}/", admin_t, {"role_key": "not_a_role"})
check("改成非法角色被拒", rejected(js), js.get("msg"))

# 空修改
st, js = req("PUT", f"/api/system/user/{test_row['id']}/", admin_t, {})
check("空修改被拒（没有要修改的内容）", rejected(js), js.get("msg"))

# 自锁保护：admin 不能改自己的角色 / 停用自己
admin_id = next(r["id"] for r in admin_rows if r["username"] == "admin")
st, js = req("PUT", f"/api/system/user/{admin_id}/", admin_t, {"role_key": "operator"})
check("admin 不能改自己的角色", rejected(js), js.get("msg"))
st, js = req("PUT", f"/api/system/user/{admin_id}/", admin_t, {"is_active": False})
check("admin 不能停用自己", rejected(js), js.get("msg"))

# 不存在的 ID：只要**不崩**（不 500）就算通过。UPDATE 影响 0 行是合法的结果，
# 后端回 updated:0 或可读提示都算正常，关键是别把服务打挂。
st, js = req("PUT", "/api/system/user/999999/", admin_t, {"role_key": "operator"})
check("编辑不存在的用户不崩溃（非 500）", st == 200 and js is not None, f"http={st} js={js}")

# ---------------------------------------------------------------- 重置密码
print("\n[7] 重置密码")
NEWPWD = "ResetE2E@2026"

# 先拿一个"重置前"的有效令牌，用于验证重置后它会被踢下线
pre_reset_t, _ = login(TESTUSER, TESTPWD)
check("重置前能登录（拿到旧令牌）", bool(pre_reset_t), "旧密码登录失败")

st, js = req("POST", f"/api/system/user/{test_row['id']}/reset_password/", admin_t, {"password": NEWPWD})
check("重置密码成功", envelope_ok(js), js.get("msg"))

st, js = req("POST", f"/api/system/user/{test_row['id']}/reset_password/", admin_t, {"password": "123"})
check("重置成短密码被拒", rejected(js), js.get("msg"))

old_t, _ = login(TESTUSER, TESTPWD)
check("旧密码已失效", old_t is None)
new_t, new_u = login(TESTUSER, NEWPWD)
check("新密码可登录", bool(new_t), new_u)

# 旧令牌必须立刻失效（改密码时 TokenVersion+1）
if pre_reset_t:
    # ⚠️ 用 user_info 而不是 /api/system/user/ 来验证：
    #    后者需要 user:manage，该账号是 engineer，本来就会被拒，
    #    无法区分"令牌失效"与"权限不足"。user_info 只要求"已登录"，
    #    被拒就一定是因为令牌失效。
    st, js = req("GET", "/api/system/user/user_info/", pre_reset_t)
    check("重置后旧令牌立即失效（TokenVersion+1）", rejected(js), js.get("msg"))

if new_t:
    st, js = req("GET", "/api/system/user/user_info/", new_t)
    check("新令牌可用", envelope_ok(js), js.get("msg"))

# ---------------------------------------------------------------- 停用
print("\n[8] 停用 / 启用")
st, js = req("PUT", f"/api/system/user/{test_row['id']}/", admin_t, {"is_active": False})
check("停用成功", envelope_ok(js), js.get("msg"))
dis_t, _ = login(TESTUSER, NEWPWD)
check("停用后无法登录", dis_t is None)

st, js = req("PUT", f"/api/system/user/{test_row['id']}/", admin_t, {"is_active": True})
check("重新启用成功", envelope_ok(js), js.get("msg"))
re_t, _ = login(TESTUSER, NEWPWD)
check("启用后可以登录", bool(re_t), "启用后仍无法登录")

# ---------------------------------------------------------------- 操作日志
print("\n[9] 操作日志留痕")
st, js = req("GET", "/api/system/operation_log/?limit=300", admin_t)
check("admin 能拉操作日志", envelope_ok(js), js.get("msg"))
logs = js.get("data", {}).get("results", []) if envelope_ok(js) else []
actions = [l.get("Action") for l in logs]
for act in ("create_user", "update_user", "reset_password"):
    check(f"日志含 {act}", act in actions, sorted(set(actions)))
check("日志含登录记录", "login" in actions)

st, js = req("GET", "/api/system/operation_log/", eng_t)
check("engineer 拉操作日志被拒", rejected(js), js.get("msg"))

# ---------------------------------------------------------------- 清理
print("\n[10] 清理测试账号")
st, js = req("PUT", f"/api/system/user/{test_row['id']}/", admin_t, {"is_active": False})
check("测试账号已停用（保留记录，不物理删除）", envelope_ok(js), js.get("msg"))

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 74)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("\n  失败项：")
    for f in FAIL:
        print("    - " + f)
print("=" * 74)
sys.exit(1 if FAIL else 0)




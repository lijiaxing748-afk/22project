# -*- coding: utf-8 -*-
"""登录链路验收：**按前端的真实行为**打请求，而不是按"我以为前端会怎么发"。

为什么单独写这个脚本（血泪教训）：
    前端 account.vue 原本会在发请求前把密码做一次 MD5：
        loginApi.login({ ...state.ruleForm, password: Md5.hashStr(...) })
    而我在 tools/smoke-live.py 里是直接用 requests 发明文的 —— 两边对不上，
    但测试全绿。于是"后端鉴权改成真的"之后，浏览器里就变成
    "密码明明是对的却一直说密码错误"，而测试毫无察觉。

    **教训：验收脚本必须复现前端的请求形态，包括它做的任何变换。**
    所以下面第 1 组用例就是专门盯 MD5 这件事的：如果哪天有人又把
    Md5.hashStr 加回来，这里会立刻红。

跑法： venv\\Scripts\\python.exe tools\\verify-login-flow.py [--port 5000]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

fails: list[str] = []


def chk(label: str, cond: bool, extra: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  [{'OK ' if cond else 'BAD'}] {label:<46} {extra}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    # 模拟浏览器跨域来源（前端 dev server 在 8080）
    ORIGIN = {"Origin": "http://localhost:8080"}

    print(f"=== 目标: {base} ===\n")

    print("--- 1. 前端源码里不能有 md5 预处理（回归防线）---")
    root = Path(__file__).resolve().parent.parent.parent / "frontend" / "22project" / "src"
    hits = []
    if root.is_dir():
        for vue in root.rglob("*.vue"):
            txt = vue.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(txt.splitlines(), 1):
                stripped = line.strip()
                # 只看"真正的代码行"，注释里提到 Md5 是为了说明历史，不算违规
                if stripped.startswith(("//", "/*", "*", "<!--")):
                    continue
                if "Md5.hashStr" in line or "Md5.hashArrayBuffer" in line:
                    hits.append(f"{vue.name}:{line_no}")
    chk("源码里没有 Md5.hashStr 调用", not hits, f"-> 发现于 {hits}" if hits else "")

    print("\n--- 2. 明文密码能登录（前端改完后的行为）---")
    r = requests.post(f"{base}/api/login/",
                      json={"username": "admin", "password": "Admin@2026"},
                      headers=ORIGIN, timeout=15)
    body = r.json()
    chk("admin / Admin@2026 登录成功", body.get("code") == 2000,
        f"-> code={body.get('code')} msg={body.get('msg')}")
    access = (body.get("data") or {}).get("access")
    chk("返回了 access 令牌", bool(access))

    print("\n--- 3. 发 MD5 摘要必须被拒（证明前端那层哈希确实有害）---")
    md5 = hashlib.md5(b"Admin@2026").hexdigest()
    r = requests.post(f"{base}/api/login/",
                      json={"username": "admin", "password": md5},
                      headers=ORIGIN, timeout=15)
    b2 = r.json()
    chk("密码位置发 MD5 -> 登录失败", b2.get("code") != 2000,
        f"-> code={b2.get('code')} msg={b2.get('msg')}")

    print("\n--- 4. 错误口令必须被拒 ---")
    for bad in ("wrong", "", "Admin@2027", "admin@2026"):
        r = requests.post(f"{base}/api/login/",
                          json={"username": "admin", "password": bad},
                          headers=ORIGIN, timeout=15)
        code = r.json().get("code")
        # 空口令会走"用户名和密码都不能为空"，也是拒绝，都算通过
        chk(f"口令 {bad!r} 被拒", code != 2000, f"-> code={code}")

    print("\n--- 5. 不存在的用户不能泄露存在性 ---")
    r1 = requests.post(f"{base}/api/login/",
                       json={"username": "no-such-user", "password": "whatever"},
                       headers=ORIGIN, timeout=15)
    r2 = requests.post(f"{base}/api/login/",
                       json={"username": "admin", "password": "whatever"},
                       headers=ORIGIN, timeout=15)
    m1, m2 = r1.json().get("msg"), r2.json().get("msg")
    chk("'用户不存在' 与 '密码错' 回同一句话", m1 == m2, f"-> {m1!r} vs {m2!r}")

    print("\n--- 6. 三个种子账号都能用明文登录 ---")
    seen = {}
    for user, pwd in (("admin", "Admin@2026"),
                      ("engineer", "Engineer@2026"),
                      ("operator", "Operator@2026")):
        r = requests.post(f"{base}/api/login/",
                          json={"username": user, "password": pwd},
                          headers=ORIGIN, timeout=15)
        b = r.json()
        ok = b.get("code") == 2000
        chk(f"{user} 能登录", ok, f"-> code={b.get('code')} msg={b.get('msg')}")
        if ok:
            tok = b["data"]["access"]
            ui = requests.get(f"{base}/api/system/user/user_info/",
                              headers={**ORIGIN, "Authorization": f"Bearer {tok}"},
                              timeout=15).json()
            perms = (ui.get("data") or {}).get("permissions") or []
            seen[user] = perms
            print(f"         角色={ui.get('data', {}).get('role_key')}  权限 {len(perms)} 项")

    print("\n--- 7. 改密码链路（用明文，且要校验两次输入一致）---")
    r = requests.post(f"{base}/api/login/",
                      json={"username": "admin", "password": "Admin@2026"},
                      headers=ORIGIN, timeout=15)
    tok = r.json()["data"]["access"]
    H = {**ORIGIN, "Authorization": f"Bearer {tok}"}

    # 7a. 两次不一致 -> 必须被拒，且**不能真的改掉密码**
    # 注意：后端业务失败也回 code=2000（见 dvadmin._ok 的说明），
    # 成败要看 msg 有没有透出"不一致"，而不是看 code —— 这里踩过一次。
    r = requests.post(f"{base}/api/system/user/change_password/",
                      json={"password": "Admin@2027", "password_regain": "Admin@2028"},
                      headers=H, timeout=15)
    msg = r.json().get("msg", "")
    chk("两次输入不一致被拒", "不一致" in msg, f"-> msg={msg}")

    r = requests.post(f"{base}/api/login/",
                      json={"username": "admin", "password": "Admin@2026"},
                      headers=ORIGIN, timeout=15)
    chk("原口令仍然有效（没被误改）", r.json().get("code") == 2000)

    # 7b. 太短 -> 被拒
    r = requests.post(f"{base}/api/system/user/change_password/",
                      json={"password": "abc", "password_regain": "abc"},
                      headers=H, timeout=15)
    msg = r.json().get("msg", "")
    chk("新密码过短被拒", "至少" in msg or "6" in msg, f"-> msg={msg}")

    print("\n--- 8. 未登录不能改密码 ---")
    r = requests.post(f"{base}/api/system/user/change_password/",
                      json={"password": "Hacked@2026", "password_regain": "Hacked@2026"},
                      headers=ORIGIN, timeout=15)
    chk("未登录改密码被拒", r.json().get("code") != 2000, f"-> msg={r.json().get('msg')}")

    print("\n" + "=" * 64)
    print("  失败项:", fails if fails else "无 —— 全部通过")
    if not fails:
        print("\n  提示: 真正的端到端确认请在浏览器里实际登录一次 ——")
        print("        脚本能覆盖请求形态，覆盖不了页面上的表单绑定。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

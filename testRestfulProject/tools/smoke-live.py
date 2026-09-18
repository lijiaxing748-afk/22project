# -*- coding: utf-8 -*-
"""对**已启动的服务**做一次真实 HTTP 全站冒烟，把中文原样打出来（不走 PowerShell 管道）。

用法：
    venv\\Scripts\\python.exe tools\\smoke-live.py                    # 默认 8099
    venv\\Scripts\\python.exe tools\\smoke-live.py --port 8080        # 指定端口

⚠️ 为什么用 Python 而不是 PowerShell 发请求：
    PowerShell 5.1 的 Invoke-RestMethod 默认按系统 ANSI 代码页解码响应体，
    服务端返回的是 UTF-8，中文会变成 "ç³»ç»Ÿç®¡ç†å‘˜" 这种乱码，
    排查时很容易把"编码问题"误判成"数据错了"。
    requests 直接按 UTF-8 解，所见即所得。Windows 控制台本身还要再输出一次，
    所以开头强制把 stdout 切成 utf-8。

⚠️ 这里**不会打印任何令牌内容**，只断言"令牌非空"。
"""
from __future__ import annotations

import argparse
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

fails: list[str] = []


def chk(label: str, cond: bool, extra: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  [{'OK ' if cond else 'BAD'}] {label:<44} {extra}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    print(f"=== 目标服务: {base} ===\n")

    print("--- A. 首页与静态资源 ---")
    r = requests.get(f"{base}/", timeout=10)
    chk("/ 是 HTML（前端首页）", r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""),
        f"-> {r.status_code} {r.headers.get('Content-Type')}")
    chk("Server 头不暴露 waitress", r.headers.get("Server") == "ModelManagementPlatform",
        f"-> {r.headers.get('Server')}")
    import re
    m = re.search(r'src="(/assets/[^"]+\.js)"', r.text)
    chk("首页引用 /assets/*.js", bool(m))
    if m:
        a = requests.get(f"{base}{m.group(1)}", timeout=10)
        chk("静态资源 200", a.status_code == 200, f"-> {a.status_code}")
        chk("静态资源长缓存", "max-age=31536000" in a.headers.get("Cache-Control", ""),
            f"-> {a.headers.get('Cache-Control')}")

    print("\n--- B. SPA 兜底（按 F5 不白屏）---")
    # ⚠️ 这里只列**真实存在的前端路由**：写死的 /home /login，加后端菜单里的 /platform/*。
    #    别随手编一个 /system/user 之类 —— 它不是页面，web.py 会（正确地）按接口回 404。
    #    前端菜单路径见 model_service/dvadmin.py 的 _menu_payload()。
    for p in ("/home", "/login", "/platform/model", "/platform/publish",
              "/platform/dataset", "/platform/visual", "/platform/system"):
        x = requests.get(f"{base}{p}", timeout=10)
        chk(f"{p} -> index.html",
            x.status_code == 200 and "<div id=" in x.text and "text/html" in x.headers.get("Content-Type", ""),
            f"-> {x.status_code}")

    print("\n--- C. 接口没被 SPA 吃掉 ---")
    for p in ("/health", "/models", "/datasets", "/api"):
        x = requests.get(f"{base}{p}", timeout=10)
        chk(f"{p} -> JSON", x.status_code == 200 and "application/json" in x.headers.get("Content-Type", ""),
            f"-> {x.status_code} {x.headers.get('Content-Type')}")

    print("\n--- D. 拼错的接口必须回 JSON 404（不能悄悄变成 HTML）---")
    # ⚠️ 这条是"接口名打错"的真实场景：前端 axios 拿到的要是 HTML，
    #    报错会是 "Unexpected token <"，排查时会往语法错误上跑偏。
    #    所以只要第一段是已知接口资源（models/datasets/system/health…），
    #    即使路径本身没注册，也必须回 JSON 404。
    for p in ("/models/nope/nope", "/trainings/abc", "/datasets/xyz/abc",
              "/api/definitely-not-a-route", "/api/system/nope/"):
        x = requests.get(f"{base}{p}", timeout=10)
        chk(f"{p} -> JSON 404",
            x.status_code == 404 and "application/json" in x.headers.get("Content-Type", ""),
            f"-> {x.status_code} {x.headers.get('Content-Type', '')[:24]}")

    print("\n--- E. 三个种子账号登录 + 权限差异（演示要点）---")
    accts = (("admin", "Admin@2026"), ("engineer", "Engineer@2026"), ("operator", "Operator@2026"))
    seen = {}
    for user, pwd in accts:
        lr = requests.post(f"{base}/api/login/", json={"username": user, "password": pwd}, timeout=15)
        body = lr.json() if lr.headers.get("Content-Type", "").startswith("application/json") else {}
        ok = body.get("code") == 2000
        chk(f"{user} 能登录", ok, f"-> code={body.get('code')} msg={body.get('msg')}")
        if not ok:
            continue
        tok = body["data"]["access"]
        chk(f"{user} 拿到令牌", bool(tok))
        ui = requests.get(f"{base}/api/system/user/user_info/",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()
        chk(f"{user} 可读自身信息", ui.get("code") == 2000, f"-> {ui.get('msg')}")
        chk(f"{user} 角色正确", ui.get("data", {}).get("role_key") == user,
            f"-> {ui.get('data', {}).get('role_key')} / {ui.get('data', {}).get('role_name')}")
        seen[user] = ui.get("data", {}).get("permissions", [])
        print(f"         权限 {len(seen[user])} 项: {', '.join(seen[user][:6])}{' …' if len(seen[user]) > 6 else ''}")

    print("\n--- F. 权限边界（核心演示：角色不同、能做的事不同）---")
    if "admin" in seen and "operator" in seen:
        chk("admin 权限多于 operator", len(seen["admin"]) > len(seen["operator"]),
            f"-> admin={len(seen['admin'])} operator={len(seen['operator'])}")
        chk("operator 没有 train:run", "train:run" not in seen["operator"])
        chk("admin 有 train:run", "train:run" in seen["admin"])
    if "engineer" in seen:
        chk("engineer 有 train:run（能训练）", "train:run" in seen["engineer"])
        chk("engineer 没有 user:manage（不能管用户）", "user:manage" not in seen["engineer"])

    print("\n--- G. 鉴权拦截 ---")
    x = requests.post(f"{base}/train", json={}, timeout=10)
    chk("未登录 POST /train -> 401", x.status_code == 401, f"-> {x.status_code}")
    x = requests.get(f"{base}/models/1DCNN/exports/x.zip", timeout=10)
    chk("未登录下载发布包 -> 401", x.status_code == 401, f"-> {x.status_code}")
    bad = requests.post(f"{base}/api/login/", json={"username": "admin", "password": "definitely-wrong"}, timeout=10).json()
    chk("错误口令被拒", bad.get("code") != 2000, f"-> code={bad.get('code')} msg={bad.get('msg')}")

    print("\n--- H. 目录穿越防护 ---")
    for p in ("/../db.env", "/assets/../../db.env", "/..%2f..%2fdb.env"):
        x = requests.get(f"{base}{p}", timeout=10)
        leaked = "MODEL_DB" in x.text or "MODEL_SECRET" in x.text
        chk(f"{p} 未泄露配置", not leaked, f"-> {x.status_code}")

    print("\n" + "=" * 62)
    print("  失败项:", fails if fails else "无 —— 全部通过")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

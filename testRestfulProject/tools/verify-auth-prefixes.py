# -*- coding: utf-8 -*-
"""回归：Authorization 前缀兼容性（Bearer / JWT / 裸值 / ?token=）。

起因：前端 service.ts 原来发的是 `Authorization: JWT <token>`（从 django-vue-admin
模板抄的，那边后端是 DRF，配了 JWT_AUTH_HEADER_PREFIX='JWT'），而本项目 Flask 后端的
_auth_header_token() 只认 `Bearer ` 前缀，于是把它当成整串令牌去验签 → 必然失败，
表现为"登录成功却立刻提示登录已失效"。

修复：
    · 前端统一改成标准 `Bearer <token>`
    · 后端 _auth_header_token() 改为前缀白名单 (bearer / jwt)，并兼容裸值

本脚本覆盖**四种取值方式**，并额外验证：
    · 大小写混写（BEARER / Jwt）
    · 前缀后多个空格
    · 加了前缀反而应该失败的情形（错前缀不许当裸值放行）
    · 伪造令牌必须仍被拒（别为了兼容把校验放松了）

跑法： venv\\Scripts\\python.exe tools\\verify-auth-prefixes.py [--port 5000]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

fails: list[str] = []


def chk(label: str, cond: bool, extra: str = "") -> None:
    if not cond:
        fails.append(label)
    print(f"  [{'OK ' if cond else 'BAD'}] {label:<52} {extra}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    B = f"http://{args.host}:{args.port}"
    URL = f"{B}/api/system/user/user_info/"

    print(f"=== 目标: {B} ===\n")

    # 拿一个真实令牌
    r = requests.post(f"{B}/api/login/",
                      json={"username": "admin", "password": "Admin@2026"}, timeout=20)
    body = r.json()
    if body.get("code") != 2000:
        print(f"!! 连登录都失败，无法继续: {body}")
        return 1
    tok = body["data"]["access"]
    print(f"已取得 admin 令牌: {tok[:32]}...\n")

    def probe(headers=None, params=None):
        """返回 (是否成功, 响应体)"""
        rr = requests.get(URL, headers=headers or {}, params=params or {}, timeout=20)
        try:
            j = rr.json()
        except Exception:  # noqa: BLE001
            return False, {"raw": rr.text[:120]}
        return j.get("code") == 2000, j

    print("--- A. 四种取值方式：应全部通过 ---")
    ok, j = probe(headers={"Authorization": f"Bearer {tok}"})
    chk("① Authorization: Bearer <token>", ok, f"-> code={j.get('code')}")

    ok, j = probe(headers={"Authorization": f"JWT {tok}"})
    chk("② Authorization: JWT <token>（旧前端兼容）", ok, f"-> code={j.get('code')}")

    ok, j = probe(headers={"Authorization": tok})
    chk("③ Authorization: <token>（裸值）", ok, f"-> code={j.get('code')}")

    ok, j = probe(params={"token": tok})
    chk("④ ?token=<token>（URL 参数下载用）", ok, f"-> code={j.get('code')}")

    print("\n--- B. 自定义 token 头（dvadmin 模板写法）---")
    ok, j = probe(headers={"token": tok})
    chk("⑤ token: <token>", ok, f"-> code={j.get('code')}")

    print("\n--- C. 大小写 / 空格健壮性：应全部通过 ---")
    for label, hdr in [
        ("⑥ BEARER <token>（全大写）", f"BEARER {tok}"),
        ("⑦ Jwt <token>（混合大小写）", f"Jwt {tok}"),
        ("⑧ bearer <token>（全小写）", f"bearer {tok}"),
        ("⑨ Bearer   <token>（前缀后多空格）", f"Bearer   {tok}"),
    ]:
        ok, j = probe(headers={"Authorization": hdr})
        chk(label, ok, f"-> code={j.get('code')}")

    print("\n--- D. 非法输入：必须仍被拒（别为了兼容放松校验）---")
    forged = "Bearer eyJ1IjoiaGFja2VyIn0.forged.sig"
    tamper = tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")
    cases = [
        ("⑩ 伪造令牌", forged),
        ("⑪ 空令牌", "Bearer "),
        ("⑫ 未知前缀", f"Token {tok}"),
        ("⑬ 真令牌被篡改", f"Bearer {tamper}"),
        ("⑭ 完全不带凭证", None),
        ("⑮ 乱码", "Bearer not-a-token-at-all"),
    ]
    for label, hdr in cases:
        headers = {} if hdr is None else {"Authorization": hdr}
        ok, j = probe(headers=headers)
        chk(label, not ok, f"-> code={j.get('code')} msg={str(j.get('msg'))[:22]}")

    print("\n" + "=" * 66)
    print("  失败项:", fails if fails else "无 —— 全部通过")
    if not fails:
        print("\n  结论：Bearer / JWT / 裸值 / ?token= 四种方式均已兼容，"
              "\n        且非法令牌依然被正确拒绝。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

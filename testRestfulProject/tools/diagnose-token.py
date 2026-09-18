# -*- coding: utf-8 -*-
"""诊断：登录拿到的 token 为什么在 user_info 上被判"登录已失效"。

背景：现象是登录成功（拿到 access token），但拿这个 token 去访问任何受保护接口
都返回 `{"code":4000,"msg":"登录已失效，请重新登录"}`，curl 直连后端也能复现。

⚠️ 关键点：`authenticate()` 里对 TokenError 是 **静默吞掉** 的：

        try:
            payload = verify_token(token)
        except TokenError:
            return None          # <- 异常原因丢了！

所以从 HTTP 层永远看不到"到底是过期、签名错、还是别的"。这个脚本直接调
verify_token / authenticate，**把真实异常打出来**，定位问题在哪一环。
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

from model_service import auth
from model_service.config import config
from model_service.db import database


def hr(title: str) -> None:
    print("\n" + "=" * 66)
    print(f"  {title}")
    print("=" * 66)


def main() -> int:
    token_arg = sys.argv[1] if len(sys.argv) > 1 else None

    hr("0. 配置：签名密钥与有效期")
    print(f"  secret_key          = {config.secret_key!r}")
    print(f"  secret_key 长度      = {len(str(config.secret_key))}")
    print(f"  token_ttl_hours     = {config.token_ttl_hours}")
    print(f"  auth_disabled       = {getattr(config, 'auth_disabled', '(无此属性)')}")
    print(f"  计算得到 max_age(秒) = {config.token_ttl_hours * 3600}")

    hr("1. 数据库里的 admin 行")
    row = None
    try:
        row = database.user_by_username("admin")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    if not row:
        print("  !! 查不到 admin 用户（库没初始化？）")
        return 1
    for k in ("UserID", "Username", "RoleKey", "IsActive", "TokenVersion"):
        print(f"  {k:<14} = {row.get(k)!r}")
    print(f"  TokenVersion 类型    = {type(row.get('TokenVersion')).__name__}")
    print(f"  IsActive 类型        = {type(row.get('IsActive')).__name__}")

    hr("2. 现签一个 token，并立刻校验（进程内闭环）")
    fresh = auth.issue_token(row)
    print(f"  issue_token 结果     = {fresh[:60]}...")
    try:
        payload = auth.verify_token(fresh)
        print(f"  [OK] verify_token 通过 -> {payload}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [BAD] verify_token 抛异常: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    # 进程内闭环过了，说明同一进程内签发/校验是自洽的。
    # 那问题就八成出在"签发时的进程"和"校验时的进程"配置不一致 —— 见第 4 步。

    hr("3. 校验你手上那个 token（如果有传参）")
    if token_arg:
        print(f"  输入 token           = {token_arg[:60]}...")
        try:
            p = auth.verify_token(token_arg)
            print(f"  [OK] 该 token 校验通过 -> {p}")
        except auth.TokenError as exc:
            print(f"  [BAD] TokenError: {exc}  (expired={exc.expired})")
            # 继续往下刨，看 itsdangerous 到底报什么
            try:
                auth._serializer().loads(token_arg, max_age=config.token_ttl_hours * 3600)
            except Exception as inner:  # noqa: BLE001
                print(f"  [真实异常] {type(inner).__name__}: {inner}")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    else:
        print("  (未传 token 参数，跳过。用法: python tools\\diagnose-token.py <token>)")

    hr("4. 关键怀疑点：签发进程 vs 校验进程的 secret_key 是否一致")
    print("  itsdangerous 的签名密钥来自 config.secret_key。")
    print("  如果服务是**多进程/多 worker**启动，且 secret_key 是每次启动随机生成的，")
    print("  那么 worker A 签发的 token 拿到 worker B 校验就会 BadSignature → 被判失效。")
    print()
    print(f"  当前进程读到的 secret_key = {config.secret_key!r}")
    env_path = ROOT / "db.env"
    print(f"  db.env 是否存在      = {env_path.exists()}")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k = s.split("=", 1)[0].strip()
            if "SECRET" in k.upper() or "TTL" in k.upper() or "AUTH" in k.upper():
                print(f"    [db.env] {s}")
    print()
    print("  ⚠️ 另外要确认：启动服务的**进程环境变量**里有没有 MODEL_SECRET_KEY。")
    print("     环境变量优先级通常高于 db.env，如果设置不一致，两个进程就会用不同的密钥。")

    hr("5. 用 authenticate() 走一次和真实请求一样的路径")
    try:
        from flask import Flask
        app = Flask(__name__)
        # 模拟带 Authorization 头的请求
        with app.test_request_context("/api/system/user/user_info/",
                                      headers={"Authorization": f"Bearer {fresh}"}):
            who = auth.authenticate()
            if who:
                print(f"  [OK] authenticate() 认出用户: {who.get('Username')}")
            else:
                print("  [BAD] authenticate() 返回 None —— 说明被静默拦下了")
                # 手动逐步复现，定位是哪一步 return None
                tok = auth._extract_token()
                print(f"        _extract_token() = {str(tok)[:50]}...")
                try:
                    pl = auth.verify_token(tok)
                    print(f"        verify_token 通过 -> {pl}")
                except Exception as e:  # noqa: BLE001
                    print(f"        第 1 步被拦: verify_token 抛 {type(e).__name__}: {e}")
                    raise SystemExit(0)
                u = pl.get("u")
                r2 = database.user_by_username(u) if u else None
                print(f"        第 2 步 user_by_username -> {bool(r2)}")
                if r2:
                    print(f"        IsActive = {r2.get('IsActive')!r}")
                    a = int(pl.get("tv") or 0)
                    b = int(r2.get("TokenVersion") or 0)
                    print(f"        第 3 步 tv 比对: token.tv={a}  db.TokenVersion={b}  "
                          f"{'一致' if a == b else '<<< 不一致，就是这里！'}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    return 0


if __name__ == "__main__":
    sys.exit(main())

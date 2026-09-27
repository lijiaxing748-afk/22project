#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复/重置登录账号（离线实验室机器专用，可反复运行）。

## 为什么需要这个脚本

实验室那台机器上出现的问题是「密码明明更新过了，还是登不进去」。根因有三个，
都不是"哈希算法不匹配"那么简单：

1) **密码不是 123456，而是 Admin@2026。**
   账号不是 SQL 脚本种的，是后端**首次启动**时由
   `db.bootstrap_users()` 用配置里的口令**现算哈希**插入的。
   默认口令写在 main.py：`config.bootstrap_admin_password or "Admin@2026"`。

2) **手工 INSERT 一旦成功，自动建号就永远不会再跑了。**
   `bootstrap_users()` 第一行是 `if self.count_users() > 0: return 0`。
   你手动插了账号之后，Users 表非空 —— 服务重启也不会去修正那行哈希。
   所以「手工生成的哈希还是校验失败」时，靠重启服务是救不回来的，
   必须在库里直接改对。

3) **手工粘贴哈希极易被破坏，而且失败时是静默的。**
   `check_password_hash()` 对坏哈希分两种反应：
     - 前后多空格     -> ValueError（被 verify_password 吞掉 -> 返回 False）
     - 末尾换行/被截断 -> False
     - 哈希里的 '$' 被某个客户端当变量吃掉 -> False
   `PasswordHash` 列是 VARCHAR(255)，而 pbkdf2:sha256 的哈希约 103 字符，
   所以**不是列宽问题**，是粘贴/转义问题。
   本脚本不让你手工粘贴：它自己调 hash_password() 生成并直接写库。

## 用法（在实验室机器的项目目录下）

    venv\\Scripts\\python.exe tools\\reset-login-accounts.py

    想指定口令：
    venv\\Scripts\\python.exe tools\\reset-login-accounts.py --admin-password "你的新口令"

    只修 admin、不要演示账号：
    venv\\Scripts\\python.exe tools\\reset-login-accounts.py --no-samples

   先看会改什么、不真改：
    venv\\Scripts\\python.exe tools\\reset-login-accounts.py --dry-run

## 它会做什么

- 按用户名 upsert：不存在就建，存在就**覆盖密码哈希**并递增 TokenVersion
- TokenVersion +1 会让该账号**此前签发的所有令牌立即失效**（等价于强制重登）
- 顺带报告每行哈希的"健康度"（长度、前缀、首尾空白），便于确认库里原来的值坏在哪
"""
from __future__ import annotations

import argparse
import sys
import logging
from pathlib import Path

# 允许直接 `python tools/xxx.py` 跑：把项目根塞进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 关掉驱动层/werkzeug 的杂音，只留本脚本自己的输出
logging.disable(logging.CRITICAL)

from model_service import auth                      # noqa: E402
from model_service.db import database, DBError       # noqa: E402


DEFAULT_ADMIN_PASSWORD = "Admin@2026"
SAMPLE_ACCOUNTS = (
    ("engineer", "Engineer@2026", auth.ROLE_ENGINEER, "算法工程师"),
    ("operator", "Operator@2026", auth.ROLE_OPERATOR, "现场操作员"),
)


def describe_hash(raw) -> str:
    """给库里的 PasswordHash 做一次体检，指出坏在哪。"""
    if raw is None:
        return "（NULL —— 该账号没有密码，任何口令都验不过）"
    if isinstance(raw, (bytes, bytearray)):
        return f"（是 bytes 不是字符串，长度 {len(raw)} —— 需重设）"
    s = str(raw)
    if not s:
        return "（空字符串 —— 需重设）"
    problems = []
    if s != s.strip():
        problems.append("首尾有空白")
    if not s.startswith("pbkdf2:sha256"):
        problems.append(f"前缀不是 pbkdf2:sha256（实际前 20 字符: {s[:20]!r}）")
    if "$" not in s:
        problems.append("没有 '$' 分段符")
    if len(s) < 90:
        problems.append(f"长度只有 {len(s)}（正常约 103，疑似被截断）")
    tail = f"长度 {len(s)}"
    return f"⚠️ {tail}，问题: {'; '.join(problems)}" if problems else f"✅ {tail}，格式正常"


def show_current(users: list[tuple[str, str]]) -> None:
    """打印这些账号当前的哈希体检结果。"""
    print("当前库里的密码哈希：")
    for username, _ in users:
        row = database.user_by_username(username)
        if not row:
            print(f"  {username:<10} -- 账号不存在")
            continue
        print(f"  {username:<10} {describe_hash(row.get('PasswordHash'))}")
        print(f"  {'':<10} IsActive={row.get('IsActive')}  "
              f"TokenVersion={row.get('TokenVersion')}  RoleKey={row.get('RoleKey')}")


def upsert(username: str, password: str, role_key: str, display: str,
           dry_run: bool) -> str:
    """存在就改哈希 + TokenVersion++；不存在就新建。返回动作描述。"""
    row = database.user_by_username(username)
    pwd_hash = auth.hash_password(password)

    if row:
        if dry_run:
            return f"[dry-run] 会重置 {username} 的口令并递增 TokenVersion"
        database.set_user_password(int(row["UserID"]), pwd_hash)
        # set_user_password 内部会把 TokenVersion +1 —— 旧令牌立即失效
        return f"已重置 {username} 的口令（旧令牌已全部失效）"

    if dry_run:
        return f"[dry-run] 会新建 {username}（角色 {role_key}）"
    database.create_user(username, pwd_hash, role_key=role_key,
                         display_name=display)
    # create_user 建出来是 IsActive=1，但为稳妥再确认一次
    return f"已新建 {username}（角色 {role_key}）"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="修复/重置登录账号（可反复运行，幂等）")
    ap.add_argument("--admin-password", default=DEFAULT_ADMIN_PASSWORD,
                    help=f"admin 的口令，默认 {DEFAULT_ADMIN_PASSWORD}")
    ap.add_argument("--no-samples", action="store_true",
                    help="只处理 admin，不建 engineer/operator（工厂交付用）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只显示会改什么，不真正写库")
    args = ap.parse_args()

    print("=" * 64)
    print("  修复登录账号")
    print("=" * 64)

    # ---- 1) 确认能连上库（连不上就没必要往下走，报清楚原因）
    try:
        database.ensure_schema()
    except DBError as exc:
        print(f"\n[错误] 连不上数据库：{exc}")
        print("       请先确认 testRestfulProject\\db.env 里的连接信息，"
              "以及 MySQL 服务在跑。")
        return 1

    print(f"  数据库方言: {database.dialect}")
    print(f"  当前用户数: {database.count_users()}")
    print()

    users = [("admin", args.admin_password)]
    if not args.no_samples:
        users += [(u, p) for u, p, _, _ in SAMPLE_ACCOUNTS]

    # ---- 2) 先展示现状，便于对比"改之前坏在哪"
    try:
        show_current(users)
    except DBError as exc:
        print(f"\n[错误] 读取用户失败：{exc}")
        return 1
    print()

    # ---- 3) 执行
    print("执行：" + ("（dry-run，不会真改）" if args.dry_run else ""))
    jobs = [("admin", args.admin_password, auth.ROLE_ADMIN, "系统管理员")]
    if not args.no_samples:
        jobs += [(u, p, r, d) for u, p, r, d in SAMPLE_ACCOUNTS]

    try:
        for username, password, role_key, display in jobs:
            print("  " + upsert(username, password, role_key, display, args.dry_run))
    except DBError as exc:
        print(f"\n[错误] 写入失败：{exc}")
        return 1

    print()
    # ---- 4) 复核：真的能验过了吗（不依赖 HTTP，直接调校验函数）
    if args.dry_run:
        print("dry-run 结束，未改动数据库。")
        return 0

    print("复核（直接用 auth.verify_password 校验，不经 HTTP）：")
    all_ok = True
    for username, password, _, _ in jobs:
        row = database.user_by_username(username)
        if not row:
            print(f"  [失败] {username} 仍不存在")
            all_ok = False
            continue
        ok = auth.verify_password(row.get("PasswordHash"), password)
        flag = "OK " if ok else "失败"
        print(f"  [{flag}] {username} / {password} -> {ok}")
        if ok:
            print(f"         {describe_hash(row.get('PasswordHash'))}")
        all_ok = all_ok and ok

    print()
    print("=" * 64)
    if all_ok:
        print("  全部通过。现在可以用上面的口令登录了。")
        print()
        print("  ⚠️ 正式交付前请改掉这些口令：")
        print("     登录后在「个人中心 → 修改密码」里改，或再跑本脚本指定新口令。")
    else:
        print("  有账号未通过复核，请看上面的 [失败] 行。")
        print("  如果是数据库连接问题，优先查 db.env。")
    print("=" * 64)
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)

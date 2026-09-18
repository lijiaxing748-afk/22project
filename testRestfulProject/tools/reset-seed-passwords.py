# -*- coding: utf-8 -*-
"""把种子账号的口令对齐到文档里写的那三个（幂等，可重复跑）。

背景：开发过程中 seed 相关的代码改过几轮，本地库里 operator 的哈希
是用**旧版字符串**建的，于是文档写 Operator@2026、实际却登不进去。
交付前必须让"文档说的"和"库里存的"一致，否则现场演示第一个卡点就是这个。

用法：
    venv\\Scripts\\python.exe tools\\reset-seed-passwords.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from model_service import auth  # noqa: E402
from model_service.db import database  # noqa: E402

SEEDS = (
    ("admin", "Admin@2026"),
    ("engineer", "Engineer@2026"),
    ("operator", "Operator@2026"),
)

database.ensure_schema()
print("对齐种子账号口令：")
for name, pwd in SEEDS:
    row = database.user_by_username(name)
    if not row:
        print(f"  [跳过] {name} 不存在（本机可能是 with_samples=False 只建了 admin）")
        continue
    if auth.verify_password(row.get("PasswordHash"), pwd):
        print(f"  [无需改动] {name} 已可用文档中的口令登录")
        continue
    database.set_user_password(int(row["UserID"]), auth.hash_password(pwd))
    # 复验，避免"改了但没生效"
    ok = auth.verify_password(database.user_by_username(name).get("PasswordHash"), pwd)
    print(f"  [已重置] {name} -> 复验通过: {ok}")
print("\n完成。")

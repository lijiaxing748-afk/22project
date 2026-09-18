# -*- coding: utf-8 -*-
"""清掉鉴权验证过程中留下的一次性测试库。

背景：验证 schema 时建过 model_management_authcheck / model_management_shakedown
两个临时库。前者因为当时后端还开着、连着它，DROP 卡在元数据锁上没删成。

⚠️ 跑之前**先停掉后端服务**，否则 DROP 又会等锁。
用法： venv\\Scripts\\python.exe tools\\cleanup-test-db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql  # noqa: E402

from model_service.config import config  # noqa: E402

STALE = ("model_management_authcheck", "model_management_shakedown")

conn = pymysql.connect(host=config.db_host, port=config.db_port, user=config.db_user,
                       password=config.db_password, charset="utf8mb4", connect_timeout=8)
try:
    cur = conn.cursor()
    cur.execute("SHOW DATABASES")
    have = {r[0].lower() for r in cur.fetchall()}

    for db in STALE:
        if db.lower() not in have:
            print(f"  [跳过] {db} 不存在")
            continue
        # 给 DROP 设个超时，免得又无声地挂住
        cur.execute("SET SESSION lock_wait_timeout = 15")
        try:
            cur.execute(f"DROP DATABASE `{db}`")
            conn.commit()
            print(f"  [已删] {db}")
        except Exception as exc:
            conn.rollback()
            print(f"  [失败] {db}: {exc}")
            print("         多半是后端还开着并连着它 —— 先停掉后端再跑一次")

    cur.execute("SHOW DATABASES")
    print()
    print("剩余库:", [r[0] for r in cur.fetchall()])
finally:
    conn.close()

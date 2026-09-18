#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""后端唯一入口：把业务接口 + dvadmin 兼容层挂到一个 Flask app 上。

启动：`venv\\Scripts\\python.exe main.py`  → http://127.0.0.1:5000

两层路由：
  model_service.api     业务接口（返回**裸 JSON**）：/api /health /models /datasets /train /trainings /predict …
  model_service.dvadmin 前端 django-vue3-admin 要的兼容接口（返回 `{code,data,msg}` 信封）+ CORS

历史上这里还有一套 flask_restful 官方示例的 `/todos` 资源与 `PcaAD` 演示代码，
与本平台无关，已删除；需要看原示例请回查 git 历史或 flask_restful 文档。
"""
import sys
import traceback
from datetime import datetime
from pathlib import Path
from flask import Flask, request
from flask_restful import Api
# 让 `adtk/`、`1DCNN/` 这些原项目目录可以被 import（trainer 里按需插入，这里兜个底）
sys.path.append(str(Path(__file__).parent))
from model_service.api import register_api                    # noqa: E402
from model_service.dvadmin import register_dvadmin            # noqa: E402
from model_service.config import LOG_DIR                      # noqa: E402
from model_service.db import database                          # noqa: E402
from model_service.web import register_frontend                # noqa: E402

app = Flask(__name__)
api = Api(app)

# ---------------------------------------------------------------------------
# 全局异常兜底：把**完整 traceback**同时写到控制台和 data/logs/error-<日期>.log
#
# 为什么需要这个：业务接口在出错时会把 500 包成
#     {"error": "...", "traceback": "..."}
# 返回给前端，但前端大部分情况下只弹一句"服务器内部错误"，
# 于是日志里就只剩 `POST /predict 500` 这一行 —— 真正的报错信息全丢了。
# 排查时只能靠猜。加上这个 handler 之后，任何未捕获异常都会落盘，
# 直接去看 data/logs/error-YYYYMMDD.log 就能拿到源码行号。
# ---------------------------------------------------------------------------
ERROR_LOG = LOG_DIR / f"error-{datetime.now().strftime('%Y%m%d')}.log"


@app.errorhandler(Exception)
def _log_unhandled(exc):
    """任何未被 Resource 自己捕获的异常都会走到这里。"""
    tb = traceback.format_exc()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = (
        f"\n{'=' * 70}\n"
        f"[{stamp}] {request.method} {request.path}\n"
        f"  remote_addr: {request.remote_addr}\n"
        f"  args: {dict(request.args)}\n"
        f"  body: {_safe_body()}\n"
        f"{'-' * 70}\n{tb}"
    )
    # 控制台：训练/推理窗口里能直接看见，不用去翻文件
    print(entry, flush=True)
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as fh:
            fh.write(entry)
    except Exception:
        pass                                    # 日志写不进去也不能把响应带崩
    return {
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": tb[-1500:],
        "log_file": str(ERROR_LOG),
        "hint": "完整 traceback 已写入上面的 log_file，也打印在后端窗口里",
    }, 500


def _safe_body():
    """把请求体尽量原样记下来（不记二进制/超大内容），排查时很有用。"""
    try:
        if request.is_json:
            data = request.get_json(silent=True)
            text = repr(data)
            return text[:800] + ("..." if len(text) > 800 else "")
        raw = request.get_data(as_text=True) or ""
        return raw[:800] + ("..." if len(raw) > 800 else "")
    except Exception:
        return "<无法读取>"


register_dvadmin(app)          # 先注册兼容层（含 404 兜底与 CORS，必须在业务接口之前）
register_api(api)              # 再注册业务接口
# ⚠️ 前端托管必须放**最后**。它的兜底路由 `/<path:path>` 是无差别匹配，
#    注册早了会把 /health、/models 这些接口一起吃掉，统一返回 index.html
#    （表现为"接口全部返回一坨 HTML"，前端 axios 报 Unexpected token <）。
#    Flask 按注册顺序匹配，所以"最后注册 = 最低优先级"正是我们要的。
register_frontend(app)


def _bootstrap_auth():
    """首次启动时补建鉴权相关的东西。**任一环节失败都不阻止服务启动。**

    为什么允许失败：这个函数只在"库还没建过表 / 还没账号"时有实际动作。
    如果数据库连不上，服务本来就该带着"数据库不可用"的状态起来、
    在 /health 里如实回报，而不是直接启动不了——后者会让排查变得很难
    （连界面都打不开，看不到任何错误信息）。

    ⚠️ 建表这一步在 ensure_schema() 里已经做了（Users/Roles/OperationLogs
    随 schema_mysql.sql 一起建），这里只负责**造种子账号**：
    账号密码要用配置里的值现算哈希，不能写死在 SQL 里（那样每台机器一个密码）。
    """
    from model_service import auth
    from model_service.config import config
    try:
        n = database.bootstrap_users(
            auth.hash_password(config.bootstrap_admin_password or "Admin@2026"),
            # 没显式配 MODEL_BOOTSTRAP_ADMIN_PASSWORD 时，连带造两个演示账号，
            # 方便"发给老师前先自己试"。真要交付工厂时，env 里配上自己的口令
            # 并把 with_samples 关掉（见 README）就不会留下默认口令的账号。
            with_samples=not config.bootstrap_admin_password,
        )
        if n:
            print(f"[鉴权] 已创建 {n} 个初始账号（admin / engineer / operator）")
        if config.auth_disabled:
            print("[鉴权] ⚠️ 鉴权已被 MODEL_AUTH_DISABLED 关闭，任何人都能调用接口！")
        elif config.auth_key_is_default:
            print("[鉴权] ⚠️ 未配置 MODEL_SECRET_KEY，本次启动使用随机密钥"
                  "（重启后需要重新登录）")
    except Exception as exc:
        print(f"[鉴权] 初始化跳过（{type(exc).__name__}: {exc}）；"
              f"服务继续启动，若无法登录请检查数据库连接")


if __name__ == '__main__':
    _bootstrap_auth()
    # threaded=True：/train 是同步阻塞的，避免一条训练请求把整个服务卡住
    print(f"[启动] 未捕获异常会写入: {ERROR_LOG}")
    app.run(debug=True, threaded=True)

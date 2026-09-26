# -*- coding: utf-8 -*-
"""生产环境启动入口：用 waitress 跑 Flask，**不开调试模式**。

为什么不直接用 main.py？
    main.py 里是 `app.run(debug=True, threaded=True)` —— 那是**开发用**服务器：
      · debug=True   ：会暴露 Werkzeug 调试器，出错时页面上能执行任意代码，
                       生产环境（尤其工厂内网）绝对不能开
      · app.run()    ：Flask 自带服务器是单进程、非为生产设计的，
                       几个人同时点训练/推理就会排队卡顿，还会在日志里刷警告
    本文件换成 **waitress**：纯 Python 的 WSGI 服务器，Windows 上零依赖、
    不需要编译，天生适合"实验室那台 Windows 机器"这种部署场景。

用法：
    venv\\Scripts\\python.exe serve.py                 # 默认 0.0.0.0:8080
    venv\\Scripts\\python.exe serve.py --port 9000
    venv\\Scripts\\python.exe serve.py --threads 8

环境变量（优先级低于命令行参数）：
    MODEL_HOST      监听地址，默认 0.0.0.0（0.0.0.0 = 同一局域网都能访问）
    MODEL_PORT      监听端口，默认 8080
    MODEL_THREADS   工作线程数，默认 4

⚠️ 为什么是 0.0.0.0 而不是 127.0.0.1：
    交付后老师/工人在**别的电脑**上输这台机器的 IP 来访问。
    绑 127.0.0.1 的话只有本机能连，别人全是"无法访问此网站"。
    ⚠️ 代价是同一局域网内谁都能访问 —— 所以这套系统必须有登录鉴权
    （已完成），且**首次部署务必改掉默认口令**。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ⚠️ 必须在 import app 之前把项目根塞进 sys.path：
#    main.py 里有 `sys.path.append(...)` 兜底，但那是它自己模块级执行的；
#    这里直接 import main 时 cwd 未必是项目根（nssm 启动时 cwd 是 system32），
#    不先加路径会 ImportError: No module named 'model_service'。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import app, _bootstrap_auth  # noqa: E402  （app 已注册完所有路由）


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description="模型管理平台 · 生产启动器（waitress）")
    parser.add_argument("--host", default=os.environ.get("MODEL_HOST", "0.0.0.0"),
                        help="监听地址，默认 0.0.0.0（局域网可访问）")
    parser.add_argument("--port", type=int, default=_env_int("MODEL_PORT", 8080),
                        help="监听端口，默认 8080")
    parser.add_argument("--threads", type=int, default=_env_int("MODEL_THREADS", 4),
                        help="工作线程数，默认 4")
    args = parser.parse_args()

    # ⚠️ 生产启动**必须**补跑一次 bootstrap：
    #    main.py 只在 `if __name__ == '__main__'` 里调用它，而这里 import 的是模块本体，
    #    那段代码不会执行。少了这一步，新机器上 Users 表永远是空的 → 谁也登不进去。
    _bootstrap_auth()

    try:
        from waitress import serve
    except ImportError:
        print("[错误] 没装 waitress。请先执行：")
        # ⚠️ 路径按平台给：Windows 是 venv\Scripts\，Linux/macOS 是 venv/bin/
        if os.name == "nt":
            print(r"       venv\Scripts\pip.exe install waitress")
        else:
            print("       ./venv/bin/pip install waitress")
        print("       （离线机器上用离线包里的 wheels 装，见离线部署手册）")
        return 2

    from model_service.config import config
    from model_service.web import _dist_dir

    dist = _dist_dir()

    print("=" * 64)
    print("  模型管理平台 · 生产模式（waitress）")
    print("=" * 64)
    print(f"  监听地址   : http://{args.host}:{args.port}")
    if args.host == "0.0.0.0":
        print("               （本机可用 http://127.0.0.1:%d 访问；"
              "局域网用 http://<本机IP>:%d）" % (args.port, args.port))
    print(f"  工作线程   : {args.threads}")
    print(f"  调试模式   : 关闭（生产环境不开 Werkzeug 调试器）")
    print(f"  前端托管   : {'是 —— ' + str(dist) if dist else '否（只有后端接口）'}")
    print(f"  鉴权       : {'已关闭（MODEL_AUTH_DISABLED）' if config.auth_disabled else '开启'}")
    print(f"  令牌密钥   : {'已固定' if not config.auth_key_is_default else '⚠️ 未配置，重启会掉线'}")
    print("=" * 64)
    # ⚠️ 这行按平台给不同提示：Windows 用 nssm 装服务，Linux 用 systemd。
    #    以前写死"作为 Windows 服务"，在 Linux 上跑会给出错误的运维指引。
    if os.name == "nt":
        print("  按 Ctrl+C 停止。作为 Windows 服务运行时无需手动启动（见 安装服务脚本）。")
    else:
        print("  按 Ctrl+C 停止。作为 systemd 服务运行时无需手动启动"
              "（systemctl start model-platform）。")
    print()

    # ⚠️ channel_timeout 调大：/train 是**同步阻塞**的（可能要几分钟），
    #    默认 120 秒会在训练还没结束时就掐断连接，前端表现为"训练莫名其妙失败"。
    #    600 秒对应"单次训练不超过 10 分钟"的预期。
    serve(
        app,
        host=args.host,
        port=args.port,
        threads=args.threads,
        channel_timeout=600,
        # ident 会出现在响应头 Server: 里；用默认值会暴露 "waitress" 与版本号
        ident="ModelManagementPlatform",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

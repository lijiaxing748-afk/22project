#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 main.py 的全局异常兜底是否真的把 traceback 写进日志。

做法：起一个后台线程跑 Flask，打一个必定 500 的请求，
      然后检查 data/logs/error-*.log 里有没有出现预期的异常类型。

这是"日志能力"的回归测试 —— 以前这个能力是缺的，导致线上只能看到
`POST /predict 500` 这一行、看不到真正原因。
"""
import io
import sys
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import main                                              # noqa: E402
from flask import Flask                                  # noqa: E402

# 故意挂一个必定抛异常的路由，模拟"业务代码崩了"
@main.app.route("/__boom__")
def _boom():
    raise RuntimeError("这是回归测试故意抛的异常 __BOOM_MARKER__")


def main_test() -> int:
    log_dir = PROJECT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    before = sorted(log_dir.glob("error-*.log"))
    before_size = {p: p.stat().st_size for p in before}

    # 在后台线程里起服务（测试环境用 127.0.0.1 的一个冷门端口）
    server = threading.Thread(
        target=lambda: main.app.run(host="127.0.0.1", port=5099, debug=False,
                                    threaded=True, use_reloader=False),
        daemon=True,
    )
    server.start()
    time.sleep(4)                                        # 等 Flask 起来

    import urllib.request
    status, body = None, ""
    try:
        urllib.request.urlopen("http://127.0.0.1:5099/__boom__", timeout=10)
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", "replace")
    except Exception as exc:
        print(f"[错误] 请求都发不出去: {type(exc).__name__}: {exc}")
        return 1

    print(f"HTTP 状态: {status}")
    print(f"响应体是否含 traceback 字段: {'traceback' in body}")
    print(f"响应体是否含 log_file 字段:  {'log_file' in body}")
    if "RuntimeError" not in body:
        print("[错误] 响应体里没有 RuntimeError，兜底 handler 可能没生效")
        print("响应体前 400 字:", body[:400])
        return 1

    # 找最新写的日志
    after = sorted(log_dir.glob("error-*.log"))
    target = None
    for p in after:
        old = before_size.get(p, 0)
        if p.stat().st_size > old:
            target = p
            break

    if target is None:
        print(f"[错误] 没有发现新写入的 error-*.log（目录: {log_dir}）")
        print(f"       目录内容: {[p.name for p in after]}")
        return 1

    content = target.read_text(encoding="utf-8", errors="replace")
    print(f"日志文件: {target.name}")
    print(f"日志里含 __BOOM_MARKER__: {'__BOOM_MARKER__' in content}")
    print(f"日志里含 Traceback:      {'Traceback' in content}")
    print(f"日志里含源码行号:        {'_boom' in content}")

    ok = ("__BOOM_MARKER__" in content and "Traceback" in content and "RuntimeError" in body)
    print()
    print("结论:", "通过 —— 异常已完整落盘" if ok else "未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    buf = io.StringIO()
    with redirect_stdout(buf):                           # 屏蔽 Flask 自己的启动日志
        code = main_test()
    print(buf.getvalue())
    sys.exit(code)

# -*- coding: utf-8 -*-
"""验证 _dist_dir() 能识别三种前端产物布局。

不启服务、不连库：只构造临时目录树，直接调 _dist_dir()。
"""
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

FAIL = 0


def check(name, got, want):
    global FAIL
    ok = (got == want)
    if not ok:
        FAIL += 1
    print(f"  [{'OK' if ok else '失败'}] {name}")
    if not ok:
        print(f"       期望: {want}")
        print(f"       实际: {got}")


def build_tree(root: Path, layout: str) -> Path:
    """按布局造出 index.html，返回 workspace 根。"""
    ws = root / "22project"
    backend = ws / "testRestfulProject"
    (backend / "model_service").mkdir(parents=True)
    (backend / "data").mkdir(parents=True)

    if layout == "repo":
        d = ws / "frontend" / "22project" / "dist"
    elif layout == "packed":
        d = ws / "frontend" / "dist"
    elif layout == "dataweb":
        d = backend / "data" / "web"
    elif layout == "none":
        d = None
    else:
        raise ValueError(layout)
    if d is not None:
        d.mkdir(parents=True)
        (d / "index.html").write_text("<html>x</html>", encoding="utf-8")
    return ws


def reload_with(ws: Path):
    """让 config 认为 WORKSPACE_DIR 就是 ws，然后返回 _dist_dir() 的结果。

    做法：直接放一个假的 model_service 包结构太啰嗦，
    改为 monkeypatch config 的路径常量。
    """
    for m in list(sys.modules):
        if m.startswith("model_service"):
            del sys.modules[m]
    import importlib
    cfg = importlib.import_module("model_service.config")
    # ⚠️ DATA_DIR 也依赖 PROJECT_DIR，必须一起改，否则 data/web 那条候选
    #    会指向真实项目目录，测试就测了个寂寞。
    backend = ws / "testRestfulProject"
    cfg.WORKSPACE_DIR = ws
    cfg.PROJECT_DIR = backend
    cfg.SERVICE_DIR = backend / "model_service"
    cfg.DATA_DIR = backend / "data"
    # 候选列表在 Config 类里（self.dist_candidates），所以构造一个只含必要字段的替身。
    # 用 SimpleNamespace 而不是 Config()：后者会读环境变量、校验方言，测试没必要连库。
    from types import SimpleNamespace
    fake = SimpleNamespace(dist_candidates=(
        ws / "frontend" / "22project" / "dist",
        ws / "frontend" / "dist",
        cfg.DATA_DIR / "web",
    ))
    web = importlib.import_module("model_service.web")
    web.config = fake
    return web._dist_dir()


def main():
    print("=" * 60)
    print("  _dist_dir() 布局探测验证")
    print("=" * 60)

    for layout, label in [
        ("repo", "源码仓库布局 frontend/22project/dist"),
        ("packed", "打包分发布局 frontend/dist"),
        ("dataweb", "部署布局 data/web"),
    ]:
        tmp = Path(tempfile.mkdtemp(prefix="distprobe-"))
        try:
            ws = build_tree(tmp, layout)
            got = reload_with(ws)
            expect_suffix = {
                "repo": "frontend/22project/dist",
                "packed": "frontend/dist",
                "dataweb": "testRestfulProject/data/web",
            }[layout]
            ok = got is not None and str(got).replace("\\", "/").endswith(expect_suffix)
            check(label, ok, True)
            if got:
                print(f"       命中: {got}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # 反例：什么产物都没有 -> 应返回 None（服务照常跑）
    tmp = Path(tempfile.mkdtemp(prefix="distprobe-"))
    try:
        ws = build_tree(tmp, "none")
        got = reload_with(ws)
        check("无任何产物时返回 None（只跑后端也是合法状态）", got, None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(f"失败 {FAIL} 项")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

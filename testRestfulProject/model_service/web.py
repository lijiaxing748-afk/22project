# -*- coding: utf-8 -*-
"""前端静态托管：让「一个端口跑完整站」。

**解决什么问题**
    改造前跑起来要开两个黑窗口：后端 Flask 在 5000，前端 Vite 在 8080。
    给别人演示/交付时得解释"先开这个再开那个，浏览器别输错端口"，
    而且 Vite 是**开发服务器**，不该出现在生产环境。
    改完之后前端 `npm run build` 的产物由 Flask 直接托管，
    浏览器只输一个地址就能用。

**路由怎么排**
    /api/**     dvadmin 兼容层（登录、用户信息、动态菜单）
    /health 等  model_service 业务接口（裸 JSON）
    /assets/**  打包出来的 JS/CSS（带 hash，可长缓存）
    /**         其余一律回 index.html，交给 Vue Router

⚠️ 最后那条"其余一律回 index.html"是本模块存在的核心原因，也是一般人最容易漏的：
    Vue Router 默认是 **history 模式**，URL 长这样 `/platform/model`。
    它**不是真实文件** —— 服务器上没有 platform/model 这个路径。
    用户直接访问（或者按 F5 刷新）时，请求会打到 Flask，
    如果没有兜底路由，就是一个 404 白页。
    用户在「模型管理」页按一下 F5 就白屏，会以为系统坏了。

⚠️ 兜底**绝不能**吞掉 API 的 404。
    如果无脑把所有未匹配请求都回 index.html，那么前端请求一个拼错的接口
    （比如 /models/xxx 打成了 /model/xxx）会拿到一坨 HTML，
    axios 解析 JSON 失败后报出的是"Unexpected token <"这种莫名其妙的错，
    排查时会往语法错误上跑偏。所以下面显式排除了 API 前缀。
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, send_from_directory

from . import config

# ⚠️ 这些前缀下的 404 必须**如实回 404**，不能被 SPA 兜底吃掉。见模块顶部说明。
#
# ⚠️⚠️ 这个列表**只放"绝不会与前端路由撞名"的接口**，多写一个是会出事的：
#    一开始我按"业务接口有哪些"把 `system` 也列了进来，结果前端「系统管理→用户管理」
#    的路径正是 `/system/user` —— 它不在 `_ROUTES` 里（那是留给 dvadmin 兼容层的
#    `/api/system/...`），于是被这里判成"接口不存在"直接 404。
#    用户在「用户管理」页按 F5 就白屏，而且返回的是 JSON，看着像接口坏了。
#    实测就是靠 tools/smoke-live.py 里那条 `/system/user -> index.html` 抓出来的。
#    结论：**前缀宁可少列**。漏列一个，最坏情况是某个 API 404 返回了 HTML
#    （前端报错难看但一眼能看出是打错接口）；多列一个，前端整页打不开。
#    真正必须挡住的是 `/api/...`：前端绝不会用这个前缀做页面路由
#    （前端自己的请求都走它），而且它是 dvadmin 兼容层的命名空间。
_API_PREFIXES = ("api/", "assets/")


def _api_segments() -> frozenset[str]:
    """业务接口的第一段集合，例如 {"models", "datasets", "health", ...}。

    ⚠️ 延迟 import：web.py 是在 main.py 里、register_api() **之后**被调用的，
    而 api.py 顶层 import 了 flask_restful 等一堆东西；放在模块顶层会形成
    `web -> api -> ...` 的导入链，让 register_frontend 的调用时机变得依赖导入顺序。
    这里按需取，既避免循环导入，也保证拿到的是**最终**的 _ROUTES。
    """
    try:
        from .api import api_root_segments
        return api_root_segments()
    except Exception:  # noqa: BLE001
        # 理论上不会失败；真失败了就退回只用前缀判断（宁可少拦，不可误拦）
        return frozenset()

# 静态资源长缓存的扩展名。带 hash 的 js/css 改名后 URL 就变了，可以放心缓存一年；
# 但 index.html **绝对不能**缓存 —— 它引用着带新 hash 的 js 文件名，
# 缓存住了用户会一直加载到旧版本的资源（"改了代码没生效"的经典原因）。
_LONG_CACHE = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
               ".woff", ".woff2", ".ttf", ".eot", ".map")


def _dist_dir() -> Path | None:
    """找到可用的前端产物目录；没有就返回 None（服务照常跑，只是不托管前端）。

    候选位置定义在 config.dist_candidates（**不要在这里另写一份**），依次是：
      1. frontend/22project/dist  —— 源码仓库里 `npm run build` 的默认产物
      2. frontend/dist            —— 打包分发时的布局（目录被压平）
      3. data/web                 —— 部署时把产物拷到这里，与代码分离

    两个都没有时**不报错**：后端本来就是独立可用的（/health、/api 都在），
    只是访问 / 会看到一个说明页。这样"只部署后端"也是合法状态。
    """
    for d in config.dist_candidates:
        if d and Path(d).is_dir() and (Path(d) / "index.html").is_file():
            return Path(d)
    return None


def _describe_dist_probe() -> str:
    """把"找过哪些位置"列出来，用于没找到前端时的提示。

    ⚠️ 只在找不到时才调用。以前这里只写死一句"未找到 frontend/22project/dist 或
    data/web"，候选位置一变就和实际不符，照着提示去查会白费功夫 —— 现在直接从
    config.dist_candidates 生成，提示和代码天然同步。
    """
    return "；".join(f"{d}（{'有' if Path(d).is_dir() else '无'}此目录）"
                     for d in config.dist_candidates)


def _make_not_found_page() -> str:
    """没有前端产物时，给一个**能自己解释情况**的页面。

    比一个光秃秃的 404 强得多：能看到"后端是活的、只是没放前端"，
    以及接下来该敲哪条命令。线上排查最怕的就是"什么都没有"。
    """
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>模型管理平台 · 后端已启动</title>
<style>body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;
max-width:640px;margin:80px auto;padding:0 24px;color:#303133;line-height:1.7}
code{background:#f5f7fa;padding:2px 6px;border-radius:4px;font-size:13px}
.box{border:1px solid #e4e7ed;border-radius:8px;padding:20px 24px;margin-top:20px}
.ok{color:#67c23a;font-weight:600}</style></head><body>
<h2>后端已启动，但还没有前端页面</h2>
<p class="ok">✓ Flask 服务本身工作正常</p>
<div class="box">
<p><b>为什么会看到这个页面？</b></p>
<p>后端没找到打包好的前端产物（<code>index.html</code>）。
这通常意味着前端还没构建，或者构建产物没放到指定位置。</p>
<p><b>怎么解决：</b></p>
<p>在 <code>frontend/22project</code> 目录下执行 <code>npm run build</code>，
或把已构建好的 <code>dist</code> 整个拷到 <code>&lt;后端目录&gt;/data/web</code>。
构建完成后重启后端即可。</p>
<p>也可以直接访问下面的接口确认后端状态：</p>
<p><a href="/health">/health</a> · <a href="/api">/api</a> · <a href="/models">/models</a></p>
</div>
</body></html>"""


def register_frontend(app, dist: Path | None = None) -> None:
    """把前端产物挂到 app 上。dist 传 None 时自动探测。

    ⚠️ 必须在**所有 API 路由注册完之后**调用。Flask 按注册顺序匹配，
    兜底路由要是抢在前面，/models 这类接口会被它当成前端路由吃掉、
    统一返回 index.html，表现为"接口全挂了"。
    （实测过：注册顺序反了会让 /health 也返回 HTML。）

    ⚠️⚠️ 关于根路径 `/` 的归属（这决定改动能不能真的"只输一个地址就能用"）：
    业务层把 ApiIndex 同时注册在 `/` 和 `/api` 上（接口自描述清单）。
    前端产物**存在**时，`/` 必须让给前端首页 —— 这是本模块的目的，
    否则用户输 http://ip:8080/ 看到的是一坨 JSON 接口清单，根本进不了系统。
    接口清单不会丢：**`/api` 是同一个东西**，两边内容一致。

    产物**不存在**时（只部署后端）保持原样，`/` 继续是接口清单 ——
    这对"只想调接口"的场景更友好，也保住了老行为。
    实现方式是"先注册先匹配"：本函数在最后调用，所以下面这条 `/` 规则
    排在最末；要抢过业务层那条，必须**显式在路由表里把它提到前面**（见下）。
    """
    dist = dist or _dist_dir()

    if dist is None:
        @app.get("/")
        def _no_frontend():
            return _make_not_found_page(), 200
        print(f"[前端] 未找到打包产物，只提供后端接口；浏览器访问 / 会看到提示页")
        print(f"[前端] 已查找：{_describe_dist_probe()}")
        return

    # ⚠️⚠️ 下面这段是"把 / 从业务层手里拿回来"，踩了三个坑才写对，别再简化它：
    #
    #   1. `app.url_map._rules.remove(rule)` —— 删不掉。Rule 的 __eq__ 不是按身份比，
    #      remove() 会静默找不到目标（改了也没报错，但路由纹丝不动）。
    #   2. 只改 `_rules[:]` 列表 —— 也没用。Map 内部持有**记忆化的 matcher**，
    #      改了 _rules 不会触发它重建。实测：打印 _rules 里 '/' 确实只剩一条，
    #      但 adapter.match('/') 依然命中 apiindex —— 查的列表和匹配用的不是一套数据。
    #   3. 手动把 `_matcher` 置 None —— 更糟。Flask 后续 add_url_rule 会立刻去读
    #      matcher.merge_slashes，直接 AttributeError，服务起不来。
    #
    #   正解：**换个干净的 Map**。Map 是 werkzeug 的公开结构，new 一个空 Map、
    #   把该保留的规则重放进去，再整体赋给 app.url_map —— 这样 matcher 自然从零构建，
    #   不依赖任何私有缓存字段。代价是 O(规则数) 一次，只在启动时做，可以忽略。
    #
    #   ⚠️ 为什么要动它而不是"直接再注册一条 /"：Flask 同路径按**规则顺序**取第一条，
    #      ApiIndex 注册在前，再注册一条只会排在后面，永远匹配不到。
    #   ⚠️ 为什么不干脆 pop 掉 "apiindex" 这个 endpoint：`/` 与 `/api` 是
    #      "一次 add_resource 挂两个 URL"共用**同一个 endpoint**（flask_restful 用
    #      类名小写当 endpoint，拆成两次注册会 AssertionError）。pop 掉会让 `/api`
    #      也一起失效（实测 500）。所以这里**只摘掉 '/' 这一条规则**，保留 endpoint。
    from werkzeug.routing import Map as _WzMap

    old_map = app.url_map
    kept = [r for r in old_map._rules
            if not (str(r) == "/" and r.endpoint == "apiindex")]
    new_map = _WzMap(
        # 这几项必须从旧 map 抄过来，否则 URL 解析行为会漂（尾斜杠、编码、域名匹配）
        converters=old_map.converters,
        strict_slashes=old_map.strict_slashes,
        merge_slashes=old_map.merge_slashes,
        redirect_defaults=old_map.redirect_defaults,
        host_matching=old_map.host_matching,
    )
    for rule in kept:
        # ⚠️ 规则对象是绑在旧 map 上的（rule.map 指向它），必须重新 bind 到新 map，
        #    否则匹配时会去旧 map 里找 converters。
        rule.map = None
        new_map.add(rule)
    app.url_map = new_map

    assets = dist / "assets"

    @app.get("/")
    def _index():
        """前端首页。⚠️ max_age=0：index.html **绝不能**缓存。

        它引用着带 hash 的 js 文件名；一旦被浏览器缓存住，
        发新版后用户会拿着旧 index.html 去找已被删除的旧 js，
        表现为白屏或"改了代码没生效"。带 hash 的 assets 才该长缓存。
        """
        return send_from_directory(dist, "index.html", max_age=0)

    @app.get("/assets/<path:filename>")
    def _assets(filename):
        """打包出的 JS/CSS。带 hash，可以长缓存。"""
        return send_from_directory(assets, filename, max_age=31536000)

    @app.get("/favicon.ico")
    def _favicon():
        # 没有这个路由时浏览器每个页面都会报一次 404，控制台看着很脏
        ico = dist / "favicon.ico"
        if ico.is_file():
            return send_from_directory(dist, "favicon.ico", max_age=86400)
        return "", 204

    @app.get("/<path:path>")
    def _spa(path):
        """静态文件优先，找不到就回 index.html（交给 Vue Router）。

        ⚠️ 三层优先级的顺序不能变：
          1. API 前缀 → **如实 404**（理由见模块顶部）
          2. 真实存在的文件（logo.png、version-build 等）→ 直接给
          3. 其余 → index.html
        如果第 2、3 步放到第 1 步前面，API 的 404 就变成 HTML 了。
        """
        target = (dist / path).resolve()
        # ⚠️ 目录穿越防护：`/../../db.env` 这种请求必须挡住。
        #    只靠 send_from_directory 的校验不够——它先做路径拼接再判断，
        #    而这里我们要在**读文件之前**就确定"这是不是一个真实文件"。
        try:
            target.relative_to(dist.resolve())
        except ValueError:
            return {"error": "非法路径"}, 403

        # ① 已知接口前缀（或第一段是已知接口资源）→ 如实 404，不交给前端路由
        first_seg = path.split("/")[0] if path else ""
        if path.startswith(_API_PREFIXES) or first_seg in _api_segments():
            return {"error": f"接口不存在：/{path}"}, 404

        # ② 真实文件
        if target.is_file():
            ext = target.suffix.lower()
            age = 31536000 if ext in _LONG_CACHE else 0
            return send_from_directory(dist, path, max_age=age)

        # ③ 其余交给前端路由
        return send_from_directory(dist, "index.html", max_age=0)

    print(f"[前端] 已托管打包产物：{dist}（访问 / 即进入系统，接口清单在 /api）")
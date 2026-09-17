# -*- coding: utf-8 -*-
"""Django-Vue3-Admin（dvadmin）兼容层 —— 让 frontend/22project 直接跑在本服务上。

⚠️ 这个模块存在的全部理由：
   frontend/22project 是 dvadmin 的前端工程，它的 axios 拦截器**强制校验 `{code, data, msg}` 信封**
   （约定 code=2000 表示成功，否则当业务失败弹错误）。而 model_service 自己的业务接口
   返回的是**裸 JSON**（没有 code 字段），两者天然不兼容。于是在同一个端口上并存两套路由：
     * 本模块：凡是被前端模板直接调用的系统接口，一律包成 `{code, data, msg}` 信封；
     * model_service.api：业务接口仍回裸 JSON —— 裸 JSON 里没有 code 字段，
       前端的拦截器认不出信封会直接放行，所以两种风格互不影响、不用改造业务接口。

frontend/22project 启动时会打一组 Django 接口；这里用 Flask 把**最小必需集合**实现出来，
数据全部来自本服务（模型产物 / 数据集 / 图 / 库表）：

    POST /api/login/                              登录   → {code:2000, data:{access, username}}
    GET  /api/system/user/user_info/               用户信息
    GET  /api/system/menu/web_router/              动态菜单（后端控制路由，五个模块在这里）
    GET  /api/init/dictionary/?dictionary_key=all  字典（data 必须是数组）
    GET  /api/system/message_center/get_newest_msg/ 站内消息（空数组即可）
    GET  /api/captcha/                             验证码（返回 captcha_state=false，登录页不显示）
    POST /api/logout/                              退出

说明：
  * 登录只做形式校验（任意非空账号口令都通过）：这是一个局域网内的演示平台，
    没有用户体系；真要接权限，把这里换成真实的鉴权即可。
  * 同时装上 CORS 头：前端 dev server 在 8080、本服务在 5000，属于跨域。
  * ⚠️ 这里的返回值字段名是**照着前端源码反推**出来的，不是照着 Django 后端文档写的；
    少一个字段前端往往会静默走错分支（页面空白/不跳转），改动前先看对应的前端文件。
"""
from __future__ import annotations
import uuid
from flask import Blueprint, jsonify, request
# 五个模块（后端控制路由：前端的 dynamicRoutes[0].children 会被这份数据替换）
def _menu_payload() -> list[dict]:
    """下发侧边栏菜单（真正的"后端控制路由"）。

    这里**不要**再放"首页"。模板里 stores/frontendMenu.ts 已经写死了一个 /home
    （已改为指向本平台的 platform/home/index），两边都下发就会出现"两个首页"。
    路由守卫登录成功后 next('/home')、dynamicRoutes[0].redirect 也是 /home，与它一致。
    """
    modules = [
        (106, "模型发布", "ele-Upload", "/platform/publish", "platformPublish", "platform/publish/index", False),
        (102, "模型管理", "ele-Cpu", "/platform/model", "platformModel", "platform/model/index", False),
        (103, "数据集管理", "ele-Coin", "/platform/dataset", "platformDataset", "platform/dataset/index", False),
        (104, "数据展示", "ele-DataLine", "/platform/visual", "platformVisual", "platform/visual/index", False),
        (105, "系统管理", "ele-Setting", "/platform/system", "platformSystem", "platform/system/index", False),
    ]
    return [{
        "id": mid, "parent": None, "title": title, "icon": icon,
        "web_path": path, "component_name": comp_name, "component": component,
        # ⚠️ cache=False → 不加入 KeepAlive：每次切回该页都重新挂载，onMounted 里的
        # 数据加载会重新执行。之前给 True，页面被缓存后切回来不重新挂载，
        # 一旦首次加载失败（或后端重启过）就会一直显示空，必须先刷新浏览器。
        "visible": True, "cache": False, "is_affix": affix, "is_iframe": False,
        "is_catalog": False, "is_link": False, "link_url": "",
    } for mid, title, icon, path, comp_name, component, affix in modules]
def _ok(data=None, msg: str = "success"):
    """dvadmin 信封：{code, data, msg}，code=2000 表示成功（前端 axios 拦截器按这个判断）。

    ⚠️ 这套前端判断成败看的是 **body 里的 code**，不是 HTTP 状态码：
    业务失败时也照样回 HTTP 200、只把 code 换成非 2000（见 `login()` 的 4000），
    否则前端的错误提示分支拿不到 msg。所以别按 REST 习惯去改这里的状态码。
    """
    return jsonify({"code": 2000, "data": data, "msg": msg})
def _user_payload() -> dict:
    """本地演示账号。字段名要跟前端 user store 的期望对齐，缺字段会导致页头/权限判断报错。"""
    return {
        "id": 1, "username": "admin", "name": "管理员", "avatar": "",
        "email": "admin@localhost", "mobile": "", "gender": "1",
        "dept_info": {"dept_id": 1, "dept_name": "模型管理平台"},
        "role_info": [{"id": 1, "name": "超级管理员", "key": "admin"}],
        "roles": ["admin"], "is_superuser": True, "pwd_change_count": 1,
        "description": "本地演示账号（由 model_service 兼容层提供）",
    }
def build_blueprint() -> Blueprint:
    """把 dvadmin 需要的最小接口集合装进一个 Blueprint。"""
    bp = Blueprint("dvadmin", __name__)
    @bp.post("/api/login/")
    def login():
        """登录：只做形式校验（任意非空账号口令都通过），返回 user + 两个 token。"""
        body = request.get_json(silent=True) or {}
        username = (body.get("username") or "").strip()
        if not username:
            return jsonify({"code": 4000, "data": None, "msg": "用户名不能为空"}), 200
        # ⚠️ 登录响应必须带上 pwd_change_count，且要比 0 大。
        # 前端的登录成功分支是：
        #   if (data.pwd_change_count == 0) return router.push('/login');   // 强制改密码
        #   ... loginSuccess() 里 if (pwd_change_count > 0) 才会 router.push('/home')
        # 少了这个字段（undefined）两边都进不去，表现就是"登录后页面不跳转"。
        data = _user_payload()
        data.update({"access": uuid.uuid4().hex, "refresh": uuid.uuid4().hex,
                     "username": username, "pwd_change_count": 1})
        return _ok(data, "登录成功")
    @bp.post("/api/logout/")
    def logout():
        """退出。没有会话要清，直接把前端领到"已退出"分支即可。"""
        return _ok(None, "已退出")
    @bp.get("/api/system/user/user_info/")
    def user_info():
        """当前登录用户信息（前端每次刷新都会拉一次）。"""
        return _ok(_user_payload())
    @bp.post("/api/system/user/update_user_info/")
    @bp.put("/api/system/user/update_user_info/")
    def update_user_info():
        """改个人资料：把请求体合并进默认账号后原样返回（本地演示不落库）。"""
        data = dict(_user_payload())
        data.update(request.get_json(silent=True) or {})
        return _ok(data, "已更新（本地演示不会真的落库）")
    @bp.post("/api/system/user/change_password/")
    @bp.put("/api/system/user/change_password/")
    @bp.post("/api/system/user/login_change_password/")
    def change_password():
        """改密码：三个路由都指向这里，统一回复成功，避免前端弹错。"""
        return _ok(None, "本地演示环境不需要改密码")
    @bp.post("/api/system/file/")
    def upload_file():
        """文件/头像上传（前端 `personal/api.ts` 的 uploadAvatar 打的就是这里）。

        dvadmin 约定的上传接口：表单字段名 **file**，落盘到 `data/uploads/`，
        返回 `{url, name}`；前端把 `data.url` 直接当头像地址用（`<img src>`），
        所以 url 必须是 `/media/uploads/<文件名>`，由下面的 `/media/<path>` 提供静态访问。

        ⚠️ 这个接口以前**根本不存在**，于是踩了一个非常难查的坑：
        浏览器对带自定义头的 POST 会先发 OPTIONS 预检 → 预检撞上 404 →
        控制台报出来的却是 "CORS policy: Response to preflight request doesn't pass
        access control check"。真正的"接口没实现"被跨域错误盖住，现象只是"头像换不上去"，
        排查时极易往 CORS 配置上跑偏（这也是后来加 `_preflight()` 兜底的原因）。
        """
        import time
        from pathlib import Path
        from .config import config
        item = request.files.get("file") or request.files.get("files")
        if item is None and request.files:
            item = next(iter(request.files.values()))
        if item is None or not item.filename:
            return _ok(None, "没有收到文件（表单字段名用 file）"), 400
        # 文件名只保留字母数字与 . _ -（避免路径穿越 / 奇怪字符）
        safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in Path(item.filename).name)
        target_dir = config.upload_dir.parent / "uploads"
        target_dir.mkdir(parents=True, exist_ok=True)
        stored = f"{int(time.time())}-{safe or 'upload'}"
        (target_dir / stored).write_bytes(item.read())
        return _ok({"url": f"/media/uploads/{stored}", "name": item.filename,
                    "file_name": stored, "size": (target_dir / stored).stat().st_size})
    @bp.get("/api/system/menu/web_router/")
    def web_router():
        """动态菜单：后端控制路由的入口。"""
        return _ok(_menu_payload())
    @bp.get("/sse/")
    def sse_stub():
        """dvadmin 的站内消息推送（前端用 EventSource 连 /sse/?token=...）。

        本地演示环境不做推送，但又不能直接回 404：EventSource 失败后会**自动无限重连**，
        控制台就会被 404 和「连接已关闭」刷屏，把真正有用的报错淹掉。
        所以返回一个**合法的空事件流**（一次就结束，不带 data 事件），并下发
        `retry: 3600000` 把重连间隔抬到 1 小时，等于"告诉前端别再来了"。
        ⚠️ Content-Type 必须是 text/event-stream，否则 EventSource 会判定连接非法并立刻重连。
        """
        return "retry: 3600000\n\n", 200, {"Content-Type": "text/event-stream",
                                           "Cache-Control": "no-cache"}
    @bp.get("/api/init/dictionary/")
    def dictionary():
        """数据字典。data 必须是**数组**（前端会 forEach/映射）。"""
        return _ok([], "本地演示环境暂无字典数据")
    @bp.get("/api/init/settings/")
    def settings():
        """系统设置。前端把这个对象直接当字典读，例如 systemConfig['base.captcha_state']。

        ⚠️ 返回的是**平铺的 key-value**，不是列表：前端拿它当 map 下标取值，
        给成数组会让 `systemConfig['base.captcha_state']` 恒为 undefined（登录页验证码又冒出来）。
        """
        return _ok({"base.captcha_state": False, "base.site_name": "模型管理平台",
                    "base.login_title": "模型管理平台",
                    # 登录页大标题/副标题：前端优先读这两个 key（见 views/system/login/index.vue），
                    # 缺省才会回落到 themeConfig.globalViceTitle。
                    "login.site_title": "模型管理平台",
                    "login.site_name": "轴承故障诊断模型管理平台"})
    @bp.get("/api/system/menu_button/menu_button_all_permission/")
    def menu_button_all_permission():
        """按钮级权限清单：本地演示不做权限，回空数组。

        ⚠️ 必须是**数组**（`data` 会被前端逐条 forEach），回成对象或 null 会在控制台抛错。
        """
        return _ok([], "本地演示环境不做按钮级权限")
    @bp.get("/api/system/message_center/get_newest_msg/")
    @bp.get("/api/system/message_center/get_self_receive/")
    def message_center():
        """站内消息：两个路由合并，固定回空数组。"""
        return _ok([], "无消息")
    @bp.get("/api/captcha/")
    def captcha():
        """验证码：captcha_state=false 时登录页不显示验证码框（本地演示不需要人机校验）。

        ⚠️ 三个字段都要给全：前端读 `data.captcha_state`，为假才隐藏输入框；
        key/image_base64 给 None 是让"显示验证码"的分支即使被走到也不会拿 undefined 去渲染 img。
        """
        return _ok({"captcha_state": False, "key": None, "image_base64": None})
    @bp.get("/api/system/system_config/get_table_data/")
    def system_config():
        """系统配置表（另一条取配置的路径，与 /api/init/settings/ 给同样的值）。"""
        return _ok({"base.captcha_state": False, "base.site_name": "模型管理平台"})
    @bp.get("/api/system/dept/all_dept/")
    @bp.get("/api/system/dept/dept_all/")
    def all_dept():
        """部门树（两个路由合并）。data 必须是数组且每项带 id/parent，前端才能建树。

        ⚠️ 前端用 `XEUtils.toArrayTree(ret.data, {parentKey:'parent'})` 建树：
        data 必须是**数组**，且每项要有 id / parent。之前返回 `{results,total}` 这种
        分页对象，报错是 "Cannot create property 'id' on number '0'" —— 报错点在建树，
        根因却在返回结构，别被带偏。
        """
        return _ok([{"id": 1, "parent": None, "name": "模型管理平台",
                     "dept_name": "模型管理平台", "key": 1, "owner": [], "status": True}])
    @bp.get("/api/dvadmin3_social_oauth2/backend/get_login_backend/")
    def login_backend():
        """第三方登录后端列表：空数组 = 登录页不显示第三方登录入口。"""
        return _ok([], "未启用第三方登录")
    @bp.get("/api/system/role/")
    @bp.get("/api/system/user/")
    @bp.get("/api/system/area/")
    def fast_crud_list():
        """fast-crud 的通用分页列表（角色/用户/地区三个列表共用）。

        ⚠️ fast-crud 的约定是 `{results, total}`（外面再包一层信封 data）：
        直接回数组前端取不到 results 会直接报错，回空也必须是这个形状。
        """
        return _ok({"results": [], "total": 0}, "本地演示环境暂无数据")
    return bp
def register_dvadmin(app) -> None:
    """注册兼容接口，并给**整个应用**装上 CORS（前端 8080 → 本服务 5000 是跨域）。

    ⚠️ main.py 里必须在注册业务接口**之前**调用本函数：404 兜底与 before_request
    是全局钩子，越早装上越能覆盖后续注册的所有路由。
    """
    app.register_blueprint(build_blueprint())
    @app.get("/media/<path:relpath>")
    def uploaded_media(relpath):
        """上传文件的静态访问入口（头像 <img src> 指向这里）。

        ⚠️ 注册在 **app** 而不是 blueprint 上：blueprint 可能带 url_prefix，
        挂上去会变成 /api/media/... ，而前端拿到的相对地址是 /media/...（拼 VITE_API_URL 后
        仍是 /media/...），对不上就是头像 404 破图。URL 是前端写死的，所以路由也得钉死。
        ⚠️ 所以本轮把 blueprint 里那份**完全相同的** `/media/<path:relpath>` 删掉了（原先同一 URL
        注册了两份）：留着它不仅冗余，一旦 build_blueprint 哪天被带上 url_prefix，就会多出一条
        /api/media/... 的幽灵规则，正是"头像破图"的成因。现在全局只此一处。
        """
        from flask import send_from_directory
        from .config import config
        # 挂 data/ 而不是 data/uploads/：上传返回的是 /media/uploads/<文件>，
        # 若把 uploads 目录本身挂在 /media 下，就会去找 uploads/uploads/<文件> → 404（头像破图）
        return send_from_directory(config.upload_dir.parent, relpath)
    @app.before_request
    def _preflight():
        """所有 OPTIONS 预检直接回 2xx（CORS 头由下面的 after_request 补）。

        ⚠️ 这是本文件里最"反直觉但必要"的一段：
        不拦 OPTIONS 的话，**未实现**的接口在预检阶段就命中 404，浏览器于是只报
        "CORS policy: preflight request ... does not have HTTP ok status" ——
        一个"接口没写"的问题被伪装成"跨域配置错"。两次排查的时间都花在了 CORS 头上，
        最后发现是路由根本不存在（"头像更新不了"就是这么被误导的）。
        让预检无条件通过后，真正的请求才会发出去，404 才能以 404 的样子出现在网络面板里。

        只拦 OPTIONS：GET/POST 等仍走正常路由，未实现的接口照旧回 JSON 404（见 `_not_found`）。
        """
        if request.method == "OPTIONS":
            return "", 200
        return None
    @app.after_request
    def _cors(response):                       # noqa: ANN001
        """给**所有**响应补 CORS 头，一个都不能漏。

        ⚠️ 为什么是"每个响应都要补"而不是只补预检：浏览器的跨域校验是**逐响应**做的，
        只要最终那个 200/404/500 响应上缺少 Allow-Origin，前端拿到的就是
        "已被 CORS 策略阻止"而不是真实的响应内容 —— 连错误信息都会被吞掉。
        （4xx/5xx 同样需要这些头，否则报错接口的表现会退化成"看不见的失败"。）

        ⚠️ Allow-Origin 必须**回显请求里的 Origin** 而不能写死 `*`：本平台的前端带 cookie，
        而规范禁止 `Allow-Credentials: true` 与 `*` 同时出现，写死会被浏览器直接拒绝。
        请求没带 Origin（同源、curl）时退回 `*`，只是为了让响应仍然可读。
        """
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        # 回显预检声明的头：前端会带 Authorization 等自定义头，缺一个预检就失败
        response.headers["Access-Control-Allow-Headers"] = request.headers.get(
            "Access-Control-Request-Headers", "Content-Type,Authorization")
        response.headers["Access-Control-Max-Age"] = "86400"   # 预检结果缓存一天，少一轮往返
        return response
    @app.errorhandler(404)
    def _not_found(err):                       # noqa: ANN001
        """**任何**未匹配的路径都回 JSON 404（不再是 Flask 默认的 HTML 页面）。

        Flask 默认的 404 是一整页 HTML：前端 axios 拿到的是一坨 `<html>`，报错信息里既看不出
        缺哪个接口、也过不了信封解析；换成 `{code:404, msg:...}` 后 msg 里带上 `request.path`，
        缺哪个接口一眼就能看到。

        原来只对 `/api/**` 这么做，其它路径 `return err` 落回 HTML —— 于是删掉 `/ui` 控制台后，
        访问 `/ui` 拿到的是 HTML 404（Content-Type 是 text/html），状态码虽然对，但看着像
        "另一个问题"。现在统一成 JSON：`/favicon.ico` 之类也一样返回 JSON，浏览器只是不显示，
        没有副作用。

        ⚠️ 这里**不能**改用 `@app.route('/api/<path:...>', methods=['OPTIONS'])` 那种兜底路由：
        它会参与 URL 匹配，把未注册的 /api/xxx 请求截成 405 METHOD NOT ALLOWED
        （请求方法对不上），反而比 404 更难懂。CORS 预检已由上面的 `_preflight`
        （before_request，只拦 OPTIONS）统一放行，这里只需专心处理"找不到"。
        """
        return jsonify({
            "code": 404,
            "data": None,
            "msg": f"未找到该路径：{request.path}",
        }), 404

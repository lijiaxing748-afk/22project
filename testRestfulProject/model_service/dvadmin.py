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
from flask import Blueprint, g, jsonify, request
from . import auth
from .db import DBError, _bit, database
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
    """**已废弃**：原先返回写死的演示账号（恒定超管）。

    ⚠️ 保留这个函数只为说明历史：鉴权改造前，登录、user_info 都返回它，
    于是"任何人输任意密码都是超级管理员"。现在所有出口都走
    `auth.login_payload(数据库里的真实用户行)`。
    如果后续有人想加个"匿名兜底用户"，别用它——那等于把刚补上的洞重新打开。
    """
    raise RuntimeError(
        "_user_payload() 是改造前的写死演示账号，已废弃；"
        "请改用 auth.login_payload(user_row)")
def build_blueprint() -> Blueprint:
    """把 dvadmin 需要的最小接口集合装进一个 Blueprint。"""
    bp = Blueprint("dvadmin", __name__)
    @bp.post("/api/login/")
    def login():
        """登录：**真正查库校验密码**，成功后签发自签令牌。

        ⚠️ 这里原先是"任意非空账号口令都通过，且恒定返回超级管理员"的演示实现。
        在"交给工厂使用"的场景下那等于没有登录——任何人随手输个密码进来就是超管。
        现在改成：查 Users 表 → 校验 pbkdf2 哈希 → 校验 IsActive → 签发令牌。

        ⚠️ 失败时**不区分"用户不存在"和"密码错误"**，统一回同一句话：
        区分开等于提供了一个用户名枚举接口（能试出哪些账号存在）。
        """
        body = request.get_json(silent=True) or {}
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not username or not password:
            return jsonify({"code": 4000, "data": None, "msg": "用户名和密码都不能为空"}), 200

        try:
            row = database.user_by_username(username)
        except DBError as exc:
            # 数据库连不上**不让登录**：这是鉴权路径，宁可登不进来也不要放行。
            # 回一句能指导排查的话，而不是笼统的"登录失败"。
            return jsonify({"code": 4000, "data": None,
                            "msg": f"无法连接用户数据库：{exc}"}), 200

        if not row or not auth.verify_password(row.get("PasswordHash"), password):
            auth.log_operation("login", target=username, result="失败",
                                message="用户名或密码错误")
            return jsonify({"code": 4000, "data": None, "msg": "用户名或密码错误"}), 200

        if not row.get("IsActive"):
            auth.log_operation("login", target=username, result="失败", message="账号已停用")
            return jsonify({"code": 4000, "data": None,
                            "msg": "该账号已被停用，请联系管理员"}), 200

        # ⚠️ 登录响应必须带上 pwd_change_count，且要比 0 大。
        # 前端的登录成功分支是：
        #   if (data.pwd_change_count == 0) return router.push('/login');   // 强制改密码
        #   ... loginSuccess() 里 if (pwd_change_count > 0) 才会 router.push('/home')
        # 少了这个字段（undefined）两边都进不去，表现就是"登录后页面不跳转"。
        data = auth.login_payload(row)
        data.update({"access": auth.issue_token(row),
                     "refresh": auth.issue_token(row),      # 无状态令牌，续期就是重签一个
                     "pwd_change_count": 1})
        database.touch_login(row["UserID"])
        # 记日志要在 g.current_user 设好之前——login 是匿名接口，
        # 直接用刚查到的 row 把身份传进去，否则日志里会是空的操作人。
        g.current_user = row
        auth.log_operation("login", target=username)
        return _ok(data, "登录成功")

    @bp.post("/api/logout/")
    def logout():
        """退出。令牌是无状态的，服务端没有会话要清，前端删掉本地令牌即可。"""
        user = auth.authenticate()
        if user:
            g.current_user = user
            auth.log_operation("logout", target=user.get("Username"))
        return _ok(None, "已退出")

    @bp.get("/api/system/user/user_info/")
    def user_info():
        """当前登录用户信息（前端每次刷新都会拉一次）。

        ⚠️ 这里必须**按令牌解析出的真实身份**返回，不能再用写死的演示账号。
        前端拿这份数据渲染页头与按钮权限，返回假身份会让权限显示与后端不一致。
        未登录时回 4000，前端拦截器会把人领回登录页。
        """
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        g.current_user = user
        return _ok(auth.login_payload(user))

    @bp.post("/api/system/user/update_user_info/")
    @bp.put("/api/system/user/update_user_info/")
    def update_user_info():
        """改个人资料（显示名/邮箱/手机）。**不改角色、不改密码**。

        ⚠️ 角色字段从请求体里被**显式丢弃**：前端表单里没有角色项，但请求体是
        客户端可控的，如果原样透传给 update_user()，任何登录用户都能把自己改成 admin。
        """
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        g.current_user = user
        body = request.get_json(silent=True) or {}
        fields = {}
        for src, dst in (("name", "DisplayName"), ("email", "Email"), ("mobile", "Mobile")):
            if src in body:
                fields[dst] = (body.get(src) or "").strip() or None
        if fields:
            try:
                database.update_user(user["UserID"], fields)
            except DBError as exc:
                return _ok(None, f"保存失败：{exc}")
        fresh = database.user_by_id(user["UserID"]) or user
        return _ok(auth.login_payload(fresh), "已更新")

    @bp.post("/api/system/user/change_password/")
    @bp.put("/api/system/user/change_password/")
    @bp.post("/api/system/user/login_change_password/")
    def change_password():
        """改密码：三个路由都指向这里。

        ⚠️ 原先这里直接回"本地演示环境不需要改密码"——等于改密码是假的。
        现在真落库，并且 set_user_password 会把 TokenVersion +1，
        **改完密码旧令牌立即失效**，需要重新登录（这是应有行为，
        否则改密码就防不住已经泄露的令牌）。
        """
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        g.current_user = user
        body = request.get_json(silent=True) or {}
        # 前端字段名不统一（不同模板版本用过 password / new_password），两个都认
        new_pwd = (body.get("password") or body.get("new_password") or "").strip()
        old_pwd = body.get("old_password") or ""
        # 前端 changePwd 表单里的"再次输入"字段。⚠️ 前端自己会比对一次，
        # 但那是**客户端**校验、可以绕过（直接构造请求就行），所以服务端也留一道。
        regain = body.get("password_regain")
        if not new_pwd:
            return _ok(None, "未提交新密码")
        if regain is not None and regain != new_pwd:
            return _ok(None, "两次输入的新密码不一致")
        full = database.user_by_id(user["UserID"]) or user
        # 带了旧密码就必须对；没带（前端表单只有新密码那一栏）则要求已登录即可 ——
        # 已登录本身已经验过令牌，这里做的是一次纵深校验，不强制前端改表单。
        if old_pwd and not auth.verify_password(full.get("PasswordHash"), old_pwd):
            return _ok(None, "原密码不正确")
        if len(new_pwd) < 6:
            return _ok(None, "新密码至少 6 位")
        database.set_user_password(user["UserID"], auth.hash_password(new_pwd))
        auth.log_operation("change_password", target=user.get("Username"))
        return _ok(None, "密码已修改，请重新登录")
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
    @bp.get("/api/system/user/")
    def user_list():
        """用户列表（fast-crud 约定的 `{results, total}` 形状）。

        ⚠️ 需要 user:manage 权限。这里**不复用下面三个路由共用的空实现**：
        用户清单是真数据（而且含账号名），让 operator 也能拉到不合适。
        没权限时回 4000 + 明确文案，前端会弹提示而不是显示空表——
        "空表"会让人以为没数据，而不是"你没权限看"。
        """
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        if "user:manage" not in auth.perms_of(user.get("RoleKey")):
            return jsonify({"code": 4000, "data": None, "msg": "没有查看用户列表的权限"}), 200
        g.current_user = user
        rows = database.list_users()
        results = [{
            "id": r["UserID"], "username": r["Username"],
            "name": r.get("DisplayName") or r["Username"],
            "dept_info": {"dept_id": 1, "dept_name": r.get("DeptName") or "模型管理平台"},
            "role_info": {"id": r.get("RoleKey"), "key": r.get("RoleKey"),
                          "name": auth.role_name_of(r.get("RoleKey"))},
            "email": r.get("Email") or "", "mobile": r.get("Mobile") or "",
            "is_active": bool(r.get("IsActive")),
            "last_login": str(r.get("LastLogin") or ""),
            "login_count": r.get("LoginCount") or 0,
            "description": auth.role_name_of(r.get("RoleKey")),
        } for r in rows]
        return _ok({"results": results, "total": len(results)})

    @bp.get("/api/system/role/")
    def role_list():
        """角色列表（用户管理页的下拉框数据源）。同样要 user:manage。"""
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        if "user:manage" not in auth.perms_of(user.get("RoleKey")):
            return jsonify({"code": 4000, "data": None, "msg": "没有查看角色列表的权限"}), 200
        g.current_user = user
        from .auth import ROLE_NAMES, perms_of
        rows = database.roles_in_db()
        # ⚠️ 以数据库为准，但**权限点取自代码**（_ROLE_PERMS）。库里只存"有哪些角色"，
        # 不存权限——权限写死在 auth.py 里，见那边的说明。这里把两边合起来给前端。
        results = [{
            "id": r["RoleKey"], "key": r["RoleKey"],
            "name": r.get("RoleName") or ROLE_NAMES.get(r["RoleKey"], r["RoleKey"]),
            "description": r.get("Description") or "",
            "permissions": perms_of(r["RoleKey"]),
            "is_active": bool(r.get("IsActive")),
        } for r in rows]
        if not results:      # 库里空表时用代码里的定义兜底，保证下拉框有东西可选
            results = [{"id": k, "key": k, "name": v, "permissions": perms_of(k),
                        "description": "", "is_active": True} for k, v in ROLE_NAMES.items()]
        return _ok({"results": results, "total": len(results)})

    @bp.get("/api/system/area/")
    def area_stub():
        """地区（部门）树：本项目不用组织架构，回一个单节点让页面正常渲染。

        ⚠️ fast-crud 的约定是 `{results, total}`（外面再包一层信封 data）：
        直接回数组前端取不到 results 会直接报错，回空也必须是这个形状。
        """
        return _ok({"results": [{"id": 1, "parent": None, "name": "模型管理平台",
                                 "dept_name": "模型管理平台", "key": 1,
                                 "owner": [], "status": True}], "total": 1})

    @bp.post("/api/system/user/create/")
    def user_create():
        """新建用户。需要 user:manage。"""
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        if "user:manage" not in auth.perms_of(user.get("RoleKey")):
            return jsonify({"code": 4000, "data": None, "msg": "没有新建用户的权限"}), 200
        g.current_user = user
        body = request.get_json(silent=True) or {}
        username = (body.get("username") or "").strip()
        password = (body.get("password") or "").strip()
        role_key = (body.get("role_key") or body.get("role") or "").strip()
        if not username or not password:
            return _ok(None, "用户名和密码都不能为空")
        if len(password) < 6:
            return _ok(None, "密码至少 6 位")
        if role_key not in auth._ROLE_PERMS:
            return _ok(None, f"角色不合法：{role_key or '（空）'}")
        try:
            uid = database.create_user(
                username, auth.hash_password(password), role_key,
                display_name=(body.get("name") or "").strip() or None,
                dept_name=(body.get("dept_name") or "").strip() or None,
                email=(body.get("email") or "").strip() or None,
                mobile=(body.get("mobile") or "").strip() or None)
        except DBError as exc:
            return _ok(None, f"新建失败：{exc}")
        auth.log_operation("create_user", target=username,
                            detail={"role": role_key})
        return _ok({"id": uid}, "已新建")

    @bp.put("/api/system/user/<int:user_id>/")
    @bp.post("/api/system/user/<int:user_id>/update/")
    def user_update(user_id: int):
        """改用户（角色/启停/显示名）。需要 user:manage。

        ⚠️ 加了两条自我防护，都是"管理员把自己锁在门外"的经典场景：
          1. 不许改自己的角色 —— 一键把自己从 admin 降成 operator 就再也改不回来了；
          2. 不许停用自己 —— 同上。
        真要转移管理员，让另一个人来操作。
        """
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        if "user:manage" not in auth.perms_of(user.get("RoleKey")):
            return jsonify({"code": 4000, "data": None, "msg": "没有修改用户的权限"}), 200
        g.current_user = user
        body = request.get_json(silent=True) or {}
        fields = {}
        if "role_key" in body or "role" in body:
            role_key = (body.get("role_key") or body.get("role") or "").strip()
            if role_key not in auth._ROLE_PERMS:
                return _ok(None, f"角色不合法：{role_key or '（空）'}")
            if user_id == user["UserID"] and role_key != user.get("RoleKey"):
                return _ok(None, "不能修改自己的角色（避免把自己降权后无法恢复）")
            fields["RoleKey"] = role_key
        if "is_active" in body:
            if user_id == user["UserID"] and not body.get("is_active"):
                return _ok(None, "不能停用自己")
            fields["IsActive"] = _bit(body.get("is_active"))
        for src, dst in (("name", "DisplayName"), ("email", "Email"), ("mobile", "Mobile")):
            if src in body:
                fields[dst] = (body.get(src) or "").strip() or None
        if not fields:
            return _ok(None, "没有要修改的内容")
        try:
            n = database.update_user(user_id, fields)
        except DBError as exc:
            return _ok(None, f"保存失败：{exc}")
        auth.log_operation("update_user", target=str(user_id), detail=fields)
        return _ok({"updated": n}, "已保存")

    @bp.post("/api/system/user/<int:user_id>/reset_password/")
    def user_reset_password(user_id: int):
        """管理员重置他人密码。需要 user:manage。

        ⚠️ 重置同样会 TokenVersion+1，被重置的人**当前登录立即失效**——
        这正是重置密码想要的效果（账号可能已泄露）。
        """
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        if "user:manage" not in auth.perms_of(user.get("RoleKey")):
            return jsonify({"code": 4000, "data": None, "msg": "没有重置密码的权限"}), 200
        g.current_user = user
        body = request.get_json(silent=True) or {}
        new_pwd = (body.get("password") or "").strip()
        if len(new_pwd) < 6:
            return _ok(None, "新密码至少 6 位")
        try:
            target = database.user_by_id(user_id)
            if not target:
                return _ok(None, "用户不存在")
            database.set_user_password(user_id, auth.hash_password(new_pwd))
        except DBError as exc:
            return _ok(None, f"重置失败：{exc}")
        auth.log_operation("reset_password", target=target.get("Username"))
        return _ok(None, "密码已重置，该用户的登录会立即失效")

    @bp.get("/api/system/operation_log/")
    def operation_log_list():
        """操作日志（供「系统管理」页展示）。需要 log:read 权限。"""
        user = auth.authenticate()
        if not user:
            return jsonify({"code": 4000, "data": None, "msg": "登录已失效，请重新登录"}), 200
        if "log:read" not in auth.perms_of(user.get("RoleKey")):
            return jsonify({"code": 4000, "data": None, "msg": "没有查看操作日志的权限"}), 200
        g.current_user = user
        limit = min(int(request.args.get("limit") or 100), 500)
        rows = database.recent_logs(limit=limit)
        return _ok({"results": rows, "total": len(rows)})

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

        ⚠️⚠️ **托管前端之后这个 handler 的作用变了**（2026-09 加静态托管时补的说明）：
        web.py 注册的 SPA 兜底路由 `@app.get('/<path:path>')` 会接住 `/platform/model`
        这类前端路由。所以这个 404 handler 现在**只在下面两种情况下触发**：
          · 非 GET 方法的未知路径（SPA 兜底只注册了 GET）→ 回 JSON 404 正确
          · 前端产物缺失、web.py 没注册任何路由 → 回 JSON 404 也正确
        也就是说它不会再"抢走"前端路由，保持原样即可，不需要额外分支。
        """
        return jsonify({
            "code": 404,
            "data": None,
            "msg": f"未找到该路径：{request.path}",
        }), 404

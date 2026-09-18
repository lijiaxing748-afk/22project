# -*- coding: utf-8 -*-
"""鉴权：密码哈希、令牌签发与校验、角色权限判定。

这个模块解决的是一个**很具体的问题**：原先 `dvadmin.login()` 只做形式校验
（任意非空账号口令都通过，且恒定返回超级管理员身份），在"交给工厂使用"的
场景下等于没有登录。本模块把这件事补上，并且刻意把**权限判定**收拢到一处。

设计取向（三条，都影响了下文写法）：

1. **权限写死在代码里，不建通用权限表。**
   本平台角色就三个（admin / engineer / operator），变动极少。做成
   "角色表 + 权限表 + 角色权限关联 + 前端按钮权限点"那套通用 RBAC，收益是
   "不用改代码就能加角色"——而这个场景根本没有这个需求；代价是
   "这个角色到底能干什么"变得只能查库才能回答。所以 `_ROLE_PERMS` 直接写在
   下面，一眼看得到全部权限。

2. **令牌是自签的，无状态，不落库。**
   工厂单机部署、单进程运行，没有多实例共享会话的需求。用 itsdangerous
   签一个带过期时间的 JSON 就够，省掉 sessions 表的读写在每个请求上的开销。
   代价是"无法主动踢下线"——所以留了 `token_version` 的口子：改密码时
   递增版本号，旧令牌立即失效（见 verify_token 的 tv 校验）。

3. **鉴权失败一律 401 + 明确原因，不静默放行。**
   宁可让前端弹一次"请重新登录"，也不能出现"看起来进去了、其实身份是空的"
   这种状态——后者会让权限判断全部退化成一个悄悄通过的默认值。
"""
from __future__ import annotations

import functools
import json
from datetime import datetime

from flask import g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .config import config

# ---------------------------------------------------------------- 角色与权限

# 三个角色。值是**稳定标识**，存在 Users.RoleKey 里，前端也按它判按钮显隐，
# 所以不能随便改字面量（改了要同时更新数据库里的存量用户）。
ROLE_ADMIN = "admin"          # 超级管理员：全部权限，含用户管理
ROLE_ENGINEER = "engineer"    # 算法工程师：训练/推理/发布/删除模型
ROLE_OPERATOR = "operator"    # 现场操作员：只能看和跑推理，不能训练、不能发布

# 权限点 → 中文名。**这是权限的唯一定义处**，加权限就在这里加一行。
PERM_LABELS = {
    "model:read": "查看模型与产物",
    "model:write": "登记/修改模型",
    "model:delete": "删除模型（含产物）",
    "train:run": "发起训练",
    "predict:run": "发起推理",
    "export:run": "发布/导出模型包",
    "export:delete": "删除发布包",
    "dataset:write": "上传/登记数据集",
    "user:manage": "管理用户与角色",
    "log:read": "查看操作日志",
}

# 角色 → 权限集合。用 frozenset 是因为它只做"在不在里面"的判断，且不可变，
# 避免有人不小心在别处 .add() 改掉全局定义。
_ROLE_PERMS: dict[str, frozenset[str]] = {
    ROLE_ADMIN: frozenset(PERM_LABELS),          # 管理员拿全部，含 user:manage
    ROLE_ENGINEER: frozenset({
        "model:read", "model:write", "model:delete",
        "train:run", "predict:run",
        "export:run", "export:delete", "dataset:write",
    }),
    ROLE_OPERATOR: frozenset({
        "model:read", "predict:run",
    }),
}

# 角色显示名（给前端展示 + 兜底）。数据库 Roles 表里也有一份，
# 以数据库为准；这里的是"库里查不到时"的兜底，保证界面不会显示空。
ROLE_NAMES = {
    ROLE_ADMIN: "超级管理员",
    ROLE_ENGINEER: "算法工程师",
    ROLE_OPERATOR: "现场操作员",
}


def perms_of(role_key: str | None) -> list[str]:
    """角色 → 权限列表（排序后，前端直接渲染）。

    未知角色返回**空集**而不是全部：这是刻意的失败方向。
    如果哪天数据库里出现一个拼错的 RoleKey，宁可让人登进去什么都干不了、
    立刻发现异常，也不要因为兜底给全权限而悄悄提权。
    """
    return sorted(_ROLE_PERMS.get((role_key or "").strip(), frozenset()))


def role_name_of(role_key: str | None) -> str:
    """角色键 → 中文名，查不到就原样返回（便于发现拼错）。"""
    key = (role_key or "").strip()
    return ROLE_NAMES.get(key, key or "未知角色")


# ---------------------------------------------------------------- 密码

def hash_password(plain: str) -> str:
    """明文 → 哈希。用 werkzeug 自带的 pbkdf2:sha256（Flask 依赖，无需新装包）。

    ⚠️ 绝不能把明文写进库，也不要"自己写个 md5 省事"——字典表几秒就能跑出来。
    """
    return generate_password_hash(plain, method="pbkdf2:sha256")


def verify_password(stored_hash: str | None, plain: str | None) -> bool:
    """校验密码。哈希或输入任一为空都返回 False（不抛异常）。

    ⚠️ 用 check_password_hash 而不是"自己再哈希一次比对字符串"：
    它内部按哈希串里记录的算法与 salt 来算，将来换算法（比如 argon2）
    存量密码照样能校验，不需要全量重置。
    """
    if not stored_hash or not plain:
        return False
    try:
        return check_password_hash(stored_hash, plain)
    except Exception:
        # 哈希串被人手工改坏时 check_password_hash 可能抛异常。
        # 这里当"校验失败"处理：一个坏掉的密码哈希不应该 500，应该只是登不进去。
        return False


# ---------------------------------------------------------------- 令牌

def _serializer() -> URLSafeTimedSerializer:
    """按当前配置造序列化器。每次现造，避免 config 在测试里被改后拿到旧实例。"""
    return URLSafeTimedSerializer(config.secret_key, salt="model-platform-auth")


def issue_token(user: dict) -> str:
    """签发令牌。user 是数据库里的一行（至少含 Username / RoleKey / TokenVersion）。

    载荷刻意做小：令牌是每个请求都带的，塞太多字段纯属浪费带宽。
    只放"我是谁、我什么角色、令牌版本号"三件事——权限由服务端按角色现算，
    **不写进令牌**：写进去的话，改了权限还得等令牌过期才生效。
    """
    payload = {
        "u": user.get("Username"),
        "r": user.get("RoleKey"),
        # 令牌版本：改密码时递增，让旧令牌立刻失效。没这个字段时按 0 处理。
        "tv": int(user.get("TokenVersion") or 0),
        "iat": int(datetime.now().timestamp()),
    }
    return _serializer().dumps(payload)


class TokenError(Exception):
    """令牌无效/过期。带上给用户看的原因，前端据此决定是否跳登录页。"""

    def __init__(self, message: str, expired: bool = False):
        super().__init__(message)
        self.expired = expired


def verify_token(token: str | None) -> dict:
    """校验令牌并返回载荷。失败抛 TokenError（带上"过期"与"签名错"的区分）。

    ⚠️ 区分过期与签名错误是有用的：签名错说明令牌被伪造或密钥换过，
    前端应该直接清掉本地令牌重新登录；而过期只是"该续期了"。
    两者对用户来说动作一样（都要重登），但对排查问题差别很大。
    """
    if not token:
        raise TokenError("未提供登录令牌")
    try:
        return _serializer().loads(token, max_age=config.token_ttl_hours * 3600)
    except SignatureExpired:
        raise TokenError("登录已过期，请重新登录", expired=True)
    except BadSignature:
        raise TokenError("登录令牌无效（可能服务端密钥已更换），请重新登录")
    except Exception as exc:
        raise TokenError(f"登录令牌无法解析：{exc}")


# ---------------------------------------------------------------- 请求上下文

def current_user() -> dict | None:
    """取当前请求的用户（由 @require_login 塞进 flask.g）。未鉴权时为 None。"""
    return getattr(g, "current_user", None)


def current_perms() -> list[str]:
    """当前请求用户的权限列表；未登录时为空。"""
    user = current_user()
    return perms_of(user.get("RoleKey")) if user else []


# Authorization 头里认哪些认证方案前缀。**改这里就是改兼容面**，别在下面写死下标。
#
# ⚠️ 为什么同时认 bearer 和 jwt：
#   · `Bearer ` 是 RFC 6750 定义的标准写法，前端 service.ts / platformRequest.ts 现在都用它。
#   · `JWT ` 是 django-vue-admin 模板的私有约定（那边后端是 DRF，配了
#     JWT_AUTH_HEADER_PREFIX='JWT'）。本项目前端最初照抄了这个前缀，而 Flask 后端
#     按标准只认 Bearer —— 前端发 `JWT xxx`、后端把整串（含 "JWT "）当令牌去验签，
#     必然失败，表现为"登录成功但立刻提示登录已失效"。
#   前端已经统一改成 Bearer，这里**继续兼容 JWT 是刻意的**：实验室机器和队友浏览器里
#   可能还缓存着旧版 bundle，只改前端会让那边突然集体登不进去。多认一个前缀是纯增量，
#   不影响任何标准请求。
#
# 比大小写：比较时统一转小写，所以 `bearer`/`BEARER`/`Jwt` 都认。
_AUTH_PREFIXES = ("bearer ", "jwt ")


def _auth_header_token() -> str | None:
    """从 Authorization 头里取令牌。认 `Bearer xxx` / `JWT xxx` / 裸 `xxx` 三种写法。

    裸写法是为了兼容前端模板——dvadmin 原本把令牌放在 header 里叫 `token`，
    不是标准的 Bearer 格式。三种都认，省得前端改来改去。

    ⚠️ 截取长度用 `len(prefix)` 算，**不要写死下标**（原来是 `raw[7:]`，只对应
    `'Bearer '` 这 7 个字符）。写死的话，以后往 _AUTH_PREFIXES 里加一个长度不同的
    前缀（比如 `Token `），就会悄悄截错位置——不报错，只是验签莫名失败。
    ⚠️ 前缀比对统一转小写，避免 `BEARER xxx` 这类大小写差异漏判。
    """
    raw = (request.headers.get("Authorization") or "").strip()
    if not raw:
        return None
    low = raw.lower()
    for prefix in _AUTH_PREFIXES:
        if low.startswith(prefix):
            return raw[len(prefix):].strip()
    return raw


def _extract_token() -> str | None:
    """按优先级取令牌：Authorization 头 → 自定义 token 头 → query 参数。

    query 参数那条是给"浏览器直接下载文件"用的：<a href> 带不了自定义头，
    模型包下载、图片查看这类链接只能靠 ?token= 传递。
    ⚠️ 令牌出现在 URL 里会被浏览器历史与服务器访问日志记下来，
    所以它排在最后，只在确实没法用头的时候才走。
    """
    return (_auth_header_token()
            or request.headers.get("token")
            or request.args.get("token"))


def authenticate() -> dict | None:
    """解析当前请求的令牌并**回库核对**，返回用户行；无有效身份返回 None。

    ⚠️ 为什么要回库：令牌里只有 Username 与 RoleKey。如果管理员把这个用户
    停用了（IsActive=0）或改了角色，光看令牌是发现不了的——令牌还没过期。
    回库核对一次才能让"停用/降权"立刻生效。
    代价是每个受保护请求多一次主键查询，本项目 QPS 极低，完全划算。

    拿不到库时**不放行**（返回 None）：这是鉴权路径，宁可让人登不进来
    （会看到明确的 401），也不能在数据库故障时敞开大门。
    """
    token = _extract_token()
    if not token:
        return None
    try:
        payload = verify_token(token)
    except TokenError as exc:
        # ⚠️ 这里原来只有一行裸 `return None`，把**失败原因整个丢掉**了。
        # 后果：登录成功拿到 token、紧接着访问 user_info 却回 4000"登录已失效"时，
        # 日志里没有任何线索——分不清是过期、签名错、密钥不一致还是载荷缺字段，
        # 只能靠猜（这次就绕了很大一圈）。鉴权失败必须留痕。
        # expired 单独标出来：排查时"过期"和"签名错"含义完全不同，
        # 前者是 TTL 配短了或用户放太久，后者才指向密钥不一致 / 令牌被伪造。
        _auth_log("令牌校验未通过", err=exc, kind="已过期" if exc.expired else "签名/格式错误")
        return None
    username = payload.get("u")
    if not username:
        _auth_log("令牌里没有用户名", payload=payload)
        return None
    try:
        from .db import DBError, database
        row = database.user_by_username(username)
    except DBError as exc:
        # 库不可用时不放行（宁可 401，也不能在数据库故障时敞开大门），
        # 但必须记下来——否则"库挂了"会表现成"令牌错了"，把人往完全错的方向引。
        _auth_log("查询用户时数据库异常", username=username, err=exc)
        return None
    if not row:
        _auth_log("令牌里的用户在库中不存在", username=username)
        return None
    if not row.get("IsActive"):
        _auth_log("用户已被停用", username=username)
        return None
    # 令牌版本核对：改过密码的旧令牌在这里被拦下
    token_tv = int(payload.get("tv") or 0)
    db_tv = int(row.get("TokenVersion") or 0)
    if token_tv != db_tv:
        # 这是最容易让人困惑的一种：改过密码后旧令牌立刻失效，而前端本地还留着旧令牌，
        # 表现成"刚登录就失效"。把两个版本号都打出来，一眼看出是"令牌比库里旧"，
        # 而不是密钥对不上——否则又要往 config / 多进程方向白查一轮。
        _auth_log("令牌版本已过期（通常是改过密码后旧令牌未清除）",
                  username=username, token_tv=token_tv, db_tv=db_tv)
        return None
    return row


def _auth_log(reason: str, **fields) -> None:
    """记一条"鉴权为什么失败"的诊断线索。**失败不抛异常**。

    为什么不用 logging 模块：本项目没有任何 logging 配置，控制台输出统一是
    `print(..., flush=True)`（见 main.py 的异常兜底、web.py 的托管提示），
    这里跟着现有约定走，免得引入两套互不相干的日志体系。

    ⚠️ 只记"为什么失败"，**绝不记令牌原文与密码**：
    日志文件会被打包进离线升级包、也可能被截图贴进文档，
    令牌一旦落盘就等于长期有效的凭证泄露（它 12 小时内都能直接用）。
    """
    try:
        bits = " ".join(f"{k}={v!r}" for k, v in fields.items())
        print(f"[鉴权] 拒绝：{reason}{('  ' + bits) if bits else ''}", flush=True)
    except Exception:
        # 记日志是旁路，编不出来就算了，不能因为日志把鉴权流程带崩
        pass


# ---------------------------------------------------------------- 装饰器

def _deny(message: str, code: int = 401, *, need: str | None = None):
    """统一的拒绝响应：`(dict, 状态码)` 二元组。

    ⚠️ **不能返回 jsonify(...) 对象**。这些装饰器包的是 flask_restful 的 Resource 方法，
    而 flask_restful 拿到 return 值后会走自己的 `make_response()` 再做一次 JSON 序列化。
    如果这里回一个已经序列化好的 Flask Response，它会尝试把 Response 对象本身
    json.dumps 一遍，报 `TypeError: Object of type Response is not JSON serializable`
    —— 现象是"本该 401，实际 500"，而且 500 把真正的原因盖住了，很难查。
    所以这里只回**纯 dict + 状态码**，让 flask_restful 自己去序列化。
    （dvadmin.py 那边是原生 Flask 视图，那边用 jsonify 是对的，两边规矩不同。）
    """
    body = {"error": message}
    if need:
        body["required_permission"] = need
        body["hint"] = f"当前账号没有「{PERM_LABELS.get(need, need)}」权限，请联系管理员"
    return body, code


def require_login(fn):
    """要求已登录。**不检查具体权限**，只确认"是个有效用户"。

    用在"看数据"这类所有角色都能用的接口上。
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = authenticate()
        if not user:
            return _deny("请先登录")
        g.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def require_perm(perm: str):
    """要求已登录**且**具备某个权限点。权限点见 PERM_LABELS。

    用法：`@require_perm("train:run")`，放在 Resource 的方法上。
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = authenticate()
            if not user:
                return _deny("请先登录")
            g.current_user = user
            if perm not in perms_of(user.get("RoleKey")):
                return _deny(f"没有权限执行该操作（需要 {PERM_LABELS.get(perm, perm)}）",
                             403, need=perm)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def login_payload(user: dict) -> dict:
    """把用户行整理成前端 user store 认识的结构。

    ⚠️ 字段名不能改：前端 `stores/userInfo.ts` 直接读 `role_info` / `is_superuser`
    / `dept_info` 这些键，少一个就会在页头或权限判断处报错。
    这里把"真实角色"映射进去，是本模块对外的**唯一出口**——
    以前那个"恒定超管"的假身份就是在这个位置，现在换成实打实查库的结果。
    """
    role_key = user.get("RoleKey") or ROLE_OPERATOR
    return {
        "id": user.get("UserID"),
        "username": user.get("Username"),
        "name": user.get("DisplayName") or user.get("Username"),
        "avatar": "",
        "email": user.get("Email") or "",
        "mobile": user.get("Mobile") or "",
        "gender": "1",
        "dept_info": {"dept_id": 1, "dept_name": user.get("DeptName") or "模型管理平台"},
        "role_info": [{"id": role_key, "name": role_name_of(role_key), "key": role_key}],
        "roles": [role_key],
        "is_superuser": role_key == ROLE_ADMIN,
        # 权限列表：前端据此决定按钮显隐。**显隐只是体验，真正的拦截在服务端**，
        # 不能只靠前端藏按钮——那样绕过前端直接调接口就失效了。
        "permissions": perms_of(role_key),
        "role_key": role_key,
        "role_name": role_name_of(role_key),
    }


def log_operation(action: str, target: str | None = None, *,
                  detail=None, result: str = "成功", message: str | None = None) -> None:
    """记一条操作日志。**失败不抛异常**（记日志不该让业务操作失败）。

    调用点见 api.py / dvadmin.py。这里只负责"拿到当前用户与 IP"，
    落库交给 db.log_operation()，两层都做了异常兜底。
    """
    try:
        from .db import DBError, database
        user = current_user()
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
            or request.remote_addr
        database.log_operation(
            username=(user or {}).get("Username"),
            role_key=(user or {}).get("RoleKey"),
            action=action, target=target,
            detail=detail, client_ip=ip,
            result=result, message=message,
        )
    except Exception:
        # 包括 DBError、json 序列化失败、request 上下文缺失……全吞。
        # 记日志是"尽力而为"的旁路，它挂掉不能影响主流程。
        pass

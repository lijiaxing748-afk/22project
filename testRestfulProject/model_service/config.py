# -*- coding: utf-8 -*-
"""运行期配置。

所有可变项都走环境变量，代码里只留「本机开发默认值」：

    MODEL_DB_DIALECT    目前**只接受 mysql**（写别的值会直接抛 RuntimeError）
    MODEL_DB_HOST       默认 127.0.0.1
    MODEL_DB_PORT       默认 3306
    MODEL_DB_USER       默认 root
    MODEL_DB_PASSWORD   默认空（本机开发用；生产请放 db.env，不要提交进仓库）
    MODEL_DB_NAME       默认 model_management

⚠️ 下面两个变量是历史遗留：早期支持过 SQL Server，现在**代码里已经没有任何地方读它们**
   （db.py 的方言分支也已收敛到 MySQL）。保留在文档里只为说明"别再用它们配库"：
    MODEL_DB_ODBC_DRIVER  SQL Server 用（已废弃）
    MODEL_DB_TRUSTED     SQL Server Windows 信任连接用（已废弃）

项目曾经"没装库也能跑"，靠 sqlite 兜底、并分叉出 sqlserver 分支；结果三套方言各自演化
（占位符 `%s`/`?`、TOP/LIMIT、建表语句），踩了不少坑，现已统一到 MySQL：
模型产物与图仍然落在文件系统上，数据库只负责索引/元数据，表结构见 sql/schema_mysql.sql。
"""
from __future__ import annotations
import os
import tempfile
from pathlib import Path


def match_dir_case_insensitive(base: Path, name: str) -> Path | None:
    """在 `base` 下找**名字大小写不敏感**相等的目录；找不到（或目录读不了）返回 None。

    为什么需要它：Windows 文件系统不区分大小写，所以"目录名 = 用户输入的名字"（`MyModel`）与
    "调用方一律用小写产物键来找"（`mymodel`）在 Windows 上能凑合跑；换到 **Linux（大小写敏感）**
    就变成"模型 / 图库 / 发布包明明在，却报找不到或看起来是空的"。
    现在**写入侧**已统一用小写键（见 `api._artifact_dir_name`），这个函数是给**历史数据**兜底：
    只在精确路径不存在时才做一次只读匹配。
    ⚠️ 只读查找、不建目录、不覆盖：找到谁就用谁。
    """
    lower = str(name).lower()
    try:
        for entry in base.iterdir():
            if entry.is_dir() and entry.name.lower() == lower:
                return entry
    except OSError:
        return None                              # 目录不存在/无权限 → 交给调用方走原来的路径
    return None


def normalize_user_path(raw: str | os.PathLike | None) -> str:
    """把"用户/前端给的路径"归一化成当前平台能解析的形式。

    ⚠️ 存在的唯一理由：**Windows 风格的 `\\` 在 Linux 上不是分隔符**。
       前端（以及 console.html、外部脚本）拼路径时普遍写成
           `${dataset_dir}\\${filename}`      →  "1DCNN\\0HP\\x.csv"
       在 Windows 上 `Path()` 认它；在 Linux 上 `\\` 只是普通字符，
       整个串会被当成"一个名字里带反斜杠的文件"，于是 is_file() 为假、
       报"文件不存在" —— 而真实的文件其实好好躺在那里。
       这个 bug 在 Windows 开发机上**永远复现不出来**，只会在 Linux 部署后炸。

    归一化规则：
        · `\\` → `/`（正斜杠在所有平台都是合法分隔符）
        · 盘符写法 `D:/x` / `D:\\x` → 去掉盘符前缀（Linux 上没有盘符概念，
          留着会变成一个叫 "D:" 的目录名，必然找不到）
        · 其余原样保留

    安全性说明：这里**不做**越界校验，调用方（_guard_path / _resolve_workspace_path）
    必须在归一化之后**照旧**做 relative_to 检查 —— 归一化只是让路径能被解析，
    不能替代安全校验。

    ⚠️ 这是**模块级函数**，同时以静态方法形式挂在 Config 上（见类内
       `normalize_user_path = staticmethod(normalize_user_path)`）。
       原因是调用方写法不统一：有的用 `config.normalize_user_path(...)`（实例），
       有的可能 import 这个函数。两种都支持，省得再踩"实例上没有这个方法"的坑。
    """
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    # 反斜杠统一成正斜杠。放在最前面：后面判断盘符、切分目录都基于正斜杠。
    text = text.replace("\\", "/")
    # Windows 盘符：`D:/...` 或裸 `D:`。只在"单字母 + 冒号"且位于开头时才处理，
    # 避免误伤 `http://` 之类的写法（那种不会被传进来，但防御性写清楚）。
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        # ⚠️⚠️ Windows 上 `D:/x` 本身就是**绝对路径**，去掉盘符会把它降级成相对路径
        #     （`22project/testRestfulProject/1DCNN/0HP`）。调用方随后按项目根再拼一次，
        #     就得到 `...\testRestfulProject\22project\testRestfulProject\1DCNN\0HP` —— 目录当然不存在。
        #     2026-09-27 的 `/train` 500 就是这么来的：实测日志里的报错路径与这个推演**逐字一致**。
        #     所以：**有盘符概念的平台上必须原样保留**；只有 Linux 这种没有盘符的地方才把盘符当噪声丢掉
        #     （那边 `D:/x` 无论如何都指不到真实文件，丢掉盘符后靠"按项目根拼"或
        #       `dataset_dir_candidates()` 的锚点回退才可能找到）。
        if os.name == "nt":
            return text
        text = text[2:]
        text = text.lstrip("/")          # `D:/x` → `/x` → `x`
        if not text:
            return ""
    return text


def dataset_dir_candidates(raw: str | os.PathLike | None) -> list[Path]:
    """把"数据集目录"的各种写法展开成**候选路径**（按最可能命中排序，已去重）。

    为什么不能只算一个：同一个字符串在不同来源下含义不同 ——
      · 前端从 `Datasets.DataPath` 读出来的是**绝对**路径：`D:\\22project\\testRestfulProject\\1DCNN\\0HP`
      · 老前端/外部脚本给的是**相对项目根**的写法：`1DCNN\\0HP`
      · 表里也可能存**相对工作区**的写法：`testRestfulProject/1DCNN/0HP`
      · 迁移到 Linux 后，老库里存的仍是上面那种 Windows 绝对路径（盘符在那边没有意义）

    解析顺序：
      ① 原样（正斜杠）—— Windows 的 `D:/x` 与 Linux 的 `/opt/x` 都能被 `Path` 认成绝对路径
      ② 去掉盘符/前导斜杠后，按**项目根**拼、再按**工作区**拼（老语义的两种口径）
      ③ 以「项目目录名 / 工作区目录名」为锚点取尾巴 —— 跨机器、跨平台最稳：
         `D:/22project/testRestfulProject/1DCNN/0HP` 与 `testRestfulProject/1DCNN/0HP`
         都会落到 `<项目根>/1DCNN/0HP`
    """
    text = str(raw or "").strip()
    if not text:
        return []
    posix = text.replace("\\", "/")
    out: list[Path] = []

    def add(candidate) -> None:
        candidate = Path(candidate)
        if candidate not in out:
            out.append(candidate)

    add(posix)                                        # ①
    stripped = normalize_user_path(text)              # ②
    if stripped:
        add(PROJECT_DIR / stripped)
        add(WORKSPACE_DIR / stripped)
    parts = [p for p in posix.split("/") if p not in ("", ".")]        # ③
    for anchor, base in ((PROJECT_DIR.name, PROJECT_DIR), (WORKSPACE_DIR.name, WORKSPACE_DIR)):
        for index in range(len(parts) - 1, -1, -1):
            if parts[index].lower() == anchor.lower() and index + 1 < len(parts):
                add(base / "/".join(parts[index + 1:]))
                break
    return out


def dataset_dir_error_message(raw: str, candidates: list[Path]) -> str:
    """数据集目录找不到时的中文说明：把"试过哪些位置"如实列出来。

    ⚠️ 原先只说 `数据集目录不存在：<拼错的绝对路径>`，用户看到的是一个自己从没输入过的路径
    （`...\\testRestfulProject\\22project\\testRestfulProject\\...`），根本没法排查。
    """
    tried = "；".join(str(c) for c in candidates[:4]) or "（无候选）"
    message = f"数据集目录不存在：{raw}\n    已尝试的位置：{tried}"
    files = [c for c in candidates if c.is_file()]
    if files:
        message += (f"\n    注意：{files[0]} 存在但**是个文件**（不是目录），"
                    f"请填它所在的目录（例如 {files[0].parent}）")
    return message


# 兼容直接 from .config import normalize_user_path 的写法
__all__ = ["normalize_user_path", "dataset_dir_candidates", "dataset_dir_error_message",
           "match_dir_case_insensitive", "config", "Config"]


SERVICE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SERVICE_DIR.parent            # testRestfulProject
WORKSPACE_DIR = PROJECT_DIR.parent          # 22project
DATA_DIR = PROJECT_DIR / "data"
MODEL_DIR = DATA_DIR / "models"             # 模型产物（对应图里的「Pxl模型」）
LOG_DIR = DATA_DIR / "logs"                 # 训练日志
UPLOAD_DIR = DATA_DIR / "datasets"          # 上传/存放的表格数据集（一个子目录 = 一个数据集）
EXPORT_DIR = DATA_DIR / "exports"           # 模型发布包（一个训练产物一个 zip，按模型分子目录）
SQL_DIR = PROJECT_DIR / "sql"
# 前端产物目录候选位置 —— **定义在 Config 类里**（见 self.dist_candidates），
# 这里不再重复一份：两份定义迟早会不一致，而 web.py 只认类里那份。
# 兼容旧引用：历史上这两个名字是模块级常量，外部若还有引用不至于直接崩。
DIST_DIR = WORKSPACE_DIR / "frontend" / "22project" / "dist"
WEB_DIR = DATA_DIR / "web"
# ⚠️ 原来的 SQLITE_PATH（sqlite 兜底库路径）已删除：它零引用，且 sqlite 兜底本身
#    也早在 __init__ 里被"只支持 MySQL"的校验挡掉了。
# 内置的 CWRU .mat 数据集：键是前端/接口里用的数据集名，值是磁盘目录
DATASET_DIRS = {
    "CWRU-0HP": PROJECT_DIR / "1DCNN" / "0HP",
    "CWRU-0HP(cwt)": PROJECT_DIR / "cwt_cnn" / "0HP",
}
# ⚠️ 原来的 ADTK_DATASET_DIR（adtk/dataset，adtk 自带样例数据的目录）已删除：全项目零读取方。
#    adtk 分支的基线文件现在完全由训练请求的 dataset_dir 决定，找不到就明确报错
#    （见 training._train_adtk）——那个"静默退回 adtk/dataset/cpu.csv"的兜底早就删掉了，
#    这个常量是它留下的最后一截尾巴。
# 这几个目录是运行期必需品，import 时就建好，免得别处还要各自判存在性
for _d in (DATA_DIR, MODEL_DIR, LOG_DIR, UPLOAD_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
def load_env_file() -> str | None:
    """可选的本地配置：testRestfulProject/db.env。

    格式为 `KEY=VALUE`（# 开头为注释），只在不与已有环境变量冲突时生效，
    这样开发时不用每次都 export 一串 MODEL_DB_*。已存在同名环境变量则以环境变量为准。

    ⚠️ 优先级刻意设计成「真实环境变量 > db.env」：db.env 只是本机开发的便捷默认值，
    部署时用环境变量覆盖它即可，不必去改文件（也避免把账号密码提交进仓库）。
    返回值是"实际加载到的文件路径"，只会用于 /health 展示 —— 文件不存在或一行都没生效时回 None。
    """
    path = PROJECT_DIR / "db.env"
    if not path.is_file():
        return None
    loaded = []
    # ⚠️ 用 utf-8-sig 读：有人（或 PowerShell 5.1 的 -Encoding UTF8）会给 db.env 加上 BOM，
    #    那样第一行会变成 "\ufeffMODEL_DB_DIALECT"，键名多一个不可见字符 → 整行配置读不到。
    #    utf-8-sig 会自动吃掉开头的 BOM；没有 BOM 时与 utf-8 完全等价，属于纯防御。
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return str(path) if loaded else None
ENV_FILE = load_env_file()
def ensure_writable_tempdir() -> str:
    """确认临时目录可写，不可写就整体退到项目内的 data/tmp。

    起因：Keras `model.save()` 会先写一个 NamedTemporaryFile 再改名，在受限环境
    （沙箱 / 严格 ACL）下这一步会抛 PermissionError，导致"训练成功但模型存不下来"。
    这里只在探测失败时才切换，正常机器上行为不变。
    """
    def _writable(path: str) -> bool:
        """在 path 里真写一个临时文件试试——mkdir 成功不等于能写（ACL 可能只给读）。"""
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, delete=True) as fh:
                fh.write(b"probe")
            return True
        except Exception:
            return False
    current = tempfile.gettempdir()
    if _writable(current):
        return current
    fallback = DATA_DIR / "tmp"
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(fallback)
    tempfile.tempdir = str(fallback)
    return str(fallback)
TEMP_DIR = ensure_writable_tempdir()
def _env(name: str, default: str | None = None) -> str | None:
    """读环境变量；空字符串按"没设"处理（否则 MODEL_DB_PASSWORD= 会被当成真的是空密码）。

    这里就是"环境变量与默认值"的唯一入口：调用处统一写成 `_env("MODEL_DB_XXX", 本机默认值)`，
    所以默认值只有一处定义，改默认值不会漏。
    """
    v = os.getenv(name)
    return v if v not in (None, "") else default
class Config:
    """一次进程生命周期内不变的服务配置。"""

    # 把模块级的路径归一化函数挂成静态方法，让 `config.normalize_user_path(...)`
    # （config 是**实例**，不是模块）也能用 —— 调用方两种写法都有，统一支持。
    # ⚠️ 新增路径相关的模块级函数时**必须**在这里也挂一份：只加模块级函数的话，
    #    `config.xxx(...)` 会 AttributeError（本轮就踩了一次，测试直接红了）。
    normalize_user_path = staticmethod(normalize_user_path)
    dataset_dir_candidates = staticmethod(dataset_dir_candidates)
    dataset_dir_error_message = staticmethod(dataset_dir_error_message)
    match_dir_case_insensitive = staticmethod(match_dir_case_insensitive)

    def __init__(self) -> None:
        """把模块级的路径常量与环境变量快照成一份不可变配置。"""
        # ⚠️ 这里原来的 self.service_dir 与文件末尾的 self.adtk_dataset_dir 已删除：
        #    两个属性全项目都没有任何读取方（只有赋值行本身），属于纯占位的配置面。
        #    模块级常量 SERVICE_DIR **保留**——上面的 PROJECT_DIR = SERVICE_DIR.parent 依赖它。
        self.project_dir = PROJECT_DIR
        self.workspace_dir = WORKSPACE_DIR
        self.data_dir = DATA_DIR
        self.model_dir = MODEL_DIR
        self.log_dir = LOG_DIR
        self.upload_dir = UPLOAD_DIR
        self.export_dir = EXPORT_DIR
        self.sql_dir = SQL_DIR
        # 前端产物候选位置（web.py 的 _dist_dir() 按顺序探测，先命中哪个用哪个）。
        # ⚠️ **集中定义在这里**，不要在 web.py 里另列一份 —— 历史上两处各写一份、
        #    注释还不一致，加一个候选位置要改两个文件，很容易漏。
        # 覆盖三种实际存在的布局：
        #   1. frontend/22project/dist —— 源码仓库里 `npm run build` 的默认输出
        #   2. frontend/dist           —— **打包分发**时的布局（目录被压平，少一层）
        #   3. data/web                —— 部署时把产物拷到这里，让"代码"和"构建产物"分开
        self.dist_candidates = (
            WORKSPACE_DIR / "frontend" / "22project" / "dist",
            WORKSPACE_DIR / "frontend" / "dist",
            DATA_DIR / "web",
        )
        self.dataset_dirs = dict(DATASET_DIRS)
        # 本项目**只支持 MySQL**：早期为了"没装库也能跑"写过 SQLite 兜底与 SQL Server 分支，
        # 结果是三套方言各自演化、埋了不少坑（占位符、TOP/LIMIT、建表语句）。现在统一到 MySQL，
        # 别的取值直接报错，免得有人配错了却"看起来能跑"。
        # ⚠️ 报错信息里带上收到的取值与 db.env 位置：这个异常是在 import 期抛的，
        # 不指路的话使用者只能看到一个莫名其妙的启动失败。
        self.db_dialect = (_env("MODEL_DB_DIALECT", "mysql") or "mysql").lower()
        if self.db_dialect != "mysql":
            raise RuntimeError(f"本项目只支持 MySQL（MODEL_DB_DIALECT=mysql），收到 {self.db_dialect!r}；"
                               f"请检查 testRestfulProject/db.env")
        # 连接参数（MySQL 默认端口 3306；账号密码放 db.env，不入库）。
        # ⚠️ 这些默认值是**本机开发**用的（127.0.0.1 / root / 空口令），只能在开发机上成立；
        # 换机器或部署务必用环境变量或 db.env 覆盖。
        self.db_host = _env("MODEL_DB_HOST", "127.0.0.1")
        self.db_user = _env("MODEL_DB_USER", "root")
        self.db_password = _env("MODEL_DB_PASSWORD", "")
        self.db_name = _env("MODEL_DB_NAME", "model_management")
        self.db_port = int(_env("MODEL_DB_PORT", "3306") or "3306")
        # ---- 鉴权 ----
        # 令牌签名用的密钥。**必须在部署时换成随机值**（见 db.env 里的 MODEL_SECRET_KEY），
        # 否则拿到源码的人可以自己签一个 admin 令牌出来，鉴权等于没有。
        # ⚠️ 这里给了一个默认值只为"开发机上开箱能跑"；config.describe() 会回报
        #    auth_key_is_default，前端与部署脚本据此提示"该换密钥了"。
        self.secret_key = _env("MODEL_SECRET_KEY", "")
        self.auth_key_is_default = not self.secret_key
        if not self.secret_key:
            # 没配就每次启动随机生成：安全性不降（反而更高，重启即失效旧令牌），
            # 代价只是"重启后需要重新登录"。对本项目完全可接受。
            import secrets as _secrets
            self.secret_key = _secrets.token_hex(32)
        # 令牌有效期（小时）。工厂场景一天一个班次，8 小时太短、30 天太长，默认 12 小时。
        self.token_ttl_hours = int(_env("MODEL_TOKEN_TTL_HOURS", "12") or "12")
        # 鉴权总开关。默认 True；测试脚本或本地纯调试可以 MODEL_AUTH_DISABLED=1 关掉。
        # ⚠️ 关掉时 /health 会显式回报 auth_disabled，避免"以为在鉴权其实没鉴"。
        self.auth_disabled = (_env("MODEL_AUTH_DISABLED", "") or "").lower() in ("1", "true", "yes")
        # 缺省管理员口令：**首次启动**用来生成种子账号，生成完就写进库、此后不再读它。
        # 空值 = 不生成种子账号（部署方自己 inser 用户，或已经有账号了）。
        self.bootstrap_admin_password = _env("MODEL_BOOTSTRAP_ADMIN_PASSWORD", "")
        # 登录页验证码（人机校验）。默认**关闭**，配 MODEL_CAPTCHA=1 打开。
        # ⚠️ 打开前请确认登录页能正常显示图片：前端读的是 `image_base`，后端返回的字段名
        #    必须一致（见 captcha.py 与 dvadmin.captcha()）—— 反过来说，前端那个"必填"规则
        #    只有在开关打开时才该生效，所以两边的开关都读这一个配置，不会各说各话。
        # 为什么要它：没有验证码时，弱口令可以在线慢慢爆破（登录接口没有失败计数）。
        self.captcha_enabled = (_env("MODEL_CAPTCHA", "") or "").strip().lower() in ("1", "true", "yes", "on")
        # 自助注册开关（MODEL_ALLOW_REGISTER）。默认**打开**。
        # 为什么默认开：本平台是实验室/内网工具，新人自己注册一个"现场操作员"账号就能开工，
        # 不必每次都找管理员开号。注册出来的账号**角色强制"普通用户"**（见 dvadmin.register），
        # 想提权只能由管理员在「用户管理」页改。
        # ⚠️ 交付到工厂等正式环境时**建议关掉**（db.env 里写 MODEL_ALLOW_REGISTER=0）：
        #    关掉后登录页不显示「注册」页签，后端接口也会直接拒绝。
        self.allow_register = (_env("MODEL_ALLOW_REGISTER", "1") or "1").strip().lower() in ("1", "true", "yes", "on")
        # ⚠️ 这里原来还有一个 self.defaults 字典（三套模型的默认超参速查表），已删除：
        #    它全项目零引用（只有本行赋值），运行时真正生效的默认值写在 training.py 里，
        #    形式是 `opts.get("epochs", 10)` 这类内联字面量。**改默认超参请改 training.py。**
    # ---- 便于 /health 与日志展示 ----
    def describe(self) -> dict:
        """给 /health 与前端「运行信息」用的配置摘要（只读快照，不含密码）。

        数据库只可能是 MySQL（`__init__` 里已保证），所以这里的 db 块实际就是
        "dialect / 主机 / 端口 / 库名"四项；账号密码放 db.env，**刻意不返回**。
        """
        return {
            "project_dir": str(self.project_dir),
            "model_dir": str(self.model_dir),
            "temp_dir": TEMP_DIR,                 # 探测后真正生效的临时目录（可能是 data/tmp）
            "env_file": ENV_FILE,                 # None = 没有 db.env 或一行都没生效
            "db": {
                "dialect": self.db_dialect,
                # 本项目只支持 MySQL，这里不再有任何方言分支：原先是 `x if dialect != "sqlite" else ...`
                # 三元，但 dialect 在 __init__ 里已被强制成 mysql（别的取值直接 RuntimeError），判断恒真、
                # else 永远走不到；而且 else 引用的 self.sqlite_path 属性在本类里早已不存在，
                # 一旦真放开 sqlite 就会 AttributeError —— 死分支反而成了陷阱，故直接返回值。
                "host": self.db_host,
                "port": self.db_port,
                "database": self.db_name,
            },
            "datasets": {k: str(v) for k, v in self.dataset_dirs.items()},
            "upload_dir": str(self.upload_dir),
            "export_dir": str(self.export_dir),
            # 鉴权状态摘要。**不含密钥本身**，只表明"用的是默认/随机密钥"，
            # 让部署方一眼看出该不该换。auth_disabled 要显式露出：
            # 这是个"关掉就完全没有防护"的开关，藏在后台最危险。
            "auth": {
                "enabled": not self.auth_disabled,
                "key_is_default": self.auth_key_is_default,
                "token_ttl_hours": self.token_ttl_hours,
                # 两个登录页开关也露出来：交付前自检想知道"注册开着没有 / 验证码开着没有"，
                # 不必去翻 db.env；它们不含任何敏感信息。
                "allow_register": self.allow_register,
                "captcha_enabled": self.captcha_enabled,
            },
        }
config = Config()

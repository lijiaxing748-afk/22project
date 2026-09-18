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
SERVICE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SERVICE_DIR.parent            # testRestfulProject
WORKSPACE_DIR = PROJECT_DIR.parent          # 22project
DATA_DIR = PROJECT_DIR / "data"
MODEL_DIR = DATA_DIR / "models"             # 模型产物（对应图里的「Pxl模型」）
LOG_DIR = DATA_DIR / "logs"                 # 训练日志
UPLOAD_DIR = DATA_DIR / "datasets"          # 上传/存放的表格数据集（一个子目录 = 一个数据集）
EXPORT_DIR = DATA_DIR / "exports"           # 模型发布包（一个训练产物一个 zip，按模型分子目录）
SQL_DIR = PROJECT_DIR / "sql"
# 前端产物目录（两个候选位置，web.py 里按顺序探测，先命中哪个用哪个）：
#   1. frontend/22project/dist —— 开发机上 `npm run build` 的默认输出
#      ⚠️ 注意层级：PROJECT_DIR 是 testRestfulProject，WORKSPACE_DIR 才是仓库根 22project
#   2. data/web                —— 部署时把产物拷到这里，让"代码"和"构建产物"分开，
#                                 更新代码不用连前端产物一起覆盖
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
    for raw in path.read_text(encoding="utf-8").splitlines():
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
            },
        }
config = Config()

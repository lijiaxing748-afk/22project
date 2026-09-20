# -*- coding: utf-8 -*-
"""数据库写入层：按外键顺序把「训练」和「推理」写进 8 张表。

外键顺序（唯一的建表脚本 sql/schema_mysql.sql 已排好，这里严格照做）：

    ① Datasets ─┐
                ├─▶ ② Models ─▶ ③ Trainings ─┬─▶ ④ ModelInvocations（调用日志）
    ② Models  ──┘                            └─▶ ⑤ InferenceTasks ─▶ ⑥ InferenceResults
                                                   （另需 TargetDatasetID→①、ModelID→②）

关于"「InferenceTasks.TrainingID 与 DeploymentID 谁为权威锚点」"这个老悬案
（它原先记在被删掉的 T-SQL 版 sql/schema.sql 末尾，现把结论落在代码这边），
这里的选择是：**TrainingID 为权威锚点**——推理结果的可信度取决于"哪一次训练"，部署只是
同一次训练的投放位置。因此本服务写库时 DeploymentID / DeviceID 留空（NULL），等「边缘设备」
那条支线真正落地后再回填。

数据库：**只用 MySQL**（pymysql）。早期为"没装库也能跑"写过 SQLite 兜底与 SQL Server(pyodbc)
两条分支，三套方言各自演化出占位符 / LIMIT-TOP / 建表脚本 / 取主键 等一堆差异，维护成本远大于
收益，现已统一：连接参数见 db.env，建表脚本只有 sql/schema_mysql.sql（自带 CREATE DATABASE + USE）。

写库失败一律抛 DBUnavailable / DBError，由上层决定「降级但显式回报」，不允许静默吞掉。
"""
from __future__ import annotations
import json
import re
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from .config import config

# pymysql 的异常类型：驱动缺失时也要能 import 本模块（首次启动可能还没装），
# 所以这里做软导入，缺了就退化成"永远不会匹配"的占位类型。
# ⚠️ 用元组形式给 except 使用；不要在多处写 `import pymysql`，
#    否则异常类型来自不同导入点，`except` 可能匹配不上。
try:
    from pymysql.err import IntegrityError as _IntegrityError
except Exception:                                    # pragma: no cover - 驱动缺失的兜底
    class _IntegrityError(Exception):                # type: ignore[no-redef]
        """pymysql 缺失时的占位：没有任何异常会是它，等价于"不捕获"。"""


class DBError(RuntimeError):
    """数据库层通用错误。"""
class DBUnavailable(DBError):
    """连不上或驱动缺失——上层据此降级并回报，而不是静默忽略。"""
# 建表脚本里应该有的表（_tables_present 用它判断"是否已经建好、可以跳过 DDL"）
# ⚠️ 这里必须与 sql/schema_mysql.sql 里的表**完全一致**：少写一张，老库上就会
#    出现"表存在但名单里没有 → 判定为未建表 → 反复跑建表脚本"；
#    多写一张不存在的，则**永远判定为未建表**，每次请求都白跑一遍脚本。
#    ⚠️ 而且 _tables_present 是"全都在才返回 True"，任何一个名字对不上都会退化成
#    "每次都跑脚本"，所以新增表时**两处必须同步改**（这就是它被放在 _TABLES 常量里的原因）。
_TABLES = ("Datasets", "Models", "Trainings", "ModelInvocations",
           "ModelDeployments", "InferenceTasks", "InferenceResults", "EdgeDevices",
           "Roles", "Users", "OperationLogs")
def _now() -> str:
    """统一时间戳格式：MySQL 能解析的字符串（截断到毫秒）。"""
    return datetime.now().isoformat(sep=" ", timespec="milliseconds")
def _dump_json(value):
    """落 LONGTEXT 前的 JSON 文本；None 保持 SQL NULL（**不**写成字符串 "null"）。

    ⚠️ `ModelInvocations.RequestParams` 是"无条件 dumps"的另一种口径（那列 NOT NULL），
    需要"永远写文本"就别用这个函数。
    default=str 兜住 datetime 之类的非标准类型：审计日志不值得为一个字段 500。
    """
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)
def _bit(value):
    """TINYINT(1) 列的值：None 保持 NULL，其余显式转 1/0。

    不能直接塞 True/False：不同驱动对 bool 的处理不一致，落库取值会漂。
    """
    return None if value is None else (1 if value else 0)
def _strip_sql_comments(text: str) -> str:
    """去掉 /* */ 块注释与整行的 -- 行注释，好按分号安全切分脚本。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*--.*$", "", text, flags=re.M)
    return text
def _statements(sql: str) -> list[str]:
    """把建表脚本切成一条条可执行的 SQL（按分号切，切之前先去掉注释，避免注释里的分号捣乱）。

    够用就好的简易切分：schema_mysql.sql 里没有存储过程 / BEGIN…END，不需要真正的 SQL 解析器。
    ⚠️ 它是"裸切"，如果哪天在字符串字面量里写了分号或 `--`，会被切错——建表脚本里保持别这么写。
    """
    return [s.strip() for s in _strip_sql_comments(sql).split(";") if s.strip()]
def _clip(value, limit: int):
    """按列宽截断，避免超长文本直接触发数据库报错。

    规则：只对 str 生效；超长时保留前 `limit - 3` 个字符再补 "..."，让**总长仍 <= limit**，
    正好卡在列宽边界上也不会被 MySQL（严格模式）判成超长。数字 / None / bool 原样透传。
    ⚠️ limit 必须与建表脚本里的列宽一致（如 Description VARCHAR(500)、Status VARCHAR(20)），
    两边对不上就退化成"要么提前截断、要么照样报错"。
    """
    if isinstance(value, str) and len(value) > limit:
        return value[:limit - 3] + "..."
    return value
def _jsonable(value):
    """把驱动返回的对象转成可 JSON 序列化的值。

    pymysql 读 DATETIME 列会返回 datetime 对象、读 DECIMAL 会返回 Decimal、读 BLOB 会返回
    bytes —— 直接塞进 Flask 的 jsonify 会报 "Object of type datetime is not JSON serializable"。
    所有回读接口都必须先过这里（`/trainings` 曾经 500 就是漏了这一步）。
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
class Database:
    """数据库门面（**只用 MySQL**）：连接按线程复用、幂等建表、写入与回读。

    历史说明：早期支持过 SQLite（零配置兜底）与 SQL Server（pyodbc），
    但三套方言各自演化出一堆分支（占位符 `%s`/`?`、`LIMIT`/`TOP`、建表脚本、
    `PRAGMA foreign_keys`…），维护成本远大于收益，现已统一到 MySQL，
    其他方言在 config 与这里各挡一次。
    """
    def __init__(self, cfg=config) -> None:
        """准备连接缓存与行数缓存；方言不是 MySQL 就直接失败（不猜、不降级）。"""
        self.cfg = cfg
        self.dialect = cfg.db_dialect
        if self.dialect != "mysql":
            raise DBError(f"本项目只支持 MySQL，收到 {self.dialect!r}")
        self._schema_ready = False
        self._schema_lock = threading.Lock()   # 建表必须串行化，否则并发首启会撞 MySQL 死锁（见 ensure_schema）
        self.last_bootstrap = None      # 记录「顺便建了库/表」的事实，供 /health 展示
        self._local = threading.local()  # 每线程复用一个连接（之前是每个请求都新建连接）
        self._counts_cache = {"at": 0.0, "data": None}
    # ------------------------------------------------------------------ 连接
    @property
    def placeholder(self) -> str:
        """参数占位符：MySQL 用 %s（sqlite/SQL Server 的 `?` 分支已移除）。"""
        return "%s"
    def _ping(self, conn) -> bool:
        """探活：连接超时或数据库重启过时会失败，调用方据此决定重连。"""
        try:
            conn.ping(reconnect=False)
            return True
        except Exception:
            return False
    def _connect(self, require_db: bool = True):
        """取本线程的连接（存在 threading.local 里）；require_db=False 时连到 master（建库前用）。

        复用而不是"每请求新建"：一次 MySQL 握手 + 认证是实打实的开销，早期那种写法是接口变慢的来源之一。
        ⚠️ 缓存必须连 require_db 一起比对：master 连接没执行过 USE，拿它跑业务 SQL 会直接 "No database selected"。
        """
        cached = getattr(self._local, "conn", None)
        # 缓存的连接必须与本次的 require_db 一致：连到 master 的连接不能拿去做业务查询
        if cached is not None and getattr(self._local, "req_db", None) == require_db:
            if self._ping(cached):
                return cached
            try:                                   # 连接失效（超时/重启）就先丢弃再重连
                cached.close()
            except Exception:
                pass
            self._local.conn = None
        conn = self._connect_new(require_db)
        self._local.conn = conn
        self._local.req_db = require_db
        return conn
    def _connect_new(self, require_db: bool = True):
        """建立 MySQL 连接；缺驱动 / 连不上统一抛 DBUnavailable（调用方据此降级）。

        `require_db=False` 用于"库还不存在"的首次启动：先连到服务器，再执行
        `schema_mysql.sql` 里的 CREATE DATABASE + USE。
        """
        cfg = self.cfg
        try:
            import pymysql
        except ImportError as exc:
            raise DBUnavailable("缺少 pymysql 驱动：pip install pymysql") from exc
        kwargs = dict(host=cfg.db_host, port=cfg.db_port, user=cfg.db_user,
                      password=cfg.db_password, charset="utf8mb4", autocommit=False)
        if require_db:
            kwargs["database"] = cfg.db_name
        try:
            return pymysql.connect(**kwargs)
        except Exception as exc:
            raise DBUnavailable(
                f"MySQL 连接失败({cfg.db_host}:{cfg.db_port}/{cfg.db_name if require_db else '-'})：{exc}") from exc
    @contextmanager
    def cursor(self, commit: bool = False):
        """借出一个游标；块内正常结束才按 commit 决定提交，异常回滚并把原异常抛出去。

        commit=False 是只读默认值；commit=True 时整块当**一个事务**看——要么全落、要么全不落。
        异常必须先 rollback：不退事务的连接会停在"事务开着、InnoDB 行锁没放"的状态，
        一直挂到连接断开，后面同线程的操作会互相等锁。

        ⚠️⚠️ 只读块也**必须结束事务**（rollback），这是实测复现过的**脏快照 bug**：
        本项目连接是 `autocommit=0` + MySQL 默认的 `REPEATABLE-READ`。只读块不提交也不回滚，
        连接就一直停在"事务开着"的状态 —— 于是这条连接**后续所有读**看到的都是
        事务启动那一刻的旧快照，在 REPEATABLE-READ 下永远不会推进。

        具体症状（用户管理页实测）：管理员「新建用户」成功（INSERT 已提交），
        紧接着刷新列表，**新用户就是不出来**，列表里永远只有建号那一刻之前的那些账号。
        更隐蔽的是：换个浏览器/重启服务就好了（换连接 = 换新快照），所以极易被当成前端缓存问题。
        同类症状还会出现在"新建的数据集/模型刷新后不显示"等任何 write-then-read 流程上。

        修法：只读路径也走 rollback 结束事务，下一次读就会开一个新快照。
        rollback 对纯读事务没有语义损失（本来就没有要保留的修改）。

        finally 里**只关游标、不关连接**：连接是按线程复用的资源，生命周期归 _connect/_ping 管；
        在这里 close 掉，等于把复用的连接又降级回"每请求新建"，白付一次握手认证成本。
        ⚠️ 所以 cursor() 只做语句级隔离，需要跨多次 cursor() 的复合写要自己塞进同一个游标里（见 insert_task_with_results）。
        """
        conn = self._connect()
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
            else:
                # 只读块：也必须退出事务，否则 REPEATABLE-READ 的旧快照会一直粘在这条连接上
                conn.rollback()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass
    # -------------------------------------------------------------- 建表/体检
    def _tables_present(self, conn) -> bool:
        """8 张表是否都在（都在就不必再跑建表脚本）。
        
        用 information_schema 一次问清，比"跑一遍 CREATE TABLE IF NOT EXISTS 看会不会报错"便宜得多，
        而且**不碰任何行锁** —— 这正是并发死锁的关键（见 ensure_schema 里那段说明）。
        ⚠️ 表名比较要忽略大小写：Windows 上 MySQL 的 lower_case_table_names 默认是 1，
        information_schema 回来的可能全是小写。
        """
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                            (self.cfg.db_name,))
                have = {str(row[0]).lower() for row in cur.fetchall()}
            finally:
                cur.close()
        except Exception:                              # 查不了就当"不确定"，退回跑一遍建表脚本（幂等）
            return False
        return all(name.lower() in have for name in _TABLES)
    def ensure_schema(self) -> None:
        """幂等建表（**只用 MySQL**）：执行 sql/schema_mysql.sql。表已齐全时一条语句都不执行。
        
        ⚠️ 为什么要加锁 —— 这是一个实测复现过的**线上 500**：
        前端页面一加载就并行打出 /health、/models、/trainings、/inference-tasks 四个请求。
        冷启动时 `_schema_ready` 还是 False，四个线程于是**各自在自己的连接上把整份建表脚本跑一遍**。
        
        死锁**不在** CREATE TABLE 上（元数据锁冲突报的是 1205 lock wait timeout），
        而在脚本末尾那两条种子数据的 `INSERT IGNORE`：
        `INSERT IGNORE` 撞到重复键时会在该记录上取**共享锁**，两个事务都拿到共享锁之后
        又都要往同一个唯一键里插 —— 共享锁要升级、互等成环，InnoDB 直接判死并回 **1213**。
        1213 是 InnoDB 的**行锁**死锁，这条错误码本身就把范围指到了 DML 上。
        
        实测数据（6 线程并发执行同一条语句，各 40 轮）：
          · `INSERT IGNORE INTO Models ... VALUES (…),(…),(…)`  死锁 166/240
          · 把它拆成 3 条单行 `INSERT IGNORE`                   死锁 173/240（拆了没用！）
          · 单行的 `INSERT IGNORE INTO Datasets ...`            死锁 0/240
          · 10 条 `CREATE TABLE IF NOT EXISTS`                  死锁 0/240
        所以这**与插入几行无关**，是"并发 INSERT IGNORE 撞同一批重复键"本身的特性。
        正解只能是"别让多个线程同时跑脚本"：拿锁串行 + 表已存在就直接返回（连脚本都不读）。
        
        实测对照（25 轮 × 6 线程，每轮一个全新 Database 实例模拟冷启动）：
          修复前（无锁、必跑脚本）：死锁 6/150，脚本被执行 150 遍
          只加锁                 ：死锁 0/150，脚本被执行 25 遍（每轮一个线程赢锁）
          加锁 + 快路径（现状）   ：死锁 0/150，脚本被执行 0 遍
        
        ⚠️ 锁是**进程内**的。若在空库上同时启动两个进程，理论仍可能撞车；
        本项目单进程运行，真要支持多进程得给脚本加重试，到时候再说。
        """
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:                     # 等锁期间别人已经建好了
                return
            try:
                conn = self._connect()                 # 库已存在
            except DBUnavailable:
                conn = self._connect(require_db=False)  # 库还不存在：脚本里有 CREATE DATABASE + USE
                self.last_bootstrap = f"MySQL 库 {self.cfg.db_name} 由 schema_mysql.sql 顺手创建"
            try:
                if self._tables_present(conn):
                    # 表已经齐全：一条语句都不用跑。服务每次重启、每个线程的首次调用都会走到这里，
                    # 白白跑一遍脚本既慢、又会去抢 INSERT IGNORE 的锁，没必要。
                    self._schema_ready = True
                    return
                sql = (self.cfg.sql_dir / "schema_mysql.sql").read_text(encoding="utf-8")
                cur = conn.cursor()
                try:
                    for stmt in _statements(sql):
                        cur.execute(stmt)
                    conn.commit()
                finally:
                    cur.close()
            finally:
                # ⚠️ 关掉的是 _connect() 返回的**线程本地复用连接**，所以必须把缓存一起清掉，
                #    否则 self._local.conn 会指向一条已关闭的连接，下次 _connect 得先 ping 失败
                #    再重连（多一次无谓的往返）。
                #    master 连接（require_db=False）也必须在这里关：它没执行过 USE，本来就不能复用。
                try:
                    conn.close()
                finally:
                    if getattr(self._local, "conn", None) is conn:
                        self._local.conn = None
            self._schema_ready = True
    def ping(self) -> dict:
        """体检：顺便建表 + 取行数，**永远返回 dict 不抛异常**（/health 靠它保持可用）。"""
        try:
            self.ensure_schema()
            counts = self.table_counts()
            return {"ok": True, "dialect": self.dialect, "counts": counts,
                    "target": f"{self.cfg.db_host}:{self.cfg.db_port}/{self.cfg.db_name}",
                    "bootstrap": self.last_bootstrap}
        except Exception as exc:
            return {"ok": False, "dialect": self.dialect, "error": str(exc),
                    "target": f"{self.cfg.db_host}:{self.cfg.db_port}/{self.cfg.db_name}"}
    # ------------------------------------------------------------------ 写入
    def _ph(self, n: int) -> str:
        """生成 n 个占位符并用逗号连起来，如 "%s, %s, %s"（VALUES 子句用）。"""
        return ", ".join([self.placeholder] * n)
    def _insert_sql(self, table: str, cols: tuple[str, ...]) -> str:
        """拼一条 INSERT：**列名只写一遍**，占位符个数由 len(cols) 推出。

        以前是"手写列清单" + "手数占位符个数（_ph(14)）"两处各写一遍，加一列忘了改另一处，
        就得到一个只在运行时才炸的 "Column count doesn't match value count"。
        """
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({self._ph(len(cols))})"
    def _insert_cur(self, cur, table: str, cols: tuple[str, ...], values: tuple) -> int:
        """在该游标上 INSERT 一行并返回自增主键。只管执行、不管事务（事务归调用方的 cursor()）。"""
        cur.execute(self._insert_sql(table, cols), values)
        return int(cur.lastrowid)
    def _find_id(self, cur, table: str, pk_col: str, name_col: str, name: str) -> int | None:
        """按"名字列"查主键，查不到返回 None（不抛异常）。

        ensure_dataset / ensure_model 的"有就取"、register_dataset 的探测、model_exists、
        model_references 都在做这件事，以前各写一遍 SELECT。表名/列名是写死的字面量，值走占位符。
        ⚠️ 相等比较由 MySQL 做，受该列 collation 影响（本库 utf8mb4_unicode_ci，**大小写不敏感**）。
        """
        cur.execute(f"SELECT {pk_col} FROM {table} WHERE {name_col} = {self.placeholder}", (name,))
        row = cur.fetchone()
        return int(row[0]) if row else None
    def ensure_dataset(self, name: str, source: str | None = None, sample_count: int | None = None,
                       class_count: int | None = None, data_path: str | None = None,
                       description: str | None = None) -> int:
        """① Datasets：有就取、没有就建（幂等），返回 DatasetID 主键。

        按 DatasetName 查（表上有唯一键）：命中直接返回既有主键，否则 INSERT 再回主键。
        做成幂等是因为每次训练/推理都要先把依赖行落实，调用方不必自己判断"该插还是该取"。
        ⚠️ 命中分支**不更新**任何已有字段：同名再传 SampleCount/Description 也是白传
        （曾经配套的 update_dataset() 已随零调用的 CRUD 路由一起删除，要改就直接写 SQL）。
        返回值是主键 ID，给 Trainings.DatasetID / InferenceTasks.TargetDatasetID 当外键用——
        外键顺序必须是 Datasets → Models → Trainings/InferenceTasks，反过来写数据库直接拒绝。
        """
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            found = self._find_id(cur, "Datasets", "DatasetID", "DatasetName", name)
            if found is not None:
                return found
            return self._insert_cur(
                cur, "Datasets",
                ("DatasetName", "Source", "SampleCount", "ClassCount", "DataPath", "Description", "CreatedDate"),
                (name, _clip(source, 200), sample_count, class_count, _clip(data_path, 500),
                 _clip(description, 500), _now()),
            )
    def ensure_model(self, name: str, description: str | None = None, model_type: str | None = None,
                     api_endpoint: str | None = "/predict", status: str | None = "可运行") -> int:
        """② Models：有就取、没有就建（幂等），返回 ModelID 主键。

        语义与 ensure_dataset 完全对称：按 ModelName（唯一键）命中就复用，未命中才插。
        ⚠️ 命中分支同样**不更新**已有行：模型描述/类型改了不会因为再调一次而生效。
        传进来的名字必须先过 training.db_model_name() 换算成库里的规范写法（'1DCNN' 而不是 '1dcnn'），
        否则登记与显示的名字会和 schema 种子数据、data/models/<键> 目录名对不上。
        """
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            found = self._find_id(cur, "Models", "ModelID", "ModelName", name)
            if found is not None:
                return found
            return self._insert_cur(
                cur, "Models",
                ("ModelName", "Description", "ApiEndpoint", "ModelType", "CreatedDate", "IsActive", "Status"),
                (name, _clip(description, 500), _clip(api_endpoint, 255), _clip(model_type, 50), _now(), 1,
                 _clip(status, 20)),
            )
    def insert_training(self, model_id: int, dataset_id: int | None, train_name: str,
                        epochs: int | None, batch_size: int | None, accuracy: float | None,
                        loss: float | None, model_path: str | None, status: str,
                        started: str | None = None, completed: str | None = None,
                        created_by: str | None = "model_service", remark: str | None = None) -> int:
        """③ Trainings：一次训练写一行，返回 TrainingID（推理任务的外键锚点）。

        字段来源：ModelID/DatasetID 由 ensure_model/ensure_dataset 先落实；Epochs/BatchSize/Accuracy/Loss
        来自训练结果；ModelPath 是 registry 落盘的权重路径；StartedDate/CompletedDate 由调用方给，
        CreatedDate 这里补成写入时刻——失败的那次也照样写一行（Status=失败），便于追溯。
        超长文本一律过 _clip，避免一个长路径/长备注把整次落库带崩。
        """
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            return self._insert_cur(
                cur, "Trainings",
                ("ModelID", "DatasetID", "TrainName", "Epochs", "BatchSize", "Accuracy", "Loss",
                 "ModelPath", "Status", "CreatedDate", "StartedDate", "CompletedDate", "CreatedBy", "Remark"),
                (model_id, dataset_id, _clip(train_name, 200), epochs, batch_size, accuracy, loss,
                 _clip(model_path, 500), _clip(status, 20), _now(), started, completed,
                 _clip(created_by, 100), _clip(remark, 500)),
            )
    def insert_invocation(self, model_id: int, training_id: int | None, api_endpoint: str,
                          request_params, response_result=None, duration_ms: int | None = None,
                          is_success: bool | None = None, status_code: int | None = None,
                          error_message: str | None = None, client_ip: str | None = None,
                          status: str | None = None) -> int:
        """④ ModelInvocations：每次 /predict 调用留一条（失败也留），相当于调用审计日志。

        ⚠️ request_params / response_result 是任意结构的 Python 对象，落 LONGTEXT 前先 json.dumps；
        RequestParams 那列用 `_dump_json` 的反面（无条件 dumps）：它的列是 NOT NULL，
        所以 None 在这里写的是字符串 "null" 而不是 SQL NULL，别"顺手统一"。
        """
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            return self._insert_cur(
                cur, "ModelInvocations",
                ("ModelID", "TrainingID", "ApiEndpoint", "RequestParams", "ResponseResult",
                 "DurationMs", "IsSuccess", "StatusCode", "ErrorMessage", "ClientIP", "Status", "InvocationDate"),
                (model_id, training_id, _clip(api_endpoint, 255),
                 json.dumps(request_params, ensure_ascii=False, default=str),
                 _dump_json(response_result),
                 duration_ms, _bit(is_success), status_code,
                 error_message, _clip(client_ip, 50), _clip(status, 20), _now()),
            )
    def _insert_task_cur(self, cur, training_id: int, target_dataset_id: int, task_name: str,
                         task_type: str, status: str, inference_params=None, result_summary=None,
                         error_message: str | None = None, model_id: int | None = None,
                         input_path: str | None = None, output_path: str | None = None,
                         progress: int | None = None, started: str | None = None,
                         completed: str | None = None, created_by: str | None = "model_service") -> int:
        """⑤ InferenceTasks 的 SQL 本体（单写、或与结果同事务，两种入口复用）。

        只做 INSERT、不管事务：事务边界由调用方的 cursor() 决定，这样才能既支持"只写任务"，
        也支持 insert_task_with_results 把它和 ⑥ 塞进同一个事务。
        DeploymentID / DeviceID 显式写 None：本服务以 TrainingID 为权威锚点，这两个字段留给边缘设备支线回填。
        """
        return self._insert_cur(
            cur, "InferenceTasks",
            ("TrainingID", "TargetDatasetID", "TaskName", "TaskType", "Status",
             "InferenceParams", "ResultSummary", "ErrorMessage", "DeploymentID", "ModelID", "DeviceID",
             "InputPath", "OutputPath", "Progress", "CreatedDate", "StartedDate", "CompletedDate", "CreatedBy"),
            (training_id, target_dataset_id, _clip(task_name, 200), _clip(task_type, 20), _clip(status, 20),
             _dump_json(inference_params),
             _dump_json(result_summary),
             error_message, None, model_id, None, _clip(input_path, 500), _clip(output_path, 500), progress,
             _now(), started, completed, _clip(created_by, 100)),
        )
    def _insert_results_cur(self, cur, task_id: int, rows: list[dict]) -> int:
        """⑥ InferenceResults 的 SQL 本体（同上复用），返回写入行数。

        一个任务的明细是"一个窗口一行"，可能几百上千行，所以逐行 execute 最直白；
        也避免拼一条巨型 INSERT 撞上 MySQL 的 max_allowed_packet 而整批失败。
        空 rows 直接返回 0：推理可能一个窗口都没切出来，此时不该报错，也不该写空值行。
        ⚠️ ResultTimestamp 缺省取本次统一的 now，保证同一个任务里所有明细的时间戳一致；
        布尔列同样必须转 1/0；detail 是 JSON 字符串（列宽 500 的 FeatureSnapshot 走 _clip）。
        """
        if not rows:
            return 0
        cols = ("InferenceTaskID", "RowIdentifier", "ResultTimestamp", "PredictedValue", "AnomalyScore",
                "IsAnomaly", "PredictedCategory", "Confidence", "FeatureSnapshot", "ModelID", "SampleIndex",
                "PredictedClass", "PredictedLabel", "Score", "ActualClass", "ResultDetail", "CreatedDate")
        sql = self._insert_sql("InferenceResults", cols)   # 与上面几处共用：列名只写一遍
        now = _now()
        for row in rows:
            cur.execute(sql, (
                task_id, _clip(row.get("row_identifier"), 100), row.get("result_timestamp") or now,
                row.get("predicted_value"), row.get("anomaly_score"),
                _bit(row.get("is_anomaly")),
                _clip(row.get("predicted_category"), 50), row.get("confidence"),
                _clip(row.get("feature_snapshot"), 500), row.get("model_id"), row.get("sample_index"),
                row.get("predicted_class"), _clip(row.get("predicted_label"), 100), row.get("score"),
                row.get("actual_class"),
                _dump_json(row.get("detail")),
                now,
            ))
        return len(rows)
    def insert_task_with_results(self, task_kwargs: dict, rows: list[dict]) -> tuple[int, int]:
        """⑤+⑥ **同一个事务**写完任务与全部结果，返回 (task_id, 结果行数)。

        存在的意义：以前是两次独立 commit，结果插入一旦失败，任务行已经按 `Status=成功、Progress=100`
        提交掉了，留下一个"有任务、没结果"的孤儿任务——前端明细点开是空的，日志里还写着成功。
        现在共用一个 cursor（=一个事务），结果失败会连带任务一起 rollback，要么都成功、要么都没写。
        所以推理落库**只走这个入口**：原先还并列着 insert_inference_task / insert_inference_results
        两个"单独写一半"的公开方法，全项目零调用，已删除，免得有人以为落库有第二条路径。
        """
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            task_id = self._insert_task_cur(cur, **task_kwargs)
            return task_id, self._insert_results_cur(cur, task_id, rows)
    # -------------------------------------------------- 发布（ModelDeployments）
    def local_device_id(self, cur=None) -> int:
        """取『本地导出』占位设备的 DeviceID（发布记录的外键目标）。

        ⚠️ 为什么必须有这么个设备：ModelDeployments.DeviceID 是 **NOT NULL 外键**，
        而本项目还没有真实边缘设备。占位行由 sql/schema_mysql.sql 的种子数据插入
        （DeviceType='local'）。查不到就直接抛——发布功能没它写不进库，
        与其让调用方在 INSERT 时撞外键报一个难懂的 1452，不如在这里给出明确原因。
        """
        sql = "SELECT DeviceID FROM EdgeDevices WHERE DeviceType = %s ORDER BY DeviceID"
        if cur is not None:
            cur.execute(sql, ("local",))
            row = cur.fetchone()
        else:
            self.ensure_schema()
            with self.cursor() as own:
                own.execute(sql, ("local",))
                row = own.fetchone()
        if not row:
            raise DBError("找不到『本地导出』占位设备（EdgeDevices.DeviceType='local'）；"
                          "请重跑 sql/schema_mysql.sql 补上种子数据")
        return int(row[0])

    def count_deployments(self, model_id: int) -> int:
        """某模型已成功发布过几个包——发布时用它推算下一个版本号（v1/v2/…）。

        ⚠️ 只数**成功**的记录：失败的那次没有产出包，不该占掉一个版本号，
        否则"发布失败一次、下次直接从 v2 开始"，而 v1 从来没存在过。
        """
        self.ensure_schema()
        with self.cursor() as cur:
            return self._count(
                cur, f"SELECT COUNT(*) FROM ModelDeployments WHERE ModelID = {self.placeholder} "
                     f"AND DeployStatus = {self.placeholder}", (model_id, "已导出"))

    def insert_deployment(self, model_id: int, training_id: int, device_id: int, *,
                          version: str | None = None, version_alias: str | None = "latest",
                          environment: str | None = "test", deployed_path: str | None = None,
                          deploy_url: str | None = None, runtime_params=None,
                          deploy_status: str = "已导出", deployed_by: str | None = None,
                          error_message: str | None = None, remark: str | None = None) -> int:
        """写一条 ModelDeployments 发布记录，返回 DeploymentID。

        本项目把这张表当"模型发布/导出"的流水账用（原设计是"发布到边缘设备"，但还没有
        真设备），各列的落地口径见 docs/模型发布-设计方案.md §2.1。几处必要的偏离：

          · ServicePort 一律 **NULL**：该列有 CHECK (BETWEEN 1 AND 65535)，写 0 会被拒；
            本功能不涉及服务部署，端口没有含义。
          · DeployedPath / DeployUrl 改存**导出包**的磁盘路径与下载地址。
          · IsCurrent：新发布的这条是当前版（1），同一模型的旧记录在下面被降级。
          · ⚠️ 同一模型只允许一条 IsCurrent=1 —— 下面同一个事务里把旧的清掉，
            保证"最新一条"唯一，否则前端按 IsCurrent 取最新版会拿到多行。

        ⚠️ training_id **不能为 None**：TrainingID 是 NOT NULL 外键。调用方必须先确保有
        一条训练记录（api 层为此做了"成功 → 任意状态 → 报 409"的三级兜底），
        别把 None 传进来撞 1452。
        """
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            if version_alias == "latest":
                # 同模型旧记录降级：别名撤掉、当前版标记清掉。放在 INSERT 之前，
                # 这样即便后面 INSERT 失败回滚，也不会留下"两条都是当前版"的中间态
                cur.execute(
                    f"UPDATE ModelDeployments SET VersionAlias = NULL, IsCurrent = 0 "
                    f"WHERE ModelID = {self.placeholder} AND IsCurrent = 1", (model_id,))
            return self._insert_cur(
                cur, "ModelDeployments",
                ("ModelID", "TrainingID", "DeviceID", "Version", "VersionAlias", "Environment",
                 "DeployUrl", "DeployedPath", "ServicePort", "RuntimeParams", "IsActive", "IsCurrent",
                 "DeployStatus", "DeployedDate", "DeployedBy", "ErrorMessage", "Remark"),
                (model_id, training_id, device_id, _clip(version, 50), _clip(version_alias, 20),
                 _clip(environment, 20), _clip(deploy_url, 255), _clip(deployed_path, 500),
                 None,                                       # ServicePort：见上面 ⚠️，必须 NULL
                 _dump_json(runtime_params), 1, 1,
                 _clip(deploy_status, 20), _now(), _clip(deployed_by, 100),
                 error_message, _clip(remark, 500)),
            )

    def recent_deployments(self, model_name: str | None = None, limit: int = 50) -> list[dict]:
        """发布记录列表（带模型名、训练名），供「发布历史」用。

        ⚠️ 两个 JOIN 都必须是 LEFT：
          · TrainingID 可空（发布时可以不带来源训练）；
          · 模型可能只有发布记录而 Models 行被改过名。
        INNER JOIN 会让这些记录整条从列表里消失。
        排序按 DeploymentID DESC（自增主键即时间序，比按日期列排更稳）。
        """
        cols = ("d.DeploymentID, d.ModelID, d.TrainingID, d.DeviceID, d.Version, d.VersionAlias, "
                "d.Environment, d.DeployUrl, d.DeployedPath, d.DeployStatus, d.DeployedDate, "
                "d.DeployedBy, d.ErrorMessage, d.Remark, d.IsCurrent, "
                "m.ModelName, t.TrainName")
        tail = ("FROM ModelDeployments d "
                "LEFT JOIN Models m ON m.ModelID = d.ModelID "
                "LEFT JOIN Trainings t ON t.TrainingID = d.TrainingID")
        if model_name:
            # _select_limited 只收 (cols, tail, limit)，带参的 WHERE 得自己走一遍 cursor
            self.ensure_schema()
            sql = f"SELECT {cols} {tail} WHERE m.ModelName = {self.placeholder} " \
                  f"ORDER BY d.DeploymentID DESC LIMIT {int(limit)}"
            with self.cursor() as cur:
                cur.execute(sql, (model_name,))
                return self._rows_to_dicts(cur)
        return self._select_limited(cols, tail + " ORDER BY d.DeploymentID DESC", limit)

    def deployment_by_id(self, deployment_id: int) -> dict | None:
        """按主键取一条发布记录（删除包时要用它回填 DeployStatus）。找不到返回 None。"""
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(f"SELECT * FROM ModelDeployments WHERE DeploymentID = {self.placeholder}",
                        (deployment_id,))
            rows = self._rows_to_dicts(cur)
        return rows[0] if rows else None

    def mark_deployment_deleted(self, deployed_path: str | None) -> int:
        """把一个发布包的记录标成「已删除」（按 DeployedPath 匹配），返回受影响行数。

        只改状态、**不删记录**：发布流水要留痕——包被删了，但"曾经发布过 v1"是历史事实，
        删记录会让审计链断掉。
        ⚠️ 库里的 DeployedPath 存的是**相对路径**（响应脱敏后的口径），而调用方手里是绝对路径，
        所以只用**文件名**匹配，避免因盘符/前缀写法不同而匹配不上。
        """
        if not deployed_path:
            return 0
        self.ensure_schema()
        tail = str(deployed_path).replace("\\", "/").split("/")[-1]   # 只用文件名匹配
        with self.cursor(commit=True) as cur:
            cur.execute(
                f"UPDATE ModelDeployments SET DeployStatus = {self.placeholder}, IsCurrent = 0 "
                f"WHERE DeployedPath LIKE {self.placeholder}", ("已删除", f"%{tail}"))
            return max(cur.rowcount, 0)

    # ------------------------------------------------------------------ 读取
    def _rows_to_dicts(self, cur) -> list[dict]:
        """把游标里剩下的行读成 [{列名: 值}]，每个值都过一遍 _jsonable。

        列名直接取 cursor.description（=SELECT 里的实际列名），所以什么 SQL 都能用这一个函数收口。
        ⚠️ 过 _jsonable 不是可选项：pymysql 会把 DATETIME 读成 datetime、DECIMAL 读成 Decimal、
        BLOB 读成 bytes，原样丢给 Flask 的 jsonify 会抛
        "Object of type datetime is not JSON serializable" —— /trainings 曾经 500 就是漏了这一步。
        """
        cols = [d[0] for d in cur.description]
        return [{c: _jsonable(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
    def _select_limited(self, cols: str, tail: str, limit: int) -> list[dict]:
        """`SELECT <cols> <tail> LIMIT <n>` 的共用收口（recent_trainings 等三处同构）。

        这三处的差别只有"选哪些列 / JOIN 谁 / 按什么排序"，前后几行一字不差地重复了三遍。
        ⚠️ LIMIT 是 f-string 拼**数字**不是占位符（LIMIT 后只能跟字面量），安全性靠这里
        int() 再强转一道；cols / tail 是各方法写死的字面量，没有外部输入。
        """
        self.ensure_schema()
        # ⚠️ SQL 必须在进 cursor 之前算好：`int(limit)` 转不动时要像以前一样"还没连库就抛"。
        #    写进 with 里面的话，库连不上时抛的会是 DBUnavailable（上层映射 503），
        #    而不是原来的 ValueError/TypeError —— 异常类型被换掉了。
        sql = f"SELECT {cols} {tail} LIMIT {int(limit)}"
        with self.cursor() as cur:
            cur.execute(sql)
            return self._rows_to_dicts(cur)
    def latest_training(self, model_name: str | None = None, only_success: bool = True) -> dict | None:
        """取最近一次训练——它同时是推理任务的外键锚点（TrainingID）。

        only_success=True 是默认值，也是这套设计的要害：**失败的训练没有可用权重**，
        拿它当锚点会推理出一个"路径指向不存在的文件"的任务；所以默认只在 Status='成功' 里挑。
        排序按 TrainingID DESC（自增主键即时间序，比按日期列排更稳，不受时钟回拨影响）。
        传 model_name 就只在该模型内挑；两者都没配到时返回 None，由调用方决定报错还是降级。
        """
        self.ensure_schema()
        sql = ("SELECT t.TrainingID, t.ModelID, t.DatasetID, t.TrainName, t.Accuracy, t.Loss, t.ModelPath, "
               "t.Status, t.CreatedDate, m.ModelName "
               "FROM Trainings t JOIN Models m ON m.ModelID = t.ModelID WHERE 1 = 1")
        params: list = []
        if model_name:
            sql += f" AND m.ModelName = {self.placeholder}"
            params.append(model_name)
        if only_success:
            sql += f" AND t.Status = {self.placeholder}"
            params.append("成功")
        sql += " ORDER BY t.TrainingID DESC"
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = self._rows_to_dicts(cur)
        return rows[0] if rows else None
    def training_by_id(self, training_id: int) -> dict | None:
        """按主键取一次训练（显式传 training_id 做推理锚点时会用到）。

        `SELECT *` 是有意的：调用方（推理侧要读 ModelPath/Status/模型类型）需要整行，
        多查几列比再补一个"挑列"的参数简单；这里的行宽很小，不值得为省流量牺牲通用性。
        找不到返回 None，不抛异常——"训练记录不存在"在接口层是要转成 404 的业务事实。
        """
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(f"SELECT * FROM Trainings WHERE TrainingID = {self.placeholder}", (training_id,))
            rows = self._rows_to_dicts(cur)
        return rows[0] if rows else None
    def recent_trainings(self, limit: int = 20) -> list[dict]:
        """最近的训练记录（带模型名、数据集名，供列表页直接显示）。

        ⚠️ 两个 JOIN 都必须是 LEFT：DatasetID 可空（数据集被删时置空），
        INNER JOIN 会让这些训练整条从列表里消失。
        """
        return self._select_limited(
            "t.TrainingID, t.TrainName, t.Epochs, t.BatchSize, t.Accuracy, t.Loss, t.Status, t.ModelPath, "
            "t.StartedDate, t.CompletedDate, t.CreatedDate, m.ModelName, d.DatasetName",
            "FROM Trainings t LEFT JOIN Models m ON m.ModelID = t.ModelID "
            "LEFT JOIN Datasets d ON d.DatasetID = t.DatasetID ORDER BY t.TrainingID DESC",
            limit)
    def recent_inference_tasks(self, limit: int = 20) -> list[dict]:
        """最近的推理任务（带模型名，供列表页直接显示）。

        ⚠️ 同 recent_trainings：LEFT JOIN ModelName 是必要的——上传/占位模型可能不在 Models 里，
        INNER JOIN 会让这些任务凭空消失。
        """
        return self._select_limited(
            "k.InferenceTaskID, k.TaskName, k.TaskType, k.Status, k.Progress, k.TrainingID, "
            "k.TargetDatasetID, k.ResultSummary, k.CreatedDate, k.CompletedDate, m.ModelName",
            "FROM InferenceTasks k LEFT JOIN Models m ON m.ModelID = k.ModelID "
            "ORDER BY k.InferenceTaskID DESC",
            limit)
    def inference_task(self, task_id: int) -> dict | None:
        """取一个推理任务及其全部结果明细（明细挂在返回值的 results 里）。

        任务行与明细行分成两条 SELECT，然后手工把 results 挂进 tasks[0]，而不是 JOIN 成一张宽表：
        JOIN 会把任务行按明细行数复制一遍，还得在 Python 里去重。
        ⚠️ 一次把该任务的**全部结果行**返回，没有分页也没有 LIMIT——几千个窗口就是几千行 JSON，
        明细页会明显变慢；要支持大任务得在这里加 offset/limit 并让接口透传。
        任务不存在返回 None（接口层转 404），明细为空就是 results: []，不额外报错。
        """
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(f"SELECT * FROM InferenceTasks WHERE InferenceTaskID = {self.placeholder}", (task_id,))
            tasks = self._rows_to_dicts(cur)
            if not tasks:
                return None
            # 明细可能很多行，按 ResultID 排序保证点开顺序稳定
            cur.execute(f"SELECT * FROM InferenceResults WHERE InferenceTaskID = {self.placeholder} ORDER BY ResultID",
                        (task_id,))
            tasks[0]["results"] = self._rows_to_dicts(cur)
        return tasks[0]
    def models_in_db(self) -> list[dict]:
        """Models 表的全部登记行（供模型清单与「系统管理→数据库」页读）。

        这里**不加 LIMIT**：模型是人工登记的小表（种子数据只有 3 行），清单页必须能看全，
        被截断反而会让人以为模型丢了。行数大的是 Trainings / InferenceResults，不在这个函数里。
        """
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute("SELECT ModelID, ModelName, Description, ApiEndpoint, ModelType, Status, IsActive "
                        "FROM Models ORDER BY ModelID")
            return self._rows_to_dicts(cur)
    def datasets_in_db(self, limit: int = 200) -> list[dict]:
        """Datasets 表登记的数据集（供「数据集管理」页读）。

        ⚠️ 默认 limit=200 是硬上限：第 200 条之后的数据集在这个接口上"查不到"，
        页面看起来像数据丢了（实际在库里）。要翻页得由调用方显式传更大的 limit。
        """
        return self._select_limited(
            "DatasetID, DatasetName, Source, SampleCount, ClassCount, DataPath, Description, CreatedDate",
            "FROM Datasets ORDER BY DatasetID",
            limit)
    def register_dataset(self, **kwargs) -> dict:
        """登记数据集，并告知是新建还是已存在（供 POST /datasets/db）。

        先单独 SELECT 一次只为了拿到 already_existed 这个事实：ensure_dataset 本身是幂等的，
        但它只说"ID 是多少"，不区分"这次真建了"还是"本来就有"——前端要靠这个提示用户。
        ⚠️ 探测查询外面套了 try/except 并把 existed 当 False：探测失败时不能连带把登记也搞失败，
        宁可少一个提示，也不能让"登记数据集"这个主操作断在半路。
        """
        name = kwargs.get("name")
        existed = False
        self.ensure_schema()
        try:
            with self.cursor() as cur:
                existed = self._find_id(cur, "Datasets", "DatasetID", "DatasetName", name) is not None
        except Exception:
            existed = False        # 探测失败只丢一个提示，绝不能让"登记"这个主操作跟着失败
        dataset_id = self.ensure_dataset(
            name=name, source=kwargs.get("source"), sample_count=kwargs.get("sample_count"),
            class_count=kwargs.get("class_count"), data_path=kwargs.get("data_path"),
            description=kwargs.get("description"))
        return {"DatasetID": dataset_id, "already_existed": existed, "DatasetName": name}
    # ------------------------------------------------------ 模型 CRUD
    # 可被 update_model 改的列白名单——SQL 里 set 的列名只能从这个元组来，
    # 外部传进来的键名一律不当列名用，否则就是一条"任意列名拼进 SQL"的注入面
    _MODEL_FIELDS = ("Description", "ModelType", "ApiEndpoint", "Status", "IsActive")
    # 改名时要一起改的"路径"列（表名 → 列名）：模型改名后磁盘目录跟着改名，
    # 库里这些列存的是旧目录下的绝对/相对路径，不一起换掉，列表页会显示成"产物丢失"
    _PATH_FIELDS = (("Trainings", ("ModelPath",)), ("InferenceTasks", ("InputPath", "OutputPath")),
                    ("ModelDeployments", ("DeployedPath", "DeployUrl")))
    def _count(self, cur, sql: str, params: tuple) -> int:
        """执行 COUNT(*) 取标量，把类型与空行两处兜底收在一处（引用统计要把 5 个 COUNT 逐个取出来）。

        统一 int(...) 转换：COUNT(*) 的返回类型随驱动而异（pymysql 给 int，别家可能给 Decimal），
        转一次就能免掉后面比较/相加时的类型意外。
        fetchone() 为 None 理论上不会发生（COUNT 必有行），兜底成 0 而不是抛异常。
        """
        cur.execute(sql, params)
        row = cur.fetchone()
        return int(row[0]) if row else 0
    def model_references(self, name: str) -> dict:
        """某模型被哪些表引用了多少行——删之前必须先看这个，否则外键会直接拒绝。

        逐表 COUNT 而不是一条 UNION：前端要按表逐项展示，一条 UNION 只能给出总数。
        ⚠️ 计数口径与 delete_model 的级联口径**不完全一致**：这里按 InferenceResults.ModelID 数，
        而 force 删除走的是"结果 ← 任务"的子查询。如果某条结果行的 ModelID 与它所属任务的 ModelID 不同，
        它既不会被级联删掉、又会在外键上挡住 Models 行的删除（表现为"计数说是 0、删却删不掉"）。
        模型名不存在时抛 DBError 而不是返回空引用——"不存在"和"存在但没人引用"必须能区分。
        """
        self.ensure_schema()
        with self.cursor() as cur:
            mid = self._find_id(cur, "Models", "ModelID", "ModelName", name)
            if mid is None:
                raise DBError(f"模型 {name} 不存在于 Models 表")
            refs = {}
            # 五张表的引用列都叫 ModelID，所以列名不随表变化，只有表名是变量
            for table in ("Trainings", "ModelInvocations", "ModelDeployments",
                          "InferenceTasks", "InferenceResults"):
                refs[table] = self._count(
                    cur, f"SELECT COUNT(*) FROM {table} WHERE ModelID = {self.placeholder}", (mid,))
            total = sum(refs.values())
            return {"ModelID": mid, "references": refs, "total": total, "deletable": total == 0}
    def model_exists(self, name: str) -> bool:
        """Models 表里有没有这个名字（改名查重、上传登记都会用）。

        只取主键判存在，不 SELECT *：调用方只关心 True/False，少读几列少一次反序列化。
        ⚠️ 比较交给 MySQL 做，判重结果受 ModelName 列的 collation 影响：本库是 utf8mb4_unicode_ci，
        **大小写不敏感**，所以 '1dcnn' 与 '1DCNN' 在这里算同名；名字统一走 db_model_name() 更省心。
        """
        self.ensure_schema()
        with self.cursor() as cur:
            return self._find_id(cur, "Models", "ModelID", "ModelName", name) is not None
    def rename_model_paths(self, old: str, new: str) -> dict:
        """模型改名后，把库里已存的**路径前缀**一起换掉（...\\models\\old\\... → ...\\models\\new\\...）。

        只动路径列：Trainings.ModelPath、InferenceTasks.InputPath/OutputPath、
        ModelDeployments.DeployedPath/DeployUrl（清单见 _PATH_FIELDS）。
        ⚠️ 为什么必须做：改名时 api._rename_model() 会把磁盘目录一并搬走，库里这些列存的还是旧目录名，
        不换掉就会出现"记录里指着一个已经不存在的路径"，列表页/明细页一致显示产物丢失。
        实现用 SQL 的 REPLACE() 就地改（两种分隔符各来一遍，兼容 Windows 反斜杠与 POSIX 斜杠），
        rowcount 是"被替换到的行数"，全 0 也不报错——本来就可能没有任何记录引用过旧路径。
        ⚠️ touched 的键固定用 cols[0]（该表首列名），而值是所有列累加的行数：
        键名只当"这张表动过"的标记看，不代表只有首列被改。
        """
        self.ensure_schema()
        pairs = ((f"\\models\\{old}\\", f"\\models\\{new}\\"), (f"/models/{old}/", f"/models/{new}/"))
        touched: dict[str, int] = {}
        with self.cursor(commit=True) as cur:
            for table, cols in self._PATH_FIELDS:
                hits = 0
                for col in cols:
                    for old_pat, new_pat in pairs:
                        cur.execute(f"UPDATE {table} SET {col} = REPLACE({col}, {self.placeholder}, {self.placeholder})",
                                    (old_pat, new_pat))
                        hits += max(cur.rowcount, 0)
                if hits:
                    touched[f"{table}.{cols[0]}"] = hits
        return touched
    def update_model(self, name: str, fields: dict, new_name: str | None = None) -> dict:
        """改 Models 表的登记信息（**不碰产物文件**）。

        改名：传 `new_name`，这里只负责「查重 + 改 ModelName」；
        磁盘上的产物目录要由 api._rename_model() 同步搬，两个动作必须成对调用
        （只改库 = 路径失联，只搬目录 = 名字对不上）。

        列名只能从 _MODEL_FIELDS 白名单来，值一律走占位符——这是防 SQL 注入的关键，别改成拼字符串。
        ⚠️ 值统一按 500 截断，比 Status(20)/ModelType(50) 的列宽宽，超长值这里拦不住，
        会由 MySQL 严格模式报 "Data too long"；换名字时才会先查重，避免直接撞唯一键报错。
        `sets` 为空时主动抛 DBError：静默成功会让调用方以为改生效了（rowcount==0 同理，判"不存在"）。
        """
        self.ensure_schema()
        # touched 是与 sets 平行的"改了哪些列"清单：以前是靠 `s.split(" =")[0]` 从拼好的 SQL 串里
        # 反推列名，一旦 SET 片段的写法稍变（比如改成 `col=?,`）就会悄悄取错；直接记下来更直白。
        sets, params, touched = [], [], []
        for col in self._MODEL_FIELDS:
            if col in fields and fields[col] is not None:
                touched.append(col)
                sets.append(f"{col} = {self.placeholder}")
                params.append(_clip(fields[col], 500))
        if new_name and new_name != name:
            if self.model_exists(new_name):
                raise DBError(f"模型名 {new_name} 已被占用，换一个")
            touched.append("ModelName")
            sets.append(f"ModelName = {self.placeholder}")
            params.append(_clip(new_name, 100))
        if not sets:
            raise DBError("没有可更新的字段（支持：" + ", ".join(self._MODEL_FIELDS)
                          + "，改名传 NewModelName）")
        params.append(name)
        with self.cursor(commit=True) as cur:
            cur.execute(f"UPDATE Models SET {', '.join(sets)} WHERE ModelName = {self.placeholder}", tuple(params))
            if cur.rowcount == 0:
                raise DBError(f"模型 {name} 不存在于 Models 表")
        return {"updated": name, "new_name": new_name or name, "fields": touched}
    def delete_model(self, name: str, force: bool = False) -> dict:
        """删 Models 表登记行。有引用时默认拒绝，force=True 才连带删除引用行。

        默认拒绝而不是默默级联：模型被训练/调用记录引用着，随手删掉会让历史明细全成孤儿。
        force 的删除顺序是**从子到父**（结果 → 任务 → 调用 → 发布 → 训练 → 模型），
        反了就会被外键约束当场拒绝。
        ⚠️ InferenceResults 没有直接的 ModelID 外键约束语义，只能经 InferenceTasks 的子查询间接删；
        子查询与 DELETE 写同一条语句里是有意的——分成两条会在中间留下"任务已删、结果还在"的窗口。
        """
        self.ensure_schema()
        refs = self.model_references(name)
        if refs["total"] and not force:
            raise DBError(f"模型 {name} 仍被引用（{refs['references']}），"
                          f"要么先清理这些记录，要么用 force=true 连带删除")
        mid = refs["ModelID"]
        with self.cursor(commit=True) as cur:
            if force:
                # InferenceResults 没有直接的 ModelID 外键约束语义，只能经由 InferenceTasks 的子查询间接删；
                # 所以它单独写一条（子查询与 DELETE 同句是有意的，见上面的 ⚠️），其余四张表单走同一个循环
                cur.execute(
                    "DELETE FROM InferenceResults WHERE InferenceTaskID IN "
                    f"(SELECT InferenceTaskID FROM InferenceTasks WHERE ModelID = {self.placeholder})", (mid,))
                for table in ("InferenceTasks", "ModelInvocations", "ModelDeployments", "Trainings"):
                    cur.execute(f"DELETE FROM {table} WHERE ModelID = {self.placeholder}", (mid,))
            cur.execute(f"DELETE FROM Models WHERE ModelID = {self.placeholder}", (mid,))
        return {"deleted": name, "cascaded": bool(force and refs["total"]), "references": refs["references"]}
    # 说明：原先这里还有 dataset_references / update_dataset / delete_dataset 三个方法
    # （对应 GET/PUT/DELETE /datasets/db/<id>）。三者全项目零调用——前端只在
    # api/platform/index.ts 里声明过 updateDataset/deleteDataset 两个方法，没有任何页面调它们，
    # 路由本身也从来只是"登记的补录入口"，所以整组一并删除。
    # 数据集登记的**写入**仍走 POST /datasets/db，对应下面的 ensure_dataset()。
    # -------------------------------------------------------------- 用户与角色
    def user_by_username(self, username: str) -> dict | None:
        """按用户名取一行（含 PasswordHash 与 TokenVersion）。

        ⚠️ 这个函数**会把密码哈希带出去**，只给 auth.py 的登录校验与
        authenticate() 用。任何要"返回给前端"的地方都必须走 auth.login_payload()，
        它对字段做了白名单，不会漏出哈希。
        """
        if not username:
            return None
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(f"SELECT * FROM Users WHERE Username = {self.placeholder}",
                        (username,))
            rows = self._rows_to_dicts(cur)
        return rows[0] if rows else None

    def user_by_id(self, user_id: int) -> dict | None:
        """按主键取一行。同样含哈希（供改密码用）。"""
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute(f"SELECT * FROM Users WHERE UserID = {self.placeholder}", (user_id,))
            rows = self._rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_users(self) -> list[dict]:
        """用户清单（**不含 PasswordHash**，这个结果会直接发给前端）。"""
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute("SELECT UserID, Username, DisplayName, RoleKey, DeptName, Email, "
                        "Mobile, IsActive, LastLogin, LoginCount, CreatedDate "
                        "FROM Users ORDER BY UserID")
            return self._rows_to_dicts(cur)

    def create_user(self, username: str, password_hash: str, role_key: str, *,
                    display_name: str | None = None, dept_name: str | None = None,
                    email: str | None = None, mobile: str | None = None) -> int:
        """新建用户，返回 UserID。用户名重复会抛 DBError（唯一键冲突）。

        ⚠️ 只收**已经哈希好**的密码：本层不做哈希，免得多一条"有人绕过哈希
        直接传明文"的路径。调用方必须用 auth.hash_password()。

        ⚠️ 必须在这里把 `pymysql.err.IntegrityError` 转成 DBError：
        Users 表有唯一键 UQ_Users_Username，重复插会抛 IntegrityError。
        而调用方 `dvadmin.user_create()` 只 `except DBError` —— 不转换的话
        异常会穿到顶层变成 **HTTP 500**，前端拿不到任何提示，
        用户看到的就是"点了新建什么反应都没有"。这类"约束冲突"是**预期内的业务失败**，
        必须以可读消息回给用户，而不是当成服务端故障。
        """
        self.ensure_schema()
        try:
            with self.cursor(commit=True) as cur:
                cur.execute(
                    f"INSERT INTO Users (Username, PasswordHash, DisplayName, RoleKey, DeptName, "
                    f"Email, Mobile, IsActive, TokenVersion, CreatedDate) VALUES "
                    f"({self.placeholder}, {self.placeholder}, {self.placeholder}, {self.placeholder}, "
                    f"{self.placeholder}, {self.placeholder}, {self.placeholder}, 1, 0, {self.placeholder})",
                    (username, password_hash, display_name or username, role_key, dept_name,
                     email, mobile, _now()))
                return int(cur.lastrowid)
        except _IntegrityError as exc:
            # 1062 = Duplicate entry。Users 表上唯一的唯一约束就是用户名
            if getattr(exc, "args", [None])[:1] == (1062,):
                raise DBError(f"用户名已存在：{username}") from exc
            raise DBError(f"新建用户失败：{exc}") from exc

    def set_user_password(self, user_id: int, password_hash: str) -> None:
        """改密码，并把 TokenVersion +1（让旧令牌立刻失效）。

        ⚠️ 两件事必须在**同一个 UPDATE** 里做。分开写的话，中间崩溃就会出现
        "密码改了但令牌没失效"，或者反过来"令牌失效了但密码没改成"——
        前者是安全问题（旧令牌还能用），后者是可用性问题（用户被锁在外面）。
        """
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            cur.execute(
                f"UPDATE Users SET PasswordHash = {self.placeholder}, "
                f"TokenVersion = COALESCE(TokenVersion, 0) + 1, UpdatedDate = {self.placeholder} "
                f"WHERE UserID = {self.placeholder}",
                (password_hash, _now(), user_id))

    def update_user(self, user_id: int, fields: dict) -> int:
        """改用户的可编辑字段（角色/启停/显示名等）。返回受影响行数。

        白名单式写入：只认下面这几个键，别的键静默忽略。
        ⚠️ 刻意**不允许**从这里改 Username 与 PasswordHash：
        用户名是令牌载荷里的身份键，改了会让存量令牌全部对不上；
        密码必须走 set_user_password() 才能保证 TokenVersion 一起递增。
        """
        allowed = ("DisplayName", "RoleKey", "DeptName", "Email", "Mobile", "IsActive")
        sets, params = [], []
        for key in allowed:
            if key in fields:
                sets.append(f"{key} = {self.placeholder}")
                params.append(fields[key])
        if not sets:
            return 0
        sets.append(f"UpdatedDate = {self.placeholder}")
        params.append(_now())
        params.append(user_id)
        self.ensure_schema()
        with self.cursor(commit=True) as cur:
            cur.execute(f"UPDATE Users SET {', '.join(sets)} WHERE UserID = {self.placeholder}",
                        tuple(params))
            return cur.rowcount

    def touch_login(self, user_id: int) -> None:
        """记录一次成功登录（LastLogin + LoginCount++）。

        ⚠️ 用 `LoginCount = COALESCE(LoginCount, 0) + 1` 而不是在 Python 里读出来加一：
        并发登录时读-改-写会丢计数，交给数据库做自增才准。
        失败**不抛异常**——登录已经成功了，更新统计失败不该让人登不进来。
        """
        try:
            with self.cursor(commit=True) as cur:
                cur.execute(
                    f"UPDATE Users SET LastLogin = {self.placeholder}, "
                    f"LoginCount = COALESCE(LoginCount, 0) + 1 WHERE UserID = {self.placeholder}",
                    (_now(), user_id))
        except Exception:
            pass

    def roles_in_db(self) -> list[dict]:
        """角色清单（Roles 表；空表时返回空，由调用方兜底代码里的默认三个）。"""
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute("SELECT RoleID, RoleKey, RoleName, Description, IsActive "
                        "FROM Roles ORDER BY RoleID")
            return self._rows_to_dicts(cur)

    def count_users(self) -> int:
        """用户数量。用来判断"是否还没初始化过账号"（决定要不要种种子用户）。"""
        self.ensure_schema()
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM Users")
            return int(cur.fetchone()[0])

    def bootstrap_users(self, admin_password_hash: str, *, with_samples: bool = True) -> int:
        """首次启动时造种子账号。**只在 Users 表为空时**才插，返回插了几行。

        ⚠️ 为什么不在 sql/schema_mysql.sql 里写 INSERT IGNORE 种子用户：
        那样每个部署都会拿到**同一个密码哈希**，等于全网一个密码；而且脚本是幂等的，
        想改密码还得手工 UPDATE。放在这里就能用配置里的口令现算哈希，
        每台机器各自独立。
        ⚠️ with_samples=False 时只建 admin：工厂交付时不该留着一堆默认口令的演示账号。
        """
        if self.count_users() > 0:
            return 0
        from .auth import ROLE_ADMIN, ROLE_ENGINEER, ROLE_OPERATOR, hash_password, role_name_of
        seeded = [("admin", admin_password_hash, ROLE_ADMIN, "系统管理员")]
        if with_samples:
            # 演示账号口令是固定的，**部署到工厂前应当删掉或改密**。
            # 用与 admin 不同的口令，避免"一个密码开所有门"。
            seeded = [
                ("admin", admin_password_hash, ROLE_ADMIN, "系统管理员"),
                ("engineer", hash_password("Engineer@2026"), ROLE_ENGINEER, "算法工程师"),
                ("operator", hash_password("Operator@2026"), ROLE_OPERATOR, "现场操作员"),
            ]
        n = 0
        for username, pwd_hash, role_key, display in seeded:
            try:
                self.create_user(username, pwd_hash, role_key,
                                 display_name=display, dept_name="模型管理平台")
                n += 1
            except Exception:
                # 并发启动时另一个线程可能已经插进去了（唯一键冲突），忽略继续
                continue
        # 角色表也补上，供「用户管理」页展示
        try:
            with self.cursor(commit=True) as cur:
                for key in (ROLE_ADMIN, ROLE_ENGINEER, ROLE_OPERATOR):
                    cur.execute(
                        f"INSERT IGNORE INTO Roles (RoleKey, RoleName, IsActive, CreatedDate) "
                        f"VALUES ({self.placeholder}, {self.placeholder}, 1, {self.placeholder})",
                        (key, role_name_of(key), _now()))
        except Exception:
            pass
        return n

    # -------------------------------------------------------------- 操作日志
    def log_operation(self, *, username: str | None, role_key: str | None, action: str,
                      target: str | None = None, detail=None, client_ip: str | None = None,
                      result: str = "成功", message: str | None = None) -> None:
        """写一条操作日志。**任何失败都不抛异常**（记日志是旁路，不能拖垮主流程）。

        调用方已经有一层 try/except，这里再兜一层：本函数的调用点散布在
        api.py 各处，漏包一处就会让"删除成功但日志写失败"变成 500。
        """
        try:
            with self.cursor(commit=True) as cur:
                cur.execute(
                    f"INSERT INTO OperationLogs (Username, RoleKey, Action, Target, Detail, "
                    f"ClientIP, Result, Message, CreatedDate) VALUES "
                    f"({self.placeholder}, {self.placeholder}, {self.placeholder}, {self.placeholder}, "
                    f"{self.placeholder}, {self.placeholder}, {self.placeholder}, {self.placeholder}, "
                    f"{self.placeholder})",
                    (username, role_key, _clip(action, 50), _clip(target, 200),
                     _dump_json(detail), _clip(client_ip, 45), _clip(result, 20),
                     _clip(message, 500), _now()))
        except Exception:
            pass

    def recent_logs(self, limit: int = 100) -> list[dict]:
        """最近的操作日志（新的在前）。

        ⚠️ `Detail` **必须在列清单里**。它曾经被漏掉：写入侧（log_operation 的 detail=…）
        一直在正常落库，但查询侧不 SELECT 这一列，于是「谁把模型删了、覆盖上传换掉了什么」
        这些关键信息**查得到日志、看不到内容**——审计等于白记。
        前端日志页要展示操作对象详情，也依赖这一列。
        Detail 是 _dump_json() 存进去的 JSON **字符串**，不是对象；读出来就是 str，
        调用方要自己 json.loads()（保留字符串是刻意的：列类型是 LONGTEXT，
        直接回原串可以避免 db 层因为一段坏 JSON 把整个日志列表打成 500）。
        """
        return self._select_limited(
            "LogID, Username, RoleKey, Action, Target, Detail, ClientIP, Result, Message, CreatedDate",
            "FROM OperationLogs ORDER BY LogID DESC",
            limit)

    def table_counts(self, max_age: float = 30.0) -> dict:
        """8 张表的行数。**带 30 秒缓存**——/health 与 /system 每次都要它，而 8 条 COUNT(*) 在
        MySQL 上不算便宜（之前每个请求都真跑一遍，是页面跳转慢的一个来源）。

        失效方式只有一种：时间到期（`now - at >= max_age`）后下次调用重算，**写入路径不会主动失效**，
        ⚠️ 所以刚写完一次训练，30 秒内的 /health 行数仍可能是旧值——这是有意用"短暂陈旧"换请求延迟，
        要立刻刷新就显式传 max_age=0。
        返回的是 `dict(...)` 浅拷贝：调用方随便改都不会污染缓存（8 个 int 的浅拷贝足够，不需要深拷贝）。
        cache 里连 `at` 一起换掉（整体赋值）而不是分两步改，避免出现"新数据配旧时间戳"的中间态。
        """
        now = time.time()
        if self._counts_cache["data"] is not None and now - self._counts_cache["at"] < max_age:
            return dict(self._counts_cache["data"])
        self.ensure_schema()
        out: dict[str, int] = {}
        with self.cursor() as cur:
            for table in ("Datasets", "Models", "Trainings", "ModelInvocations",
                          "ModelDeployments", "InferenceTasks", "InferenceResults", "EdgeDevices",
                          "Users", "OperationLogs"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                out[table] = int(cur.fetchone()[0])
        self._counts_cache = {"at": now, "data": out}
        return dict(out)
database = Database()

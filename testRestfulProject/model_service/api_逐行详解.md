# api.py 逐行详解

> 对应文件：`testRestfulProject/model_service/api.py`（本文基准版 `e361fa6` 共 1604 行；当前 `06a8fb8` 为 1649 行，见下方「行号基准」）
> 本文按**行号**逐行解释：每一行都有对应的条目，相邻且属于同一逻辑的行合并为一条（写在
> 一个区间里），但**没有任何一行被跳过**。行号与当前文件一一对应，改动代码后请重新生成。

> ## ⚠️ 行号基准（2026-09-18 补记）
>
> 本文写于提交 `e361fa6`，当时 api.py 是 **1604 行**。此后提交 **`06a8fb8`** 修掉了本文
> 列出的 **5 个问题**（落在后端 7 处代码位点 + 前端 4 处文案），**净增 45 行**（现 **1649 行**）。
> 本文已把那几处的正文改写成当前实现口径并标注了新行号，**其余的行号引用一律仍是
> `e361fa6` 的旧编号**（文末有精确换算表，一眼可换算）。之所以不整体重排：文中大量出现
> `784`、`500`、`1500` 这类**数据字面量**，与行号混在一句话里，机器批量加偏移会把字面量一起改错。
>
> 改动位点（旧行号 → 新行号）：
>
> | 改动 | 旧 | 新 |
> | --- | --- | --- |
> | `_PACKAGES` 去掉 pyodbc/pywin32/python-docx | 44–46 | 44–48 |
> | 新增 `_PICKLE_MAX_OPS` | — | 49–50 |
> | `_HEAD_LAYER_RE` 加词边界 | 60–61 | 65–72 |
> | `probe_weight` docstring 按实现重写 | 158–159 | 169–181 |
> | 后缀不支持时的 reason 补 `.pt2` | 168 | 190–191 |
> | `.pkl` 判据改成`pickletools` 操作码校验 | 278–282 | 301–325 |
> | 上传两处文案补 `.pt2` | 1012 / 1032 | 1055–1056 / 1076–1077 |

## 怎么用这份文档

1. 先看下面的目录，找到你关心的模块，再去对应小节；
2. 每节的格式是：`作用` 一句话 → 逐行条目（`- **行号** 代码 — 解释`）；
3. 标了 `⚠️ 存疑` 的地方是写这份文档时**发现的可疑点**（注释与代码不符、恒真分支、
   未捕获的异常等），值得单独确认；
4. 文件本身的中文注释已经写得很密，所以本文**刻意不复述注释**，重点是解释代码实际做了什么。

---

# 第 1 段 · 行 1–289

> 范围：`testRestfulProject/model_service/api.py` 第 1–289 行（模块 docstring / imports / 模块级常量 /
> `_keras_shapes` / `_exported_input_len` / `probe_weight`）。行号均为文件真实行号，范围连续、无跳行。
> 骨架里写的「docstring 1–21 / imports 23–41」略有偏差：**22 行**才是三引号的收尾、**42 行**是最后一条
> import（`from .training import ...`），所以下面按 **1–22 / 23–42** 分段，避免漏行。
> 涉及外部符号时已实际读过 `config.py` / `registry.py` / `training.py` / `inference.py` / `figures.py` /
> `datasets.py` / `tabular.py` 核对，未凭猜测。

## 行 1–22 · 模块 docstring

- **1** `# -*- coding: utf-8 -*-` — 源码编码声明；Python 3 默认已是 UTF-8，这行只对老编辑器/工具链有意义，但文件里中文注释与中文文案极多，保留无副作用。
- **2** 第一行 `"""flask_restful 接口资源（流程图里的「Web访问」盒子）。` — 定位本模块职责：它只做 HTTP↔业务函数的翻译，真正的训练/推理/落盘分别在 `training` / `inference` / `registry`。
- **4–7** 核心声明：**不许再手抄路由表**，唯一权威是 `register_api()`，运行期可看 `GET /api`（ApiIndex）。核对 `_ROUTES`（1464–1489）→ `register_api`（1514–1517）→ `api.add_resource(resource, *paths)`，以及 `_route_index()`（1497–1513）由同一张表生成索引，这段说法成立。
- **6–7** 提到「ApiIndex 的键与 register_api 一一对应，也是前端接口索引页的数据源」 — 对应 `_route_index()` 直接用 `_ROUTES` 生成 `{路径: 用途}`，所以**改 `_ROUTES` 就等于同时改路由与索引**，这条约定是有代码兜底的，不是口号。
- **9–19** 按用途列出的四组（实际排了 6 个小标题行）路由清单。**⚠️ 存疑**：这本身又是"手抄清单"，且已经漂了 —— 表里真实存在 `GET /api`、`PUT /models/<model_name>`（改名，见 887 行 `def put`）、`GET /system/logs/<name>`、`GET /` 都没列；第 4 行说 `register_api` 曾注册 27 条，而现在 `_ROUTES` 只有 **24 个资源 / 25 条 URL 规则**（`Console`、`DatasetRecord` 已按 1490–1493 的注释删掉）。数字与清单都属历史残留，别当权威用。
- **21** 约定「任何失败都返回 `{"error": ...}` + 合适状态码，细节写进 ModelInvocations」 — 与代码一致：400/404/409/503/500 各分支都回 `{"error": ...}`；推理失败路径由 `_log_failed_inference`（615）写 `ModelInvocations`，且它刻意只写库、不吞原始异常（648）。
- **22** `"""` — docstring 收尾。
- **3**（空行） — 分段空行（2 与 4 之间），无代码语义。
- **8**（空行） — 分段空行（7 与 9 之间），无代码语义。
- **20**（空行） — 分段空行（19 与 21 之间），无代码语义。三处空行只把 docstring 分成"定位 / 权威清单提醒 / 路由分组 / 约定"四段。

## 行 23–42 · imports

- **23** `from __future__ import annotations` — 让所有注解**延迟求值**：本文件大量写 `int | None`、`dict[str, str]`、`Path | str` 这类新式写法，在 Python 3.9 及以下运行时也不会在 import 期求值报错。运行期行为无变化（`typing.get_type_hints` 之外没人解析这些注解）。
- **24** `import json` — 只做两件事：`json.loads` 解析**模型自带的**结构文件（187 读 Keras zip 里的 `config.json`、204 读 HDF5 的 `model_config` 属性、776 读已有 `meta.json`、1124 读用户上传的 `meta.json`），以及 `json.dumps(..., ensure_ascii=False, indent=2)` 写产物 `meta.json`（781、1043）。接口响应体由 flask_restful 自己序列化，**不走**这里的 json。
- **25** `import platform` — 唯一用途是 `GET /system` 的 runtime 块（1391）：`platform.platform()`（如 `Windows-10-...`）与 `platform.machine()`（`AMD64`）。别处没有任何调用。
- **26** `import re` — 三处 `re.compile` 常量（43 的 `_ANSI`、61 的 `_HEAD_LAYER_RE`、1528 的 `_DRIVE_RE`）+ 两处运行期 `re.sub`（316 把模型/数据集名里的非法字符替换成 `_`、1506 去掉 docstring 首行的 `GET /xxx —— ` 前缀）。
- **27** `import sys` — 唯一用途在 `GET /system`（1390）：`sys.version.split()[0]` 取 Python 版本号、`sys.executable` 取解释器路径。注意这个文件**不**用 `sys.path`（那是 `training._import_project_module` 干的）。
- **28** `import traceback` — 唯一用途在 `Predict.post` 的兜底 `except Exception`（699–701）：把 `traceback.format_exc()[-1500:]` 截尾后塞进 500 响应，方便前端直接显示（正常参数错走 400，不给 traceback）。
- **29** `from datetime import datetime` — 只 import 了类本身（没用 `date`/`timedelta`），用在两处：生成上传产物的 `uploaded_at`（1153 `datetime.now().isoformat(timespec="seconds")`）与日志文件列表的 `modified`（1414 `datetime.fromtimestamp(...)`）。
- **30** `from importlib.metadata import PackageNotFoundError, version` — 给 `GET /system` 里的 `dist_version()`（1368–1375）用：`version(name)` 查已安装包版本，`PackageNotFoundError` 表示"没装"→ 返回 `None`（前端显示"未安装"），其余异常退化成字符串 `"读取失败"`，绝不让 `/system` 500。
- **31** `from pathlib import Path` — 四处主力用途：取后缀/文件名（163、458、464–465、1097–1100）、解析并校验工作区路径（327–339 `_resolve_workspace_path`）、产物目录换算（800、837 改名时的 `config.model_dir / key`）、以及防路径穿越的二次清洗（1314、1420 `Path(name).name != name`）。
- **32** 注释「`Response` / `redirect` 已随零构建控制台（console.html + GET /ui）一起删掉，如无新用途别再 import」 — 与 1230–1232 的删除记录一致；这行是"反向说明"，提醒后来者别顺手把 `Response` 加回来（要返回文件现在走 `send_from_directory`）。
- **33** `from flask import request, send_from_directory` — `request` 是全局代理对象，贯穿所有 Resource：`request.get_json(silent=True)`（296 即 `_body()`）、`request.form`（453/999/1138）、`request.args`（499/513/603/1207）、`request.files`（1084）、`request.remote_addr`（688/693）。`send_from_directory` 只在 `FigureFile.get`（1229）用一次，负责发 PNG 并自带 `safe_join` 穿越防护。
- **34** `from flask_restful import Resource` — 本文件 340–1434 行之间全部 **24 个资源类**的基类；flask_restful 靠同名 HTTP 方法（`get`/`post`/`put`/`delete`）分发，所以 `/models` 能由 `ModelList`(GET) 与 `ModelCreate`(POST) 两个类共存。
- **35** `from . import datasets as ds` — `datasets` 模块起别名 `ds`（避免与本地变量/`datasets` 路由概念混淆）。四处使用：`ds.describe_dataset(path)`（413，`GET /datasets` 里逐个内置 .mat 目录体检）、`ds.CWRU_0HP_CLASSES`（1142 按类别号排序造 10 个标签、1341 由文件名反查标签与类别号）、`ds.read_de_channel(path)`（1338 取一段 DE 通道信号画波形）、`ds.guess_label(path.name)`（1342 兜底标签）。
- **36** `from . import tabular` — 表格(Excel/CSV)数据集能力，六处使用：`TABLE_SUFFIXES`（465 校验上传文件、467/510 拼"支持哪些格式"的提示）、`describe_directory`（439/487 列数据集概要 → 注意它带 120 秒 TTL 缓存，所以上传后 485 行显式 `cache_clear()`）、`label_from_filename`（482/1332 文件名当标签）、`is_table`（509/1329 判断能否预览）、`preview`（513 表格预览）、`read_signal`（1331 取信号列画波形）。
- **37** `from .config import config` — 全局配置单例（`config.py` 末尾 `config = Config()`）。用到的属性：`workspace_dir`/`project_dir`（330/334、562–567 路径解析与越界校验）、`model_dir`（800/837 改名搬目录）、`upload_dir`（429/460、1300–1303 上传数据集目录，并判 `is_dir()` 兜目录被删）、`dataset_dirs`（411/1295–1297 内置数据集名→真实目录）、`log_dir`（1380/1410/1422 训练日志）、以及方法 `describe()`（365/1393 给 `/health`、`/system` 的路径快照，**刻意不含密码**）。
- **38** `from .db import DBError, database` — `DBError` 是本文件所有库异常的**唯一边界**，被 13 处 `except DBError` 捕获并映射成业务语义（390/608/813/854/883/919/961/1055/1177/1196/1248/1264 等，如"库挂了 → 503"、"名字冲突 → 409"）；`database` 是唯一库访问入口，用到的方法有 `ping`/`models_in_db`/`recent_trainings`/`latest_training`/`insert_invocation`/`inference_task`/`ensure_model`/`update_model`/`delete_model`/`model_exists`/`model_references`/`rename_model_paths`/`register_dataset`/`datasets_in_db`/`table_counts`/`recent_inference_tasks` 以及属性 `dialect`/`last_bootstrap`。
- **39** `from .figures import FIG_DIR, clear_figures, list_figures` — `FIG_DIR` 是图库磁盘根，既当 `/figures/<path:relpath>` 的发送根（1229，穿越防护交给 `send_from_directory` 的 `safe_join`），也当 `/health`、`/system` 里的 `"dir"`（372、1401）；`list_figures` 列图（372 `limit=1000`、1214 `limit=500` —— 1211 注释解释了为什么要比请求的 limit 多取再过滤）；`clear_figures` 是 `POST /system/maintenance` 目前唯一的动作（1443）。
- **40** `from .inference import InvalidInput, predict` — `InvalidInput` 是 `inference.py:27` 定义的 `ValueError` 子类；本文件既**抛**它（309/339/535/539/546/548/664/670/674/677/761/763/806/880）也**捕**它转 400（515、604、1208），并且常常只写 `except ValueError`（697、885、921）——因为子类会被一起接住（注释里点明了这一层）。`predict` 只被 `Predict.post` 调用一次（679–691），把校验过的参数翻译成一次推理并返回给前端的整份 payload。
- **41** `from .registry import abort_artifact, begin_artifact, commit_artifact, delete_artifact, list_artifacts, load_artifact` — 产物层 API：`begin_artifact`→`commit_artifact`/`abort_artifact` 是上传的"暂存-提交"三步（1035 开暂存、1044 提交、1046 失败只删暂存），保证一次失败的上传不会毁掉上一份好产物；`load_artifact` 读某模型产物的 meta（862，抛 `FileNotFoundError` → 404）；`list_artifacts` 列产物（362 `/health`、387 `/models`、946 `/models/<name>/overview`、1378 `/system` 占用统计）；`delete_artifact` 对应 `DELETE /models/<名>?scope=artifact`（876）。
- **42** `from .training import MODEL_META, ALIASES, normalize_model, train` — `MODEL_META` 是「内部键 → 库名/描述/类型」表（398 作为 `known_models` 发给前端、752 由库名反查内部键、824 决定改名后是否提示"重训"）；`ALIASES` 提供接口别名（350 `GET /api` 里 `sorted(set(ALIASES.values()))` 得到可选模型名）；`normalize_model` 把用户写的别名/大小写/中文规范化成内部键（532 `/train`、742 `_db_model_name`，认不出会抛 `ValueError` → 400）；`train` 是训练实现（580，同步阻塞，`/train` 因此耗时且不能并发压）。

## 行 43–61 · 模块级常量

- **43** `_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")` — 匹配 CSI 形态的 ANSI 转义序列（Keras 训练进度条会往 stdout 吐 `\x1b[K`、`\x1b[1m` 之类，被重定向进训练日志）。唯一使用点是 `SystemLogFile.get`（1430）`_ANSI.sub("", ln)`：日志按 `encoding="utf-8", errors="replace"` 读出来后在浏览器里显示，不剥掉就是乱码。
- **44–46**（**今 44–48 行；`06a8fb8` 已改**）`_PACKAGES = ("numpy", ..., "torch")` — `/system` 依赖版本表的**白名单**（1392 `{name: dist_version(name) for name in _PACKAGES}`）。写成元组常量而不是内联列表，是为了让它成为"本服务关心的包"的唯一清单；注意里面同时列了 `tensorflow`/`tf-nightly`、`keras`/`keras-nightly`，未安装的项会被 `dist_version` 变成 `None`。**改动**：删掉了 `pyodbc`、`pywin32`、`python-docx` —— 全项目零引用（SQL Server 分支早已删除），列在"依赖版本"里只会让人误以为平台依赖它们；`requirements.txt` 是 `pip freeze` 的整体快照，不等于依赖清单，所以只清理这张展示表。名字数从 17 变成 **14**。
- **49–50**（新增）`_PICKLE_MAX_OPS = 20000` — `.pkl` 校验时最多解码多少个 pickle 操作码。为什么需要封顶：解码操作码是纯 Python，实测真 adtk 产物（610 个操作码）只要 0.37 ms，但"20 万个小键的 dict"这种畸形 2.7 MB 文件要解 60 万个操作码 / 358 ms，足以拖住一个工作线程。超限时判据退化为"前缀合法即放过"（宁可宽松，也不为畸形大文件卡住请求）。
- **47** `MAX_EPOCHS = 200` — `/train` 的 `epochs` 上界（534–535：`1 <= epochs <= MAX_EPOCHS`，超出抛 `InvalidInput` → 400）。注释说"防止一条 HTTP 请求把服务占住几小时"，因为训练是同步阻塞的。
- **48** `MAX_LIMIT = 500` — `POST /predict` 的 `limit`（窗口数）上界（669–670）。与 `/figures` 那类接口里硬编码的 `200`/`500` 是两套数字，改这里不会影响它们。
- **49–51** 三条注释 — 交代探测功能的设计前提：「上传时不要求用户填 input_len/类别数，先按扩展名分类，再打开文件看内容」。这就是 `probe_weight` 的存在理由，也解释了为什么它的失败态是 `ok=False` + 人话 `reason`（前端逐条展示）而不是抛异常。
- **52–56** `WEIGHT_SUFFIXES = {...}` — 后缀 → 框架名的**第一层分类**（粗筛）。两个使用点：`probe_weight` 的开头闸门（164）与 `ModelUpload` 的 `_upload_blobs(..., WEIGHT_SUFFIXES, ...)`（1009 当作 `weight_whitelist` 挑候选）。它的**值**必须与 `inference._DISPATCH` 的键一致（`tensorflow-keras`/`pytorch`/`pytorch-exported`/`adtk`，见 inference.py:336–338），而 `pytorch-jit` 只在内容探测后才可能出现（232）。
- **57–59** `KEEP_SUFFIXES = {...}` — 上传**文件夹**时"允许落盘"的附件白名单（1009 传给 `_upload_blobs` 的 `keep_suffix`），比权重白名单宽得多：允许 `scaler.npz`、`meta.json`、`*.txt/*.yaml/*.onnx` 等一起带上来，其余文件只记进响应里的 `skipped` 不写盘。注意它列了 `.pt2`/`.pickle`，而 168 行的错误提示文本里曾经**漏了 `.pt2`** —— **`06a8fb8` 已补**（今 190–191 行，后端 3 处 + 前端 4 处文案一起补的）。
- **60–61**（**今 65–72 行；`06a8fb8` 已改**）`_HEAD_LAYER_RE = re.compile(r"(?<![A-Za-z0-9])(?:fc|classifier|linear|head|dense|out|output)\d*\.weight$")` — 用来在 torch `state_dict` 的键名里认出"分类头"（唯一使用点 271 `_HEAD_LAYER_RE.search(k)`），从而把该层 weight 的第 0 维当类别数。**改动**：加了否定环视 `(?<![A-Za-z0-9])`；没有它时 `re.search` 会把**更长的层名后缀**也算命中 —— 实测 `dropout.weight`、`about.weight`、`readout.weight`、`without.weight` 都因为结尾的 `out` 而匹配上，类别数就可能取到别的层。环视只挡"字母/数字左边"，`_` 是**故意放行**的（`self._fc.weight` 这类私有属性仍要认出来，而 `dropout` 前面是字母 `p`，照样被挡）。顺便把 `(?:...)` 改成非捕获组、注释写清了这条边界：`features.0.weight` 这种纯序号命名谁也认不出，走 272 行的兜底。

## 行 62–109 · `_keras_shapes(config)`

**作用**：从 Keras 导出的模型结构 dict 里尽力猜出 `(input_len, num_classes)`，猜不到就给 `None`，绝不抛异常。

- **62** `def _keras_shapes(config: dict) -> tuple[int | None, int | None]:` — 返回二元组而不是 dict，调用方两处都是 `input_len, units = ...`（189、205）直接解包；类型注解里 `int | None` 靠第 23 行的 future import 才不会在旧解释器上炸。
- **63–69** docstring — 说明两件事：① 形参名 `config` **遮蔽**了第 37 行导入的全局配置对象（本函数内 `config` 一律指 Keras 结构 dict，别误用成 `config.model_dir`）；② 这是纯猜测逻辑，失败只返回 `(None, None)`。代码与之一致：全程 `isinstance` 防御，函数体内没有 `try`，也真的不会抛。
- **70–73** 外壳兼容 — `conf = config.get("config", config)`：先按 `{"class_name": ..., "config": {...}}` 试，取不到就认为传进来的**就是**内层 config；非 dict（如 `json.loads` 出来一个 list）直接 `(None, None)`。三行一起看就是"两种存档形态都吃、垃圾输入不吃"。
- **74–76** `layers = conf.get("layers") if isinstance(conf.get("layers"), list) else []` — 把"缺 `layers`""`layers` 是 dict"统一成空列表，后面两个循环就不用各自判类型；副作用是**空列表不会报错**，只是什么都猜不到。
- **77–82** `def first_dim(shape)` + docstring — 取形状里第一个"有意义的"维度：跳过 batch 维（`shape[0]`）与 `None`/`0`。文档举的例子 `[None, 784, 1] → 784` 与实现一致。
- **83–84** — 非 list 直接 `None`（Keras config 被手工改坏或存成 tuple 的情况）。
- **85–86** `dims = [d for d in shape[1:] if isinstance(d, int) and d > 0]` — 关键一步：把 batch 维和占位维度一起滤掉。**⚠️ 注意语义耦合**：它取的是"第一个正整数"，所以对**通道在前**的形状（如 `[None, 1, 784]`）会返回 `1` 而不是 `784`。本平台的数据窗口固定是 `(length, 1)`（`1DCNN.py:100` 用 `shape=(x_train.shape[1], x_train.shape[2])`，selftest 也造 `[None, input_len, 1]`），与 `inference.py:462` 把 `input_len` 当窗口长度的口径一致，所以对本项目正确；对外部通道在前的 Keras 模型则会给出错误的 input_len（只是一个提示值，不改写用户显式填的 meta，见 1132–1134）。
- **87** `return int(dims[0]) if dims else None` — `int()` 是多余的（元素已经是 `int`），但它顺手拒绝了 `bool`/`numpy` 整型之类"看着像整数"的东西？并不是 —— `isinstance(d, int)` 本来就把它们挡住了（`True` 会被当 int 接受，量级上无影响）。属于无害的防御写法。
- **88** `input_len = None` — 显式初始化，保证后面 `if input_len is None` 的兜底判断引用的变量一定存在。
- **89–97** 逐层扫描输入层 — 遍历 `layers`，每层取 `layer["config"]`（不是 dict 就跳过），再用 `first_dim(lc.get("batch_input_shape")) or first_dim(lc.get("batch_shape"))` 同时兼容 Keras2（`batch_input_shape`）与 Keras3（`batch_shape`）。三行一起看：`or` 的短路语义正好表达"左边没结果才退到右边"，命中后立刻 `break`（96–97）是为了防止后续层的空形状把已经拿到的值覆盖成 `None`——这是这段代码里唯一必须 `break` 的原因。
- **98–99** 顶层兜底 — 若逐层都没扫到，再试 `conf` 顶层的 `batch_input_shape`/`batch_shape`（有些导出结构把形状挂在模型级而不是 InputLayer 上）。
- **100** `units = None` — 同上，先占位，避免"没进 104 的循环"时 `UnboundLocalError`。
- **101–103** 三条注释 — 解释类别数的取法：**必须倒着找**第一个带 `units` 的层，不能取 `layers[-1]`（导出结构末尾常是 `Activation`/`Dropout`，没有 `units`）；并如实说明该等式只在"最后一层是分类输出"时成立，回归头/嵌套子模型读到的只是"最后一层的宽度"。
- **104–108** 倒序扫描 — `for layer in reversed(layers)`：能安全用 `reversed()` 的前提是第 76 行已保证 `layers` 是 list；条件 `isinstance(lc.get("units"), int) and lc["units"] > 0` 同时挡掉了 `units` 缺失与 0/负数，命中即 `break`。
- **109** `return input_len, units` — 两个值都可能是 `None`；调用方用 `if config else (None, None)` 短路掉 `config is None` 的情况（189、205），所以本函数不需要自己处理 `config=None`（但第 71 行其实也兜住了）。

## 行 110–150 · `_exported_input_len(blob, names)`

**作用**：从 torch.export 的 `.pt2` 包里读回导出时的示例输入，取出窗口长度。

- **110** `def _exported_input_len(blob: bytes, names: list[str]) -> int | None:` — 入参用已经解好的 `namelist()`（222–223）而不是自己再开一次 zip；同一份 `blob` 因此被打开两次（223 取名单、128 读条目），属于可接受的取舍。
- **111–120** docstring — 说清三件事：包内路径是 `archive/data/sample_inputs/<名>`；用 `weights_only=True` 读它安全（只有张量，不执行代码）；结构是 `[args, kwargs]` **嵌套**（实测 `[[Tensor(2,1,784)], {}]`），只看一层会读不到，所以要递归找"至少二维"的张量。还说明读不出来就返回 `None`，调用方退回表单/meta 的值，不该因为一个提示值让整个上传失败——TorchScript 正属于读不出来的那类。
- **121–122** `import io` / `import zipfile` — 函数内局部导入，与本文件其它重依赖（h5py/torch）一致的做法：把可选依赖推迟到真正用到时，Flask 启动阶段不背这些成本。这里两个都是标准库，写成局部只是风格统一。
- **123–125** `candidates = [n for n in names if n.startswith("archive/data/sample_inputs/")]`，空则 `return None` — 用包内条目**存在性**当作"这确实是 torch.export 产物"的旁证，同时避免对 TorchScript 之类白跑一趟。
- **126–132** 三步全包一个 `try` — 懒导入 `torch`、`zipfile.ZipFile(io.BytesIO(blob))` 打开内存包、`zf.read(candidates[0])` 取原始字节、再 `torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)` 反序列化；任何一步失败（没装 torch、包损坏、条目其实是目录）都 `return None`。**⚠️ 小风险（未复现，需实机确认）**：读的是 `candidates[0]`，若 zip 里同时存在显式**目录条目** `archive/data/sample_inputs/`（以 `/` 结尾，排序通常在前），它会排在真实文件之前，`zf.read` 得到空字节、`torch.load` 抛错 → 静默退化成 `None`。docstring 说"实测读到 `[[Tensor(2,1,784)], {}]`"，说明实际产物不带这种目录条目，所以现状可用；但如果哪天换成会写目录条目的打包器，这个函数会**静默失效**（不报错、只是 input_len 变成 None）。
- **133–136** `def dig(node, depth=0)` 与深度上限 — `depth > 5` 直接放弃，防止畸形包（自引用结构、超深嵌套）把递归拖爆；`[args, kwargs]` 实际只有 2 层，上限 5 足够宽。
- **137–138** 张量分支 — `isinstance(node, torch.Tensor)` 时，只有 `node.dim() >= 2` 才取 `shape[-1]`：这样 `(n, 1, L)`（1D 卷积输入）与 `(n, L)`（全连接输入）都得到 `L`，而一维的 batch 索引/标量被跳过。这正是注释说的"最后一维都是 length"。
- **139–143** 序列分支 — 对 `list`/`tuple`（含 `args` 与 `kwargs` 里的参数表）按顺序递归，**先找到先返回**：返回的是 DFS 遇到的第一个合格张量，而不是最深的那个。
- **144–148** dict 分支 — `kwargs` 或 `{"x": tensor}` 这类命名输入也支持，按 `values()` 顺序递归。
- **149** `return None` — 走到这里说明整棵结构里没有 dim≥2 的张量（例如 TorchScript 的 traced_inputs，docstring 已点名）。
- **150** `return dig(obj)` — **⚠️ 一处小瑕疵**：`dig` 内部用 `if found:` 判断"找到了"，所以合法但为 `0` 的返回值（长度 0 的退化张量）会被当成"没找到"继续往下找；实际张量长度不可能为 0，影响为零。

## 行 151–289 · `probe_weight(filename, blob)`

**作用**：判断一个上传文件"是不是模型权重"，并尽量读出 `input_len` / `num_classes` —— 它是上传接口的核心判据。

- **151** `def probe_weight(filename: str, blob: bytes) -> dict:` — 只吃内存字节（调用方在 `_upload_blobs` 里已把文件读进内存），所以本函数不做任何磁盘 IO，天然可测（`_selftest_upload.py` 就是直接喂字节）。
- **152–160**（**今 169–181 行；`06a8fb8` 已按实现重写**）docstring — 列出每种后缀的判据：`.h5` 要看 HDF5 里有没有 `model_weights` 组或 `model_config` 属性；`.keras` 看是不是 zip 且含 `config.json`/`metadata.json`；`.pt/.pth/.pt2` 是**三路分支**（`archive/data/weights/` → torch.export 产物 → `pytorch-exported`；含 `"/code/"` → TorchScript → `pytorch-jit`；含 `data.pkl` → 老式 state_dict → `pytorch`），并说明前两种**自包含**、第三种要靠本项目架构重建；`.pkl` 只解析操作码流、**绝不反序列化**。原版只写了 ".pt/.pth 看 data.pkl"，与实现了三路分支的代码不符，也没有提 `.pt2`。
- **161–162** `import io` / `import zipfile` — 局部导入；本函数体被调用一次就要解 1–2 次 zip，用 `io.BytesIO` 把内存字节伪装成文件对象。
- **163** `suffix = Path(filename).suffix.lower()` — 只取后缀（不含目录部分），所以上传时带的 `C:\fake\path\model.h5` 这种 filename 不会带来任何路径风险；`.lower()` 让 `.H5`/`.Keras` 也能认。
- **164** `framework = WEIGHT_SUFFIXES.get(suffix)` — 第一层分类；`None` 表示"连后缀都不认"。这个值同时是**候选的初始框架名**，之后内容探测可以覆盖它（232）。
- **165** `result = {"ok": False, "framework": framework, "reason": "", "input_len": None, "num_classes": None}` — 一次建好 5 个键，保证**无论走哪条分支返回的字典键都齐全**。这是与前端的隐性契约：`ModelUpload` 直接读 `info["ok"]/["reason"]/["input_len"]/["num_classes"]` 并 `.get("framework")`（1016–1019），`_upload_meta` 也按这三个键取探测结果（1132–1134、1158）。**键名/`ok` 语义不能改**。
- **166–169**（**今 190–193 行；`06a8fb8` 已修**）后缀闸门 — 不在表里就直接返回并给出人话原因。**修掉了这处文案漏项**：原 reason 写"支持 `.h5/.keras/.pt/.pth/.pkl/.pickle`"，但 `WEIGHT_SUFFIXES`（52–56）与后续分支（217）都**包含 `.pt2`**，同样地 1012、1032 两处用户可见提示也漏了 —— 功能上 `.pt2` 能上传、文案却说不行。现在三处后端文案都写成 `.h5/.keras/.pt/.pth/.pt2/.pkl/.pickle`；前端另有 4 处也漏（上传页提示、`accept` 属性、`pickKind()` 的权重识别、警告文案），其中 `pickKind()` 会把 `.pt2` 标成"其他"并弹「没识别到权重文件」的误导警告，已一并补上。
- **170–172** 空文件闸门 — `if not blob`（0 字节）直接拒。放在后缀判断之后、内容判断之前：空文件即使后缀对也一定会让后面解包失败，早点给出确切原因比让异常兜底更友好。
- **173** `try:` — 从这里到 285 行是一整块；286–289 的 `except Exception` 是**统一兜底**。这种"大 try + 末尾兜底"的代价是错误原因会被降级成"读取失败，不像有效模型文件"，收益是任何畸形上传都不会 500。
- **174–176** Keras 分支入口 — 只处理 `.h5`/`.keras` 两个后缀；用 `blob[:2] == b"PK"` 区分两种形态（Keras 3 的 `.keras` 是 zip，Keras 2 的 `.h5` 是 HDF5，而 HDF5 魔数是 `\x89HDF`，两者不可能混淆）。注意判据是**内容**不是后缀：一个其实是 HDF5 的 `.keras` 会走下面的 HDF5 分支。
- **177–182** zip 形态校验 — 打开 zip 取 `namelist()`，再要求 `config.json` **或** `metadata.json` 至少有一个，否则说明这只是个碰巧叫 `.keras` 的普通 zip。reason 里带上 `names[:5]`，让用户自己看到"包里其实是什么"。
- **183–188** 按需读 `config.json` — 注释说明了这里修过的 bug：判据允许"只有 `metadata.json`"，而旧代码却无条件 `zf.read("config.json")`，于是那种包会抛 `KeyError` 被外层兜底成"不像有效模型文件"，与判据自相矛盾；现在读不到就把 `config` 置 `None`，**当"是模型但猜不出结构"**。我核对了 188 行的三元条件确实是 `if "config.json" in names else None`，与 180 行的判据一致，注释描述准确。
- **189** `input_len, units = _keras_shapes(config) if config else (None, None)` — 用真值判断短路，同时覆盖 `config is None`（只有 metadata.json）与 `config == {}` 两种"没结构可猜"的情况。
- **190–192** `result.update(ok=True, input_len=..., num_classes=units, reason=...)` — 一次性把结果与原因写进同一个 dict；reason 里嵌了 `input_len`/类别数，是因为前端会把 reason 直接展示，省得用户去数别的字段。`ok=True` 只表示"它确实是个 Keras 存档"，不保证能推理。
- **193–195** 两条注释 — 说明非 zip 就按 HDF5 处理，并且**光能打开不够**：必须有 `model_weights` 组或 `model_config` 属性，否则随便一个 HDF5 数据文件都会被误判成模型。这是"内容判定"的关键设计。
- **196–197** `import h5py` + `h5py.File(io.BytesIO(blob), "r")` — h5py 是重依赖（会把 numpy/HDF5 拖起来），所以放在函数内懒导入；本机没装 h5py 时异常会落到 286 的兜底，报"读取失败"（可接受但不够精确）。
- **198–203** 双判据 — `keys = list(handle.keys())` 只看**顶层**键；`raw_config = handle.attrs.get("model_config")` 取文件级属性。两者都没有就拒绝，并把顶层前 5 个键写进 reason，方便用户判断"这到底是个什么文件"（selftest 里 `random.h5` 这条用例就是靠 h5py 解析失败落到兜底来拒的）。
- **204** `config = json.loads(raw_config) if raw_config is not None else None` — `model_config` 属性在 Keras 里是 JSON 字符串（h5py 有时返回 bytes，`json.loads` 两种都吃），解析成 dict 才能交给 `_keras_shapes`。
- **205–208** 与 zip 分支对称的三行 — 调同一个解析器、同样的 `ok=True`，reason 换成 HDF5 口径并把顶层键名带上。两个分支结构一致是刻意的：前端只认返回结构，不关心是哪种存档。
- **209–216** 注释块 — 解释为什么 `.pt/.pth/.pt2` 要分三种：最早的路线是"重建架构 + `load_state_dict`"，**只对本服务训出来的模型有效**；要让外部 pytorch 模型"上传就能用"必须自包含 —— `.pt2`（torch.export，包内带 `archive/data/weights/`，加载不需要模型类）、TorchScript（包内带 `code/`）、老式 state_dict（只有张量、仍需架构同构）。
- **217–221** torch 分支入口 — 三个后缀共用；`blob[:2] != b"PK"` 直接拒，reason 明确写出"torch>=1.6 的 `.pt` 是 zip"并回显实际开头 4 字节。副作用（符合预期但值得知道）：torch<1.6 的 legacy 存档、以及直接 `pickle.dump` 出来的 `.pt` 都在这里被拒。
- **222–223** 单独开一次 zip 只为了取 `namelist()` 并**立刻关闭** — 后面 224–242 的形态判定全部基于这份字符串列表，不用保持文件句柄打开，也就避免了"读到一半失败"。
- **224** `is_exported = any(name.startswith("archive/data/weights/") for name in names)` — 用 torch.export 特有的权重目录前缀判定 `.pt2`。注意是**内容判据**，所以一个内容是 export 产物的 `.pt` 文件同样会被判成 exported（这正是 1021–1026 注释要的：`framework` 必须以探测结果为准，因为后缀区分不了这三种 torch 格式）。
- **225–228** `is_torchscript` — 注释点明 TorchScript 的条目是 `archive/code/__torch__/...`（带 `archive/` 前缀），所以用 `"/code/" in name or name.endswith("/code")` 而不是 `startswith("code/")`，否则会漏判并掉进老式 state_dict 分支；外面的 `not is_exported` 保证两种自包含格式同时命中时**优先算 exported**。
- **229–237** 自包含两形态的提前返回 — `kind` 只用于拼 reason；`result["framework"]` 被显式改写为 `"pytorch-exported"`/`"pytorch-jit"`（覆盖 165 行按后缀猜的值，两个都必须是 `inference._DISPATCH` 里的键）；只有 exported 才去猜 `input_len`（读包内 sample_inputs），TorchScript 直接 `None`。**⚠️ 需要知道的行为**：这一支**不设 `num_classes`**（沿用 165 的 `None`），reason 里也明说"类别数留到推理时按输出宽度定"——所以上传这两种格式后，前端的"类别数"一栏永远是空的，而 `_upload_meta`（1139、1146）在没有 labels 时也只能给它 `None`。与 docstring"尽量读出"一致，不算 bug，但要清楚这是**有意的留空**。
- **238–242** 老式 state_dict 的最后一道判据 — 要求包内存在以 `data.pkl` 结尾的条目（torch>=1.6 的 zip 序列化必然有它）；否则拒绝并列出前 5 个条目名，reason 同时点出"既没有 data.pkl，也没有 `archive/data/weights/` 或 `code/`"，与 224/227 的判据严格对应。
- **243–247** `try: import torch` — 本机没装 torch 时**不判失败**，而是 `ok=True` + reason 里说明"跳过参数解析"（把 `exc` 带上）。理由是想让"上传"这件事在无 torch 的机器上也能跑通；代价是这种产物 meta 里 `num_classes/input_len` 都是 `None`，推理时会走默认值。
- **248–253** `torch.load(io.BytesIO(blob), map_location="cpu", weights_only=True)` — 注释明确这是 `.pt` 上传路径**唯一**的防代码执行闸门，并记录了"自家 payload `{state_dict, length, num_classes}` 在 `weights_only=True` 下完全读得出来（int/dict/tensor 都在白名单里），原先用 False 是没必要的"。`map_location="cpu"` 让 GPU 上存的张量也能在无 CUDA 的机器上读。
- **254–263** `except` 的语义变更 — `weights_only=True` 读不动 = 包里带了自定义类（"存整个模型对象"那种）。旧行为是 `ok=True` 放过去、留到推理再决定；现在仍然 `ok=True`（因为它确实是 torch 存档）但 reason 里如实说明本平台不会为它反序列化，并给出两条可执行出路（`torch.export` → `.pt2`、`torch.jit.trace`+`torch.jit.save`）。**⚠️ 存疑（注释与推理侧代码已不同步）**：255–257 行说"推理那边用的是 `weights_only=False`，会把上传者提供的代码跑起来" —— 现在的 `inference._predict_torch`（inference.py:231–243）是**先试 `weights_only=True`**，只有失败且显式设了 `MODEL_ALLOW_UNTRUSTED_PICKLE` 才退到 `False`，否则抛 `InvalidInput`。所以注释描述的风险已被堵上，结论（拒收/prompt 改格式）仍然正确，只是理由过期了。
- **264** `state = obj.get("state_dict", obj) if isinstance(obj, dict) else obj` — 兼容两种 payload：本项目自己的 `{"state_dict": ..., "length": ..., "num_classes": ...}` 与外部直接 `torch.save(model.state_dict())` 的裸 state_dict。用 `.get` 而不是 `["state_dict"]`，所以裸 state_dict 只是"恰好没有这个键"。
- **265** `shapes = [(k, tuple(v.shape)) for k, v in state.items()] if hasattr(state, "items") else []` — 把参数名与形状**预先物化成 list**，是为了后面能对同一份数据 `reversed()` 两遍（271、272）而不必重新遍历；`hasattr(state, "items")` 兜住 `obj` 是单个张量/自定义对象的情况。**⚠️ 存疑（健壮性小坑）**：这个推导式对每个 `v` 直接取 `v.shape`，若 `weights_only=True` 读出来的 dict 里混有非张量值（例如 `{"epoch": 3}`、`{"cfg": {...}}` 之类），会抛 `AttributeError` 落到 286 的兜底，报成"读取失败，不像有效模型文件" —— 而这本来应该由 266–268 输出"torch 文件里没有张量参数，不像模型权重"。也就是说 266 那条精心写的提示在这种输入下不可达。
- **266–268** 空参数闸门 — `shapes` 为空（`state` 不是映射，或者映射里一个参数都没有）时明确拒绝，不把空 zip 当模型。
- **269–270** 注释 — 说明类别数的猜法：倒着找第一个"像分类头"的二维权重（`fc/classifier/linear/head...`），取第 0 维；找不到就退而取最后一个二维权重。
- **271** `head = next((s for k, s in reversed(shapes) if len(s) == 2 and _HEAD_LAYER_RE.search(k)), None)` — 只接受**二维**权重（`Linear` 的 weight 是 `(out, in)`，第 0 维正好是类别数；卷积/BN 的更高维权重被排除）且键名匹配分类头模式，倒序保证取到"最后一层"。**`06a8fb8` 已修**：`_HEAD_LAYER_RE` 加了否定环视 `(?<![A-Za-z0-9])`，现在 `dropout.weight`、`about.weight`、`readout.weight`、`without.weight` 都不再命中，而 `module.fc1.weight`、`self._fc.weight` 仍命中。**诚实补一句**：本平台现有 3 个模型都不受这个 bug 影响 —— 实测 cwt_cnn 的 state_dict 里 `fc1.weight (32,3136)` 是**隐藏层**、`fc2.weight (10,32)` 才是输出层，新旧判据都取到 `fc2`（类别数 10，与 meta.json 一致），所以这是**防御性修复**，不是线上正出错。
- **272** `head = head or next((s for _, s in reversed(shapes) if len(s) == 2), None)` — 兜底取最后一个二维权重。注意是"最后一个"而不是"第一层"：对 `Sequential(Linear(8,16), ReLU, Linear(16,3))` 这种结构能拿对（selftest 的 `fake_pt` 正是靠这条把 `num_classes` 读成 3，因为键名 `0.weight`/`2.weight` 不匹配 271 的模式）。
- **273–277** 收尾 update+return — `num_classes=int(head[0]) if head else None`；reason 同时报"多少个张量""类别数"，并**主动说明这种格式没有结构**：推理时按本项目的 `cwt_cnn` 架构重建（`inference._predict_torch` 确实 `from .training import _import_project_module` 后 `build_model(...)` + `load_state_dict`），外部模型结构不同请改用 torch.export。这段文案与推理侧行为一致，是有意把"可能失败"提前告知。
- **278–280**（**今 301–310 行；`06a8fb8` 已重写**）pickle 注释 — 说明为什么只解析操作码、绝不反序列化：反序列化 pickle 等于执行上传文件里的任意代码。新注释还记了两条实测结论，说清"判据不能怎么写"：① 不能用"首字节是不是 `0x80`"——`0x80` 是 PROTO 标记，**只有协议 2+ 才写**（`protocol=0` → `b'(d'`、`protocol=1` → `b'}q'`）；② 也不能只看"第一个操作码能不能解码"——`hello world`、`a,b,c` 的首字节恰好是合法操作码，只看一个就会把文本放进来。
- **281–310**（**今 311–325 行；`06a8fb8` 已换实现**）`pickletools.genops(blob)` 校验 — 用生成器**惰性解码操作码流**（不执行任何字节码），判据是"**能解到底且最后一个操作码是 STOP**"（合法 pickle 必以 STOP 收尾，`pickle.loads` 也必须有它）；`seen >= _PICKLE_MAX_OPS` 时提前 break，并按"前缀合法"放过（见 49–50 行的封顶理由）。实测效果：协议 0/1/2/3/4/5 全部通过；纯文本、`he is not a pickle`、JSON、CSV、随机二进制、半截 pickle、被截掉 STOP 的文件全部拒绝。**原实现（`if blob[:1] != b"\x80"`）会误拒协议 0/1 的合法 pickle**，reason 还反过来指责用户；而且它只验证 1 个字节，与推理侧 `inference._predict_adtk` 用 `pickle.load` 直接读文件的口径不一致 —— 现在两侧都接受任意合法协议。
- **281–283**（**旧实现，`06a8fb8` 已删除**）`if blob[:1] != b"\x80"` — 只检查第一个字节。**⚠️ 存疑（会误拒合法 pickle）**：`\x80`(PROTO) 只有**协议 2 及以上**才会写；实测 `pickle.dumps({"k":1}, protocol=0)` 以 `b'(d'` 开头、`protocol=1` 以 `b'}q'` 开头。所以用协议 0/1（Python 2 产物、或显式 `protocol=0/1`）存的合法 `.pkl` 会被判成"不是 pickle 文件"，reason 还是错的。本项目自己的 `detector.pkl` 用 `pickle.dump(...)` 默认协议（3.8+ 为 5）保存（training.py:474），所以不受影响；`inference._predict_adtk` 用 `pickle.load` 读文件时也不看魔数，即**探测侧与推理侧口径不一致**。→ 已按这里建议的第二种改法（"能 `pickletools.genops` 解析"）修掉，见上一条。
- **284–285**（**今 323–325 行，内容不变**）`result.update(ok=True, reason="pickle 序列化对象（adtk 检测器/传统模型；为安全起见不做反序列化校验）")` — `ok=True` 只声明"它是个 pickle 权重"，`framework` 仍是 165 行按后缀给的 `"adtk"`（`.pickle` 同理）。**⚠️ 需要知道的行为**：操作码校验只证明"这是个合法 pickle 文件"，**不证明它是个检测器**，所以任何 pickle（selftest 里连 `{"k": 1}` 都算合格）都会被当 `adtk` 模型登记；而 `inference._predict_adtk` 要求 bundle 里同时有 `feature_mode` 与 `transformer`，否则抛 `InvalidInput`；且上传产物 meta 里 `trusted=False`（1155、1130），推理默认**拒绝对它反序列化**，除非设 `MODEL_ALLOW_UNTRUSTED_PICKLE=1`。也就是说 `.pkl` 这条路的"上传成功"与"能推理"是两件事，前端的提示文案别写成"上传即可推理"。
- **286–289** 统一兜底 — 注释说"坏文件、半截文件、权限问题都会落到这里，reason 会被前端逐条展示，所以要说人话"。实现是 `f"读取失败，不像有效模型文件：{type(exc).__name__}: {exc}"`，占位符与注释一致；但它把"文件确实不是模型"与"我们自己读错了/环境缺依赖"混成同一句话，且这两类在 255–263 那种刻意区分过的场景之外没有进一步细分。**这条分支同时吞掉了所有意外异常**（包括上面的 `AttributeError` 与 `ImportError`），所以排查上传问题时 reason 是唯一线索 —— 想更精确就得看服务端日志。

---

### 本段涉及的存疑/偏差清单（汇总）

> ✅ **已修（`06a8fb8`）**：**168 行提示漏 `.pt2`**（另有 1012、1032 两处同样漏）。代码（`WEIGHT_SUFFIXES` 52–56 与分支 217）明确支持 `.pt2`，用户可见文案却写"支持 .h5/.keras/.pt/.pth/.pkl/.pickle" —— 会让 `.pt2` 用户以为格式不受支持。后端 3 处已补齐，前端另有 4 处（上传页提示、`accept`、`pickKind()`、警告文案）一并补齐。

> ✅ **已修（`06a8fb8`）**：**281 行的 pickle 魔数判据会误拒协议 0/1 的合法 pickle**（`\x80` 只有协议 2+ 才写；实测 `protocol=0` 以 `b'(d'`、`protocol=1` 以 `b'}q'` 开头），且 `reason` 文案"不是 pickle 文件"与事实相反。同一份文件在 `inference._predict_adtk` 里用 `pickle.load` 是能读的，**两侧口径不一致**。现在改成 `pickletools.genops` 解到底 + 必须 STOP 收尾（今 301–325 行），协议 0~5 全部通过，同时能挡住文本/JSON/半截文件。

> ⚠️ 存疑：**265 行的形状推导式**对每个 state 值直接取 `v.shape`，遇到 dict 里混有非张量值（int/dict 等）会抛 `AttributeError`，被 286 兜底成"读取失败，不像有效模型文件"，于是 266 行那条"torch 文件里没有张量参数"的提示在这类输入下**不可达**。

> ⚠️ 存疑：**255–257 行注释已过期**。注释说"推理那边用的是 `weights_only=False`，会把上传者提供的代码跑起来"，而现在的 `inference.py:231–243` 是**先试 `weights_only=True`**，只有失败且显式设置 `MODEL_ALLOW_UNTRUSTED_PICKLE` 才退到 `False`，否则抛 `InvalidInput`。结论（拒收 + 建议改用自包含格式）仍正确，理由是旧的了。

> ⚠️ 存疑：**4–19 行的 docstring 路由清单与计数已漂移**（与第 4 行"别再手抄清单"的自我要求相矛盾）。实际存在的 `PUT /models/<model_name>`（887）、`GET /api`、`GET /`、`GET /system/logs/<name>` 都没列；"曾注册 27 条"对不上当前 `_ROUTES` 的 **24 个资源 / 25 条 URL 规则**（`Console`、`DatasetRecord` 已删，见 1490–1493）。属历史叙述，非功能问题，但容易被后读代码的人当真。

> ⚠️ 存疑（低置信、未复现）：**`_exported_input_len` 读的是 `candidates[0]`** —— 若 `.pt2` 包内含显式目录条目 `archive/data/sample_inputs/`，它会排在真实文件前，`zf.read` 得到空字节、`torch.load` 抛错，函数静默退化成 `None`。当前产物不带这种条目（docstring 记录了实测值），所以只是潜在隐患。

> ✅ **已修（`06a8fb8`）**：**`_HEAD_LAYER_RE` 无词边界**：`search` 会命中 `dropout.weight`、`about.weight` 里的 `out.weight`，可能让类别数从"别的层"取宽度。现在加了 `(?<![A-Za-z0-9])`。本平台现有 3 个模型实测都不受影响（防御性修复）。

> ⚠️ 存疑（轻微）：**`_keras_shapes.first_dim` 假定"长度在前"** —— 对通道在前的形状 `[None, 1, 784]` 会返回 `1` 而非 `784`。本项目数据固定为 `(length, 1)`（`1DCNN.py:100` + selftest `[None, input_len, 1]`），与 `inference.py:462` 的 `input_len` 语义一致，故当前正确；对外部通道在前模型会给错提示值。

---

# 第 2 段 · 行 290–610

> 覆盖 `testRestfulProject/model_service/api.py` 第 290–610 行。行号取自实际文件（已逐行核对）。
> 本文只解释代码本身；文件里已有的中文注释不再照抄，只说明"代码实际做了什么 / 为什么不这么写会出问题 / 注释与代码对不对得上"。
> 标 `> ⚠️ 存疑` 的是我在读代码与被调模块时发现的可疑、矛盾或 bug，都给了依据。

## 行 290–297 · `_body()`

**作用**：把请求体统一读成 dict，读不到就给空 dict，让调用方永远不用判 None。

- **290** `def _body() -> dict:` — 无参辅助函数，返回标注只是提示。它紧贴上一个函数的 `return result`（289），中间没有空行——本文件顶层定义之间普遍不留空行（1604 行里只有 43 个空行，且都在 docstring 内部），不是本段的特殊写法。
- **291–295** docstring — 说明语义与 `silent=True` 的取舍：前端有些请求是 form-data 或干脆不带 body，不该因为"没有 JSON"就 400。
- **296** `data = request.get_json(silent=True)` — Flask 解析请求体；Content-Type 不是 application/json 时、以及 JSON 语法坏掉时，`silent=True` 都返回 None 而不抛 415/400。Flask 会缓存解析结果，同一请求内多次调用不会重复解析。
- **297** `return data if isinstance(data, dict) else {}` — 只放行 dict，JSON 数组/数字/字符串/None 一律收敛成 {}。代价：客户端发了数组这种明显错误被静默降级成"参数缺失、走默认值"，不会报 400。

## 行 298–309 · `_int()`

**作用**：整数参数的唯一入口——缺参给默认值，转不动抛 InvalidInput，由调用方翻成 400。

- **298** `def _int(value, default=None, name="参数"):` — `name` 只用于报错文案（"epochs 必须是整数"），不做任何参数名反射。
- **299–303** docstring — 含那条关键警告：调用方**不要**写 `_int(x, 0, "y") or 0`，因为 0 是 falsy，用户明确传的 0 会被悄悄换成别的值。
- **304–305** `if value is None: return default` — 只有"参数缺失"才用默认值；`0`、`"0"`、`""` 都会继续往下走转换。这就是它区别于 `or` 写法的地方：默认值只在 None 时生效，而 `or` 在任何 falsy 值上都生效。
- **306–307** `try: return int(value)` — 顺手做类型归一：`"5"→5`、`5.9→5`（截断不四舍五入）、`" 7 "→7`、`True→1`。
- **308–309** `except (TypeError, ValueError): raise InvalidInput(...)` — 转不动就抛 InvalidInput（`inference.py:27` 定义的 ValueError 子类），消息里用 `{value!r}` 回显原值便于定位。异常不吞掉，所以调用方必须显式给 default。

## 行 310–316 · `_sanitize_name()`

**作用**：把名字洗成磁盘安全形式（非法字符→下划线、去掉首尾点和下划线、空则用默认名），**从不抛异常**。

- **310** `def _sanitize_name(value: str, default: str) -> str:` — 调用方必须保证 `value` 是 str：`re.sub` 收到非 str 会抛 TypeError（不是 InvalidInput）。本文件两个调用点都满足（459 行来自 form 字段加 `.strip()`，836 行来自已 `str()` 的改名参数）。
- **311–315** docstring — 交代与 `_safe_model_name()` 的分工：允许静默改名的路径（上传落盘、改名回滚）用它；要求"非法就报错、不许静默改名"的路径（改模型名）用 `_safe_model_name()`（753 行）。
- **316** `return re.sub(r"[^\w\u4e00-\u9fa5.\-]+", "_", value).strip("._") or default` — 三步合一：① 连续非法字符压成**一个** `_`；② `strip("._")` 去掉首尾的点与下划线（顺手挡掉 `..`、`.hidden` 这类）；③ 清成空串就用 default。因为 `/`、`\`、`:` 都属非法字符，`../../evil` 会被洗成 `evil`，所以它天然防路径穿越。

> ⚠️ 存疑：注释说"允许中英文、数字、下划线、点、横线"，但 `\w` 在 Python 3 的 str 模式里已是 Unicode 语义、**本身就匹配中日韩字符**，所以 `\u4e00-\u9fa5` 是冗余的；真正被放行的比注释更宽（俄文、全角数字、带音符字母都算 `\w`）。实害很小（这些字符在 NTFS 上合法），但"只允许中英文"这句话与代码不符。

## 行 317–339 · `_resolve_workspace_path()`

**作用**：把用户给的路径解析成"工作区内真实存在的文件"，越界或不存在一律 InvalidInput（400）。

- **317** `def _resolve_workspace_path(raw: str) -> Path:` — 只接受 str；传 None/数字会在 `Path(raw)` 抛 TypeError（不是 InvalidInput）。本文件两个调用点（506、1322）传的都是 str。
- **318–326** docstring — 两级回退 + 用 `relative_to` 而不是字符串 startswith + 找不到就 400 且不回显解析后的真实路径。
- **327** `candidate = Path(raw)` — 纯语法解析，不碰磁盘。
- **328–330** `tries = [candidate] if candidate.is_absolute() else [config.workspace_dir / candidate, config.project_dir / candidate]` — 绝对路径只有一次机会；相对路径按"工作区优先、项目目录兜底"试两次。**这一级不能省**：响应出口脱敏（`mask_private_paths`）会把绝对路径换成"相对工作区"的形式，前端正是拿 `dataset_dir + "\" + filename` 回传给 `/datasets/table` 的（`frontend/.../dataset/index.vue:210`），只按 project_dir 拼会得到 `testRestfulProject\testRestfulProject\...` 从而误报 400。
- **331** `for path in tries:` — 候选逐个试，先命中者胜。
- **332** `resolved = path.resolve()` — 规范化并解析符号链接/junction；非 strict 模式，所以文件不存在不会在这里抛。
- **333–336** `try: resolved.relative_to(config.workspace_dir.resolve()) except ValueError: continue` — 越界就**换下一个候选**而不是立刻报错（工作区相对路径不存在时才轮得到项目目录）。用 Path 语义而非 `str.startswith`，否则 `D:\22project_evil\...` 这种同前缀目录能绕过检查；`resolve()` 会跟随链接，所以指向工作区外的 junction 也会在这里被判掉。
- **337–338** `if resolved.is_file(): return resolved` — 命中必须是**文件**：目录不算。所以 `?path=某个目录` 不会落到 pandas 手里报一堆看不懂的错，而是走到 339 明确 400。
- **339** `raise InvalidInput(f"文件不存在或不在工作区内：{raw}")` — 两个候选都失败才报错，且回显**原始 raw**而非解析后的绝对路径，少泄露本机目录（响应出口还有一层脱敏兜底）。

## 行 340–351 · `class ApiIndex(Resource)` / `.get()`

**作用**：GET `/` 与 `/api` 的自描述接口索引，也是前端「接口索引」页的数据源。

- **340** `class ApiIndex(Resource):` — 在 `_ROUTES`（1465）里一次挂两个 URL（`"/"` 与 `"/api"`）：flask_restful 用"类名小写"当 endpoint，拆成两次 add_resource 会因 endpoint 重名直接 AssertionError。
- **341** docstring — 首行会被 `_route_index()` 抓去当这条路由的说明文案。
- **342** `def get(self):` — 纯只读、无参数、无外部依赖，所以没有任何 try/except（这里确实没有会失败的操作）。
- **343–344** 注释 — 说明为什么改成从注册表生成：手抄那份漂过两次（留着早已删掉的 /todos，同时漏掉 4 条真实路由）。
- **345–348** 返回体开头 — `service`、`flow`（流程图那串文字）、`endpoints: _route_index()`；后者遍历 `_ROUTES`，取各 Resource 的 docstring 首行当描述，并用 `_PATH_DISPLAY` 把 `<int:task_id>` 显示成 `<id>`。
- **349–350** `"models": sorted(set(ALIASES.values()))` — ALIASES 的 **value** 才是内部键（`cnn` / `算法模型1` / `模型1` 都指向 `1dcnn`），所以先 set 去重再排序，得到 `['1dcnn','adtk','cwt_cnn']`。它回答的是"别名表认识哪些模型"，**不含**上传的自定义模型。
- **351** `}` — 直接返回 dict，flask_restful 会 jsonify 成 200；这四个字段名被前端接口索引页消费，不能随意改。

## 行 352–379 · `class Health(Resource)` / `.get()`

**作用**：服务 / 数据库 / 模型产物的体检接口，被前端首页概览当作"后端是否可达"的探针。

- **352** `class Health(Resource):` — 注册在 `/health`（1466）。
- **353–357** docstring — 声明"刻意不抛异常"的理由：数据库连不上也算服务活着，只在 `database.ok` 里标失败，否则前端会把"库挂了"显示成"服务不可用"。
- **358** `def get(self):` — 无参数、无请求体。
- **359–361** `db_state = database.ping()` — ping 内部 `ensure_schema()` + `table_counts()`，并把任何异常吞成 `{ok: False, error: ...}`（`db.py:280-290`），所以库挂了这里照样返回 200，前端只需看 `database.ok`。注意 `table_counts()` 带 30 秒缓存（`db.py:761`），首页 KPI 的行数可能滞后最多 30 秒，这不是"没刷新"。
- **362** `artifacts = list_artifacts()` — 扫 `data/models`，每个模型一条 Artifact（跳过 `.staging-*` 和隐藏目录）。
- **363–366** 返回体的前四项 — `service`（写死 `"ok"`）、`config: config.describe()`（快照，**刻意不含**账号密码）、`database: db_state`（原样透出 ping 结果）。
- **367–371** `artifacts` — `count` 是产物个数，`models` 是名字清单。注释说"每个模型只有一个产物"，这与 `save_artifact` 的"一模型一产物、直接替换旧产物"设计一致。
- **372** `"figures": {...}` — `count` 是 `list_figures(limit=1000)` 的长度，而 `list_figures` 是"按 mtime 倒序、凑够 limit 就 break"，所以图库超过 1000 张时这个 count 会**钉在 1000**，不是真实总数；`dir` 是 `FIG_DIR` 的绝对路径（出口脱敏会把它换成相对路径，前端 `health.figures?.dir` 就显示这个）。
- **373–378** `warnings` — 两条**写死的**说明文本（不排队、/train 同步阻塞；数据管线越界切片那个已修正的坑），不是运行时探测结果，也不会因为情况变化而消失，纯粹是给使用者看的提示。
- **379** `}` — 整个返回体没有任何分支会变成非 200。

> ⚠️ 存疑：`"service": "ok"`（364）是写死的常量，而前端首页把它直接当健康判据——`<el-tag :type="health.service === 'ok' ? 'success' : 'danger'">`（`frontend/.../home/index.vue:19`）。也就是说这颗标签**恒为绿**，只有整个请求失败才会红；它不表达任何后端状态。真正的健康信息在 `database.ok` 与 `artifacts.count` 里。

> ⚠️ 存疑：docstring 说"前端顶栏每 15 秒轮询它"，但我在仓库里找不到任何 15 秒定时器：前端只在**首页挂载时调用一次**（`home/index.vue:117-129` 的 `onMounted(load)` 里 `platformApi.health()`）；`db.py:220` 的注释写的也是"前端页面一加载就并行打出 /health、/models、/trainings、/inference-tasks 四个请求"，与前端实现一致。"15 秒轮询"只出现在这条 docstring 里，是过期描述。

> ⚠️ 存疑：docstring 承诺"刻意**不抛异常**"，但真正被兜住的只有数据库那一句（`ping()` 自己不抛）。362 的 `list_artifacts()` 和 372 的 `list_figures()` 都在任何 try 之外，而 `list_artifacts()` 会对 `data/models` 下**每个目录名**调 `registry._model_dir()`（`registry.py:197`），后者对不合规名字直接 `raise ValueError`（`registry.py:73`，正则只允许 `\w`/中文/点/横线）。依据：只要 `data/models` 下出现一个带空格或括号的手工目录（例如从别处拷进来的"新建文件夹"），`/health` 与 `/models` 就会双双 500，与本节"不抛异常"的设计目标冲突。`list_figures()` 里的 `path.stat()` 也会在"边扫边被删"的竞态下抛 FileNotFoundError，属同类问题（概率低）。

## 行 380–399 · `class ModelList(Resource)` / `.get()`

**作用**：GET `/models` —— 磁盘产物 + 库表登记两份清单，故意不合并。

- **380** `class ModelList(Resource):` — 与 `ModelCreate` 共用 `/models`（1467、1475）：GET 走这个类、POST 走那个类。
- **381–385** docstring — 说明为什么不合并：产物可能还没登记（落盘成功但写库失败），登记也可能没有产物（只占位未训练），前端要能看出这种不一致。
- **386** `def get(self):` — 无参数。
- **387** `artifacts = list_artifacts()` — 扫磁盘产物，放在 try 之外（见 Health 节那条 ⚠️：这里的 ValueError 会直接冒到 flask_restful 变成 500）。
- **388–390** `try: db_models = database.models_in_db() except DBError as exc:` — 只有库查询这一句被兜住；`DBUnavailable` 是 `DBError` 的子类（`db.py:34`），所以"库连不上"也走这条分支。
- **391–393** `db_models = [{"error": str(exc)}]` — 把错误塞进列表而不是回 503：磁盘产物照样能列出来，前端只在"库表"那一列标不可用。代价是这一列不再是纯 Models 行列表，前端渲染时必须容忍这条没有 ModelID/ModelName 的假记录。
- **394–396** `"artifacts": [a.to_dict() for a in artifacts]` 与 `"db_models": db_models` — 用 `to_dict()` 只挑 12 个字段，避免 meta 里的 history 曲线与 classification_report 文本把响应撑大几十倍（`registry.py:45-63`）。
- **397–398** `"known_models": {name: MODEL_META[name] for name in MODEL_META}` — 用推导式做一份**浅拷贝**（值仍是同一批 dict 对象），等价于 `dict(MODEL_META)`；给前端下拉框和说明文案用，是"内部键 → db_name/description/type"的权威映射（`training.py:43`）。
- **399** `}` — 三个字段名都被模型页消费。

## 行 400–447 · `class DatasetList(Resource)` / `.get()`

**作用**：数据集体检——内置 .mat 数据集与 `data/datasets` 下上传的表格数据集各体检一遍，返回 `{数据集名: 体检结果}`。

- **400** `class DatasetList(Resource):` — 注册在 `/datasets`（1468）。
- **401** docstring — 一句话说明两类数据源。
- **402** `def get(self):` — 无参数。
- **403–407** 内层 docstring — 说明"单个数据集出错只写进它自己的 error 字段，不让整页 500"。
- **408** `out = {}` — 累积结果，最后直接当响应体。
- **409–410** 注释 — 说明 `config.dataset_dirs` 是 `{前端口径的数据集名: 真实目录}`，返回的是映射所以遍历顺序无所谓（前端按 key 取）。
- **411** `for name, path in config.dataset_dirs.items():` — 内置只有两项：`CWRU-0HP → 1DCNN/0HP`、`CWRU-0HP(cwt) → cwt_cnn/0HP`（`config.py:37-40`）；键就是 `/datasets/signal` 要的 `dataset` 参数。
- **412–420** matlab 分支 — `ds.describe_dataset(path)` 用 `whosmat` 只读 .mat 头（不 loadmat，避免几百 MB 解析开销），然后补三个给前端用的字段：`dataset_type="matlab"`（前端 `isTabular` 据此为 false，见 `dataset/index.vue:169`）、`key`（唯一标识）、`dataset_dir`（绝对路径，出口脱敏会换成相对路径）。这段**没有** 120 秒缓存，`datasets.describe_dataset` 里那层废弃缓存已删除，但 `whosmat` 本身足够快。
- **421–425** matlab 失败分支 — 读失败也要占住自己的 key，返回 `error` + `dataset_dir` + `dataset_type` + `key`。跳过（少一行）会被误读成"数据集被删了"，整页 500 则连别的数据集都看不到。注意这条分支**没有**补 `file_count`/`classes`，前端用 `d.file_count ?? 0` 兜（`dataset/index.vue:184`）。
- **426–430** `upload_root = sorted([...]) if config.upload_dir.is_dir() else []` — 先判 `is_dir()` 再 `iterdir()`：目录不存在时 `iterdir()` 抛 FileNotFoundError 会让整个 `/datasets` 挂掉，这里当成"还没上传过数据集"。排序只影响返回映射的构造顺序（前端不依赖），作用是让日志/截图稳定可复现。补充：`upload_dir` 在 config 导入时就会被 mkdir（`config.py:46-47`），所以这条兜底实际挡的是"运行中被人删掉目录"。
- **431** `for directory in upload_root:` — 一个子目录 = 一个表格数据集。
- **432–434** `key = f"表格:{directory.name}"` — `表格:` 前缀既是返回体的 key，也是 `/datasets/signal` 用来认出"这是上传目录下的数据集"的口径（它靠这个前缀决定去 `data/datasets/<名>` 找文件）。
- **435–439** `info = tabular.describe_directory(directory)` — 会**真读一遍**目录里每个文件，所以带 120 秒 TTL 缓存；刚上传完这里还显示旧内容不是文件没进去，而是缓存没清（`/datasets/upload` 里那句 `cache_clear()` 就是为它加的）。
- **440–441** 体检失败 → `{"error": ..., "files": []}`，仍往下走。
- **442–445** `info.update({...})` — 无论成败都补齐 `key`/`dataset_type`/`dataset_dir`/`file_count`/`classes` 五个字段，前端不用到处判 key 在不在；`info.get("file_count", 0)` 只在"体检抛异常"那条路上生效（空目录本来就是 0/0，比 null 好渲染）。
- **446** `out[key] = info` — 表格数据集也进同一个映射。
- **447** `return out, 200` — 注意返回的是**裸映射**（不是 `{"datasets": ...}`），前端 `datasets.value = await platformApi.datasets()` 直接把它当字典用，所以顶层键只能是数据集名。

> ⚠️ 存疑：444 的 `info.update(...)` 是**就地改写**。当 `describe_directory` 命中 120 秒缓存时，它返回的是缓存里**同一个 dict 对象**（`tabular.py:280-286` 把函数返回值直接存进 store 再返回），于是这几行把 `key`/`dataset_type`/... 也写进了缓存条目。当前是幂等的（这些值都由目录名/目录路径推出，同一目录重复调用结果相同），所以看不出问题；但它属于"把共享可变对象当私有对象改"，一旦将来有第二个调用方想用不同的 `key` 复用同一条缓存就会串味。

## 行 448–494 · `class DatasetUpload(Resource)` / `.post()`

**作用**：POST `/datasets/upload` —— 把 multipart 上传的表格文件落到 `data/datasets/<数据集名>/`，一个文件 = 一个类别。

- **448** `class DatasetUpload(Resource):` — 注册在 `/datasets/upload`（1483）。
- **449** docstring — 一句话说明落盘位置与"一文件一类别"的约定。
- **450** `MAX_MB = 80` — 类属性当常量用；它与模型上传那条链路里的 `max_mb`（由调用方传，见 `_upload_blobs`）是**两套独立**的限制，改一个不会同步另一个。
- **451** `def post(self):` — 只接受 multipart。
- **452** docstring — 重申"文件名即标签"。
- **453** `name = (request.form.get("name") or "").strip()` — 表单字段；`or ""` 是为了让后面的空值判断统一（前端 `dataset/index.vue` 的"数据集名"输入框就传这个）。
- **454** `files = _uploaded_files()` — 取 `file` 字段，取不到再退回旧写法 `files`（`api.py:1079-1084`），所以两种字段名都能用。
- **455–456** 一个文件都没收到 → 400。这一步在 mkdir 之前，所以"完全没传文件"不会留下空目录。
- **457–458** 没给名字就用第一个文件名的 `stem` 当数据集名（`a.csv → a`）。
- **459** `safe_name = _sanitize_name(name, "dataset")` — 落盘前必须净化，否则 `name` 里带 `/` 或 `..` 就能写到 `upload_dir` 之外。
- **460–461** `target = config.upload_dir / safe_name; target.mkdir(parents=True, exist_ok=True)` — **无条件**创建目标目录，逐个文件的校验在它之后（这是下面第一条 ⚠️ 的根因）。
- **462** `saved, skipped, overwritten = [], [], []` — 三个回报列表，前端要把"哪些收了、哪些没收、哪些被覆盖"逐条展示。
- **463** `for item in files:` — 逐个处理。
- **464** `filename = Path(item.filename or "").name` — 削成纯文件名挡穿越：Windows 上 `Path` 是 WindowsPath，`Path("a\\b.csv").name == "b.csv"`，所以这里够用（`_upload_blobs` 里写成 `.replace("\\","/")` 是为了在 POSIX 上也成立，此处行为等价）。
- **465–468** 扩展名白名单（`tabular.TABLE_SUFFIXES = {.csv,.txt,.xlsx,.xlsm,.xls}`）——不支持就记进 `skipped` 并 `continue`，**不是**直接 400：接口语义是"能收的收，不能收的逐条说明原因"。
- **469** `blob = item.read()` — 把整个文件读进内存（下面第二条 ⚠️）。
- **470–472** 空文件拒收：0 字节会变成一个"空类别"，训练切窗时按 0 行炸，所以宁可在入口挡掉。
- **473–475** 大小上限 `MAX_MB`（80MB）。
- **476–478** `destination = target / filename`；`replaced = destination.is_file()` 先记下"是否覆盖"；`write_bytes` 落盘（同名静默覆盖，`replaced` 只是把这个事实回报出去）。
- **479–480** 覆盖过就把文件名记进 `overwritten`。
- **481–483** `saved` 追加 `{filename, size_kb, path, label, replaced}` — `label = tabular.label_from_filename(filename)`（去扩展名），与训练侧"文件名即标签"的口径一致。
- **484–485** `tabular.describe_directory.cache_clear()` — 缓存键里不含 mtime，不清就会在 TTL 内继续报旧内容。注意 `cache_clear` 实现是 `store.clear()`（`tabular.py:290`），清的是**所有**目录的缓存条目，不是只清本次目标目录：代价是别的数据集下次访问多体检一遍，换来语义简单。
- **486–489** 立刻重新体检目标目录并放进响应（`listing`），失败只写 `{"error": ...}`，不影响状态码判定。
- **490–493** 响应体 — `dataset`/`directory`/`saved`/`skipped`/`overwritten`/`listing`，外加 `hint`：只有在真发生过覆盖时才给那句"同名文件已被覆盖……覆盖会直接换掉那个类别的全部数据"的告警（`path`/`directory` 里的绝对路径由出口脱敏处理）。
- **494** `200 if saved else 400` — 只要有**一个**文件落盘就是 200（部分成功也算成功），全被跳过才 400。

> ⚠️ 存疑（失败的上传会留下一个空数据集）：460–461 先建目录，494 却可能返回 400 且 `saved` 为空——例如用户传了一个扩展名不在白名单里的 `.rar`，校验在 mkdir 之后（465–468 只 `skipped.append`，不删目录）。这个 `data/datasets/<名>/` 已经留在磁盘上，而 `/datasets` 会把 `upload_dir` 下**每个**子目录都列成 `表格:<名>`（429–434），前端也会照常渲染它（`dataset/index.vue:61-63` 显示"0 文件 / 0 类"）。也就是说"上传失败"会在数据集列表里凭空多出一个空数据集，且没有任何字段能区分它和"真实存在的空目录"。

> ⚠️ 存疑（80MB 只保护磁盘，不保护内存）：473 的大小判断发生在 469 `item.read()` **之后**，所以一个 2GB 的上传会先被完整读进内存才被拒。Flask 侧也没有更早的闸——`main.py` 没有设置 `MAX_CONTENT_LENGTH`（全仓库 grep 无此配置），Werkzeug 只在超过 500KB 时把上传体落到临时文件，`item.read()` 仍会把整份内容搬进 RAM。要真正挡住大文件得用 `request.content_length` 提前判断，或给 Flask 设 `MAX_CONTENT_LENGTH`。

> ⚠️ 存疑（本方法没有任何 try/except）：与"每个方法自己把参数错翻成 400"的约定不符——`mkdir`/`write_bytes` 抛 OSError（磁盘满、目录只读、Windows 保留名如 `CON`）时会直接冒到 flask_restful 变成 500（项目没有全局异常处理器，`register_api` 末尾 1522-1525 解释了为什么 `@app.errorhandler` 够不着）。这里能抛的还有 `_sanitize_name` 对超长名字生成的目录名（超过文件系统上限时 mkdir 抛 OSError），同样没有兜底。

## 行 495–522 · `class TablePreview(Resource)` / `.get()`

**作用**：GET `/datasets/table?path=...&rows=...&column=...` —— 表格预览：列统计 + 前 N 行 + 推荐信号列。

- **495** `class TablePreview(Resource):` — 注册在 `/datasets/table`（1484）。
- **496** docstring — 说明它被"数据展示/数据集管理"两处页面共用。
- **497** `def get(self):` — 参数全在 query string 里。
- **498–501** `raw = request.args.get("path"); if not raw: return {"error": "缺少 path 参数"}, 400` — path 必填；`?path=`（空串）也走 400，因为空串是 falsy。这一层在 try 之外，所以它只可能是 400。
- **502–504** 注释 — 提醒必须走 `_resolve_workspace_path()` 而不是自己拼 Path（两级回退 + `relative_to` 判越界）。
- **505** `try:` — 校验 + 预览共用一个大 try。
- **506** `path = _resolve_workspace_path(raw)` — 越界或不存在 → InvalidInput（400）。
- **507–510** 扩展名白名单先行 — `tabular.is_table(path)` 只看后缀不打开文件（所以很便宜），不是 csv/xlsx/xls 就直接 400 说清楚，别等 pandas 抛一层看不懂的错再回 500。放在 try 里纯粹为了共用下面那个 `except Exception`（注释自己也这么写）。
- **511–512** 注释 — 解释 `rows` 的 `or 20` 语义，以及与 `/predict` 的 `limit` 为何不能照抄。
- **513–514** `data = tabular.preview(path, rows=_int(request.args.get("rows"), 20, "rows") or 20, sheet=..., column=...)` — rows 缺参时 `_int` 就给 20；`or 20` 只在 rows=0 时生效（0 行预览没意义，退成 20 可接受）；`preview` 内部还会把行数夹到 1..200（`tabular.py:219`），所以 `rows=-5` 会变成 1、`rows=99999` 变成 200。`sheet`/`column` 缺省传 None，交给 tabular 走默认（第 0 个工作表、自动挑信号列）。前端只传 path/rows/column（`platform/index.ts:60-61`），**从不传 sheet**，所以界面上永远只能看 Excel 的第 0 个工作表。
- **515–518** `except InvalidInput: return {"error": str(exc)}, 400` — 这一档**必须**排在 `except Exception` 之前：InvalidInput 是 ValueError→Exception 的子类，顺序反了就掉进 500 分支，与其它接口"参数错→400"的口径不一致（`?rows=abc` 走的就是这条，由 `_int` 抛出）。顺带：`_resolve_workspace_path` 的"路径不存在"也从这里出去，所以那是 400 而不是 404。
- **519–521** `except Exception: return {"error": f"{type(exc).__name__}: {exc}"}, 500` — 文件损坏/加密/列名对不上/不是数值列……统一算"这份表格读不出来"。这类不是参数错，回 500 但带上异常类型便于定位（前端只展示 error 文本）。
- **522** `return data, 200` — 成功时把 `tabular.preview` 的整个 dict 原样透传；前端依赖 `format/rows/cols/size_kb/columns/column_names/numeric_columns/signal_column/head/head_rows/sheets/sheet` 这些字段（`dataset/index.vue:73-100`），字段名不能随便改。

## 行 523–585 · `class Train(Resource)` / `.post()`

**作用**：POST `/train` 的训练入口。本层只做**参数校验与归一化**，真正的训练同步跑在 `training.train()` 里，所以一个请求会占用十几秒到几分钟。

- **523** `class Train(Resource):` — 注册在 `/train`（1469）。
- **524–528** docstring — 点明"这一层只做参数校验与归一化（模型名、epochs、rate、dataset_dir 的路径安全）"，并提醒接口耗时长、不能并发压。
- **529** `def post(self):` — 请求体走 `_body()`。
- **530** `body = _body()` — 非 JSON / 非对象一律得到 `{}`，于是"什么都不传"等价于"全用默认值"。
- **531** `try:` — 校验段从 532 到 572，只有这一段被 573/576 两个 except 覆盖（结尾 580 的 `train()` 调用在 try **之外**，见下面第一条 ⚠️）。
- **532** `name = normalize_model(body.get("model"))` — 别名→内部键；不传就是 `"1dcnn"`（`training.py:61-73`）；认不出的名字抛 ValueError（**不退回默认值**，避免静默换成另一个模型训练），由 576 翻成 400。
- **533** `epochs = _int(body.get("epochs"), None, "epochs")` — 缺参得 None；`"5"→5`；`"abc"`→InvalidInput→400；`5.9→5`（截断）。None 表示"不写进 options"，让 trainer 用自己的默认值（1dcnn 10 轮、cwt_cnn 50 轮，`training.py:185/286`）。
- **534–535** `if epochs is not None and not (1 <= epochs <= MAX_EPOCHS): raise InvalidInput(...)` — MAX_EPOCHS=200（`api.py:47` 的注释写明"防止一条 HTTP 请求把服务占住几小时"）。None 时跳过校验，所以"不传 epochs"不会被这条拦住。
- **536–537** `rate = body.get("rate")` + 注释 — 不校验 rate 会一路炸到除零/空训练集（最终以 500 收场，见下面第三条 ⚠️ 的实际路径）。
- **538–539** 形状校验 — 必须是 `list`/`tuple` 且长度 3。tuple 也放行是为了兼容内部/测试调用（JSON 里只可能是数组），核心约束是"长度 3"这个形状。
- **540–543** `values = [float(x) for x in rate]` — 逐项转 float，字符串数字（`"0.7"`）也接受；转不动抛 InvalidInput 并回显原值。
- **544–546** 非负 + 和≈1 — `any(x < 0 ...) or abs(sum(values) - 1.0) > 1e-6`；1e-6 容差是为了容忍 `0.1+0.2+0.7 = 0.9999999999999999` 这类浮点误差。和不为 1 会让下游按比例算出的数据集大小与声明不符（切多/切少，静默出错）。
- **547–548** `if values[1] + values[2] <= 0: raise InvalidInput("rate[1]+rate[2] 必须大于 0（验证/测试集不能为空）")` — 前一条挡不住"全给训练集"：`[1.0, 0.0, 0.0]` 非负且和为 1，但验证/测试集一个样本都没有，训练完算不出指标、adtk 也拿不到基线。这条是它的补充。
- **549** `body["rate"] = values` — 把归一化后的 float 列表写回 body，好被 550 的 options 推导式捞走；这也解释了为什么它必须排在 550 之前（否则 `options["rate"]` 会是原始 int/字符串混合的列表）。
- **550** `options = {k: v for k, v in body.items() if k not in ("model",)}` — 除 `model` 外**整个请求体原样透传**给 trainer。训练侧真正读的是 `dataset_type`/`dataset_dir`/`dataset`/`signal_column`/`sheet`/`epochs`/`batch_size`/`rate`/`seed`/`normal`/`strict`/`legacy_scaler`（`training.py:129-170`、`load_dataset`）。
- **551–553** 这个 for 循环把 `dataset_type`/`dataset_dir`/`signal_column`/`sheet`/`dataset` 再塞一遍（见下面第二条 ⚠️）。
- **554** `if body.get("dataset_dir"):` — 只处理非空值：空串/None 都当"没传"。空串会被 550 原样放进 options，但训练侧用 `if raw_dir:` 判断（`training.py:130`），同样当没传 → 用内置 `CWRU-0HP`，所以这条 falsy 语义前后一致。
- **555** `candidate = Path(body["dataset_dir"])` — 只解析，不碰磁盘。
- **556–557** 绝对路径 → `candidate.resolve()` 直接用。
- **558–563** 相对路径的两级回退 — 先 `workspace_dir/candidate`，**存在就用**，否则 `project_dir/candidate`。必须两边都试的原因与注释一致：响应脱敏后前端拿到的是"相对工作区"的路径（`testRestfulProject\1DCNN\0HP`），只按 project_dir 拼会得到 `testRestfulProject\testRestfulProject\...`，训练侧就会报"数据集目录不存在"。判断用的是 `first.exists()`（存在即可，不区分文件/目录），这和 `_resolve_workspace_path` 的 `is_file()` 不同——这里要的是目录，存在性检查刚好合适；代价是工作区里若有个**同名普通文件**会抢先命中，最终由训练侧报错（边界情况，实际很难踩到）。
- **564–565** 注释 — 说明为什么用 `relative_to` 而不是字符串 startswith（`D:\22project_evil` 同前缀绕过），并与 `inference._guard_path` 保持同一口径。
- **566–569** 越界判定 — `resolved.relative_to(workspace.resolve())` 抛 ValueError → `raise InvalidInput("dataset_dir 必须在工作区内")`。这条拦的是"用训练接口去读工作区外的任意目录"（训练会真去读文件）。
- **570** `options["dataset_dir"] = str(resolved)` — 传**绝对路径**给训练层，绕开 `training.resolve_source` 里"相对路径按 project_dir 拼"的旧口径，避免二次拼接出错。
- **571–572** `if epochs is not None: options["epochs"] = epochs` — 这一行与 551 那个循环不同，**是有效的**：它把 epochs 从原始字符串（`"5"`）换成 `_int` 得到的 int，训练侧因此不必再解析 `"5"`，落库/日志里的 epochs 类型也统一（`training.py:604` 直接取 `params["epochs"]` 写库）。
- **573–575** `except FileNotFoundError → {"error", "hint"}, 409` — hint 指路"CWRU 默认目录是 1DCNN/0HP"（见下面第一条 ⚠️：这档实际是死分支）。
- **576–579** `except ValueError → {"error": str(exc)}, 400` — 合并处理"未知模型名""rate 不合法""dataset_dir 越界""表里没有数值列""基线文件缺失"等。注释说明了为什么不必再单列一档 InvalidInput（它是 ValueError 子类，两者都是"参数错→400+同一句话"）。这里是**唯一**给参数错的出口，所以每个 raise 的消息都必须能直接展示给用户。
- **580** `result = train(name, options)` — 在 try **之外**调用：训练是同步阻塞的（1DCNN 10 轮约 15 秒），返回时已经结束。
- **581** `http = 200 if result["status"] == "成功" else 500` — `train()` 不抛异常，它把失败写进 `result`（`status="失败"` + `error` + `traceback`），所以"训练失败"在 HTTP 上是 500 加一份完整报告，而不是空 body。
- **582–584** `if (result.get("db") or {}).get("written") is False: result["warning"] = ...` — `train()` 一定会在 `result["db"]` 里放一个 dict（`training.py:620-627`，成功 `written: True`，失败 `written: False` + `error`），`or {}` 只是防御。这条的意义是：产物可能已经落盘、但库里没有 Trainings 行，调用方只看 `status` 会误判。
- **585** `return result, http` — 注意 200 与"落库成功"无关：训练成功 + 写库失败仍是 200 + warning。

> ⚠️ 存疑（573 的 409 是死分支）：注释写的是"数据目录不存在 / 目录里没有可用数据文件"，这两句文案正是 `training.resolve_source` 抛的（`training.py:137` 与 `148`）——但它是在 **580 行的 `train()` 里**抛的，而 `train()` 调用在 try 之外，且 `train()` 内部 `except Exception` 已经把 FileNotFoundError 吞成 `status="失败"`（`training.py:574-576`）。try 体内其余操作（`normalize_model`/`_int`/`float`/`Path.resolve`/`relative_to`/`exists`）都不会抛 FileNotFoundError（`Path.resolve()` 非 strict 不抛，`exists()` 吞 OSError）。**结论：数据集目录不存在时永远走不到 409**，客户端实际拿到的是 581 给的 500 + `{"status":"失败","error":"FileNotFoundError: 数据集目录不存在：..."}`。要恢复 409，得把判断挪到 `train()` 的返回值上（例如识别 `result["error"]` 的前缀），或让 `train()` 把这类异常重新抛出。

> ⚠️ 存疑（551–553 是死代码）：550 的推导式已经把 `dataset_type`/`dataset_dir`/`signal_column`/`sheet`/`dataset` 全部放进 options 了（它们都不叫 `model`），而这 3 行的条件 `is not None` 只会**跳过**赋值、永远不会补出推导式没放进去的值，所以它对 options 没有任何影响。读代码的人很容易以为这里做了"只挑这几个键"的过滤，其实没有——真正的过滤根本不存在，`{}` 里连拼错的键都会透传。附带后果：把 `epochs` 拼成 `epoch` 之类的请求**不会报错**，训练侧 `opts.get("epochs", 10)` 拿不到就用默认值，用户看到的是"参数没生效"。

> ⚠️ 存疑（rate 校验挡不住 NaN）：538–546 的四道检查对 NaN 全部失效。依据：`float("nan")` 不抛异常；`nan < 0` 为 False，所以"非负"检查放过；`sum([nan,nan,nan]) - 1.0` 是 nan，而 `abs(nan) > 1e-6` 也是 **False**，所以"和为 1"也放过；`values[1] + values[2] <= 0` 同样是 False。于是 `{"rate": ["nan","nan","nan"]}`（或 JSON 里裸的 `NaN` 字面量，Python 的 `json.loads` 默认接受）会被写进 `body["rate"]` 并透传给训练，在下游变成 `datasets.py:159` 的 `int(number * (1 - (rate[1]+rate[2])))` → `ValueError: cannot convert float NaN to integer`（或 `datasets.py:239` 的 `test_size = rate[2]/(rate[1]+rate[2])` 这个 NaN），最终以一条**看起来与 rate 参数无关**的报错 + 500 收场。对比：`inf` 反而会被"和为 1"挡下（`inf-1.0` 是 inf，`> 1e-6` 为真）。修法是在转换后加一句 `math.isfinite(x)`（或 `sum(values) != sum(values)` 这种自比较）。

> ⚠️ 存疑（注释暗示三项都参与运算，实际只有后两项）：544 行的注释说"三项非负且和为 1：否则切出来的数据集大小算不对"，但下游只用 `rate[1]`、`rate[2]`：`datasets.py:159` 用 `number*(1-rate[1]-rate[2])` 定训练窗口数，`datasets.py:239` 用 `rate[2]/(rate[1]+rate[2])` 定划分比例，`rate[0]` 只被写进 meta/stats 供展示（`datasets.py:235-238` 的注释明说"rate[0] 不参与任何运算"）。所以 `[0.6,0.2,0.2]` 与 `[0.8,0.2,0.2]` 切出的训练/验证/测试规模**完全相同**，"和为 1"这条约束在这里只是形式上的——接口注释没写这一点，容易被误解成 rate[0] 会影响数据量。

## 行 586–610 · `_recent_list()`

**作用**：`GET /xxx?limit=N`（默认 20、上限 200）的"最近 N 条"读库接口，`/trainings` 与 `/inference-tasks` 共用。

- **586** `def _recent_list(key: str, fetch):` — `key` 是响应里的字段名，`fetch` 是 `database.recent_trainings` 这类绑定方法。
- **587–590** docstring 第一段 — 说明抽出来的理由：两个接口的方法体本来 12 行逐字重复，只差"取哪个 dict 键 / 调哪个 db 方法"。
- **591–592** `limit` 语义 — `_int()` 负责把缺参变默认 20（转不动抛 InvalidInput），`min(..., 200)` 再夹上限，防止一次把整张表拉回来。
- **593–596** docstring 的 `or 20` 说明 — `limit=0` 是 falsy，会被悄悄换成 20（不是 0 条）：对"最近 N 条"列表接口，0 条本来没意义，退成默认值与用户意图一致，所以这里可以接受；同样的写法搬到 `/predict` 的 limit 上就是 bug（那边 0 有语义），所以 `Predict.post` 刻意写成 `_int(body.get("limit"), 1, "limit")` + 独立的范围校验（`api.py:665-670`，注释还专门写了"不能写成 `or 1`，否则 limit=0 会被换成 1 放过去、绕过范围校验"）。两处写法不一致是**故意的**。
- **597–598** docstring 的第二条警告 — `_int()` 转不动时抛 InvalidInput，而 flask_restful 会把非 HTTPException 变成 500（Flask 的 errorhandler 够不着，见 `register_api` 末尾），所以这里必须自己 try 出 400。
- **599–601** docstring 的第三条警告 — `limit` 最终由 db.py 用 f-string 拼进 `LIMIT {int(limit)}`（`db.py:491`），安全性全靠 API 层保证它"是整数且 ≤200"。
- **602–603** `try: limit = min(_int(request.args.get("limit"), 20, "limit") or 20, 200)` — 缺参→20；`"abc"`→InvalidInput；`0`→20（falsy 回退）；上限 200 在这里夹住。`min()` 只夹上限，下限没有处理（见下面第一条 ⚠️）。
- **604–605** `except InvalidInput as exc: return {"error": str(exc)}, 400` — 只兜 `_int` 那一句，所以 `?limit=abc` 是明确的 400 而不是 500。
- **606** `try:` — 第二次 try，只管读库。
- **607** `return {key: fetch(limit), "dialect": database.dialect}, 200` — 字段名由 `key` 决定：`/trainings` 传 `"trainings"`、`/inference-tasks` 传 `"tasks"`（614、710 行），前端就是按这两个名字取的（`home/index.vue:125-126` 的 `(t as any).trainings` / `(k as any).tasks`），写错的话前端只会得到 undefined 而不会报错。`database.dialect` 是 `__init__` 里从配置赋的普通属性（`db.py:106`，值恒为 `"mysql"`），取它不需要连库，所以库挂了也能带上。
- **608** `except DBError as exc:` — 连接类失败（`DBUnavailable` 是 `DBError` 子类）会走这里。
- **609** 注释 — 读库失败 → 503 且带 dialect，让前端提示"数据库不可用"，而不是显示成"没有记录"。
- **610** `return {"error": str(exc), "dialect": database.dialect}, 503` — 与 607 一样保留 `dialect` 字段，前端不必为错误态单独分支。

> ⚠️ 存疑（负数 limit 会 500，而不是 400/200）：603 只夹了上限，`min(-3, 200) = -3` 会原样拼成 `LIMIT -3`（`db.py:491`），MySQL 对这种写法定直接抛 `ProgrammingError (1064, ...)`；而 db.py 只在**连接失败**时把异常包成 `DBUnavailable`，`cursor()` 对语句错误是原样 `raise`（`db.py:185-190`），所以 pymysql 的 `ProgrammingError` 不是 `DBError`，608 这档接不住，最终变成 500（flask_restful 的兜底）。对照 `Predict.post` 的 `if not (1 <= limit <= MAX_LIMIT)`（`api.py:669-670`），这里缺的正是下限校验。触发方式极简单：`GET /trainings?limit=-1`。

> ⚠️ 存疑（上限 200 是硬编码字面量）：同文件里 `MAX_LIMIT = 500`（48 行，`/predict` 与 `/figures` 都用它，见 1207 行）；`/trainings`、`/inference-tasks` 却在 603 行写死 200。这是有意的差异（docstring 明确写"上限 200"），但同一个"单次最多读几行"的概念出现了两个魔法数、且新的那个没用已有常量。不是 bug，是容易漂的一处。

---

# 第 3 段 · 行 611–974

覆盖范围：`TrainingList`(611–614)、`_log_failed_inference`(615–650)、`Predict`(651–706)、
`InferenceTaskList`(707–710)、`InferenceTaskDetail`(711–727)、模型名三套写法换算器(728–764)、
`_rewrite_meta_model`(765–781)、`_rename_model`(782–824)、`_undo_rename`(825–855)、
`ArtifactDetail`(856–925)、`ModelOverview`(926–974)。行号以当前文件为准。

## 行 611–614 · `TrainingList`

**作用**：`GET /trainings` 的薄壳，真正的读库与 limit 处理全部委托给 586–610 的 `_recent_list`。

- **611** `class TrainingList(Resource)` — flask_restful 要求一个资源 = 一个类，`get()` 方法即 GET；路由在 `_ROUTES`(1470) 注册成 `/trainings`，1330 行那个手抄路由表已作废。
- **612** docstring — 只是说明这是读库列表接口；它不碰磁盘，所以没有产物也能列。
- **613–614** `def get(self)` + `return _recent_list("trainings", database.recent_trainings)` — 注意传的是**绑定方法对象**当回调，`_recent_list` 内部再 `fetch(limit)` 补上 limit；响应键 `"trainings"` 是唯一的差异点（`/inference-tasks` 用 `"tasks"`）。limit 的夹取（默认 20、上限 200）、`?limit=abc` → 400、读库失败 → 503 全在 `_recent_list` 里，本类不重复实现。

## 行 615–650 · `_log_failed_inference(name, exc, client_ip, body)`

**作用**：在 `/predict` 失败时**补写**一条 `ModelInvocations`（`IsSuccess=0`），让失败也有审计痕迹；整段是"尽力而为"，失败绝不影响原始异常的传播。

- **615** `def _log_failed_inference(name, exc, client_ip, body)` — 四个参数都是调用方 `Predict.post` 已有的现场信息；返回 `None`，因为它只负责写日志。
- **616–623** docstring — 说明动机：以前只在成功路径写调用日志，输入被拒/产物缺失这类更常见的失败零痕迹。关键的实现约束是"**不为写日志去 `ensure_model`**"——`ModelInvocations.ModelID` 是外键，凭空登记模型会污染 `Models` 表，所以下面只有查到已有训练行才写。
- **624–626** `from .training import db_model_name` — 函数内导入。api 顶层已经 `import` 了 training(42 行)，所以今天并不构成循环依赖；这条 import 只是历史形态，保留不影响行为。
- **627** `try:` — 从这里到 646 行整段写入都包在"尽力而为"的 try 里，对应 647–650 的兜底。
- **628–631** `row = database.latest_training(db_model_name(name), only_success=False)` — 两处细节：`only_success=False` 是刻意的（默认只认 `Status='成功'`，若该模型唯一一次训练就失败，锚点会取不到，失败日志又变零痕迹）；`latest_training` 内部按 `m.ModelName = ?` 精确匹配(db.py:508–510)，MySQL 本库是 `utf8mb4_unicode_ci`(db.py:661–662)，所以大小写写法差异能匹配上。
  > ⚠️ 存疑（中）：628 行的注释说"用户可能传中文别名"，但它调的是 `training.db_model_name`，而这个函数**只做"内部键 → 库名"一跳**，不做 `normalize_model` 的别名归一(training.py:51–60)。因此用户传 `cnn` / `1d-cnn` / `算法模型1` 时，`db_model_name` 原样返回该字符串，`latest_training` 查不到行 → `row` 为 None → 直接 return，**失败调用日志静默丢失**。api 里已有的 `_db_model_name()`(734) 才是完整两跳换算器，这里用错了（或注释写大了）。
- **632–633** `if not row: return` — 拿不到训练行就没有 `ModelID`/`TrainingID` 去满足 `ModelInvocations` 的两个外键，宁可少一条日志也不造假锚点。
- **634–640** 状态码映射 — `FileNotFoundError`(产物缺失) → 409、`ValueError`（`InvalidInput` 是其子类，inference.py:27）→ 400、其它 → 500。这三档与 `Predict.post` 的外层三档是同一套口径，写进日志的 `StatusCode` 才能与调用方实际收到的码对上账。
  > ⚠️ 存疑（低）：`DBError` 在这里落进 `else` 记 500，而 `Predict.post`(697) 把 `DBError` 映射成 400，并非"逐一对应"。实际不可达——`inference._write_db` 把库异常全吞进 `db.written=False`(inference.py:368–435)，`DBError` 逃不出 `predict()`。
- **641–646** `database.insert_invocation(...)` — `model_id`/`training_id` 显式 `int()` 转换：驱动返回类型不统一（可能是 Decimal/字符串），外键列必须先转干净。`api_endpoint` 硬编码 `"/predict"`（本函数只服务这一个接口）；`request_params` 用字典推导**剔除 `samples`**：内联样本动辄几百 KB，塞进 `ModelInvocations.RequestParams` 这个 LONGTEXT 会迅速膨胀；`response_result` 只存 `"异常类名: 消息"`，不回存请求体；`duration_ms=None`（失败路径没有可信耗时）；`status="失败"` 与 `is_success=False` 一起写，两个列都能被筛。
- **647–650** `except Exception: pass` — 只捕获 `try` 内的异常（含 `int()` 转换失败、列缺失的 `KeyError`、库连不上等）；必须吞掉，因为调用方在 `_log_failed_inference` 返回后会 `raise` 原始异常(694)，日志写入的二次异常若冒出去会把真正的失败原因替换掉。`650` 的 `pass` 就是这条"静默"的落点。

## 行 651–706 · `Predict.post`

**作用**：`POST /predict` 的全部入口逻辑——参数校验、调用 `inference.predict`、失败写日志、把异常翻译成 409/400/500，成功时给"落库失败"补 warning。

- **651–656** `class Predict(Resource)` + docstring — 说明入参二选一（`samples` 内联数组 / `path` 工作区文件）与成功响应结构（`predictions`+`summary`+`figures`+`db`）。
- **657–658** `def post(self)` + `body = _body()` — `_body()`(290) 用 `request.get_json(silent=True)`，非 JSON 或 JSON 不是对象时返回 `{}`，所以下面所有 `body.get()` 都不会因缺 body 而崩。
- **659** `try:` — 外层 try 覆盖"参数解析 + 调推理"，它的 except 只负责把异常翻译成状态码；这是"校验/调用/翻译"三段式的分界。
- **660–662** `name = (body.get("model") or "").strip()` — 刻意**不做**别名白名单：推理必须支持"上传进来的模型名"（不在 `1dcnn/cwt_cnn/adtk` 别名表里），名字如何映射到产物目录交给 `inference.predict`(446–455) 自己解析；目录安全由 registry 的 `_model_dir()` 净化兜底，口径与推理侧一致。
  > ⚠️ 存疑（低）：若 `body["model"]` 不是字符串（例如 JSON 里传 `123`），`.strip()` 抛 `AttributeError` → 落到 699 的兜底 → 500 + traceback；同类"参数类型错"在别处都是 400。
- **663–664** 空名 → `raise InvalidInput("model 必填")` → 400。
- **665–668** `limit = _int(body.get("limit"), 1, "limit")` — 默认值走 `_int` 的第二个参数，**不能**写成 `_int(...) or 1`：`0` 是 falsy，会被悄悄换成 1，从而绕过下面 669 的范围校验（`_int` 的 docstring 记录了这次事故）。`limit` 是"取多少个窗口"，服务端上限由 669 控制。
- **669–670** `if not (1 <= limit <= MAX_LIMIT)` → 400 — `MAX_LIMIT=500`(48) 是"一条 HTTP 请求最多切多少窗口"的硬闸，防止一次请求把内存/响应撑爆。
- **671–674** `index = _int(body.get("index"), 0, "index")` + 负值拒绝 — 负索引在 Python/NumPy 切片里表示"从尾部数"，会切出错位窗口却照样通过一切校验，所以必须显式拦成 400。
- **675–677** `top_k = _int(body.get("top_k"), 3, "top_k")` + `1..50` — 上限 50 是响应体积闸（`top_k` 会逐窗口回传候选列表）。
- **678–691** 内层 `try:` + `payload = predict(...)` — 十个实参逐一对齐 `inference.predict` 的签名(inference.py:437–440)：`samples`/`path` 是两种输入源，`index`/`limit` 决定从哪切多少窗，`training_id` 是显式外键锚点（`_int(..., None, ...)`：没传就是 None，由推理侧退回"最近一次成功训练"），`top_k` 控制候选宽度，`write_db=bool(body.get("write_db", True))` 让调用方可以只推理不落库，`client_ip=request.remote_addr` 进审计列（反代后面拿到的是代理 IP），`column`/`sheet` 给表格输入选列与选工作表。
  > ⚠️ 存疑（低）：`bool(body.get("write_db", True))` 对字符串 `"false"` 得到 `True`——JSON 里写成字符串会被当成"要写库"，只有真正的布尔/数字 `0` 才关得掉。
- **692–694** `except Exception as exc:` → `_log_failed_inference(name, exc, request.remote_addr, body)` → `raise` — 失败也要留审计记录；用裸 `raise` 而不是 `return`，因为同一个异常在不同类型下要映射成不同状态码，翻译权交给外层。
  > ⚠️ 存疑（中）：内层 try 只包住 `predict(...)` 调用。662–677 的参数校验失败（`model` 为空、`limit`/`top_k`/`index` 越界或非整数）都在内层 try **之外**抛出，因此**不会写调用日志**——而 616–619 的 docstring 恰恰把"输入校验被拒"列为要留痕的典型场景。想覆盖它需要把校验也挪进内层 try，或在每个 `raise` 前补日志。
- **695–696** `except FileNotFoundError` → 409 + `hint` — 409 表示"资源状态冲突"而非"参数错"：产物不存在（`registry.load_artifact` 在目录缺失/无权重时都抛它，registry.py:174–178）是"你得先训练"，`hint` 直接把下一步动作告诉调用方。
- **697–698** `except (DBError, ValueError)` → 400 — `InvalidInput` 是 `ValueError` 子类(inference.py:27)，所以**不需要单独一档**，两者都是"参数错 → 400 + 同一句话"。异常元组的书写顺序不影响匹配（两者都回 400）。
  > ⚠️ 存疑（低）：把 `DBError` 归进 400 意味着"服务端数据库故障"会被报成"你的参数有问题"，与 `_recent_list` 对同一异常回 503(609) 的口径不一致。实际同样不可达（见 634–640 的存疑）。
- **699–701** 兜底 `except Exception` → 500 + 最近 1500 字符 traceback — 截断是防响应过大；`pragma: no cover` 标记"这条分支不该被测到"。
- **702–706** 成功但落库失败时补 `warning` — `inference.predict` 对库故障**不抛异常**，而是返回 `db.written=False`+原因(inference.py:363–365)，所以"库里没这条记录"必须由 API 层翻译成显式警告，否则调用方只看到一个 200。703 行用 `(payload.get("db") or {})` 防空，避免 `write_db=false` 时 `None.get` 崩掉。最后返回 `(payload, 200)`。

## 行 707–710 · `InferenceTaskList`

**作用**：`GET /inference-tasks` 的薄壳，与 `TrainingList` 共用 `_recent_list`。

- **707–708** `class InferenceTaskList(Resource)` + docstring — 同上，纯读库列表。
- **709–710** `def get(self)` + `return _recent_list("tasks", database.recent_inference_tasks)` — 响应键是 `"tasks"`（不是 `"inference_tasks"`），前端按这个键取；`recent_inference_tasks`(db.py:543) 用 `LEFT JOIN Models`，所以任务行的 `ModelName` 可能是 `NULL`（模型行被删/上传时库写失败），前端要容忍。

## 行 711–727 · `InferenceTaskDetail`

**作用**：`GET /inference-tasks/<id>` —— 返回单个任务头 + 它的全部结果明细。

- **711–712** class + docstring — 明确是"任务 + 明细"两段合一。
- **713** `def get(self, task_id)` — `task_id` 由 Werkzeug 的路由转换器注入（`/inference-tasks/<int:task_id>`，_ROUTES 1473），不是从 query 里读的。
- **714–716** 注释 — `<int:...>` 已经保证进来的是整数，`/inference-tasks/abc` 根本不会进入本方法（在路由层就 404）；所以下面那层 `_int()` 是"防御性统一写法"，不是必需的校验。
- **717–720** `try: task = database.inference_task(_int(task_id, None, "task_id"))` / `except DBError` → 503 — 读库失败回 503 且与 `_recent_list` 同口径（"数据库不可用"而不是"没这条记录"）。
- **721–722** `if task is None` → 404 + 带 `InferenceTaskID` 的消息 — 用 NULL 语义区分"查到了但没明细"和"任务不存在"。
- **723–727** `return task` — `db.inference_task`(db.py:555–574) 已经做了两件事：两条 SELECT（任务行 + 该任务全部 `InferenceResults`，按 `ResultID` 排序保证顺序稳定），并把明细挂到返回字典的 `results` 键上，所以这里不需要再组装。直接返回**裸 dict**（不是 `(dict, 200)` 元组），flask_restful 默认 200。
  > 注意（非 bug）：明细**不分页**（db.py:560–562 也标注了），一次写了上千个窗口就是上千行 JSON；要支持大任务得在 db 层加 offset/limit 再由此处透传。

## 行 728–733 · 模型名"三套写法"总注释

**作用**：说明本文件里唯一的"名字语义地图"，也是下面三个换算器的使用说明。

- **728–729** 分隔线 + 说明 — 同一个模型有三套名字，写错一处就"找不到模型"或"建出重复行"。
- **730–732** 三套名字 — ① `1dcnn`：服务内部键（`MODEL_META` / `_TRAINERS` / 前端下拉 value）；② `1DCNN`：`Models.ModelName` 的正式名（给人和 SQL 看）；③ `1dcnn`：`data/models/` 下的产物目录名。①与③字面相同但**是不同概念**，改动时不要以为可以互用（内置模型的内部键恰好等于目录名，上传模型则不然）。
- **733** "凡是要拿用户输入去查东西，先过这里" — 描述的是本段这三个函数的适用场景。实际有个刻意的例外：`Predict.post`(662) 不走换算器，直接把原始名交给 `inference.predict`，因为推理必须支持别名表之外的上传模型名。

## 行 734–744 · `_db_model_name(raw)` —— 库表口径换算器

**作用**：任意写法 → `Models.ModelName` 的正式名（`1dcnn`/`cnn`/`模型1` → `1DCNN`）；**不抛异常**，用于一切"拿名字查库/写库"的入口。

- **734–739** `def` + docstring — 说明两跳换算与"认不出就原样返回"的语义：`normalize_model` 只认别名表里三个内置模型，上传模型不在表里会抛 `ValueError`，此时返回原文，因为 CRUD 场景本来就允许操作任意已登记的模型名。
- **740** `from .training import db_model_name` — 顶层(42)已导入 `MODEL_META`/`ALIASES`/`normalize_model`，但没导入 `db_model_name`，所以在这里单独引入；同一个模块的重复 import 只走一次 `sys.modules`，代价可忽略。
- **741–742** `return db_model_name(normalize_model(raw))` — 两跳：别名/大小写/中文 → 内部键（`normalize_model`），内部键 → 库名（`db_model_name`，`MODEL_META[key]["db_name"]`，training.py:60）。少走任何一跳都会出现"库里有行、按这个名字查不到"。
- **743–744** `except ValueError: return raw` — 只吞 `normalize_model` 的"未知模型"异常；返回原文（不 strip、不改大小写），因为上传模型的名字是用户自己定的，库里存的就是它。
  > ⚠️ 存疑（低）：`normalize_model` 对**空串/None** 走的是 `if not name: return default`(training.py:68–69)，默认 `default="1dcnn"`，于是 `_db_model_name("")` 会返回 `"1DCNN"` 而不是报错或返回空串。docstring 只声明了"认不出就原样返回"，没声明这条"空值静默退成 1dcnn"。当前路由都保证名字非空，所以是潜在坑而非现行 bug。

## 行 745–752 · `_artifact_key(raw)` —— 磁盘口径换算器

**作用**：任意写法 → 产物**目录名**（`1DCNN`/`1dcnn` → `1dcnn`）；供一切"要去磁盘找目录"的入口用，**不抛异常**。

- **745–750** `def` + docstring — 声明先换正式名、再在 `MODEL_META` 里反查内部键，查不到（上传模型）退化成小写原名；强调返回的是**小写**键，别拿它去写 `Models` 表。
- **751** `name = _db_model_name(raw)` — 复用库口径换算，好处是别名（`cnn`/中文）也能吃进来；代价是它对每个输入都先做一次 `normalize_model` 尝试。
- **752** `next((k for k, v in MODEL_META.items() if v["db_name"].lower() == name.lower()), name.lower())` — 生成器 + `next(默认值)` 是"找到第一个匹配就返回、否则给默认"的惯用写法；匹配用 `lower()` 比较，所以 `1DCNN`/`1dcnn` 都能落到 `"1dcnn"`。默认分支的 `name.lower()` 就是上传模型的目录名推导规则。
  > ⚠️ 存疑（中高）：默认分支强制 `lower()`，但上传落盘时保存的是**保留大小写**的名字（`safe = _sanitize_name(name, "model")`，api.py:1006 → `begin_artifact(safe)`），而 `inference.predict` 也是用原始大小写去取产物(inference.py:453)。于是上传一个叫 `MyModel` 的模型后，`GET /models/MyModel`、`/overview`、改名换算都会去找 `data/models/mymodel`：在 NTFS/Windows 上因大小写不敏感而侥幸可用，在大小写敏感的文件系统（Linux/Docker）上就会 404 或"没有产物"。

## 行 753–764 · `_safe_model_name(name)` —— 严格校验版（唯一会抛的换算器）

**作用**：模型名 → 磁盘安全形式，非法字符**直接拒绝**；**会抛 `InvalidInput`**，只给"改名"这类有副作用、必须让用户明确纠错的入口用。

- **753–758** `def` + docstring — 说明两条设计原则：不做静默替换（`a/b` 悄悄变 `a_b` 会让用户以为改成功了）、不设默认名（清洗后为空就是"这个名字不能用"）。
- **759** `safe = _sanitize_name(name, "")` — 复用 `_sanitize_name`(310) 的清洗规则（非法字符段替换成 `_`，再去掉首尾的 `.` `_`），但把 `default` 传**空串**，好让"清洗完什么都不剩"表现为 falsy。
- **760–761** `if not safe: raise InvalidInput("模型名不合法（不能只有符号）")` — 覆盖 `"..."`、`"___"`、`" . "` 这类全被剥掉的名字。
- **762–763** `if safe != name: raise InvalidInput(...)` — 这才是"拒绝而非替换"的核心：只要清洗结果与输入不一致就报错，并把允许的字符集写进消息，用户能立刻改对。
- **764** `return safe` — 到这里 `safe == name`，等价于"这个名字既是安全的、也是用户想写的"。
  > ⚠️ 存疑（高）：本函数**没有**拦 `..`，而下游 `registry._model_dir` 明确拒绝任何含 `..` 的名字(registry.py:73–74)。把模型改名为 `a..b` 可以通过这里的校验、`_rename_model` 也会真的把目录建成 `data/models/a..b`、`update_model` 也会成功写库 → 之后 `ArtifactDetail`/`overview`/`/predict` 全部在 `_model_dir` 抛 `ValueError`（表现成 400 或"模型名非法"），**这个模型的产物再也读不出来**。建议这里与 registry 的口径统一（拒 `..`、拒点开头）。

## 行 765–781 · `_rewrite_meta_model(directory, model_name)`

**作用**：把 `<目录>/meta.json` 的 `model` 字段改写成 `model_name`；改名与回滚共用。

- **765–773** `def` + docstring — 两条约束：**无条件改写**（不做 old→new 相等判断，因为 Windows 大小写不敏感会让"1dcnn"与"1DCNN"比出相等而漏改）；meta 坏/非 JSON 直接跳过（改名是有副作用的长流程，不该为一个坏文件半途而废）。
- **774** `meta_file = directory / "meta.json"` — 只指向顶层那一份，不递归子目录。
- **775–778** `try: payload = json.loads(meta_file.read_text(encoding="utf-8")) except Exception: return` — 一个宽 except 覆盖"文件不存在 / 不是合法 JSON / 编码错 / 权限不足"，全部静默返回。代价是调用方无法区分"改好了"和"跳过了"，`_rename_model` 的返回值里也没有这个信息。
- **779–781** `if isinstance(payload, dict): payload["model"] = model_name; meta_file.write_text(...)` — 只有 dict 才改（`json.loads` 可能得到 list/字符串，`payload["model"]=...` 会 `TypeError`）；写回用 `ensure_ascii=False`（中文描述保持可读）+ `indent=2`，与 `registry.save_artifact`(registry.py:160) 和上传落盘(api.py:1043)的写法一致，保证 meta 的磁盘格式不因改名而变。注意这是**整体重写**而非原子替换，中途崩溃会留下半个 meta.json——概率低，但下游 `_read_meta` 会把它当"坏 meta"而返回空字典。

## 行 782–824 · `_rename_model(old, new)` —— 磁盘侧改名（含半程回滚）

**作用**：改名的**磁盘侧**动作：搬产物目录 + 改 meta + 改库里已存路径前缀；**①目录 ②meta ③库中路径**三件事由它负责，**④`Models.ModelName`** 不归它管（由调用方接着调 `database.update_model(..., new_name=)`）。

- **782–797** `def` + docstring — 明确"必须同步四处"：① 产物目录 `data/models/<老名>`→`<新名>`；② `meta.json` 的 `model` 字段；③ `Trainings.ModelPath` / `InferenceTasks.InputPath·OutputPath` / `ModelDeployments.DeployedPath`（实际由 `db.rename_model_paths` 按前缀 `REPLACE`，db.py:667–692）；④ `Models` 表行。以及"**为什么先搬文件再改库**"：搬目录是同盘 `rename`，几乎不失败且失败原因一眼可见；`update_model` 要过网络+SQL（查重、外键、方言）。把易失败的动作放后面，失败时才有东西可回滚；反过来先改库，一旦搬目录失败，库里全是新路径、磁盘还是老目录，之后所有训练/推理都 `FileNotFoundError`。
- **798** `key = _artifact_key(old)` — 真实目录名（`1DCNN` → `1dcnn`）。调用方传进来的 `old` 是库口径名，必须再换算一次。
- **799** `safe = _safe_model_name(new)` — **第一个可能抛错的点，且刻意排在任何磁盘动作之前**：名字非法时直接 400，磁盘与库零改动。
- **800** `old_dir, new_dir = config.model_dir / key, config.model_dir / safe` — 两个绝对路径都是 `data/models/` 的直接子目录。注意 `new_dir` 用的是 `safe`（保留用户写的大小写），这会在后续 `_artifact_key(new)` 时产生大小写落差（见 752 的存疑）。
- **801** `moved = False` — 回滚判据：只有真搬过目录才需要、也才允许搬回去。
- **802** `if old_dir.is_dir():` — 只在产物目录真的存在时才搬；"只在 `Models` 表登记、还没训练过"的模型跳过整段磁盘操作，改名退化成纯改库（这条分支下 812 的路径前缀替换通常是空操作）。
- **803–806** `if new_dir.exists(): raise InvalidInput(...)` — 用 `exists()` 而不是 `is_dir()`：同名位置被一个普通文件占着时同样不能搬，早报错好过 Windows 上 `rename` 抛一个语焉不详的异常。回 400 的文案直接告诉用户"删掉它或换个名字"。
- **807** `old_dir.rename(new_dir)` — 同盘重命名，原子且秒完成；`config.model_dir` 只有一个父目录，所以不存在跨盘 `EXDEV` 的问题。
- **808** `moved = True` — 置位发生在这里而不是 802，语义是"目录确实被搬走了"。
- **809–810** 注释 + `_rewrite_meta_model(new_dir, safe)` — ② 的落地：改写**新目录**里的 meta，`model` 写成新目录名。
  > ⚠️ 存疑（中）：809 的注释说"每个版本一个子目录（v1/v2/…），里面各有一份 meta.json，model 字段全部要跟着改"，但 810 只改 `new_dir/meta.json` 这一份，不递归 `vN/`。版本层早已拍平（registry.py:16–20 的"一个模型只有一个产物"、api.py:872 的"产物已经拍平成'一个模型一份'"），所以这段注释是 v1/v2 时代的历史残留，与当前布局和代码都不符——别按它去加递归。
- **811–813** `try: paths = database.rename_model_paths(key, safe)` — ③ 的落地：把库里已存的路径前缀就地换掉（`\models\old\` → `\models\new\`，反斜杠与正斜杠各来一遍，db.py:680）。返回值是"每张表动了几行"，键名固定取该表首列(db.py:676–677)。
- **814–818** `except DBError: if moved: new_dir.rename(old_dir); raise` — 改库失败就把目录原样搬回去，宁可整体失败成"没改过名"的干净状态，也**不留"库说新名、磁盘是老名"的脱钩**；`raise` 让 `ArtifactDetail.put` 的 `except DBError` 翻译成 409。`if moved` 保证没搬过目录时不做无意义（且必然失败）的反向 rename。
  > ⚠️ 存疑（中）：815 的注释说"meta 与路径前缀由调用方的 `_undo_rename` 收尾"，但这条 `raise` 路径上 `_undo_rename` **不会被执行**——它在 `put` 里只挂在内层 `except`（update_model 失败）分支，而此时 908 行的赋值还没完成、`rename` 仍是 `None`(914)。结果是：目录已搬回老名，`old_dir/meta.json` 里的 `model` 却还是**新名**，meta 与目录名脱钩且无人修复。修法：这条分支自己调 `_rewrite_meta_model(old_dir, key)`，或让调用方在 `_rename_model` 抛错时也走一次回滚。
- **819–824** 返回值 — `from`/`to` 用磁盘口径名；`artifact_dir_moved` 与 `artifact_dir` 分工明确（没搬目录时 `artifact_dir` 为 `None`，别误报成"新目录已就绪"）；`path_rows_updated` 透传 813 的行数统计；`note` 只在 `key in MODEL_META`（内置模型）时给，说明改名后"按老名字训练会出问题"。
  > ⚠️ 存疑（低）：823 的 note 说"内置模型改名后**不能**再按老名字训练"，实际行为更阴险：训练侧用的是内部键（`save_artifact(name, ...)` training.py:541、`ensure_model(db_model_name(name))` training.py:597），按老别名再训一次不会报错，而是**重新长出 `data/models/1dcnn/` 和 `Models` 表里名为 `1DCNN` 的一行**，改名后的那个模型就此变成孤儿。文案与真实后果不一致。

## 行 825–855 · `_undo_rename(old, new)` —— 回滚 `_rename_model` 的副作用

**作用**：`update_model` 失败时把 ①目录 ②meta ③库中路径前缀**反向改回**；**绝不抛异常**。

- **825–831** `def` + docstring — 明确那是回滚路径，原则是"尽力恢复、绝不抛异常"：它在异常处理里被调用，再抛新异常会把真正的失败原因（`update_model` 为什么失败）彻底盖掉，且此时目录已经被搬过，用户看到的现象会更乱。所以下面所有失败分支都是 `return`/`pass`。
- **832** `key = _artifact_key(old)` — 老目录名；与 `_rename_model` 798 同源，保证两边算的是同一个目录。
- **833–836** `safe = _sanitize_name(new, new)` — 用**不抛异常**的 `_sanitize_name` 而不是会 `raise` 的 `_safe_model_name`，清洗不出来就用第二个参数（原文）兜底。实践上能走到回滚就说明 `_safe_model_name(new)` 已经通过（`safe == new`），所以这个兜底主要防"函数被别处以非法名调用"。
- **837** `old_dir, new_dir = config.model_dir / key, config.model_dir / safe` — 与 `_rename_model` 800 完全对称，只是新旧位置对调。
- **838–840** `if new_dir.is_dir() and not old_dir.exists() and safe != key:` — 三个条件缺一不可：新目录得真在（不然没东西可搬回）、老目录不能被别人占用（占用时宁可不动，避免把别人覆盖掉）、清洗后名字确实不同（相同就无需搬）。
- **841–845** `try: new_dir.rename(old_dir) except OSError: return` — 目录都搬不回去时，`return` 放弃**整次**回滚（连下面的 meta 与路径前缀一起跳过），此时磁盘=新名、路径=新前缀二者自洽，只是 `Models` 行仍是老名。
  > ⚠️ 存疑（中）：这里的 `return` 与 848–851 的注释"这步和上面的目录搬回是**相互独立**的……即使目录没搬回来，路径前缀也**必须**改回去"直接矛盾。二者只能选一个：若按注释改，会得到"磁盘目录是新名、库里路径是老前缀"的断链（更糟）；所以**代码是对的、注释是错的**，但注释会误导后来者。另外注意 840 的条件不满足时也会走到 847，去改写一个"别人的" `old_dir` 的 meta。
- **846–847** `_rewrite_meta_model(old_dir, key)` — 与 `_rename_model` 810 对称：目录搬回老名后，把 meta 的 `model` 写回老名。刻意放在 `if` 之外，因为它的前提是"目录已叫 `key`"（不论这次是否刚搬回）。
- **848–851** 注释 — 解释路径前缀为何反向调用即可复原（`REPLACE` 是幂等的前缀替换），以及"能走到本函数就说明 `_rename_model` 已完整跑完"（否则它在内部就 `raise DBError` 了）这个前提。
- **852–855** `try: database.rename_model_paths(safe, key) except DBError: pass` — 把 ③ 改回老前缀；返回的行数统计被丢弃（回滚不需要回执）。`pass` 是刻意的：回滚里的失败只能吞。
- **对称性小结**：`_rename_model` 负责 ①目录 ②meta ③库中路径；`_undo_rename` 负责同样的 ①②③但方向相反；**④`Models` 行两边都不管**——因为回滚的前提正是第 ④ 步没成功，库里那行还叫老名，无需恢复。

## 行 856–867 · `ArtifactDetail.get` —— 看产物档案

**作用**：`GET /models/<模型名>` 读取该模型的产物 `meta.json`（`DELETE`/`PUT` 在下面两个小节）。

- **856–857** class + docstring — 说明这是"产物"视角的接口，与 `Models` 表登记无关。
- **858** `def get(self, model_name)` — 路径参数来自 `/models/<model_name>`（_ROUTES 1474）；注意静态段 `/models/upload` 必须注册在它前面，否则会被当成 `model_name='upload'`(1455–1458)。
- **859** docstring — 声明名字可以任意写法，先归一再查。
- **860–862** `artifact = load_artifact(_artifact_key(model_name))` — 磁盘目录只认小写内部键，所以 `1DCNN`/上传名都要先换算（`_artifact_key` 本身不抛，非法名字会在下游 `registry._model_dir` 抛）。
- **863–864** `except FileNotFoundError` → 404 — `load_artifact` 在"目录不存在"和"目录在但没有权重"两种情况下都抛它(registry.py:174–178)，所以 404 同时覆盖"没训练过"和"产物半残"。
- **865–866** `except ValueError` → 400 — 对应 `_model_dir` 对非法模型名（含 `/`、`..`、点开头）抛的 `ValueError`(registry.py:73–77)，属参数错。
- **867** `return artifact.to_dict()` — 只挑 `model/framework/weights/directory/input_len/num_classes/labels/metrics/params/dataset/created_at` 等字段(registry.py:45–63)，**不透传整份 meta**（`history` 训练曲线 + `classification_report` 会让响应膨胀几十倍）。

## 行 868–886 · `ArtifactDetail.delete`

**作用**：`DELETE /models/<名>`，两个不可混用的删除口径：`?scope=artifact` 删磁盘产物、`?scope=record` 删 `Models` 表登记行（带引用检查）。

- **868–869** `def delete` + docstring — 把两个 scope 的语义写清，避免调用方猜。
- **870–872** 注释 — 为什么必须**显式**指定 scope：一个不可恢复（删盘）、一个带外键引用检查，猜着删太危险，所以两个都没给就直接报错；并说明 `?version=vN` 的旧写法已随版本层拍平而取消。
- **873–880** try 块 — 读 `scope` 并 `strip()`；`"artifact"` → `delete_artifact(_artifact_key(model_name))`（内部会 `resolve()` 后二次确认父目录是 `model_dir`，防误删，registry.py:213–215），返回 200；`"record"` → 解析 `force` 后调 `database.delete_model(_db_model_name(model_name), force=force)`（库口径名）返回 200；其它/缺失 → `raise InvalidInput` 提示两个可选值。
  > 注意：`force` 只认 `"1"`/`"true"`/`"True"` 三个字面量(878)，`?force=yes`、`?force=TRUE` 都算 False；缺参时 `request.args.get` 返回 `None`，也不在元组里 → False，这是安全的默认方向。两个 scope 互不联动：删产物不会删登记行（会留下"登记了没产物"），删登记行也不会动磁盘。
- **881–882** `except FileNotFoundError` → 404 — 对应"还没有 `<名>` 的产物"。
- **883–884** `except DBError` → 409 — 覆盖两种库层事实：被 `Trainings`/`InferenceTasks`/… 引用着不许删(db.py:740–742)，以及"这个名字不在 `Models` 表里"(db.py:646–648)。
  > ⚠️ 存疑（低）：后一种其实是"资源不存在"，语义上更像 404，而 `ModelReferences.get` 把**同一个** `DBError` 映射成 404(api.py:1196–1199)——同一个事实两种码。下 887 的 PUT 也一样把 `DBError` 一律当 409。
- **885–886** `except ValueError` → 400 — 含 `InvalidInput`（子类），也含 `delete_artifact` 的"拒绝删除模型目录以外的路径"(registry.py:215)。

## 行 887–925 · `ArtifactDetail.put` —— 改登记信息 + 可选改名

**作用**：改 `Models` 表的 `Description`/`ModelType`/`ApiEndpoint`/`Status`/`IsActive`，带 `NewModelName`（或 `new_name`）时**连磁盘产物一起改名**，并保证失败能回滚。

- **887–894** `def put` + docstring — 复述改名要同步的三处（目录、meta、库中路径前缀），目标是不出现"库表改名、磁盘还是老目录"的脱钩。
- **895** `body = _body()` — 容忍非 JSON / 空 body（此时等价于"没有可更新字段"，会由 `update_model` 抛 `DBError` → 409）。
- **896–898** `old = _db_model_name(model_name)` — 必须用**库口径**：库里存的是 `1DCNN`，拿路径里的 `1dcnn` 直接去 `WHERE ModelName=?` 会查不到行，改名就"成功"地改了个空。
- **899–900** `new_name = str(body.get("NewModelName") or body.get("new_name") or "").strip()` — 同时兼容前端 camel 风格的 `NewModelName` 与脚本惯用的 `new_name`；`or` 链让"没传/传 None/传空串"统一成 `""`，等价于"不改名"。
- **901** `rename = None` — 只有真发生过磁盘改名才会被赋值 908；它同时是"要不要回滚"和"要不要往响应里塞 `rename` 回执"的开关。
- **902** `try:` — 覆盖"查重 → 搬目录 → 改库"三步的全部异常，统一由 917–922 翻译状态码。
- **903–904** `if new_name and new_name != old:` — 名字没变（或没传）就只当普通信息更新，完全不碰磁盘，避免无意义的 rename。注意比较是 **Python 字符串比较（大小写敏感）**，而库层判重是大小写不敏感的（见下）。
- **905–907** `if database.model_exists(new_name): return {"error": ...}, 409` — 查重放在搬目录**之前**：名字被占直接 409，别先动了磁盘才发现改不了。`model_exists` 只取主键判存在(db.py:657–666)，比较交给 MySQL（本库 `utf8mb4_unicode_ci`，大小写不敏感）。
  > ⚠️ 存疑（低）：`ModelName` 的 collation 大小写不敏感，所以"把 `1DCNN` 改写成 `1dcnn`"会通过 904 的字符串比较，然后被 906 判成"已被占用"（占用者其实就是它自己），回一句 409「模型名 1dcnn 已被占用」；`update_model` 内部(714–716)还有同样一道。用户想统一大小写时会被这句提示绕晕。
- **908** `rename = _rename_model(old, new_name)` — 先动磁盘（同盘 rename 快且失败原因直观），后改库；返回值原样带在 923–924。
- **909–916** 内层 `try: result = database.update_model(old, body, new_name=new_name or None)` / `except Exception:` — `new_name or None`：没改名时传 `None`，`update_model` 就只更新白名单列而不碰 `ModelName`(db.py:714)。改名后改库失败时 `if rename: _undo_rename(old, new_name)` 把目录/meta/路径前缀搬回老名，然后裸 `raise` 让外层翻译成正确的状态码。`if rename` 是必要的：`_rename_model` 从未成功（如查重就返回了）时 `rename` 为 `None`，没什么可回滚。
- **917–918** `except FileNotFoundError` → 404 — 兜底性质的（`_rename_model` 里 `rename` 遭并发竞争可能抛 `os` 系异常；`update_model` 的"不存在"走的是 `DBError`）。
- **919–920** `except DBError` → 409 — 覆盖查重撞名、`update_model` 的"没有可更新字段"/"模型不存在"、以及 `rename_model_paths` 的库失败。
- **921–922** `except ValueError` → 400 — 含 `InvalidInput`：名字非法（`_safe_model_name` 762–763）、新目录已被占用（806）都从 `_rename_model` 里冒出来。
- **923–925** `if rename: result["rename"] = rename` + `return result, 200` — 把 ①目录是否真的搬了 ②新目录路径 ③路径改了几行 一并回给前端（819–824 的字典），前端据此提示与排错；`result` 是 `update_model` 的回执（`updated`/`new_name`/`fields`）。

## 行 926–974 · `ModelOverview.get` —— 一个模型的完整档案

**作用**：把散在 4 个地方的信息（`Models` 表 / `Trainings` 表 / 产物 `meta.json` / 引用关系统计）合并成一个响应，前端一次请求即可渲染档案页。

- **926–932** class + docstring — 说明合并动机，并点出"选中某行要展开它自己的参数"这一交互需求。
- **933** `def get(self, model_name)` — 路由 `/models/<model_name>/overview`(1478)，同时兼顾"有产物没登记"与"登记了没训练"两种不一致状态。
- **934** docstring — 复述"一次请求给全"。
- **935–937** 注释 — 说明 `name`（库口径）与 `key`（磁盘口径）的同源关系：`_artifact_key` 内部就是"先 `_db_model_name` 再在 `MODEL_META` 反查"，所以不必就地内联推导，免得维护两份副本。
- **938** `name = _db_model_name(model_name)` — 库口径名，用于查登记行、训练记录、引用统计。
- **939** `key = _artifact_key(model_name)` — 磁盘口径名，用于读产物；两次调用会各自重做一遍 `normalize_model`，代价可忽略（都是内存字典查询）。
- **940–943** `registration = next((r for r in database.models_in_db() if str(r["ModelName"]).lower() == name.lower()), None)` — 用 `str(...)` 包一层是因为 `ModelName` 理论上可为 `NULL`（`models_in_db` 从 `Models` 直查，正常非空，但防护成本为零）。
- **940–943（续）** 为什么是 `next(..., None)` 而不是"查不到就 404"：档案页必须**如实展示不一致**——产物可能是训练落盘成功、写库失败留下的（没有登记行），登记行也可能只是占位（还没产物）。这与 `ModelList` 刻意返回 `artifacts`/`db_models` 两份清单是同一个思路(381–393)；而 `ModelReferences` 对同一个"不在表里"的事实回 404(1196–1199)，因为它问的是"能不能删"，答案必须明确。
- **944–947** `artifacts = list_artifacts(key)` / `artifact = artifacts[0].to_dict() if artifacts else None` — 这是**真磁盘 IO**（遍历目录 + 读 `meta.json`）；取 `[0]` 是因为新布局下一个模型只有一份产物（版本层已拍平）。注意 `list_artifacts` 会**跳过没有有效权重的目录**(registry.py:200–202)：所以 `artifact` 为 `None` 有两种含义——目录不存在，或目录在但权重文件缺失/0 字节。前端文案最好区分"没训练过"与"产物不完整"。
- **948** `params, metrics, labels, dataset, confusion = {}, {}, None, None, None` — 一次性给全部默认值，让下面的分支只负责"有产物时覆盖"，不用每个字段写一个 `or {}`。
- **949–955** 有产物时从 `artifacts[0].meta` 取五组字段 — `params`/`metrics` 用 `or {}` 兜成字典，`labels`/`dataset`/`confusion` 保持 `None` 语义（"文档里没有这一项"和"空列表"要能区分）；`labels` 是把 `predicted_class` 数字翻译成故障名的唯一依据。
- **956–958** `trainings = [t for t in database.recent_trainings(50) if str(t.get("ModelName","")).lower() == name.lower()][:5]` — 库层没有"按模型名查训练记录"的接口，所以拉最近 50 条再本地过滤，最后只留 5 条给前端。`t.get("ModelName","")` 是因为 `recent_trainings` 用 `LEFT JOIN`(db.py:540)，未匹配时该列是 `None`；`str(None)="none"` 不会与真实模型名误匹配。
  > ⚠️ 存疑（低）：50 条是个**窗口**而非"该模型的全部"——若最近 50 条训练都被别的模型刷满，这个模型的档案页会显示"没有训练记录"，与事实相反（注释也承认这是权宜之计）。库大了应该在 db 层加按 `ModelID` 过滤的查询。
- **959–963** `try: references = database.model_references(name)` / `except DBError: references = {"error": str(exc)}` — 引用统计只是附带信息，库出错就降级成 `error` 字段，不能让整页 500。这一档恰好覆盖"有产物但没登记"：`model_references` 对不存在的模型抛 `DBError("模型 X 不存在于 Models 表")`(db.py:646–648)，于是响应里 `registration: null` + `references: {"error": ...}`，语义自洽而不是 404。
- **964–974** 返回响应体 — `model`/`artifact_key` 回显两个口径的名字便于前端对账；`registration` 可能为 `None`；`artifact` 可能为 `None`（见 944–947）；`metrics` 用字典推导**剔除 `history`**：逐 epoch 的训练曲线比其它指标大一个量级，曲线另有 `/figures` 的图片可看；最后是 `recent_trainings`(≤5) 与 `references`，整体回 200。
  > ⚠️ 存疑（中）：本方法把 `DBError` 只包在 `model_references` 周围，而 942 的 `database.models_in_db()` 和 957 的 `database.recent_trainings(50)` 的库异常会直接冒出去 → flask_restful 把 `DBError` 变成 500（项目没有能兜住它的全局 errorhandler）。对比：`ModelList` 会把库错误塞进 `db_models` 列表(388–393)、`_recent_list` 对同异常回 503(609)，而档案页在库挂掉时整页不可用，口径不一致。
  > ⚠️ 存疑（中）：946 的 `list_artifacts(key)` 对**非法名字**会抛 `ValueError`（`registry._model_dir` 拒绝含 `/`、`..`、点开头的名字，registry.py:73–77），这里没有任何捕获 → 500；而 `ArtifactDetail.get` 对同一个 `ValueError` 明确回 400(865–866)。例如 `GET /models/a%20b/overview` 会 500 而不是 400。

---

## 存疑点清单（按严重度）

| # | 位置 | 严重度 | 结论 |
|---|------|--------|------|
| 1 | 752 `_artifact_key` 默认分支 `name.lower()` | 中高 | 与"上传落盘保留大小写"(api.py:1006) 和 `inference.predict` 用原名(inference.py:453) 不一致；仅靠 Windows 大小写不敏感侥幸可用，Linux/Docker 下上传模型会被判为"没有产物" |
| 2 | 759–763 `_safe_model_name` 不拦 `..` | 高 | 与 `registry._model_dir`(registry.py:73) 口径不一致；改名为 `a..b` 会建成一个**任何接口都读不出来**的产物目录 |
| 3 | 814–818 `_rename_model` 内部 `DBError` 分支 | 中 | 815 注释称 meta 由调用方 `_undo_rename` 收尾，但该分支 `raise` 时 `put` 的 `rename` 仍是 `None`(908/914) → 目录已回老名、`meta.json` 里仍是新名，脱钩且无人修复 |
| 4 | 626 + 628–631 用 `training.db_model_name` | 中 | 该函数只做"内部键→库名"一跳，不做别名归一(training.py:51–60)；传 `cnn`/`1d-cnn`/中文别名时静默不写失败日志，与 628 行注释"用户可能传中文别名"不符（应用 `_db_model_name`(734)） |
| 5 | 692 内层 try 的范围 | 中 | 662–677 的参数校验（`model` 空、`limit`/`top_k`/`index` 非法）在 try 之外抛出 → 不写调用日志，与 616–619 docstring 的动机（"输入校验被拒"要留痕）不符 |
| 6 | 841–845 `except OSError: return` | 中 | 跳过路径前缀回滚，与 848–851"路径前缀也必须改回去"的注释直接矛盾（代码行为更合理，注释需改） |
| 7 | 942 / 957 `ModelOverview` 未捕获 `DBError` | 中 | 库挂掉时档案页 500，而 `ModelList` 降级、`_recent_list` 回 503，同一故障三种表现；只有 `model_references`(961) 被保护 |
| 8 | 946 `list_artifacts(key)` 可抛 `ValueError` | 中 | 未捕获 → 500；`ArtifactDetail.get` 对同一异常回 400，口径不一致 |
| 9 | 809 注释讲 v1/v2 子目录 meta | 中 | 只改顶层 `meta.json`；版本层已拍平(registry.py:16–20、api.py:872)，注释是历史残留 |
| 10 | 803–806 目录占用检查的条件 | 低 | 仅在 `old_dir.is_dir()` 时执行；`old_dir` 缺失而 `new_dir` 是**别人的**产物目录时仍会 `rename_model_paths` 抢改对方路径前缀（需 DB 写失败导致"有产物无登记"才可触发） |
| 11 | 634–640 `DBError` 记 500 | 低 | 与 `Predict.post`(697) 的 400 不一致；实际不可达（`inference._write_db` 吞掉所有库异常，inference.py:368–435） |
| 12 | 697–698 `DBError` → 400 | 低 | 服务端库故障被报成客户端参数错，与 `_recent_list` 的 503 不一致；实际同样不可达 |
| 13 | 823 `note` 文案 | 低 | 内置模型改名后按老名再训练**不会报错**，而是重新长出 `data/models/1dcnn/` 与 `Models` 行 `1DCNN`(training.py:541/597)，把改名后的模型变成孤儿 |
| 14 | 904 大小写改名 | 低 | "1DCNN"→"1dcnn" 会撞到自己那一行，回 409「已被占用」（占用者是自己） |
| 15 | 883–884 `DBError` → 409 | 低 | "模型不在 `Models` 表"被当 409，而 `ModelReferences.get` 对同一异常回 404 |
| 16 | 957–958 最近 50 条窗口 | 低 | 该模型的训练记录可能被别的模型挤出窗口，档案页显示"没有训练记录"（假象） |
| 17 | 687 `bool(body.get("write_db", True))` | 低 | 字符串 `"false"` 会被判成 `True`（照写库），只有真布尔/`0` 才关得掉 |
| 18 | 662 `(body.get("model") or "").strip()` | 低 | 非字符串 `model`（如数字）→ `AttributeError` → 500，同类参数类型错在别处都是 400 |
| 19 | 743–744 `_db_model_name("")` | 低 | `normalize_model` 对空串走 `return default`(training.py:68–69) → 返回 `"1DCNN"` 而非空/报错；docstring 未声明此行为（当前路由保证非空） |

---

# 第 4 段 · 行 975–1266

## 行 975–991 · `class ModelUpload(Resource)`（类声明 + 文档字符串）

**作用**：定义上传模型的资源类，把浏览器传来的文件夹/多文件落盘成 `data/models/<模型名>/` 并登记 Models 表。

- **975** `class ModelUpload(Resource):` — 继承 flask_restful 的 `Resource`，`post()` 由 `_ROUTES`（1476 行）注册到 `POST /models/upload`。注意它紧跟上一行 `return ..., 200`，中间**没有空行**（PEP8 要求顶层类前两个空行），纯属排版遗留，不影响运行。
- **976** 文档字符串首行声称落盘到 `data/models/<模型名>/<版本>/`。
- **977–982** 说明表单字段与浏览器两条上传路径：`webkitdirectory`（整目录）与 `multiple`（多选）在**服务端走同一套逻辑**，因为 `_upload_blobs` 只用 `Path(...).name` 取 basename，相对目录结构被丢掉。
- **983–988** 交代"不再要求填 input_len / num_classes / labels"的三步替代方案：扩展名初筛 → `probe_weight` 内容探测 → 通过者当权重并从文件里读参数；带 meta.json 时以 meta 为准。
- **989–990** 说明 scaler.npz 可选、读不出 input_len 时写 null 且推理侧按 784 兜底（对应 inference.py 462 行 `or 784`）。
- **991** 文档字符串结束。

> ⚠️ 存疑：976 行的 `<版本>` 是**过期描述**。同文件 1033 行注释明确写"一个模型一份，重新上传 = 直接替换旧产物（**没有版本号可选**）"，registry.py 模块头（第 6、16–20 行）也专门说明已去掉 `v1/v2` 版本层，`begin_artifact()` 返回的就是 `config.model_dir / clean` 这一层。同一类的文档与注释自相矛盾，建议以 registry 的实际布局为准。

## 行 992 · `MAX_MB = 500`

- **992** 类属性，单文件上限 500MB；在 1009 行以 `self.MAX_MB` 传给 `_upload_blobs(..., max_mb)`。写成类属性而不是模块常量，是为了让测试/子类能覆盖（本文件其余阈值如 `MAX_LIMIT` 走的是模块常量，风格不统一）。

## 行 993–998 · `ModelUpload.post()` 声明与流程说明

- **993** `def post(self):` — 上传接口入口，无 URL 参数（模型名走表单）。
- **994–998** 文档字符串给出四步流程：① 读进内存并分类 ② 逐个内容探测定权重 ③ 落盘 + 写 meta.json ④ 登记库 + 组装响应；并声明 ①③ 分别收在 `_upload_blobs()` / `_upload_meta()` 里，本方法只留流程与**错误码映射**。这是本方法后续读代码的骨架。

## 行 999–1006 · 取表单参数与前置校验

- **999** `form = request.form` — 用 `request.form` 而不是 `_body()`，因为上传是 `multipart/form-data`，此时 `get_json(silent=True)` 拿不到东西。
- **1000** `name = (form.get("name") or "").strip()` — `or ""` 挡住 `None`（字段没传时 `get` 返回 `None`），再 `strip()` 去掉首尾空白；只含空格的名字会变成 `""`，走下一行的 400。
- **1001** `files = _uploaded_files()` — 取文件列表（1084 行的辅助函数），空就是空列表，不必在这里判 `None`。
- **1002–1003** 名字为空 → 400。字段名回归表单口径（`name`），因为前端就是按表单字段报错的。
- **1004–1005** 一个文件都没有 → 400，错误信息里点明字段名必须是 `file`，且提醒"可多选/整个文件夹"——这是用户最常见的错因（用了 `files` 或压根没选）。
- **1006** `safe = _sanitize_name(name, "model")` — 把名字转成**磁盘安全形式**（非法字符换 `_`、去首尾 `.` 与 `_`、空则用 `"model"`）。之后全程用 `safe` 而不是 `name`：它既是产物目录名，也是登记进 Models 表的 `ModelName`。

> ⚠️ 存疑：`_sanitize_name` 的正则允许 `.`，`strip("._")` 只去首尾，所以像 `a..b` 这种名字会**原样保留**；而 registry.py 的 `_model_dir()`（73 行）对含 `..` 的名字直接 `raise ValueError`。由于 1035 行的 `begin_artifact(safe)` 在 `try`（1038 行）**之外**，这个 `ValueError` 不会被 1045 行的 `except Exception` 接住，最终变成 500（flask_restful 把非 HTTP 异常统一吃成 500），用户看不到"名字不合法"的原因。而 `_sanitize_name` 会把 `/`、`\` 换成 `_`，所以能走到这条路径的只有夹着 `..` 的名字。

## 行 1007–1009 · 第 ① 步：读进内存并分类

- **1007** 注释：先读进内存再分类，避免"半途落盘"。
- **1008–1009** 调用 `_upload_blobs(files, KEEP_SUFFIXES, WEIGHT_SUFFIXES, self.MAX_MB)`，按顺序解包成 `blobs`（文件名→bytes）、`skipped`（被忽略的文件+原因）、`candidates`（权重候选）、`scaler`（scaler.npz 文件名或 None）、`meta_blob`（meta.json 原始 bytes 或 None）。两个后缀表是**模块级常量**（52–59 行），此处只是传入，不可按请求改写。

## 行 1010–1013 · 第 ② 步前置：连候选都没有

- **1010** 注释点题："判断这是不是一个模型"。
- **1011–1013** 若 `candidates` 为空（扩展名表里一个都没有），直接 400，并附带 `received: sorted(blobs)`（收到的全是非权重文件）与 `skipped`（被后缀表挡掉的文件及原因）。这两项是给前端排错用的：用户能立刻看出"我传的是 .zip/说明文档，不是权重"。**`06a8fb8` 已给这条 `error` 补上 `.pt2`**（今 1055–1056 行）。

## 行 1014–1019 · 逐个候选做内容探测

- **1014** `probed: list[dict] = []` — 累积每个候选的探测结论，最后原样回给前端（1073 行的 `probed_files`）。
- **1015** `for filename, framework in candidates:` — `candidates` 里的 `framework` 是 1109–1110 行由**后缀表**给的猜测值，仅作候选筛选标签，不保证对。
- **1016** `info = probe_weight(filename, blobs[filename])` — 真正的判定发生在这一步：打开文件内容（HDF5/zip 结构、pickle 操作码流），返回 `{ok, framework, reason, input_len, num_classes}`。用内存里的 `blobs`，不重读磁盘。
- **1017–1019** 把探测结果记进 `probed`：`framework` 优先取探测结果（`info.get("framework") or framework`），`ok`/`reason`/`input_len`/`num_classes` 原样带上。这一条是**先 append 再判 ok**，所以被采纳的那个文件也会出现在 `probed_files` 里（是好事，前端能看到"为什么选中它"）。

## 行 1020–1027 · 采纳第一个通过的候选（framework 以探测为准）

- **1020** `if info["ok"]:` — 只要探测通过就当权重，不再要求"必须唯一"或"必须是最好的那个"。
- **1021–1025** 注释给出**本段最重要的一条规则**：`framework` 必须以探测结果为准。理由是可验证的：`WEIGHT_SUFFIXES` 把 `.pt/.pth` 一律映射成 `"pytorch"`，但同一后缀下其实有三种完全不同的 torch 格式（老式 state_dict、TorchScript、torch.export）；`probe_weight` 靠包内条目区分它们并返回 `pytorch` / `pytorch-jit` / `pytorch-exported`（api.py 224–232 行），而 inference.py 336–338 行的 `_DISPATCH` 正是按这几个字符串分派加载方式。
- **1026** `weights, probe = (filename, info.get("framework") or framework), info` — 把"选中的权重"打包成一个二元组 `(文件名, 框架)`，`probe` 保存完整探测 dict。`or framework` 是兜底：万一探测没给出 framework（如本机无 torch 的早退分支）就退回后缀表的猜测。注意 `weights[0]`/`weights[1]` 的语义全靠这里约定，后面 1042、1063、1067、1071、1144、1147 行都按这个下标取值。
- **1027** `break` — 第一个通过的就是唯一权重，后面候选不再探测，也不再记进 `probed`。

> ⚠️ 存疑：不这么写会怎样——若这里沿用后缀表的 `framework`，一个 TorchScript 包会被标成 `pytorch`，推理时走到"按本项目 cwt_cnn 架构重建 + load_state_dict"那条路（inference.py 245 行附近），对自包含格式必然报键不匹配。这是"后缀不够用"的直接证据。
> 附带影响：排在命中者**之后**的候选文件不会进 `probed_files`（因为 `break`），但它们仍在 `blobs` 里、仍会被 1039–1040 行落盘。也就是说 `probed_files` 是"探测到命中为止"的部分列表，不是全部候选的清单。

## 行 1028–1032 · `for ... else`：全部候选都没通过

- **1028** `else:` — 挂在 `for` 上而不是 `if` 上：Python 的 `for...else` 在循环**未被 `break` 打断**时执行，语义正好是"没有一个候选通过"。
- **1029–1032** 回 400，带上 `detail: probed`（每个候选失败的具体原因）、`skipped`、以及一段 `hint` 说明各格式的判定条件。**`06a8fb8` 已补 `.pt2`**（今 1076–1077 行）：hint 现在写"PyTorch 的 `.pt/.pth/.pt2`（torch 的 zip 检查点；`.pt2`/TorchScript 自带结构，推荐用 `torch.export` 导出）"。

> 为什么这里能替掉 `weights is None` 的判断：1011 行已经保证 `candidates` 非空，所以循环要么 `break`（`weights`/`probe` 必然被赋值），要么耗尽走 `else` 直接 `return`。也就是说走到 1033 行之后的代码时，`weights`/`probe` 一定已绑定——用 `for...else` 把"全灭"这条分支提前 return 掉，就省掉了 `if weights is None: ...` 这种"循环后判空 + 变量可能未绑定"的静态检查困扰。反过来，如果不写 `else` 而在循环后判 `weights is None`，类型检查器（和读者）都必须考虑 `weights` 可能未赋值的情况。

## 行 1033–1036 · 第 ③ 步：开暂存目录

- **1033–1034** 注释交代两件事：产物目录"一个模型一份、重新上传直接替换旧产物"；以及**为什么要暂存**——"先写进暂存目录，写完整了才换上去，否则一次失败的上传会把上一份好产物毁掉"。
- **1035** `root, stage = begin_artifact(safe)` — registry.py 105–117 行：`root = data/models/<safe>/`（`mkdir(parents=True, exist_ok=True)`），`stage = root / ".staging-<YYYYmmdd-HHMMSS-微秒>"`（`mkdir()`）。暂存目录**建在产物目录内部**，点开头，所以 registry.py 191–194 行的 `list_artifacts()` 会跳过它，不会被误当成一个模型。
- **1036** `replaced = (root / "meta.json").is_file()` — 必须在 `commit_artifact()` **之前**取这个事实，因为 commit 第一件事就是删掉旧产物（registry.py 124–127 行）。用 meta.json 是否存在当判据，因为本平台的产物一定是"权重 + meta.json"一对（save_artifact 与本次上传都写它）。

> ⚠️ 存疑：`begin_artifact` 在 1035 行、`try` 从 1038 行才开始。除了上面说的 `..` 名字会抛 `ValueError`，`begin_artifact` 内部的 `mkdir()` 也可能抛 `PermissionError`/`OSError`（磁盘满、目录被占），这些同样不会走 1045 行的错误分支，直接 500 且无中文提示。把 1035 行也纳入 `try` 会更一致。

## 行 1037–1044 · 落盘：写文件 → 写 meta → commit

- **1037** 注释标记"3) 落盘"。
- **1038** `try:` — 从这里开始的一切异常都按"可回滚"处理。
- **1039–1040** 把 `blobs` 里的每个文件平铺写进暂存目录。这里**不分类型**：权重、`scaler.npz`、附属 `txt/yaml/csv`，以及用户自带的原始 `meta.json` 都先落一份。文件名已由 1097 行的 `Path(...).name` 扁平化，所以 `stage / filename` 不可能再带子目录。
- **1041–1042** `_upload_meta(...)` 决策出最终 meta（1122 行起判断"用户带了就以他为准"）与 `meta_generated` 标志。只调用一次，保证"写进文件的 meta"和"响应里报的 meta"是同一份对象。
- **1043** 用 `json.dumps(meta, ensure_ascii=False, indent=2)` 写 `stage/meta.json`。`ensure_ascii=False` 是为了让中文标签（"内圈故障-0.007in"）可读，`indent=2` 是为了让产物目录能被人直接打开看。这一步会**覆盖** 1040 行可能写入的用户原始 meta.json —— 这是正确的，因为 `_upload_meta` 已在其中强制 `trusted=False`、`provenance="upload"`（1129–1131 行），不能让用户的原件绕过这些标记。
- **1044** `commit_artifact(root, stage)` — registry.py 118–130 行：先删掉 root 下除 stage 以外的**所有**旧文件/目录，再把 stage 里的条目 `rename()` 到 root，最后 `rmdir()` 掉 stage。用 rename 而非 copy 是因为同盘重命名是原子的，不会出现半个文件。

> ⚠️ 存疑（Windows 特例）：`blobs` 是 Python dict，键**大小写敏感**；但产物目录在 Windows 上大小写不敏感。若一次上传里同时有 `Model.pt` 与 `model.pt`，两个键都存在 → 两次 `write_bytes` 落到同一个磁盘文件（后写的赢），而 1074 行的 `saved` 会列出两条、`probed_files` 也可能出现两条同名不同大小写的候选，报告的大小与磁盘实际内容对不上。低概率但确实存在。

## 行 1045–1047 · 失败即回滚

- **1045** `except Exception as exc:` — 故意用**宽口** `Exception`：磁盘满、路径过长、编码错误、`_int` 抛的 `InvalidInput` 全部走这里，目标只有一个——绝不让暂存目录里的半成品流到产物目录。
- **1046** `abort_artifact(stage)` — registry.py 131–133 行只做 `shutil.rmtree(stage, ignore_errors=True)`，旧产物完全不动，也不会留下"只有 scaler 没有权重"的半成品被后续 `_find_weights()` 误命中。
- **1047** 回 500，错误信息带 `type(exc).__name__` 与原文，并明说"已回滚"。此时**数据库还没写**（1052 行才开始），所以不需要回滚 DB——这也是把落盘放在登记之前的原因。

> ⚠️ 存疑：表单参数转不动本该是 400，但 `_upload_meta` 是在这个 `try` 内被调用的，它内部的 `_int()`（1138–1139 行）抛 `InvalidInput` 会被这里吞成 500。触发条件：探测没读出 `input_len`（`.pkl`、TorchScript、需要自定义类的存档都会如此）且用户同时传了 `input_len=abc`。本文件在 FigureList（1206–1209 行）对同类问题专门做了 `except InvalidInput`，此处漏了。

## 行 1048–1056 · 第 ④ 步：登记 Models 表

- **1048** 注释："同名就取用，不重复插"。
- **1049–1050** 把 meta 里的 `task` 映射成 Models 表的 `ModelType` 展示名（`classification→Classification`、`anomaly_detection→AnomalyDetection`、`regression→Regression`）。`.lower()` 容错大小写；查不到就**原样回退** `meta.get("task")`，所以上传一个 `task: "foo"` 的 meta 会把 `"foo"` 写进 ModelType 列（db 层 `_clip` 到 50 字符）。meta 里没有 `task` 时结果是 `None`，ModelType 列为空。
- **1051** `db_error = None` — 先占位，让 1076 行无条件引用它。
- **1052–1054** `database.ensure_model(safe, description=..., model_type=..., status="可运行")` — db.py 339–358 行：先按 `ModelName` 查，查到直接返回已有 `ModelID`；查不到才 insert。所以同名**不会**报错、也**不会**更新已有行的描述/类型（db 层文档明确说明命中分支不更新）。`safe` 是磁盘名，直接当库名用：内置模型名（如 `1dcnn`）靠库的 `utf8mb4_unicode_ci` 大小写不敏感命中种子行 `1DCNN`，上传的模型则原样插入。
- **1055–1056** `except DBError` → 不抛出，把错误文本收进 `db_error`、`model_id` 置 `None`，让响应照常返回（1076 行的 `db.written=false`）。

> ⚠️ 存疑：走到这里产物**已经提交到磁盘**了。若登记失败（库不可用、名字超长等），磁盘上会留下一个 Models 表里没有登记的产物目录；而 `list_artifacts()`（registry.py 184–206 行）是**直接扫盘**的，所以这个模型在"产物"视角下存在、在"模型列表"视角下不存在——两个页面会不一致。响应里只有 `db.error` 这一个线索，且状态码仍是 201，调用方很容易忽略。

## 行 1057–1064 · 组装 warnings

- **1057** `warnings = []` — 累积"非致命但要告诉用户"的提示，最终放进响应的 `warnings` 数组，前端逐条显示。
- **1058–1059** `replaced` 为真时提示旧产物已被替换且不再保留。这是**不可逆**操作（commit 已执行），必须让用户知道；同时 `replaced` 也作为独立字段返回，便于脚本判断。
- **1060–1062** `input_len` 缺失时提示"推理按默认 784 处理"，并给出修复方式（在产物目录的 meta.json 里补）。与 inference.py 462 行 `int(artifact.meta.get("input_len") or 784)` 完全一致，不是随口说的数字。
- **1063–1064** meta 声明的 `weights_file` 与探测选中的不一致时提示"以 meta 为准"。这个"以 meta 为准"是**真的**：registry.py `_find_weights()`（88–104 行）第一优先就是读 meta 里的 `weights_file`，文件存在且非空就直接用它。

## 行 1065–1078 · 返回 201 与响应体

- **1065–1066** 返回体起头：`model` 是 `safe`（磁盘目录名 = 库登记名），`directory` 是产物绝对路径。
- **1067** `framework` / `weights` / `input_len` / `num_classes` / `labels` / `scaler` 六个字段**全部取 meta**，而不是取探测结果。这是刻意的：用户带了 meta.json 时最终生效的就是 meta，响应应当反映"实际落盘生效的配置"。`weights` 用 `meta.get("weights_file") or weights[0]` 双重兜底。
- **1068–1069** 承接上一行的字段。
- **1070** `meta_generated` 直接来自 `_upload_meta` 的第二返回值；`replaced` 来自 1036 行。这两个布尔量是前端提示语（"已替换旧产物"/"meta 由系统生成"）的判据。
- **1071–1072** `probe` 子对象：探测**当时**的原始结论（选中的权重、探测定的框架、原因、读出的 input_len/num_classes）。它与 1067–1069 的 meta 口径刻意不同，这样用户可以一眼看出"探测读出了什么、而 meta 又覆盖成了什么"。
- **1073** `probed_files` 原样回传 1014–1019 行累积的逐文件明细（含失败理由）。
- **1074** `saved`：`{filename, size_kb}` 列表，大小由 `round(len(v)/1024, 1)` 从内存里的 bytes 算，不重新 stat 磁盘。
- **1075** `skipped`：被后缀/大小挡掉的文件与原因。
- **1076** `db` 子对象：`written`（`db_error is None` 的布尔化）、`ModelID`、`ModelName`、`error`。前端可据此区分"产物已落盘但库没登记"。
- **1077** `hint`：引导用户去「推理」页选这个模型，并把 input_len 或"默认 784"写进提示，省掉一次查文档。
- **1078** `}, 201` — 状态码 201 Created。选 201 而不是 200，是因为正常情况下确实新建了产物/登记行（尽管 `ensure_model` 可能是复用已有行）。

> ⚠️ 存疑：`framework` 在 1067 行取自 meta，但 `_upload_meta` 的**用户 meta 分支**（1127–1137 行）从头到尾没有写 `framework` 字段，只写 `weights_file`/`trusted`/`provenance` 并补 `input_len`/`num_classes`。于是：用户上传的 meta.json 里若没有 `framework`（很常见），落盘的 meta 就没有 framework，`load_artifact()` 读出来是 `"unknown"`（registry.py 183 行），推理分派（inference.py 336–338 行）必然失败；若写了但写错（比如 TorchScript 包写成 `"pytorch"`），则比"未知"更糟——会走错加载路径。也就是说 1021–1025 行那句"framework 必须以探测结果为准"只在**自动生成**分支被落实（1144 行），用户带 meta 的分支漏了同一处理，`weights[1]`（探测结果）在那里完全没被使用。这一处值得优先确认是否有意为之。

## 行 1079–1084 · `_uploaded_files()`

**作用**：统一读取 multipart 里的文件列表，兼容 `file` 与旧写法 `files` 两个字段名。

- **1080–1083** 文档字符串：`file` 是主字段名、`files` 是同义旧写法，两个上传接口共用；取不到就给空列表，"调用方据此回 400，不必自己判 None"。
- **1084** `return request.files.getlist("file") or request.files.getlist("files")` — 用 `or` 短路实现"主字段优先、旧字段兜底"。`getlist` 对不存在的字段返回空列表（不是 `None`），所以 `or` 的判断依据是"列表非空"。

> ⚠️ 存疑：`or` 的短路语义意味着——只要 `file` 字段有**任何一个**文件，`files` 字段的内容会被**完全忽略**而非合并。若前端某次同时提交两个字段（一半文件在 `file`、一半在 `files`），后半部分会静默丢失，且不会出现在 `skipped` 里（`skipped` 只记录通过 `files` 迭代过的条目）。
> 另外本函数只认 `multipart/form-data`：以 JSON 提交的请求 `request.files` 为空 → 1005 行回"没有收到文件"，这个提示对"发了 JSON"的用户略有误导。

## 行 1085–1115 · `_upload_blobs(files, keep_suffix, weight_whitelist, max_mb)`

**作用**：第 ① 步的全部实现——把上传文件按后缀/大小筛一遍后读进内存，并按用途分堆。

- **1086** 文档字符串声明返回 `(blobs, skipped, candidates, scaler, meta_blob)` 五元组，顺序即 1008 行解包的依据。
- **1087–1089** 解释筛选的目的：整套流程是"先全部读进来、确认是模型、才落盘"，所以被忽略的文件"既不占内存，也不该留下半个目录"。后半句关于**磁盘**的说法与实现一致（未通过筛的从不 write）；前半句关于**内存**的说法见下面的存疑。
- **1090** 文档字符串结束。
- **1091** `blobs: dict[str, bytes] = {}` — 文件名 → 原始字节。它同时是"要落盘的文件全集"（1039 行遍历它）。
- **1092** `skipped: list[dict] = []` — `{filename, reason}` 列表，最终原样进响应。
- **1093** `candidates: list[tuple[str, str]] = []` — 权重候选 `(文件名, 框架)`，注释点明"按上传顺序"。这个顺序决定了 1015–1027 行"谁是权重"的结果，所以它是**语义的一部分**，不是随便排的。
- **1094** `scaler = meta_blob = None` — 链式赋值同时初始化两个游标；用 `None` 而不是空列表，便于 1122 行直接做真值判断。
- **1095** `for item in files:` — 遍历 `FileStorage` 对象；此时还没读任何字节。
- **1096** 注释：浏览器传文件夹时 filename 可能是 `子目录\文件`。
- **1097** `filename = Path((item.filename or "").replace("\\", "/")).name` — 先把反斜杠统一成 `/`（Windows 浏览器给的是 `dir\a.pt`，而 `Path` 在 POSIX 上不认 `\`，统一后才跨平台），再取最后一段。这一行同时是**路径穿越的第一道防线**：`../../evil.pt` 取 `name` 后只剩 `evil.pt`。
- **1098–1099** `if not filename or filename.startswith("."): continue` — 空名字（理论上不该有）与点开头的隐藏文件（`.DS_Store`、`__MACOSX` 之类）静默跳过，注释说明**故意不进 `skipped`**：这些不是用户有意上传的文件，报出来只会是噪音。
- **1100** `suffix = Path(filename).suffix.lower()` — 小写化保证 `.PT` 与 `.pt` 同待遇；`Path.suffix` 只取最后一段（`a.tar.gz` → `.gz`），符合本项目的用法。
- **1101–1103** 后缀不在 `KEEP_SUFFIXES`（api.py 58–59 行）→ 记一条 `skipped`（reason 里对无扩展名的情况显式写"无扩展名"，比空白更有用）并 `continue`。
- **1104** `blob = item.read()` — **唯一一次真正读取上传流**。放在后缀筛之后，所以被后缀挡掉的文件一个字节都不读。
- **1105–1107** 超过 `max_mb * 1024 * 1024` 字节 → 记 `skipped`（"超过 500MB"）并丢弃。注意此时 `blob` 已经在内存里了。
- **1108** `blobs[filename] = blob` — 通过两道筛才入字典；保留原始 bytes 让后面的 `probe_weight` 与落盘共用同一份数据，不重复读、不重复解码。
- **1109–1110** 后缀在 `WEIGHT_SUFFIXES`（api.py 52–56 行）→ 追加进 `candidates`，值取自 `weight_whitelist[suffix]`。注释明确这只是**候选**：这里给的框架是后缀猜测，真正的框架由 `probe_weight` 定（1021–1025 行）。
- **1111–1112** `filename == "scaler.npz"` → 记 `scaler`（存的是**文件名**，1026 行那套下标风格之外，这个变量在 1150 行被当布尔用）。判据是精确文件名，改名成 `Scaler.npz` 或 `my_scaler.npz` 都认不出——这是刻意收紧的约定（推理侧也按 `scaler.npz` 找）。
- **1113–1114** `meta.json` → 把原始 bytes 存进 `meta_blob` 交给 `_upload_meta` 决定是否采信。
- **1115** 返回五元组，顺序与 1008 行解包严格对应（改顺序会静默错位，是这类"多返回值"的常见雷）。

> ⚠️ 存疑：1088 行注释说"先按扩展名**与大小**筛一遍再 `read()`"，但实现里大小只能在 `read()` **之后**用 `len(blob)` 得到（1104→1105 行），所以超大文件依旧会被完整读进内存再被拒。真正靠"不 read"省下内存的只有后缀这一道筛。顺序仍然不该换，但原因不是注释写的那句：`FileStorage` 不读就拿不到可靠字节数（请求头里的长度可能缺失或撒谎），且先读后判的顺序能让"筛掉的文件不落盘"这条不变式在最前面就成立。建议把注释改成"先筛后缀、再读、读完立刻按大小筛"。

## 行 1116–1121 · `_upload_meta(...)` 声明与语义

**作用**：决定最终落盘的 meta.json 内容，返回 `(meta, generated)`。

- **1117** 文档字符串首行点明返回值是二元组。
- **1118–1120** 两条分支的规则：用户带了 meta.json 就**以他的为准**（只补缺失项）；没带就按探测结果现造。`generated` 用来回报"这份是我们生成的"，直接对上响应里的 `meta_generated`。
- **1121** 文档字符串结束。参数 `(form, safe, weights, probe, scaler, meta_blob)` 与 1042 行的实参一一对应；`weights` 是 1026 行那个 `(文件名, 框架)` 二元组，`probe` 是探测 dict。

## 行 1122–1137 · 分支一：用户带了 meta.json

- **1122** `if meta_blob:` — 真值判断：`None` 或空 bytes（0 字节的 meta.json）都当"没带"。
- **1123** `try:` — 解析过程独立设边界。
- **1124** `meta = json.loads(meta_blob.decode("utf-8"))` — `decode("utf-8")` 不传 `errors=`，遇到 GBK 编码的 meta.json 会抛 `UnicodeDecodeError`，被下一行接住。
- **1125–1126** `except Exception: meta = None` — 坏 JSON/坏编码当"没带"处理，退回自动生成，**不让整个上传失败**。注释明确这是刻意的降级。
- **1127** `if isinstance(meta, dict):` — JSON 顶层是 list/字符串/数字也一律当没带（后面的 `.setdefault`、`meta[key]` 只对 dict 成立）。不满足就落到 1138 行的自动生成分支。
- **1128** `meta.setdefault("weights_file", weights[0])` — 只在用户**没写**这个键时补上探测选中的文件名。用户写了就完全保留（哪怕和探测结果不一致，1063–1064 行会就此给 warning）。
- **1129–1130** 强制 `meta["trusted"] = False`。注释点题：用户提供的 meta.json 自称 `trusted: true` 也不算数。这是**安全边界**，对应 inference.py 273–274 行——`trusted` 为 False 时不会反序列化产物的 `.pkl`（除非显式设置环境变量放行）。
- **1131** `meta["provenance"] = "upload"` — 用赋值而非 `setdefault`，覆盖用户可能瞎写的来源标记。
- **1132** 循环 `("input_len", "num_classes")`：只补这两项，其它键（labels、scaler_file、dataset…）完全尊重用户。
- **1133** `if not meta.get(key) and probe.get(key):` — 用**真值**而非"键是否存在"判断：用户写 `null`、`0`、`""` 都算"缺"，此时才用探测结果补。注意 `0` 被当成缺是合理的（input_len/num_classes 不可能是 0），但语义上确实丢了"用户明确写了 0"这个信息。
- **1134** 补值。
- **1135–1136** `if scaler: meta.setdefault("scaler_file", scaler)` — 收到 `scaler.npz` 才补，且仍用 `setdefault`（用户声明优先）。
- **1137** `return meta, False` — `False` 表示"这份是用户的"，响应里 `meta_generated: false`。

> ⚠️ 存疑：1132 行用 `not meta.get(key)`、1135 行用 `setdefault`，两种"补缺失"的写法不一致。前者会把用户写的 `"scaler_file"` 无关，后者不会：若用户 meta 里显式写 `"scaler_file": null`，`setdefault` 认为键已存在、**不会**补成 `scaler.npz`，于是磁盘上有 scaler 文件、meta 却说没有，推理侧不会加载它（scaler 缺失会让标准化参数对不上）。建议这里改用与 1132 相同的 `if not meta.get("scaler_file")` 写法。
> ⚠️ 存疑（同一处，更严重）：此分支**完全不设 `framework`**，而 `weights[1]`（探测定的框架）在这里根本没被使用，见 1078 行后的存疑条目。

## 行 1138–1142 · 分支二：自动生成 meta（前半）

- **1138** `input_len = probe.get("input_len") or _int(form.get("input_len"), None, "input_len")` — 探测结果优先，读不出来才用表单里的 `input_len` 兜底（虽然 983–988 行的文档说"不再要求填"，但保留了兼容入口）。`_int` 转不动会抛 `InvalidInput`（api.py 298–309 行），而本函数处于 1038 行的 `try` 内，会被吞成 500。
- **1139** 同理处理 `num_classes`。这两行都不做范围校验，所以 `input_len=-1` 会被原样写进 meta。
- **1140** `labels = [s.strip() for s in (form.get("labels") or "").split(",") if s.strip()]` — 逗号分隔拆标签，两头去空白并丢掉空项，所以 `"a, b,,"` → `["a","b"]`。
- **1141–1142** 用户没给 labels 且 `num_classes == 10` 时，直接用 CWRU 十类的中文标签。`sorted(ds.CWRU_0HP_CLASSES, key=lambda row: row[1])` 按元组第二项（`class_id`）排序，取第三项（中文标签），得到 class_id 0→9 顺序的列表。datasets.py 30–34 行的注释解释了为什么必须按 id 排而不能按表序或文件系统序——labels 的顺序就是模型输出的类别序号，错位会让历史实验无法对照。

## 行 1143–1160 · 自动生成 meta 的字段与返回

- **1143–1144** 字典起头：`model` 用 `safe`（目录名口径），`framework` 用 `weights[1]`——这里正是 1026 行"框架以探测为准"真正生效的地方。
- **1145** `task`：只有框架是 `adtk` 时算 `anomaly_detection`，其余一律 `classification`。这是个**粗判**——一个 PyTorch 回归模型会被标成分类，进而让 1049–1050 行把 ModelType 写成 `Classification`。
- **1146** `input_len` 直接写（可能是 `None`），`num_classes` 用 `num_classes or (len(labels) or None)`：标签数比 None 更有信息量，所以有 labels 就用它兜底。
- **1147** `labels or None`（空列表写成 null 而不是 `[]`），`weights_file` 用 `weights[0]`。
- **1148–1150** 注释说明 `scaler_file` 只可能来自"收到了名为 scaler.npz 的文件"这一事实（1111–1112 行置位），所以"没收到就是没有"，不需要再去磁盘上探一次；值写成固定的 `"scaler.npz"`。
- **1151** `params` 里只放 `{"source": "uploaded"}`、`metrics` 为空 dict —— 上传的模型没有训练超参与指标，但保留这两个键让 meta 结构与训练产物同形（registry.Artifact.to_dict 会读它们，1131 行等前端也按同一形状解析）。
- **1152** `dataset` 三键结构：`name` 取表单里的可选字段、`path`/`stats` 留空。此处的结构必须与训练路径写的一致，否则 `/models/<名>` 里取 `dataset.name` 会 KeyError。
- **1153** `trained_at: None`（上传不等于训练，不能假装有训练时间）+ `uploaded_at` 用秒级 ISO 字符串标记上传时刻。
- **1154** `origin: "POST /models/upload"` — 留个来源印记，便于日后判断某产物是上传还是训练来的。
- **1155** `trusted: False` — 与 1129–1130 行同一策略的注释："上传的产物一律视为不可信：推理侧不会反序列化它的 .pkl"。
- **1156** `provenance: "upload"` — 与用户分支同值，两条路的 meta 在这一点上形状一致。
- **1157–1159** `probe` 子对象：把探测的原始证据（选中的权重、框架、读出的 input_len/num_classes、reason）写进 meta 本身。这样即使日后前端页面改了，产物目录里仍留着"当初凭什么判定它是模型"的记录。
- **1160** `}, True` — 第二个返回值 `True` 表示"这份 meta 是本服务生成的"，经 1042 行传到响应里的 `meta_generated`。

## 行 1161–1184 · `class ModelCreate(Resource)` / `.post()`

**作用**：`POST /models` 只在 Models 表插一行登记，不训练、不落盘。

- **1161–1162** 类声明与一句话文档字符串，明确"不训练，只是登记/占位"。
- **1163–1164** `body = _body()` — 本接口吃 JSON（`_body` 内部用 `get_json(silent=True)`，非 JSON 请求体得空 dict 走默认值，而不是 400）。
- **1165–1166** `name = (body.get("ModelName") or body.get("name") or "").strip()` — 同时收库表风格的 `ModelName`（dvadmin 前端用）与简化写法 `name`（脚本用）；`ModelName` 优先，两个都没有时得 `""`。
- **1167–1168** 名字为空 → 400，错误信息用库表口径的键名（因为主用方是 dvadmin 前端）。
- **1169–1171** 注释解释**为什么这里不做磁盘安全化**：本接口只往 Models 表插一行、不碰磁盘，所以含 `/`、`..` 的名字也能登记成功；真正拿名字当目录名的接口（`/models/upload`、改名）才做安全化并拒绝非法字符。
- **1172** 注释说明默认值写在 `ensure_model` 的参数里。
- **1173–1176** `database.ensure_model(name, description=body.get("Description"), model_type=body.get("ModelType"), api_endpoint=body.get("ApiEndpoint") or "/predict", status=body.get("Status") or "未训练")` — 四个可选字段全部可以为 `None`（db 层 `_clip` 会处理），两个默认值用 `or` 给出：缺省端点 `/predict`、缺省状态"未训练"（占位模型还没跑过训练，比默认"可运行"更诚实）。
- **1177–1181** `except DBError as exc: return {"error": str(exc)}, 409`。注释坦诚说明：`ensure_model` 是"有就取、没有就建"，**同名并不冲突**（db.py 339–358 行命中即返回已有 ID），所以能走到 409 的是真正失败的情况——并发下两个请求同时插入撞唯一索引、字段超长、库不可用等。
- **1182–1183** 注释提醒"登记 ≠ 有产物"：本接口不训练、不落盘，要产物得走 `POST /models/upload` 或 `POST /train`。
- **1184** 返回 `{ModelID, ModelName}` 与 201。

> ⚠️ 存疑（行为不对称）：本接口在"新建"和"复用已有行"两种情况下**都回 201**，响应里也没有 `already_existed` 之类的判据，调用方无法区分。对比同一文件里 `DatasetDb.post`（1255–1256、1266 行）用 `already_existed` + 200/201 双码把这件事讲清楚了。若前端需要提示"该模型名已存在"，只能另拿 `ModelID` 去 `/models` 对账（1178–1179 行的注释也是这么建议的），属于接口层面的信息缺失。

## 行 1185–1199 · `class ModelReferences(Resource)` / `.get()`

**作用**：`GET /models/<model_name>/references`，删除前的引用体检。

- **1186** 文档字符串一句话定位：查"被哪些表引用了多少行"。
- **1187** `def get(self, model_name):` — 参数名对应路由里的 `<model_name>`（1477 行注册），由 flask_restful 注入。
- **1188–1189** 注释：必须先过 `_db_model_name()` 归一。理由可验证：库里存的是 `1DCNN` 这种正式名，拿磁盘口径的小写 `1dcnn` 直接去查会永远查不到。api.py 734–744 行的实现是 `db_model_name(normalize_model(raw))`，别名表里查不到（上传的模型）时 `except ValueError` 原样返回。
- **1190–1193** 注释说明返回体形状与判据：`{ModelID, references: {表名: 引用行数}, total, deletable}`，`deletable = (total == 0)`；引用不为 0 时删登记行会 409，必须带 `?force=true` 才会连带清理（与 `ArtifactDetail.delete` 的 `?scope=record&force=1` 对应）。这段注释是给前端交互设计用的说明书。
- **1194–1195** 直接把 db 层结果当响应体返回，只是把参数先归一再包 200。
- **1196–1199** `except DBError` → 404。注释解释这是**刻意的语义映射**：db.py 647–648 行对"名字不在 Models 表里"抛的是 `DBError`，而对调用方来说"模型不存在"属于资源不存在（404），不是服务故障（500）。

## 行 1200–1220 · `class FigureList(Resource)` / `.get()`

**作用**：`GET /figures` 列出已生成的图。

- **1201** 文档字符串：训练曲线/混淆矩阵/预测分布等。
- **1202** `def get(self):` — 无路径参数。
- **1203** 注释说明策略：先按大 limit 取回来再按 model 过滤，避免"过滤后不足 limit 条"这种别扭语义。
- **1204–1205** 注释点出 `_int()` 的坑：转不动会抛 `InvalidInput`（ValueError 子类），而项目**没有全局异常处理器**（api.py 1522–1525 行解释了原因：flask_restful 先接管异常，`@app.errorhandler` 够不着），不接住 `?limit=abc` 就会变成 500；这里包一层回 400，并声明 `or 60` 的 falsy 语义**保持原样**。
- **1206–1209** `try: limit = min(_int(request.args.get("limit"), 60, "limit") or 60, 500)` / `except InvalidInput → 400`。三层含义：`None`（没传）→ 默认 60；`or 60` 把 `0` 也变成 60；`min(..., 500)` 给上限，防止一次请求把上千条 JSON 拉回来。
- **1210** `model = request.args.get("model")` — 可选过滤器，`None` 表示不过滤。
- **1211–1213** 注释解释为什么不早点按 limit 截断：`list_figures` 内部是"按 mtime 倒序遍历 + 到 limit 就 break"（figures.py 262–268 行），先截断后过滤会漏掉"排在 500 名之后"的某个模型的图；代价是图库超过 500 张时只看得到最新的 500 张。
- **1214** `items = list_figures(limit=500)` — 固定取满 500 条再筛，与上一行注释严格对应。
- **1215** `if model:` — 空字符串也当"不过滤"，对 `?model=` 这种空参数是友好的。
- **1216–1217** 注释说明两种命中写法：`file` 是相对 `FIG_DIR` 的 posix 路径，可能同级（`1dcnn/x.png`）也可能嵌在子目录（`runs/1dcnn/x.png`）。
- **1218** `items = [i for i in items if i["file"].startswith(f"{model}/") or f"/{model}/" in i["file"]]` — 两种匹配：前缀命中（同级目录）或中间段命中（嵌套目录）。用 `f"/{model}/"` 而不是 `model in file`，是为了避免 `1dcnn` 误匹配 `1dcnn_v2` 这种子串——两侧都带分隔符才算是完整的一段目录名。
- **1219–1220** 返回 `count`（**截断后**的条数，即 `len(items[:limit])`，不是命中总数）、`figures`（最多 limit 条）与 `hint`（图片可直接用返回的 url 打开）。

> ⚠️ 存疑：`_int(...) or 60` 与 api.py 301–302 行 `_int` 自己的告警"调用方**不要**写成 `_int(x, 0, "y") or 0`：0 是 falsy，会把用户明确传的 0 悄悄换成别的值"是同一个形状。这里注释声称"falsy 语义保持原样"，也就是**知情保留**——`?limit=0` 会静默变成 60 而不是"要 0 条"。行为可接受，但与同文件另一处明文告诫相冲突，容易被后来者照抄。
> ⚠️ 存疑：负数没有被拦。`?limit=-5` → `_int` 得 `-5` → 真值 → `min(-5, 500) = -5` → `items[:-5]` 少返回最后 5 条，且 `count` 也随之变小。不会崩，但语义是"截掉尾部"而非"取前 N 条"，属于未定义输入下的怪异输出。建议加 `max(0, ...)` 或范围校验。

## 行 1221–1229 · `class FigureFile(Resource)` / `.get()`

**作用**：`GET /figures/<路径>` 直接把 PNG 交给浏览器。

- **1222** 文档字符串点明 `conditional=True` 支持 304 缓存协商。
- **1223** `def get(self, relpath):` — 参数名对应 1480 行的 `/figures/<path:relpath>`（用 `path:` 转换器才能匹配带斜杠的子目录路径）。
- **1224–1226** 注释解释为什么用 `send_from_directory` 而不是自己 `open/read`：白拿 `Content-Length`、`ETag`、`Range` 这些响应头；`conditional=True` 让它处理 `If-None-Match`/`If-Modified-Since`，命中时回 304，前端反复切页不再重复下载整张图。
- **1227–1228** 注释警告安全边界：`relpath` 直接来自 URL，穿越防护靠 `send_from_directory` 内部的 `safe_join`（规范化后若逃出 `FIG_DIR` 会抛 `NotFound` → 404），所以**别**改成 `Path(FIG_DIR / relpath).read_bytes()` 那种写法（`Path` 的 `/` 拼接不会拦 `../`）。
- **1229** `return send_from_directory(FIG_DIR, relpath, conditional=True)` — `FIG_DIR` 是 figures.py 43 行的 `config.data_dir / "figures"`，模块导入时已 `mkdir`。返回的是文件响应对象，不是 dict，所以不走 JSON 出口脱敏（脱敏 hook 只处理响应体里的路径文本）。

## 行 1230–1236 · 已删除类的注释与段标题

- **1230–1232** 说明 `class Console(Resource)`（`GET /ui`，零构建单页控制台）已整类删除：它每次请求读盘吐 `console.html`，与 Vue 前端功能重叠，属于第二套 UI；删除后 `/ui` 不再注册路由 → 404。末句备注路径当初选 `/ui` 而非 `/console` 的原因（Flask `debug=True` 时 Werkzeug 调试器独占 `/console`）。
- **1233–1235** 说明原先的 `class Root`（让 `GET /` 返回与 `GET /api` 完全一样的索引）也已删除：flask_restful 一个资源可挂多个 URL，在 `_ROUTES` 里把 `ApiIndex` 同时注册到 `"/"` 与 `"/api"` 即可，少一个只为转发而存在的类（对应 1460–1463 行的实际注册与"不能拆成两次 add_resource"的警告）。
- **1236** 段分隔标题：本行以下是"数据集管理 / 数据展示"区块。

> 说明：1230–1236 全部是注释，没有可执行代码；但它们是理解后续路由与 `_ROUTES` 的关键上下文（尤其解释了"为什么 `/` 和 `/ui` 在索引里不存在"）。

## 行 1237–1248 · `class DatasetDb(Resource)` / `.get()`

**作用**：`GET /datasets/db` 读 Datasets 表登记记录 + 各表行数。

- **1237–1238** 类声明与文档字符串（读 + 登记两个动词对应 get/post 两个方法）。
- **1239–1240** `def get(self):` 与一句话文档字符串：列出登记记录，顺带返回 8 张表的行数（前端"库表登记"页要用）。
- **1241** 注释："一次请求给两样东西"，说明这是为页面便利做的聚合，而不是 REST 语义上的单一资源。
- **1242–1244** `return {"datasets": database.datasets_in_db(), "dialect": database.dialect, "counts": database.table_counts()}, 200` — `datasets_in_db()` 默认 `limit=200`（db.py 586–595 行注明这是硬上限，第 200 条之后在此接口"查不到"，页面看起来像丢数据）；`table_counts()` 带 30 秒缓存（db.py 760–781 行），所以这个接口不是每次都真跑 8 条 `COUNT(*)`；`dialect` 是当前数据库类型（mysql/sqlite…），前端用它决定提示文案。
- **1245–1248** `except DBError` → **503 而不是 500**，且响应里照样带 `dialect`。注释解释理由：前端要能显示"配的是 MySQL、但连不上"，而不是一个什么都不带的 500；这类故障排查全靠这一句话。注意这里取的是 `database.dialect`（属性，不触发连接），所以库连不上时它依然可用。

## 行 1249–1266 · `DatasetDb.post()`

**作用**：`POST /datasets/db` 登记一个数据集，幂等。

- **1249–1250** `def post(self):` 与文档字符串，点明"同名则沿用已有行，响应里的 `already_existed` 标明是哪种"。
- **1251** `body = _body()` — JSON 请求体（与上传接口的 form 口径不同）。
- **1252** `name = (body.get("name") or "").strip()` — 只认 `name`（无 `DatasetName` 别名），与 `ModelCreate` 的双键名策略不一致，属于各接口各自为政的历史遗留。
- **1253–1254** 名字为空 → 400。
- **1255–1256** 注释说明"登记是**幂等**的"：同名由 `register_dataset` 决定复用已有行，所以成功有两种状态码——201 = 新建、200 = 复用，`already_existed` 是判据（前端据此提示"已存在"）。
- **1257–1262** `result = database.register_dataset(name=..., source=..., class_count=_int(...), sample_count=_int(...), data_path=..., description=...)` — 全部关键字传参；两个计数字段过 `_int`，缺省 `None`（db 层 `_clip`/整数列自行处理）。db.py 596–616 行的实现先用一次单独的 SELECT 探测"本来就有吗"（只为了拿到 `already_existed`），再调幂等的 `ensure_dataset`。
- **1263–1264** `except DBError` → 503 + `dialect`，与 `get()` 的错误口径一致。
- **1265** `result["dialect"] = database.dialect` — 把方言补进 db 层返回的 dict 再回给前端（`register_dataset` 自己不返回 dialect，所以在这里就地补；这也等于在改 db 层刚造出来的对象，但它是一次性产物，无副作用）。
- **1266** `return result, 200 if result["already_existed"] else 201` — 用条件表达式给出双状态码；这也要求 `register_dataset` 的返回体里**必然**有 `already_existed` 键（db.py 616 行确实固定返回它）。

> ⚠️ 存疑：1257–1262 行的 `_int(body.get("class_count"), None, "class_count")` 在参数非法时抛 `InvalidInput`（ValueError 子类），而下面的 `except` 只接 `DBError`。由于项目**没有全局异常处理器**（api.py 1522–1525 行说明 flask_restful 会把非 HTTP 异常统一变成 500），`POST /datasets/db` 带 `{"name":"x","class_count":"abc"}` 会返回 500 Internal Server Error，而不是"class_count 必须是整数"的 400。本文件在 `FigureList.get`（1206–1209 行）对同一个问题专门做了 `except InvalidInput`，此处是遗漏——更省事的做法是把这类表单/JSON 取值统一收进一个带 400 映射的小工具。

## 覆盖清单

- 覆盖范围：第 975–1266 行，共 292 行，全部有对应条目（相邻同逻辑行已合并为 `- **起–止**` 形式，区间连续无跳过）。
- 分节与条目数：内容分节 **28 节**，明细条目 **166 条**。
- 存疑标注：共 **16 处** `> ⚠️ 存疑`（其中 1127–1137 的 framework 问题在 1078 与 1127 两处各标了一次，合并后为 13 组）。
- 存疑点汇总（按行号）：976（`<版本>` 描述过期）、1006+1035（`..` 名字抛未捕获 ValueError → 500）、1026–1027（`probed_files` 只到命中者为止）、1039–1040（Windows 大小写不敏感导致同名不同大小写互相覆盖）、1045–1047（`_upload_meta` 的 `InvalidInput` 被吞成 500）、1055–1056（登记失败仍 201，盘上留下未登记产物）、1067+1127–1137（用户 meta 分支不写/不校正 `framework`，探测结果被弃用）、1084（`file`/`files` 两个字段只取其一，不合并）、1104–1105（注释"先筛大小再 read"与实现不符）、1135（`setdefault` 与 1132 的 `not ... get()` 写法不一致，`scaler_file: null` 不会被补）、1184（`ModelCreate` 无法区分新建/复用）、1207（`limit=0` 静默变 60、负数未拦）、1260（`InvalidInput` 未接住 → 500）。

---

# 第 5 段 · 行 1267–1604

> 说明：本文解释的是**代码实际行为**，不重复文件里的中文注释。凡我实测验证过的结论都直接写成结论；与注释说法不一致或有隐患的地方用 `> ⚠️ 存疑` 标出。
> 验证环境：`D:\22project\testRestfulProject\venv`（Python 3.14.7 / Flask 3.1.3 / flask-restful 0.3.10 / numpy 2.5.2），手段是用真实 `register_api()` 注册后走 `app.test_client()` 发请求。

## 行 1267–1271 · `class DatasetSignal(Resource)` 与类 docstring
**作用**：GET `/datasets/signal` —— 从 .mat 或表格文件里取一段信号并降采样成数值数组，给前端画波形。
- **1267** `class DatasetSignal(Resource):` — flask-restful 的资源类，实例化由框架负责，类名小写即注册 endpoint（`datasetsignal`，已在 url_map 里确认）。
- **1268–1271** docstring — 声明支持两类数据源（内置 .mat 的 DE 通道、表格文件的某一列）；注意首行**不是** `GET /xxx ——` 形式，所以 `_route_index()` 的正则剥不掉前缀，`GET /api` 里这一条的描述就是整句原文（已实测）。

## 行 1272–1278 · `get()` 签名、docstring 与必填参数
- **1272** `def get(self):` — 只实现 GET；本资源没有 post/put/delete，其它方法由 flask-restful 回 405。
- **1273** 方法 docstring — 只说明返回"已降采样成 points 个数值"，不涉及具体路径。
- **1274** 注释（入参分工）— 与实现一致：`dataset` 选目录、`file` 选文件、`points/start` 选窗口。
- **1275** `dataset = request.args.get("dataset") or ""` — 把 `None` 统一成 `""`，这样下面 `if/elif` 三连只判真值即可，末尾 `else` 天然覆盖"没传 dataset"的情况。
- **1276** `filename = request.args.get("file")` — 刻意**不**给默认值：保持 `None` 才能和"传了空串"区分开（空串会被 1278 的 `not filename` 一起拦下）。
- **1277–1278** 缺 `file` 直接 400 — 在任何路径计算之前返回，避免后面拿 `None` 去 `Path()` 抛异常变成 500。

## 行 1279–1290 · `points` / `start` 的解析与夹取
- **1279–1284** 注释（为什么夹在 200..4000、为什么 `_int` 必须包 try）— 与代码完全对得上：`_int` 转不动时抛 `InvalidInput`，而 flask-restful 的 `error_router/handle_error` 会自己接管非 HTTPException（已读安装包源码 293–311 行），Flask 的 `errorhandler` 够不着，所以**只有显式 try/except 才能把参数错变成 400**。
- **1285** `try:` — 唯一目的就是把下面两行的 `InvalidInput` 接到 400 分支，没有别的副作用。
- **1286** `points = min(max(_int(..., 1500, "points") or 1500, 200), 4000)` — 先 `_int` 再 `or 1500`（`points=0` 退默认）再夹到 200..4000。实测：`points=0` → 1500，`points=99999` → 4000。
- **1287–1288** `start = max(_int(..., 0, "start"), 0)` — 夹到非负。负数在 Python 切片里表示"从尾部数"，`signal[-5:]` 会切出一个合法但错位的窗口，所以必须夹。实测 `start=-5` → 0。
- **1289–1290** `except InvalidInput` → 400 — 与 1284 的注释配套；这也解释了为什么 `?points=abc` 返回 400 而不是 500（实测 400 `{"error": "points 必须是整数，收到 'abc'"}`）。
- **1291–1292** `column` / `sheet` — 原样透传给 `tabular`，只在表格分支用到：读 .mat 时响应里这两个字段就是 `null`（实测）。

## 行 1293–1303 · `dataset` 三分支：内置键 / `表格:` 前缀 / 裸目录名
- **1293** 注释（目录来自 dataset 键）— 说明 `directory` 的三条来源。
- **1294** `directory = None` — 哨兵值：只有真命中了前两支或第三支才不是 None，1304 靠它判断"要不要做数据集目录内的路径校验"。
- **1295–1297** 内置键分支 — `config.dataset_dirs` 就是 `DATASET_DIRS`（`config.py` 37–40 行），只有 `CWRU-0HP`、`CWRU-0HP(cwt)` 两个键，值是 `Path`。命中后直接取盘上目录，不做任何拼接。
- **1298–1300** `表格:` 前缀分支 — 与 `DatasetList` 返回的 key 口径对齐（`"表格:<目录名>"`）；`split(":", 1)[1]` 只切第一个冒号，目录名里再有冒号也不会被切碎。实测 `dataset=表格:../..` 会解析成 `testRestfulProject`（在工作区内，能过闸门），只是文件不存在 → 404。
- **1301–1303** 裸目录名兜底 — `config.upload_dir / dataset`。⚠️ 若这里传的是**绝对路径**，pathlib 的 `/` 会丢弃左边的基路径（`Path("...\\data\\datasets") / "D:\\Windows"` == `D:\\Windows`，已实测），所以该分支的安全性**完全依赖 1308 的工作区闸门**：实测 `dataset=D:\Windows` → 400"越出工作区"。

## 行 1304–1310 · 第一道闸门：数据集目录必须落在工作区内
- **1304** `if directory is not None:` — 只有明确指定了数据集目录才做这层校验；`dataset` 为空（走 1319 分支）时不进这里。
- **1305** `try:` — 只为接住 `relative_to` 的 `ValueError`。
- **1306–1308** `directory.resolve().relative_to(config.workspace_dir.resolve())` — 用 Path 语义而不是字符串 `startswith`，因此 `D:\22project_evil\x` 这种同前缀目录挡得住；`resolve()` 会先展开 `..` 与符号链接，所以 `..` 层级逃逸也会露馅。实测 `dataset=../../../..` → 400。
- **1309–1310** `except ValueError` → 400 — 报错文本里带上了原始 `dataset`。⚠️ 注意这个回显也会被出口脱敏改写：实测 `dataset=D:\Windows` 的报错是 `非法的 dataset 参数：'<本机>/\Windows'`，多出一个分隔符但没泄露真实盘符。
- **设计边界**：这道闸门保证的是"不逃出 `D:\22project`"，**不是**"只能指向数据集根目录"。所以 `dataset=..`（解析到 `testRestfulProject\data`）或 `表格:../..`（解析到 `testRestfulProject`）都能通过校验，只是随后通常 404。这是刻意的宽口径（内置键指向 `1DCNN/0HP`、上传集指向 `data/datasets/<名>`，本来就跨目录），但排查"为什么某个 `dataset` 值没被拦"时要记得这一点。

## 行 1311–1318 · 第二道闸门：文件名削平 + 结果必须仍在数据集目录内
- **1311–1313** 注释（两道闸门都要留）— 结论是对的（两道确实都要留），但**理由与代码不符**，见下方存疑。
- **1314** `path = (directory / Path(filename).name).resolve()` — 第一道闸门 `Path(filename).name` 把 `..\..\secret.csv` 削成 `secret.csv`、把 `C:\Windows\win.ini` 削成 `win.ini`（均实测），等于把用户输入降级成"纯文件名"。
- **1315–1318** `path.relative_to(directory.resolve())` → 不在则 400 — 第二道闸门。实测 `file=..` 时 `Path("..").name` 仍是 `".."`（**没被削平**），拼出来就是父目录，正是靠 `relative_to` 拦下的（返回 400 `文件不在该数据集目录内：..`）；同理，数据集目录内一个指向外部的符号链接也会因 `resolve()` 而在此露馅。

> ⚠️ 存疑：1312–1313 的注释写"只靠 name 挡不住**绝对路径**"，实测不成立 —— `Path(r"C:\Windows\win.ini").name == "win.ini"`，第一道闸门本身就能把绝对路径削成文件名。第二道闸门真正不可替代的场景是：①`file=..`（或 `.`、`a/..` 这类**本身就是目录**的名字，`.name` 原样保留）；②数据集目录内的**符号链接**指向目录外（`resolve()` 之后才暴露）。建议把注释理由改成这两条，否则以后有人"按注释推理"删掉第二道闸门就会真的开一个 `file=..` 的口子。

## 行 1319–1327 · `dataset` 为空的兜底分支与存在性检查
- **1319–1324** 交给 `_resolve_workspace_path()` — 这条路径复用 `/datasets/table` 的同一套解析：绝对路径只试一次，相对路径先按工作区再按项目目录试（两级回退），且每个候选都用 `relative_to(workspace)` 判越界（见 api.py 317–339）。失败抛 `InvalidInput` → 400；注意它的报错里会回显原始 `raw`。
- **1325–1327** `if not path.is_file(): 404` — 用 `path.name` 而不是完整路径回报，是为了不在响应里主动递出绝对路径；实测 `file=..\..\db.env` 得到 `{"error": "文件不存在：db.env"}`，既能看出削平生效，也印证了这条"只报文件名"的策略。

## 行 1328–1342 · 读信号：表格分支与 .mat 分支
- **1328** `try:` — 覆盖两条读取路径的全部异常（坏文件、列名对不上、非数值列、.mat 里没有 DE 通道等）。
- **1329–1334** 表格分支 — `tabular.is_table()` 只看扩展名（`tabular.py` 43–47 行），命中后用 `read_signal(column, sheet)` 取一列数值（内部 `dropna`，会静默丢点），标签直接由文件名推（`label_from_filename` = 去扩展名）。`class_id = None`、`kind = "tabular"`：表格数据集的类别号是"文件名排序位次"、由训练侧决定，这里给不出固定编号。
- **1335–1338** .mat 分支 — `ds.read_de_channel()` 只取键名含大写 `DE` 的通道（找不到抛 `KeyError`，不静默退化）。
- **1339–1342** 反查类别 — 拿文件名在写死的 `CWRU_0HP_CLASSES`（`datasets.py` 35–46 行，顺序即 class_id）里线性找，元组是 `(文件名, class_id, 中文标签)`，所以 `hit[2]` 是标签、`hit[1]` 是类别号；反查不到就退成 `guess_label()` 猜测名 + `None`，**不算错误**。实测 `48k_Drive_End_IR014_0_174.mat` → `label=内圈故障-0.014in`、`class_id=4`。
- **1343–1345** `except Exception` → 500 — 这里刻意用宽异常并带上 `type(exc).__name__`：上游会抛 `ValueError/KeyError/OSError` 等多种类型，与其逐个列举不如统一成"读不出来"+真实异常名，便于定位。

## 行 1346–1361 · 降采样与响应体
- **1346–1347** 注释（stride 口径）— 与实现一致：`stride = size // points` 保证抽到的点数 **≥** points，再 `[:points]` 截齐。
- **1348** `segment = signal[start:]` — 先按 start 截一段；注意这一步对 `start` 不做上限校验（见存疑）。
- **1349** `stride = max(1, segment.size // points)` — `max(1, ...)` 防"目标点数比实际点数还多"时步长为 0（步长 0 会让切片直接报错）。
- **1350** `values = segment[::stride][:points]` — 等间隔抽样再截断。实测 63788 点取 1500 → stride 42；取 4000 → stride 15；`segment.size < points` 时 stride=1，返回的点数会少于 points（所以响应里 `points` 报的是 `len(values)`，不是请求值）。
- **1351–1352** 注释（统计按降采样后的 values 算）— 与代码一致：`min/max/mean/std` 全部取自 `values`，和前端画的点同源，不会出现"图很平但均值很大"。
- **1353–1355** 身份字段 — `file` 只给文件名，`file_path` 给绝对路径（出口会被脱敏成 `testRestfulProject\...`，已实测）；`dataset` 为空时回 `None`；`column`/`sheet` 回显请求值。
- **1356–1357** 采样元信息 — `samples_in_file` 是**整个文件**的点数（降采样前），`start`/`stride` 让前端能说明"这是第几段、抽了多少倍"，`points` 是实际返回个数。
- **1358–1360** 统计与数值 — `round(..., 5)` 是给 JSON 瘦身；`values` 逐元素再 round 5 位。⚠️ `values` 为空时这里的 `values.min()` 会抛 `ValueError` 并被 flask-restful 变成 500（见存疑 1）。
- **1361** `}, 200` — 返回 `(dict, 状态码)` 元组，由 flask-restful 序列化成 JSON（Content-Type `application/json`，这也是出口脱敏能认出它的原因）。
- **1362** 分节注释行 — `系统管理` 段落标记，无副作用。

## 行 1363–1375 · `class SystemInfo(Resource)` / `.get()` 与内部函数 `dist_version`
**作用**：GET `/system` —— 本机自检页的数据源（运行时、依赖版本、路径、库表行数、产物/图/日志占用）。
- **1363–1365** 类定义 + docstring + `def get(self)` — 只有 GET。
- **1366–1367** 注释（读不到版本不能让整页 500）— 这是 `dist_version` 存在的理由。
- **1368–1369** `def dist_version(name):` — 闭包小工具，逐个包查版本。
- **1370–1372** `version(name)` — `importlib.metadata.version()`；包根本没装时抛 `PackageNotFoundError` → 返回 `None`（前端渲染成"未安装"）。实测 `/system` 里 `tensorflow`、`keras` 为 `null`，而 `tf-nightly`、`keras-nightly` 有版本号 —— 正因为版本探测失败只降级成 `null`，这一页才没被"缺包"打挂。
- **1373–1375** 其它异常 → `"读取失败"` — 安装元数据损坏（dist-info 缺 `METADATA`）这类情况给一个**字符串**占位，属于"明知有问题但不致命"。副作用：`packages` 的值类型是 `str | None` 混合，前端必须同时处理 `null` 和 `"读取失败"`。

## 行 1376–1386 · 三块占用统计与数据库容错
- **1376–1380** `artifacts` / `figure_items` / `logs` — `list_artifacts()` 来自 registry（只返回 `weights` **确实存在且非空**的产物，见 `registry.py` 88–104、184–205 行），所以下面 `.stat()` 是安全的；`list_figures(limit=1000)` 是"按 mtime 倒序 + 到 limit 就 break"；`glob("*.log")` **不递归**，只统计日志目录第一层。
- **1381–1386** 数据库容错 — 只有这一块允许失败：`DBError` 时把错误塞进 `counts` 并置 `db_ok = False`，页面其余部分照常返回。这正是"库连不上时最需要 /system"的写法；`table_counts()` 本身在 db.py 里带 30 秒缓存（`db.py` 760–781 行），所以连点刷新不会反复跑 8 条 `COUNT(*)`。
- **1387–1391** `runtime` 块 — `sys.version.split()[0]` 取纯版本号，`sys.executable` 与 `platform.platform()/machine()` 都是真实环境值；实测出口脱敏后 `executable` 显示成 `testRestfulProject\venv\Scripts\python.exe`。
- **1392** `packages` — 字典推导遍历模块级 `_PACKAGES`（**`06a8fb8` 后是 14 个名字**，原 17 个；含 tensorflow/torch 双栈），每个都过一次 `dist_version`，缺包不影响其它键。
- **1393** `paths` — 直接给 `config.describe()`。实测返回 `project_dir/model_dir/temp_dir/env_file/db/datasets/upload_dir`，**不含** `log_dir`、`workspace_dir`：想看日志目录得去 `logs.dir`，工作区路径不在这一页（`config.describe()` 里本来就没有）。
- **1394–1395** `database` 块 — `ok`/`counts` 来自上面那个 try，`bootstrap = database.last_bootstrap` 只在"顺手建过库/表"时有值（正常库是 `null`，实测如此）。
- **1396–1399** `artifacts` 块 — `count` 是产物个数，`items` 每项带 `size_kb = weights.stat().st_size / 1024`；只算权重文件大小（meta/scaler 不计），与 docstring 的说法一致。
- **1400–1401** `figures` 块 — `total_kb` 是把 `list_figures` 返回项的 `size_kb` 相加（不是重新 stat），`dir = str(FIG_DIR)`（`figures.py` 43 行 = `data/figures`）。
- **1402–1404** `logs` 块 — 对 `*.log` 逐个 stat 求字节和。⚠️ 与 figures 不同，这里没有上限，日志目录很大时每次 `/system` 都要 stat 一遍全部文件；另外 glob 与 stat 之间文件被删会抛 `FileNotFoundError`（极窄的时间窗，目前没人处理）。
- **1405** `}, 200` — 同上，元组返回。

## 行 1406–1415 · `class SystemLogs(Resource)` / `.get()`
**作用**：GET `/system/logs` —— 训练日志文件清单（不含内容）。
- **1406–1407** 类与 docstring — 声明"按修改时间倒序"。
- **1408–1410** `sorted(..., key=mtime, reverse=True)` — 倒序让前端下拉的第一项就是最近一次训练。实测目录里有 37 个 `.log`，`count` 与列表长度一致。
- **1411–1415** 响应 — 每项只用 `stat()` 取 `size_kb` 与本地时区格式化的 `modified`，**不读文件内容**：日志动辄几十 MB，列表页要的只是名字/大小/时间。

## 行 1416–1433 · `class SystemLogFile(Resource)` / `.get(name)`
**作用**：GET `/system/logs/<name>?tail=N` —— 看某个日志的尾部 N 行。
- **1416–1417** 类与 docstring — URL 里带一个变量段 `<name>`，所以方法签名是 `get(self, name)`，由 flask-restful 按路径参数注入。
- **1418–1421** `if Path(name).name != name: 400` — 这条防护针对的是 **Windows 反斜杠**：Flask 的 `<name>` 转换器本来就不匹配 `/`，所以 URL 里的斜杠根本进不来；但 `%5C` 解码出的 `\` 是普通字符，`..\..\db.env` 能作为"一个段"抵达这里。实测 `/system/logs/..%5C..%5Cdb.env` → 400 `非法日志名`。顺带也挡掉了 `C:x.log` 这类带盘符的形式。
- **1422–1424** 不存在 → 404 — 报错只回显 `name`（用户输入），不泄露目录。
- **1425–1426** `tail` 夹到 10..3000 — `min(max(_int(...) or 300, 10), 3000)`，`tail=0` 退成 300（实测 `tail=0` 返回了全部 21 行，因为文件本身不足 300 行）。⚠️ 这行的 `_int` **没有**包 try，见存疑 2。
- **1427–1431** 读文件并清洗 — `errors="replace"` 是必需的：日志里混进 GBK 输出或二进制碎片时严格解码会抛 `UnicodeDecodeError` 直接 500；`_ANSI`（模块级 43 行）只剥 Keras 进度条那类转义序列；`rstrip()` 顺手吃掉 Windows 的 `\r`，否则前端每行之间会多出空行。
- **1432–1433** 响应 — `returned = len(lines[-tail:])`（实际返回行数，用于提示"被截断"），`lines` 只给尾部；整段是 JSON，所以出口脱敏走 JSON 分支，日志正文里出现的绝对路径也会被改写。
- **注意**：日志名可含子目录吗？不行 —— `Path(name).name != name` 已经把任何带分隔符的名字拒掉，所以 `config.log_dir / name` 永远是第一层的文件。

## 行 1434–1445 · `class Maintenance(Resource)` / `.post()`
**作用**：POST `/system/maintenance` —— 危险维护动作（目前只有"清空图库"）。
- **1434–1435** 类与 docstring — 标注"危险、前端红按钮 + 二次确认"。
- **1436–1440** `target = (_body().get("target") or "").strip()` — `_body()` 对非 JSON/非对象请求体返回 `{}`，所以不带 body 的调用会得到 `target=""`，走下面的 400 分支而不是 500。
- **1441–1443** `if target == "figures": return clear_figures(), 200` — 白名单式分发，**不按字符串拼函数名**；`clear_figures()`（`figures.py` 270–284 行）只删 `FIG_DIR` 下的 png 并清理空目录，返回 `{removed, freed_kb, dir}`，`dir` 会在出口被脱敏。
- **1444–1445** 其它 target → 400 + `supported` — 把可选值一并回给前端。⚠️ 与注释一致：这里的 `if` 和 `supported` 列表是**两处**需要同步维护的地方，新增动作只改一处就会出现"提示支持却回 400"。

## 行 1446–1463 · `_ROUTES` 前的路由表说明注释
**作用**：声明这张表是唯一注册清单 + 为什么不能随便重排。
- **1446–1449** 单一清单 — 与实现一致：`register_api()` 遍历它注册，`_route_index()` 遍历它生成索引，两者不可能脱钩。
- **1450** 单独一行 `#` — 纯粹的空注释分隔行，把上面"清单唯一 + 顺序讲究"的总述与下面三条具体条目隔开，无代码含义。
- **1451–1454** `/models` 出现两次 — 与实现一致且已实测：`ModelList` 只有 GET、`ModelCreate` 只有 POST，`GET /models` → 200 产物清单、`POST /models` → 400 "ModelName 不能为空"，互不干扰。若以后加了同路径**同方法**的资源类，胜负取决于 werkzeug 的内部排序（同规则键时退化成插入顺序），所以确实不能那样写。
- **1455–1458** 静态段必须先于变量段 — ⚠️ 结论在本项目实际依赖的版本上**不成立**，见存疑 4。
- **1459–1463** ApiIndex 一次挂两个 URL — 与实现一致，且已验证反面：拆成两次 `add_resource(ApiIndex, "/")` / `add_resource(ApiIndex, "/api")` 会抛 `AssertionError: View function mapping is overwriting an existing endpoint function: apiindex`（endpoint 由类名小写生成，两次同名）。这也是 `/` 不再需要一个转发用的 `Root` 类的原因。

## 行 1464–1489 · `_ROUTES` 路由表本体
- **1464–1465** `_ROUTES = ((ApiIndex, ("/", "/api")), ...)` — 元组套元组：每条是 `(资源类, 路径元组)`，路径元组用 `*` 展开传给 `add_resource`。共 **24 条 / 25 条 url 规则**（ApiIndex 占两条 URL）。
- **1466–1473** 体检与推理组 — `/health`、`/models`、`/datasets`、`/train`、`/trainings`、`/predict`、`/inference-tasks`、`/inference-tasks/<int:task_id>`。注意 `InferenceTaskDetail` 用的是 `<int:task_id>`：非整数 id 在**路由层**就不匹配（回 404），不会进到方法里再校验。
- **1474–1478** 模型组（顺序最讲究的一段）— `ArtifactDetail("/models/<model_name>")` 在 `ModelUpload("/models/upload")` **之前**。实测两者都正常：`POST /models/upload` 走 ModelUpload、`GET /models/1dcnn` 走 ArtifactDetail；但 `GET /models/upload`（上传接口没实现 GET）实测会被 ArtifactDetail 当作 `model_name='upload'` 处理并回 404 `还没有任何 upload 的模型产物`。
- **1479–1489** 图 / 数据集 / 系统组 — `FigureFile` 用 `<path:relpath>`（允许斜杠的多段路径，穿越防护交给 `send_from_directory`）；`/system/logs` 与 `/system/logs/<name>` 是两条独立规则（前者静态，无冲突）。`register_api` 会把这段顺序原样反映成 url_map 的插入顺序。

## 行 1490–1493 · 已删路由的备忘注释
- **1490–1493** — 说明 `Console → /ui`、`DatasetRecord → /datasets/db/<int:dataset_id>` 已删除、别往索引里补。实测 `GET /ui` → 404，与注释一致。

## 行 1494–1496 · `_PATH_DISPLAY` 显示映射
- **1494–1496** `_PATH_DISPLAY = {"<int:task_id>": "<id>", "<path:relpath>": "<路径>", "<model_name>": "<model>", "<name>": "<名>"}` — 把 Flask 转换器写法换成中文占位符，**只作用于索引页显示**，不参与匹配；转换时机是 1510–1511 的字符串 `replace`（子串替换，所以 key 之间不能互为子串——当前四个 key 无此问题）。

## 行 1497–1513 · `_route_index()`
**作用**：路径 → 用途说明，供 `GET /`（=`GET /api`）返回。
- **1497–1501** 函数与 docstring — 说明描述直接取各 Resource 的 docstring 首行，同一路径被两个类实现时拼起来（现在只有 `/models`）。
- **1502** `out: dict[str, str] = {}` — 累加器；dict 保序，所以索引的键顺序 = `_ROUTES` 顺序（这是顺序唯一真正影响行为的地方）。
- **1503** `for resource, paths in _ROUTES:` — 遍历同一张表。
- **1504–1505** 取 docstring 首行 — `(resource.__doc__ or "")` 兼容无 docstring 的类，`splitlines()[0]` 只要第一行。
- **1506** 剥掉 `GET /health —— ` 这类前缀 — 覆盖了单个方法与组合方法（`GET/POST`、`GET/PUT/DELETE`…）两种写法；实测 24 条描述的前缀都被干净剥掉。DatasetSignal 这种首行不带 `GET /xxx ——` 的 docstring 会原样保留（设计如此，正则不匹配就不动）。
- **1507** 去 `**` 与句末 `。` — 让拼接后的句子读起来干净。
- **1508–1512** 逐 URL 生成条目 — 先做显示占位符替换，再写入 `out`：同一显示路径已存在时（只有 `/models`）用 `；` 拼接，顺序就是 `_ROUTES` 里的先后（ModelList 的描述在前、ModelCreate 的在后，实测输出："磁盘产物（artifacts）+ 库表登记（db_models）两份清单；新增一条 Models 表登记…"）。
- **1513** `return out` — 直接交给 `ApiIndex.get` 放进 `endpoints`。

> ⚠️ 存疑 3：1505 的 `splitlines()[0]` 对**没有 docstring** 的资源类是 `[][0]` → `IndexError`，会把 `GET /api` 整页打成 500（实测 `"".splitlines()` 就是空列表）。当前 24 个类都有 docstring 所以碰不到，但"新增资源类忘了写 docstring"是很容易发生的，用 `next(iter(lines), "")` 之类的写法更稳。

## 行 1514–1525 · `register_api(api)`
**作用**：把 `_ROUTES` 挂到 flask_restful.Api 上（由 `main.py` 第 25 行调用）。
- **1514–1517** 循环 `api.add_resource(resource, *paths)` — 一资源多 URL 只调一次，因此 endpoint 只有一份；`api = Api(app)` 在 `main.py` 里创建，所以 `.app` 就是那个 Flask 应用。
- **1518–1521** `_install_path_mask(api)` — 收尾挂出口脱敏。放在这里而不是 main.py，是为了"谁调 `register_api` 谁就自动带上脱敏"；传的是 Api 对象本身，函数内部自己取 `api.app`。漏挂的后果是**所有**响应都裸奔真实路径（实测：同一批路由在不调 `register_api` 的应用里，`/system/logs` 的 `dir` 就是 `D:\22project\...` 全路径）。
- **1522–1525** 注释（别用全局 errorhandler 收敛 try/except）— 与安装包实现一致：`Api.error_router` 先接管，`handle_error` 里只有 HTTPException 才走正常流程，非 HTTPException 在 `PROPAGATE_EXCEPTIONS`（debug/testing 时默认 True）为真时**重新抛出**、否则统一变成 500。所以"参数错 → 400"只能写在各方法里。⚠️ 补充：`main.py` 用 `app.run(debug=True)` 启动，意味着线上跑的就是 propagate 为真的那一种 —— 实测把 `app.debug = True` 后，`?tail=abc` 的 `InvalidInput` 会直接从请求处理里抛出来（真实服务里就是 Werkzeug 调试页），而不是那份 JSON 500。同一份代码在 debug/非 debug 下确实是两种表现。

## 行 1526–1528 · 脱敏段落与 `_DRIVE_RE`
- **1526** 分节注释 — 说明出口脱敏的目的（不暴露本机真实目录）。
- **1527–1528** `_DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")` — 匹配"单字母 + 冒号 + 分隔符"，能覆盖 `C:\` 与 `d:/`。⚠️ 注释里"能避开 `http://` 这种多字母 scheme"是**错的**，见存疑 5。

## 行 1529–1543 · `mask_private_paths()` docstring
**作用**：声明三种替换形态与"只影响显示"的边界。
- **1529–1543** — docstring 给了三个例子（工作区前缀削成相对路径、用户目录 → `<用户目录>`、其它盘符 → `<本机>/`），并解释为什么放在出口做：路径散落在 `directory`/`weights`/`dataset.path`/`log_file`/报错信息等 30 多个字段里，逐个改必漏。最后一句"前端回传的路径变成相对工作区后，后端用 `project_dir / 相对路径` 仍能解析"是关键约束：**脱敏只改显示口径，不改解析口径**，否则训练/推理会拿到一个解析不了的路径。

## 行 1544–1561 · 内部函数 `fix(text)`
- **1544–1545** `def fix(text):` — 对单个字符串做替换。
- **1546–1551** 整串等值短路 — `text == workspace` → `<工作区>`，`text == home` → `<用户目录>`。不加这两条的话，前缀替换会把整串替换成空串或剩下的残片，前端看到一个空字段会误以为"没数据"。
- **1552–1558** 前缀替换循环 — `for raw, label in ((workspace, ""), (home, "<用户目录>"))`：工作区排前面、replace 成**空串**（得到"相对工作区的相对路径"，正是前端要回传的口径），用户目录只做遮蔽。每种前缀试三种写法：`raw + "\\"`、`raw + "/"`、`raw` 本身 —— 前两种覆盖同一路径的两种分隔符写法，第三种兜"路径正好以该目录结尾/出现在句子中间、后面没有分隔符"的情况。顺序很重要：若把 `home` 放前面，工作区（假设也在用户目录下）会被先遮蔽成 `<用户目录>\...`，前端就拿不到相对口径了。
- **1559–1561** `_DRIVE_RE.sub(lambda _match: "<本机>/", text)` — 兜住工作区之外的其它盘符，保留其余目录结构（只藏机器信息，不丢可读性）。**为什么用 lambda**：`re.sub` 的替换串会走"模板"解析，`\` 是转义引导符 —— 实测模板 `"<本机>\\"`（以反斜杠结尾）会抛 `re.error: bad escape (end of pattern)`，模板 `r"\d"` 抛 `bad escape \d`，而 `"<本机>\1"` 更阴险：它被当成组引用、在没有 1 号组时静默替换成 `\x01` 字符。用函数（lambda）返回替换文本就完全绕开模板解析。
> ⚠️ 存疑 6：注意当前**字面量是 `"<本机>/"`（正斜杠结尾）**，实测把它当模板直接传并不会报错 —— 也就是说此刻用 lambda 属于"防御性写法"而非必需。只有当有人把占位符改成 `<本机>\`（想保留 Windows 分隔符）时才真的必须用 lambda。注释把"必须用 lambda"说成当下一刻的硬约束，与代码字面量不完全对得上。

## 行 1562–1573 · 内部函数 `walk(node)`
- **1562–1565** 函数与注释 — 递归遍历 JSON 结构，字符串套 `fix()`；**容器一律重建而不是就地改**，因为响应对象里的 dict/list 可能还被别处引用，就地改会连带污染原始数据；`tuple` 也重建成 `list`（JSON 序列化出去本来都是数组，形状不变）。
- **1566–1567** `str` → `fix(node)` — 只有字符串可能含路径。
- **1568–1569** `dict` → 新 dict（键不动，只 walk 值）— 键不脱敏是刻意的：键是字段名。
- **1570–1571** `list`/`tuple` → 新 list — 统一成 list。
- **1572** `return node` — int/float/bool/None 原样放行（数字不可能是路径）。
- **1573** `return walk(payload)` — 入口即返回，调用方拿到的是**新对象**。

## 行 1574–1604 · `_install_path_mask(api)` 与 `after_request` 钩子
- **1574–1575** 函数与 docstring — 给 Flask app 挂一个响应出口钩子，只处理 JSON，图片/日志/SSE 放行。
- **1576–1577** 注释（"取不到 `.app` 就直接跳过"）— 解释了 1578 行为什么用 `getattr(..., None)` 而不是直接取属性：脱敏是附加能力，不该成为注册流程的失败点。
- **1578–1580** `app = getattr(api, "app", None); if app is None: return` — 用 getattr 而不是直接 `api.app`：测试里塞个假 api 时不要因为脱敏把注册流程搞崩（`# pragma: no cover` 说明这条分支在覆盖率上被显式排除）。
- **1581–1582** `workspace, home = str(config.workspace_dir), str(Path.home())` — 在注册时算一次就够；`after_request` 每个响应都会跑，不该在里面重复 `Path.home()`。这两个字符串是 `fix()` 的前缀依据（`str()` 保证是反斜杠形式，斜杠形式由 `fix` 里的 `raw + "/"` 兜）。
- **1583–1585** `@app.after_request def _mask_response(response)` — 挂在 **app** 上而不是 blueprint 上，所以它对整个应用生效：`main.py` 里 `register_dvadmin(app)`（含 `/sse/`、CORS、404 兜底）先注册、`register_api(api)` 后注册，而 Flask 的 `after_request` 是**后注册先执行**，因此脱敏先跑、dvadmin 的 `_cors` 后跑 —— 两者都只改自己的部分，顺序无冲突。
- **1586–1591** mimetype 判断 — 只碰 `application/json` 与 `text/*`（且不是 `text/event-stream`）：
  - PNG（`/figures/<路径>` 走 `send_from_directory`）是二进制，`get_data(as_text=True)` 会做一次 **utf-8 + errors=replace 的有损解码**（实测 `bytes(range(256))` 解码再编码回来已不相等），再 `set_data()` 就把图片写花了；
  - `text/event-stream` 是流式响应（dvadmin 的 `/sse/` 显式声明这个 Content-Type，用来喂前端的 `EventSource`），`get_data()` 会把生成器**一次性读完**、`set_data()` 把响应换成一次性 body，等于把"流"降级成"一次性响应"；
  - 放在出口做而不是逐字段改，理由与 docstring 相同：字段太多必然漏。
- **1592–1599** JSON 分支 — `json.loads(get_data(as_text=True) or "null")`：`or "null"` 处理空 body；解析失败（自拼的 JSON 片段、半截 body）直接 `return response` 原样放行，这是**刻意 fail-open**：宁可漏一次脱敏，也不能把正常响应改坏。成功则 `json.dumps(..., ensure_ascii=False)` 保住中文再 `set_data()`，Content-Length 由 Flask 重新计算。
- **1600–1602** `text/*` 分支 — 排除 `event-stream` 后，把整个文本 body 交给 `mask_private_paths`（它接受字符串，`walk` 会直接走 `fix`）。覆盖对象包括日志尾部、以及 Flask/dvadmin 的 HTML 错误页。
- **1603–1604** `return response` — **每个分支都必须返回**：`after_request` 不是"可选返回值"的钩子，返回 `None` 会让 Flask 在 `process_response` 的类型校验里抛 `TypeError`，把一次正常请求变成 500。这是本段最后一行、也是整份文件最后一个可执行语句。

---

## 存疑 / 可疑点清单（均已实测或读源码确认）

1. **`get ?start` 超出文件长度 → 500**（行 1348–1358）：`segment` 为空数组时 `values.min()` 抛 `ValueError: zero-size array to reduction operation minimum which has no identity`，该行在 try 之外，被 flask-restful 变成 500。实测 `/datasets/signal?dataset=CWRU-0HP&file=48k_Drive_End_IR014_0_174.mat&points=300&start=500000` → `500 {"message": "Internal Server Error"}`。与同函数 1285–1290 精心维护的"参数错 → 400"口径自相矛盾，建议在 `start >= signal.size` 时提前回 400 或 200 空段。
2. **`/system/logs/<name>?tail=abc` → 500**（行 1426）：这个 `_int` 没包 try，实测 500（`InvalidInput` 被 flask-restful 吞成 `{"message": "Internal Server Error"}`）。同文件的 `DatasetSignal`(1285–1290)、`FigureList`(1206–1209)、`TablePreview`(515–518) 都显式接了 `InvalidInput`，此处是漏网，正是 1282–1284 那段注释在警告的情形。
3. **`_route_index()` 对无 docstring 的资源类会 `IndexError`**（行 1505）：`"".splitlines()` 是空列表，`[0]` 直接抛异常 → `GET /api` 与 `GET /` 双双 500。当前 24 个类都有 docstring，属潜在隐患。
4. **`_ROUTES` "顺序有讲究"的说法在实际版本上不成立**（行 1455–1458）：把 `reversed(_ROUTES)` 全部重新注册后实测 `POST /models/upload` 仍走 ModelUpload、`GET/POST /models` 各归其类 —— Werkzeug 会按"静态段优先、参数段靠后"排序规则，与方法分发共同保证正确性，跟注册顺序基本无关。真正受顺序影响的只有 `_route_index()` 的输出（键顺序 + `/models` 那句拼接的先后）。另外该注释说"否则 `/models/upload` 会被当成 `model_name='upload'` 丢给 ArtifactDetail（上传接口直接 404/400）"——实测 **GET** `/models/upload` 确实就是这样被 ArtifactDetail 处理并回 404 的（上传接口只实现 POST，这不算故障），说法与现象相反，容易误导后人。
5. **`_DRIVE_RE` 会误伤 `http://` / `https://`**（行 1528、1561）：正则没有前后边界，`http://x` 里的 `p:/` 就满足"单字母+冒号+分隔符"。实测 `mask_private_paths("http://127.0.0.1:5000/figures/a.png", ...)` → `"htt<本机>//127.0.0.1:5000/figures/a.png"`，`https://` → `"http<本机>//"`；而注释 1527 明确宣称"能避开 http:// 这种多字母 scheme"。当前 `model_service/*.py` 里没有任何返回 `http(s)://` 的字段（全仓只有这句注释本身命中该模式），所以是**潜在**问题；一旦有接口回绝对 URL（如外链、回调地址）就会被静默改坏。修法：`(?<![A-Za-z0-9])[A-Za-z]:[\\/]`。
6. **`fix()` 用 lambda 的理由与字面量不符**（行 1559–1561）：注释说"替换串以反斜杠结尾会让 `re.sub` 抛 bad escape"，而实际替换文本是 `"<本机>/"`（正斜杠结尾），实测当模板直接传不会报错（`"<本机>\\"` 才会抛 `PatternError: bad escape (end of pattern)`；`"<本机>\1"` 则会静默变成 `\x01`）。当前 lambda 属防御性写法，注释把机制说成了当下必需的约束。
7. **`/system` 的图库统计被 `limit=1000` 截断**（行 1379、1400–1401）：`list_figures(limit=1000)` 到 1000 条就 break，所以 `figures.count` 与 `total_kb` 在超过 1000 张图时都是"前 1000 张"的口径；`/figures` 那边同样有 500 的截断（1200–1219）。目前图库规模小，看不出问题。
8. **`DatasetSignal` 第二道闸门的存在理由需要改写注释**（行 1311–1313）：真正不可替代的是 `file=..`（实测 `Path("..").name == ".."`，未被削平，靠 `relative_to` 拦成 400）与目录内符号链接，而不是"绝对路径"（`Path(r"C:\Windows\win.ini").name == "win.ini"` 已被第一道闸门削平）。

---

## 行号换算（`e361fa6` 1604 行 → `06a8fb8` 1649 行）

本文所有行号仍是 `e361fa6` 的编号。要换到当前文件，按**旧行号落在哪个区间**加偏移即可：

| 旧行号区间 | 偏移 | 新行号区间 |
| --- | --- | --- |
| 1–43 | +0 | 1–43 |
| 44–48 | +3 | 47–51 |
| 49–59 | +5 | 54–64 |
| 62–157 | +11 | 73–168 |
| 160–167 | +22 | 182–189 |
| 169–277 | +23 | 192–300 |
| 283–1011 | +43 | 326–1054 |
| 1013–1031 | +44 | 1057–1075 |
| 1033–1604 | +45 | 1078–1649 |

那 6 个"缺口"（60–61、158–159、168、278–282、1012、1032）就是本次被改写的行本身，对应关系已在正文里逐条标了「今 X–Y 行」。

> 为什么用分段偏移而不是整篇重排：doc 里 `784`、`500`、`1500`、`1604` 这类**数据字面量**与行号混在同一句话里（例如"输入长度 784"和"（778）"），批量加偏移会把字面量一起改错。真要重新生成，稳妥办法是照当前 api.py 重写一遍，而不是改数字。

---

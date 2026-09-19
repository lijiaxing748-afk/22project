# model_service —— 把流程图上的「训练 → 模型产物 → 推理」接起来

对应你画的那张流程图：

```
Web服务器 ─▶ flask_restful 接口(Web访问) ─┬─▶ 算法模型1(1DCNN)  ──训练──▶ 数据集
                                          ├─▶ 算法模型2(cwt_cnn)          │
                                          └─▶ 算法模型3(adtk)             ▼
                                   边缘设备 ◀── 推理 ◀── Pxl模型(模型产物)
```

改造前这条链是**断的**：两个训练脚本跑完就把模型丢在内存里，仓库里没有任何权重文件，
`Trainings.ModelPath` 无值可填，也没有任何推理代码，SQL 里那 8 张表更是一行都没被写过。
本模块把断点补上，并且**每一环都能被验证**。

---

## 一、接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 接口索引（等同 `/api`；原先 302 跳到已删除的 `/ui` 控制台） |
| GET | `/api` | 接口索引 —— ⚠️ **2026-09-19 起需登录**：未登录只回 `{"endpoints": {}, "note": …}`（接口目录不再对匿名开放） |
| GET | `/health` | 服务 / 数据库 / 产物体检 —— ⚠️ 未登录只回"存活 + 库通不通 + 鉴权开没开"，路径/库名/产物清单要登录 |
| GET | `/models` | 落盘产物 + 库表登记的模型清单 |
| POST | `/models` | 登记一个模型（只写 `Models` 表，不训练、不落产物） |
| POST | `/models/upload` | 上传模型（文件夹或多个文件）→ 探测 → 落盘 → 登记 |
| GET | `/models/<name>` | 产物 meta.json 全文；`DELETE ?scope=artifact` 删除磁盘产物（危险，整份删掉、不可恢复） |
| GET | `/models/<name>/references` | 该模型被哪些表引用了多少行（删之前的体检） |
| GET | `/models/<name>/overview` | 模型档案（登记 + 产物参数 + 最近训练 + 引用统计） |
| GET | `/datasets` | 数据集体检（内置 .mat + `data/datasets` 下上传的表格数据集） |
| GET | `/datasets/db` | Datasets 表登记记录；`POST` 登记新数据集 |
| POST | `/datasets/upload` | 上传表格文件到 `data/datasets/<名称>/`（multipart：`name` + 多个 `file`） |
| GET | `/datasets/table` | 表格预览（列统计 / 前 N 行 / 推荐信号列，`?path=`） |
| GET | `/datasets/signal` | 取一段原始信号（.mat 或表格，画波形用） |
| POST | `/train` | 训练 → 落盘产物 → 写 `Trainings` |
| GET | `/trainings` | 最近训练记录（读库） |
| POST | `/predict` | 推理 → 写 `InferenceTasks` + `InferenceResults` + `ModelInvocations` |
| GET | `/inference-tasks` | 最近推理任务（读库） |
| GET | `/inference-tasks/<id>` | 任务 + 结果明细（读库） |
| GET | `/system` | 运行信息（Python/依赖版本/路径/库表行数/占用） |
| GET | `/system/logs` | 训练日志列表；`/system/logs/<name>?tail=N` 看尾部 |
| POST | `/system/maintenance` | 维护（目前支持 `target=figures` 清空图库，危险） |
| GET | `/figures` | 已生成的图（训练曲线/混淆矩阵/每类指标/预测分布/预测波形） |
| GET | `/figures/<路径>` | 直接返回 PNG（浏览器打开即可看） |

> 上面这张表与 `register_api()` 一一对应（共 24 条）。**`/todos` 已不存在**：它随 flask_restful
> 官方示例一起删除，接口索引里也不再列它。三条 `GET/PUT/DELETE /datasets/db/<id>` 单行增删改
> 路由同样已删除（全项目零调用，前端只保留 `datasetDb` / `registerDataset`）——
> 现在**唯一**的权威清单是运行中的 `GET /api`（**已登录**才有内容，见上表）。

```bash
# 训练（1dcnn / cwt_cnn / adtk，也可写 算法模型1/2/3）
curl -X POST http://127.0.0.1:5000/train -H "Content-Type: application/json" \
     -d '{"model":"1dcnn","epochs":10}'

# 推理：既可以用文件（工作区内的 .mat/.csv/.npy，按窗口切），也可以直接送数组
curl -X POST http://127.0.0.1:5000/predict -H "Content-Type: application/json" \
     -d '{"model":"1dcnn","path":"1DCNN/0HP/normal_0_97.mat","index":0,"limit":3}'
curl -X POST http://127.0.0.1:5000/predict -H "Content-Type: application/json" \
     -d '{"model":"1dcnn","samples":[[0.1,0.2,...共784个数]]}'
```

`POST /train` 常用参数：`epochs` `batch_size` `number` `length` `stride` `rate` `seed`
`strict`（是否跳过越界窗口）`legacy_scaler`（是否复刻旧脚本的标准化口径）
`dataset_type`（`matlab` / `tabular`，不传就按目录里有什么自动判断）。

adtk 另有：`detector`（默认 `PcaAD`）、`k`（默认 4）、`c`（默认 5.0）、
`feature_mode`（`stats` 10 维统计特征 / `raw` 784 点原始幅值）、`sampling_rate`（默认 48000）、
`threshold_quantile`（默认 0.995）、`factor`（默认 1.0）、`baseline_file`（默认 `normal_0_97.mat`，
**只能是文件名**）、`max_points`（默认 40 万点，超出部分截断）。
`training._train_adtk` 会读上面每一个键，可对照 `data/models/adtk/meta.json` 的 `params`。

## 二、产物约定（流程图里的「Pxl模型」）

```
data/models/<模型名>/model.keras | model.h5 | model.pt | detector.pkl
                    scaler.npz     ← 训练期标准化参数（推理必须复用）
                    meta.json      ← 输入长度、类别表、指标、超参、数据集指纹
data/logs/train-<模型>-<时间>.log          ← 训练全过程日志
```

**一个模型只有一份产物，没有版本号**：重新训练 / 同名再上传 = **直接替换**这一份。
落盘先写 `.staging-<时间戳>/` 暂存目录，写完整了才换上去；中途失败只删暂存，旧产物原封不动
（`registry.begin_artifact()` / `commit_artifact()` / `abort_artifact()`）。
旧的多版本目录（`data/models/<名>/` 下原来那一层版本子目录）已由 `archive_legacy_versions()`
一次性搬到 `data/archive/model_versions/<名>/` 归档保留（按旧版本号分子目录）—— 归档位置在
`data/models` **之外**，免得它自己被当成一个模型列出来。

`meta.json` 里**必须**带类别表（`labels`）：否则模型文件本身无法解释 0..9 对应哪种故障。

产物与图**只落在文件系统上**（`data/` 下），数据库只负责索引/元数据，且**只用 MySQL**
（表结构见 `sql/schema_mysql.sql`）。原来这里写着 `data/model_management.db ← 未接真库时的
SQLite 兜底库`，那个 sqlite 兜底连同它的 `SQLITE_PATH` 常量都已被删除——`MODEL_DB_DIALECT`
写 `mysql` 以外的值会在启动时直接 `RuntimeError`（详见第三节）。

## 二·半、「上传的模型」支持哪些格式 / 怎么让外部模型直接用

判定用的是 `api.probe_weight()`：**先看后缀，再打开文件看内容**（详见下面那张表）。
推理分派靠产物 `meta.json` 里的 `framework`，**以探测结果为准**（不是后缀表猜的那个——
`.pt` 底下有三种不同格式，后缀区分不了）。

| 后缀 | 内容判据 | framework | 推理怎么加载 | 能不能直接用外部模型 |
|---|---|---|---|---|
| `.keras` / `.h5` | zip 且含 `config.json` 或 `metadata.json` | `tensorflow-keras` | `keras.models.load_model()` **整模型加载** | ✅ **能**，任何 Keras 模型 |
| `.keras` / `.h5` | 非 zip（HDF5）且含 `model_weights` 组或 `model_config` 属性 | `tensorflow-keras` | 同上 | ✅ 能 |
| `.pt2`（推荐） | zip 含 `archive/data/weights/` | `pytorch-exported` | `torch.export.load()` → 直接可调用 | ✅ **能**，自包含 |
| `.pt` / `.pth` | zip 含 `/code/`（TorchScript 标记） | `pytorch-jit` | `torch.jit.load()` | ✅ 能，自包含（但 Py3.14 上 torch 已标记弃用，见下） |
| `.pt` / `.pth` | zip 含 `data.pkl`，`weights_only=True` 读得出 | `pytorch` | 按 **`cwt_cnn_pytorch.build_model`** 重建架构再 `load_state_dict()` | ❌ 只有结构同构才行 |
| `.pt` / `.pth` | 上面都读不出（带自定义类） | `pytorch` | **拒绝**并指路（除非设 `MODEL_ALLOW_UNTRUSTED_PICKLE=1`） | ❌ 需先导出成自包含格式 |
| `.pkl` / `.pickle` | 首字节 `0x80`（**绝不反序列化**） | `adtk` | 只认本项目 adtk 产物（要带 `feature_mode` + `transformer`） | ❌ 别的 pickle 会被拒 |

### 让外部 PyTorch 模型「上传就能用」—— 导出成自包含格式

本平台最早的 pytorch 路线是"重建架构 + `load_state_dict`"，所以只对**本项目训出来的** `.pt` 有效。
外部模型（换个网络结构）走那条必然键不匹配。要能直接用，就让**结构跟着权重一起走**：

```python
# ① 推荐：torch.export（.pt2）—— torch 在 Python 3.14 上官方推荐的序列化方式
import torch
from torch.export import export, Dim
model.eval()
ep = export(model, (torch.randn(2, 1, 848),), dynamic_shapes=({0: Dim("n")},))  # ⚠️ 必须带 dynamic_shapes
torch.export.save(ep, "model.pt2")
# 上传时把 model.pt2 + scaler.npz（可选）+ meta.json（可选，写 labels/input_len）一起选上

# ② 备选：TorchScript —— 自包含，但 torch 明确警告 Python 3.14+ 不受支持，可能失效
traced = torch.jit.trace(model, torch.randn(2, 1, 848)); torch.jit.save(traced, "model.pt")
```

三个实测踩过的坑，都已在代码里兜住或写进提示：
- **`dynamic_shapes` 不能省**：否则导出时那个示例 batch 会被烤死，换个窗口数就
  `Guard failed: x.size()[0] == 2`。输入**长度**则会被固定 —— 这符合本平台契约（推理只用产物里的 `input_len`）。
- **`.pt2` 的 `input_len` 会自动读出来**（从包内 `archive/data/sample_inputs/`，结构是嵌套的
  `[args, kwargs]`，要递归找）；**TorchScript 读不出来**，用上传表单的 `input_len` 或 meta.json 补。
- **输入形状与输出激活**都做了自适应：依次试 `(n,1,L)` / `(n,L)` / `(n,L,1)`；
  输出若每行都在 `[0,1]` 且行和≈1 就当概率，否则当 logits 做 softmax
  （想固定就在 meta.json 写 `"output_activation": "none"` 或 `"softmax"`）。

### 安全口径（`.pt` 的反序列化闸门）

`.pkl` 一直有 `trusted` 闸门；`.pt` 原先**没有**，而它的推理路径用的是
`torch.load(weights_only=False)` —— 等于上传一个 `.pt` 就能在服务端执行代码。现已收口：
- 老式 state_dict 路径改用 **`weights_only=True`**（实测我们自己的 payload 在 True 下完全读得出来，
  int/dict/tensor 都在安全白名单里，原来写 False 的理由并不成立）；
- 读不了（带自定义类）时**明确拒绝**并给出两条出路（导出成自包含格式 / 显式设
  `MODEL_ALLOW_UNTRUSTED_PICKLE=1`），**不再默认降级到会执行代码的那条路**；
- 自包含格式（`.pt2` / TorchScript）加载的是受限 IR，不含 Python 代码，所以不需要闸门。

## 二·补、出图（matplotlib，落 PNG 不弹窗）

原来"表现"结果的地方只有三个脚本里的 `plt.show()`（1DCNN 的准确率/损失曲线、cwt_cnn 的混淆矩阵、
adtk 的时序图），**进程一退图就没了，也拿不进接口**。现在统一由 `model_service/figures.py`
用 matplotlib 的 **Agg 后端 + `savefig`** 落盘：

```
data/figures/<模型>/training_curves.png        准确率/损失（训练集 vs 验证集）
                   /confusion_matrix.png         混淆矩阵（带计数标注）
                   /per_class_metrics.png        每类 精确率/召回率/F1
                   /predict-<时间戳>/prediction_distribution.png   本次推理的预测分布
                                   /predicted_windows.png        窗口原始信号 + 预测标签
```

- 训练完成自动出 3 张，每次 `/predict` 自动出 2 张；响应里带 `figures[]`（含可直接打开的 `url`）
  与 `figures_dir`；推理图目录同时写进 `InferenceTasks.OutputPath`，训练图目录写进 `Trainings.Remark`。
- **出图失败不影响训练/推理**：只在响应里回一个 `figures_error`。
- 中文字体按 `Microsoft YaHei → SimHei → SimSun` 顺序自动挑选（本机三个都在），
  负号与刻度正常；`MPLCONFIGDIR` 被指到 `data/.cache/matplotlib`，避免受限环境写用户目录失败。
- 彩蛋级的坑：`✓/✗` 这类符号在雅黑/宋体里**没有字形**，会渲染成方框，所以命中/未命中用中文标。

## 二·补、表格数据集（Excel / CSV）

除了 CWRU 的 `.mat`，服务还支持**表格格式的数据集**，约定是：
**一个文件 = 一个类别，文件名即标签，表内指定一列作为振动信号。**

- 支持 `.csv` `.txt` `.xlsx` `.xls`（xlsx 走 openpyxl，xls 走 xlrd；CSV 依次试 utf-8-sig / utf-8 / **gbk**，
  中文 Excel 导出的 CSV 常见 GBK）
- 上传：控制台「数据集管理 → 表格数据集」，或 `POST /datasets/upload`（multipart，字段 `name` + 多个 `file`），
  落到 `data/datasets/<数据集名>/`
- 信号列选择：显式 `column=`/`signal_column=` 优先；否则按「列名像信号」（振幅/振动/加速度/value/signal/…）
  → 「首个有波动的数值列」的顺序自动挑，**时间/序号列会被排除**。推理时也能用 `column` 覆盖。
- 训练：`POST /train` 传 `dataset_type=tabular` + `dataset_dir` +（可选）`signal_column`，
  其余 `length/number/stride/rate/seed/strict` 与 `.mat` 完全一致——两个数据源共用同一套切窗、
  标准化、划分逻辑（`datasets.finalize_windows`），所以 1DCNN / cwt_cnn 一行没改。
- 越界窗口的处理与 `.mat` 一致：`strict=true` 跳过并在结果里回报，**绝不补 NaN**。
- 实测（`data/datasets/DEMO-轴承表格数据`：4 个文件 = 4 类，3 个 CSV + 1 个 xlsx，
  每文件 40000 行 × 3 列，故意混入「时间」「温度」两列干扰）：自动识别出信号列 `振动幅值`；
  `length=512, number=280, stride=128, epochs=30` → 测试准确率 **1.0000**、验证 0.9940，
  推理 CSV/xlsx 均给出 ~0.999 的置信度。（这是我自己造的演示数据，类别区分度大，重点在链路通。）

## 三、数据库

```
① Datasets ─┐
            ├─▶ ② Models ─▶ ③ Trainings ─┬─▶ ④ ModelInvocations
② Models  ──┘                            └─▶ ⑤ InferenceTasks ─▶ ⑥ InferenceResults
                                               （另需 TargetDatasetID→①、ModelID→②）
```

- **权威锚点**：`InferenceTasks.TrainingID`（不是 DeploymentID）。理由是推理结果的可信度取决于
  「哪一次训练」，部署只是同一次训练的投放位置；因此 `DeploymentID`/`DeviceID` 留空，
  等「边缘设备」支线落地后再回填。这条正是 `sql/schema_mysql.sql` 里自己标注的悬案
  （见 `InferenceTasks.TrainingID` 的注释"权威锚点"）。
- **`TargetDatasetID` 是 NOT NULL**：内联样本没有"数据集"概念，服务会登记一条
  `ADHOC-<模型名>` 数据集，而不是为了满足外键去伪造真实数据集。
- **只用 MySQL**（`MODEL_DB_DIALECT=mysql`）：驱动 pymysql，建表脚本只有 `sql/schema_mysql.sql`
  （脚本自带 `CREATE DATABASE` + `USE`，全部是 `CREATE TABLE IF NOT EXISTS`，可重复执行）。
  `Config.__init__` 会校验这个变量，**写 `mysql` 以外的值会在启动时直接 `RuntimeError`**，
  不会静默换库、也不会"看起来能跑"。
  ⚠️ 早期为了"没装库也能跑"支持过 sqlite 兜底与 SQL Server（pyodbc），三套方言各自演化出
  占位符 `%s`/`?`、`LIMIT`/`TOP`、建表脚本等一堆差异，现已全部移除：`sql/` 下只剩
  `schema_mysql.sql`。

连接变量：`MODEL_DB_HOST`（默认 `127.0.0.1`）`MODEL_DB_PORT`（默认 `3306`）
`MODEL_DB_USER`（默认 `root`）`MODEL_DB_PASSWORD`（默认空）`MODEL_DB_NAME`（默认 `model_management`）。
⚠️ 曾经用过的 `MODEL_DB_ODBC_DRIVER` / `MODEL_DB_TRUSTED`（SQL Server 专用）**已废弃**：
代码里没有任何地方读它们，配了也不起作用。

**本机现状（已接通）**：MySQL 9.2 @ `127.0.0.1:3306`，库 `model_management`，
应用账号 `ljx666`（已授权 `model_management.*`）。这些值写在项目根的 **`db.env`** 里，
服务启动时自动读取，所以直接 `python main.py` 即可，不需要 export 任何变量；
`db.env.example` 是不含口令的同款模板，正式环境请自行替换账号或改回 `root`。

> 注意：`db.env` 含明文口令，不要外发或提交版本库。
>
> 历史记录（该分支已删除）：SQL Server 那一路在本机就跑不通——`MSSQL$SQLEXPRESS` 服务虽然在跑，
> 但机器上只有过时的 `SQL Server` / `SQL Server Native Client 10.0` ODBC 驱动，用信任连接报
> "安全包中没有可用的凭证"、用旧驱动报 SSL 错误。这也是后来统一到 MySQL、把 sqlserver 分支
> 整体删掉的原因之一。

## 四、与既有脚本的关系（改了什么、没改什么）

| 文件 | 处理 |
|---|---|
| `1DCNN/1DCNN.py`、`1DCNN/preprocessing.py` | **未改动**，命令行行为完全一致 |
| `cwt_cnn/preprocess.py` | **未改动** |
| `cwt_cnn/cwt_cnn_pytorch.py` | 重构：训练主体收进函数、入口移入 `__main__`，`python cwt_cnn_pytorch.py` 表现不变；`fc1` 输入维度由硬编码 `16*196` 改为按 `length` 推导 |
| `main.py` | 只加了 `register_api(api)` 与 `threaded=True` |
| `sql/schema_mysql.sql` | **唯一保留**的建表脚本（MySQL 专用） |

> ⚠️ 这句以前写的是「`sql/schema*.sql` 未改动，新增一份 `schema_sqlite.sql`」——两份都不在了：
> `sql/` 目录下现在**只有 `schema_mysql.sql`**（T-SQL 版 `schema.sql` 与 SQLite 版都随各自方言分支
> 一起删除）。如果看到别处还提到 `schema.sql`，那是没跟着清的墓碑注释。

服务侧**没有**复用 `1DCNN/preprocessing.py` 的切片逻辑，而是新增 `datasets.py`，差异都是刻意的：

1. **跳过越界窗口而不是补 NaN**（`strict=True`）：原逻辑对长度不足的文件会切出短数组再补成整行
   NaN，实测 0HP 里 `IR014` 只有 63788 点，导致验证/测试集各有 10% 的全 NaN 样本，
   NaN 子集准确率恒为 0。服务侧改为跳过并在响应/库备注里回报跳过数量。
2. **标准化只用训练集拟合**（原脚本把训练+测试拼起来拟合，属于统计量泄漏）。
3. **固定随机种子**（原 `StratifiedShuffleSplit` 未固定，同参数两次跑出过 0.5933 与 0.750）。
4. **类别号写死**：原 `add_labels()` 的类别号来自 `os.listdir()` 顺序，文件名一改就错位；
   现在用显式映射表，并随产物存进 `meta.json`。
5. **标准化参数随模型落盘**，推理侧套用同一套均值/方差——第一次端到端验证时正是漏了这步，
   测试集 0.83 的模型对原始信号窗口的预测全是错的。

## 五、明确的已知限制

1. ~~**adtk 分支判别力不足**~~ —— **已解决，别再照这段下结论**。这里原先写的是"以正常信号为基线
   fit `PcaAD(k=1)`，在原始振动窗口上故障窗口的异常点占比（0.026~0.103）反而低于基线（0.137），
   标定后全判正常"。根因不是 adtk 不行，而是**喂错了形状**：`PcaAD` 内部是
   `PcaReconstructionError(k)` + `InterQuartileRangeAD(c)`，它把 **DataFrame 的每一行**当成高维空间
   里的一个点，而老代码喂的是「采样点 × 1 列」，PCA 退化成 1 维、重构误差恒为 0，只剩 IQR 在噪声上乱响。
   改成「行 = 窗口」（窗口 × 统计特征）之后，**实测 AUC = 1.0000，正常文件 0/20 判异常、
   4 个故障文件 19~20/20 判异常**，阈值另用留出集（未参与拟合的那 30% 窗口）标定，
   `baseline_false_positive_rate` 才有意义。当前产物 `data/models/adtk/`（`detector.pkl` + `meta.json`）就是新格式。
   （另：老格式产物已**不再支持**，推理侧遇到会直接报错，不会静默按错误阈值判"正常/异常"。）
2. **`/train` 是同步阻塞的**，没有任务队列；开发服务器开了 `threaded=True`，
   但一条训练请求会占住一个线程（实测 1DCNN 10 epoch 约 15 秒，cwt_cnn 50 epoch 约 40 秒）。
3. **`model_service` 不再有模型版本号**（一个模型只有一份产物，重训/重传直接替换），`ModelDeployments` 表和
   「边缘设备 → 机床」那条支线仍未接入，`EdgeDevices` 表还是空的。
4. **环境相关的坑**（已规避，换机器可能不再复现）：
   - 某些受限环境禁止在 `mkdtemp` 建的目录里写文件 → Keras 原生 `.keras`（zip，先写临时文件再改名）
     必然失败，代码会自动回退到 h5py 直写的 `.h5`；失败的 `.keras` 半成品会被显式删除，
     否则它（只有 config.json、没有权重）会被权重查找误命中。
   - pip 在这类环境下也装不了包（同样的临时目录限制），本次 `pymysql` 是直接解包 wheel 到
     site-packages 安装的。（`pyodbc` / `pywin32` 那次是为了当时还没删的 SQL Server 分支装的，
     现已不需要，`requirements.txt` 里也没有它们。）

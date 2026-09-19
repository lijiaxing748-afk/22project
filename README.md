# 东风设备轴承故障诊断模型管理平台

把「轴承振动数据 → 训练模型 → 模型产物 → 在线推理 → 落库 → Web 展示」串成一条**能真跑通**的流水线。
后端 Flask + flask-restful，前端 Vue3 + Element Plus，数据落 MySQL，模型产物按模型落磁盘（**一个模型一份，重训直接替换**）。

> 一句话：**不是演示 Demo，是一条有数据库、有产物管理、有审计记录的完整链路**——训练出来的模型能推理、推理结果能查到明细、每个模型参数都能在页面上看到。

---

## 目录

- [功能一览](#功能一览)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [三个模型](#三个模型)
- [两套数据集](#两套数据集)
- [目录结构](#目录结构)
- [接口与数据库](#接口与数据库)
- [自测与验证](#自测与验证)
- [常见问题](#常见问题)
- [文档](#文档)
- [第三方依赖与致谢](#第三方依赖与致谢)

---

## 功能一览

| 模块 | 能力 |
|---|---|
| **首页** | 平台概览：模型/数据集/训练/推理任务统计、健康检查、最近活动 |
| **模型管理** | 模型清单（登记信息 + 产物参数 + 指标）、**上传模型**（文件夹或单文件，自动识别框架/输入长度/类别数）、训练（三个模型可选）、推理（按窗口，看类别+置信度或异常分数）、训练记录、推理任务与结果明细、模型档案、改名、删除产物 |
| **数据集管理** | CWRU 内置数据集体检、表格数据集上传（一文件一类别）、信号列预览与统计 |
| **数据展示** | 波形/频谱等可视化，训练与推理自动出的图（混淆矩阵、训练曲线、异常时序） |
| **系统管理** | 运行环境与依赖、8 张表行数、日志查看、接口索引、维护（清空图库/删除模型产物） |

**工程上的几个亮点**（都是踩坑后补的）：

- **产物扁平化（无版本号）**：`data/models/<模型名>/`，权重 + scaler + `meta.json` 一套，**一个模型只有一份产物**，重训/重传就是直接替换那一份；可删产物、可改名（连目录带库里路径一起搬）
- **上传即校验**：不只看后缀，而是**打开文件看内容**判断"这是不是一个模型"，并自动读出输入长度与类别数
- **无监督异常检测真能用**：adtk 的 PcaAD 按"行 = 窗口"喂（关键），AUC 1.0，正常文件 0/20 误报、故障文件 19~20/20 命中
- **响应脱敏**：所有 JSON/文本响应里的绝对路径都会被替换，不暴露本机目录结构
- **可审计**：每次训练/推理都写 `Trainings`/`InferenceTasks`/`InferenceResults`/`ModelInvocations`，**失败路径也留记录**
- **安全闸门**：模型名净化（防路径穿越）、上传产物标记为不可信（推理侧不反序列化其 `.pkl`）、上传与推理的每一步都有明确错误码

---

## 系统架构

```
┌─────────────────────────────┐        ┌──────────────────────────────────────────┐
│  前端  Vue3 + Vite :8080     │        │  后端  Flask + flask-restful :5000        │
│  frontend/22project          │  HTTP  │  testRestfulProject/main.py              │
│  ├ 首页/模型管理/数据集管理   │ ─────▶ │  ├ model_service/api.py    业务接口(裸JSON)│
│  │  /数据展示/系统管理        │  CORS  │  ├ model_service/dvadmin.py 兼容层(信封)  │
│  └ utils/platformRequest.ts  │        │  ├ training.py   ┌ 1dcnn  (Keras)        │
│    (专用 axios，绕开信封校验) │        │  │               ├ cwt_cnn(PyTorch)      │
└─────────────────────────────┘        │  │               └ adtk   (PcaAD 无监督) │
                                        │  ├ inference.py  推理 + 落库              │
        ┌────────────────┐              │  ├ datasets.py   CWRU .mat 读取/切窗     │
        │ MySQL          │◀────────────▶│  ├ tabular.py    表格数据集              │
        │ model_management│   8 张表     │  ├ registry.py   产物管理                │
        │ Datasets/Models│              │  └ figures.py    出图(无头 matplotlib)   │
        │ Trainings/...  │              └──────────────────────────────────────────┘
        └────────────────┘                        │
                                                  ▼
                              data/models/<模型>/{model.h5|model.pt|detector.pkl,
                                                 scaler.npz, meta.json}
```

**为什么要两层接口**：前端是 django-vue3-admin 模板，它强制校验 `{code, data, msg}` 信封；
业务接口按 REST 惯例返回裸 JSON。于是 `dvadmin.py` 提供登录/菜单/权限等兼容接口，
`utils/platformRequest.ts` 提供一个不走信封校验的 axios 实例，两边互不污染。

---

## 快速开始

### 0. 环境要求

| | 版本 |
|---|---|
| Python | 3.14（`testRestfulProject/venv` 已含 tensorflow / torch / adtk 等依赖，约 2.7GB） |
| Node.js | 18+ |
| MySQL | 8.0+（本项目在 9.2 上验证） |

### 1. 数据库

```sql
CREATE DATABASE model_management DEFAULT CHARSET utf8mb4;
-- 建表（8 张表 + 外键 + 索引 + 种子数据，可重复执行）
source D:\22project\testRestfulProject\sql\schema_mysql.sql;
```

复制 `testRestfulProject/db.env.example` 为 `db.env`，填自己的账号密码：

```ini
MODEL_DB_DIALECT=mysql
MODEL_DB_HOST=127.0.0.1
MODEL_DB_PORT=3306
MODEL_DB_USER=<你的账号>
MODEL_DB_PASSWORD=<你的密码>
MODEL_DB_NAME=model_management
```

> ⚠️ **只连 MySQL，没有兜底库**：`MODEL_DB_DIALECT` 只接受 `mysql`，配成别的值（例如曾经示例里的
> `sqlserver`）会在服务启动的 import 期直接报 `RuntimeError`。历史上确实有过"探测不到库就退回
> SQLite"的兜底，那条路径连同 `SQLITE_PATH` 常量都已删除 —— 现在**必须**先备好一个可用的 MySQL
> 库，`db.env` 里那六行是唯一的配置方式。

### 2. 后端（必须先起）

```powershell
cd D:\22project\testRestfulProject
venv\Scripts\python.exe main.py        # → http://127.0.0.1:5000
```

### 3. 前端

```powershell
cd D:\22project\frontend\22project
npm install        # 首次
npm run dev        # → http://127.0.0.1:8080
```

默认账号：任意用户名 + 任意密码（兼容层不校验），进入后左侧是 5 个业务菜单。

### 两个地址

| 地址 | 说明 |
|---|---|
| http://127.0.0.1:5000/api | 接口索引（JSON，列出所有业务接口）—— **需登录**：未登录只回一句"需要登录后查看" |
| http://127.0.0.1:8080 | 平台前端 |

> ⚠️ `/api` 与 `/health` 对**未登录**访问做了收敛（2026-09-19）：
> `/api` 不再吐接口清单，`/health` 只回"服务是否活着 + 库通不通 + 鉴权开没开"，
> 不再回项目目录/数据集路径/库名/产物清单。登录后（前端「系统管理 → 接口索引」页）
> 拿到的是与以前完全一样的完整信息。运维探活仍用匿名 `GET /health`（只看 HTTP 200）。

> 原先还有一个 `http://127.0.0.1:5000/ui` 的零构建调试控制台（`console.html`），
> 功能已被 Vue 前端完全覆盖，已连同 `console.html` 一起删除；后端现在只有 `/` 与 `/api` 两个 JSON 入口。

---

## 三个模型

| 模型 | 类型 | 框架 | 数据源 | 产物 | 说明 |
|---|---|---|---|---|---|
| `1DCNN` | 分类（CWRU 10 类） | TensorFlow / Keras | `.mat` 或表格 | `model.h5` + `scaler.npz` | 复用原项目网络结构，测试准确率 **0.9457** |
| `cwt_cnn` | 分类（同任务，PyTorch 实现） | PyTorch | `.mat` 或表格 | `model.pt` + `scaler.npz` | 全批量训练，测试准确率 **0.6680** |
| `adtk` | **无监督异常检测** | adtk（PcaAD） | 只需一段"正常"基线 | `detector.pkl` | 窗口级 PCA 重构误差，见下 |

**adtk 这条最容易踩坑**（也是本项目最有意思的一处）：`PcaAD` 内部是
`PcaReconstructionError(k)` + `InterQuartileRangeAD(c)`，它把 **DataFrame 的每一行**当成高维空间里的一个点。
所以必须喂「**行 = 一个窗口**」的矩阵；如果按"采样点 × 1 列"喂，PCA 会退化成 1 维、重构误差恒为 0，
判出来的"异常"与故障完全无关。改正后实测：**连续分数 AUC = 1.0000**，正常文件 0/20 误报、故障文件 19~20/20 命中。

```powershell
# 训练 adtk
curl -X POST http://127.0.0.1:5000/train -H "Content-Type: application/json" -d "{\"model\":\"adtk\"}"
# 推理（正常文件应判"正常"，故障文件应判"异常"）
curl -X POST http://127.0.0.1:5000/predict -H "Content-Type: application/json" -d "{\"model\":\"adtk\",\"path\":\"1DCNN/0HP/48k_Drive_End_IR007_0_109.mat\",\"index\":0,\"limit\":5}"
```

---

## 两套数据集

| 数据集 | 位置 | 格式 | 约定 |
|---|---|---|---|
| **CWRU 0HP**（内置只读） | `testRestfulProject/1DCNN/0HP/*.mat` | MATLAB `.mat`，取 **DE（驱动端）通道**，48 kHz | **一个文件 = 一个类别**，10 个文件 10 类；`datasets.py::CWRU_0HP_CLASSES` 固定「文件名 → class_id → 中文标签」映射 |
| **表格数据集**（可上传） | `testRestfulProject/data/datasets/<数据集名>/` | `.csv .txt .xlsx .xlsm .xls` | **一个文件 = 一个类别，文件名即标签**；表内自动挑信号列（`振动幅值` 会被选中，`时间`/`温度` 等干扰列会自动跳过） |

10 类清单（class_id 顺序即标签顺序）：

| id | 文件 | 标签 | 点数 |
|---|---|---|---|
| 0-2 | `48k_Drive_End_B007/B014/B021_0_*.mat` | 滚动体故障 0.007/0.014/0.021in | 24.4~24.9 万 |
| 3-5 | `48k_Drive_End_IR007/IR014/IR021_0_*.mat` | 内圈故障 0.007/0.014/0.021in | ⚠️ IR014 只有 **63,788** 点 |
| 6-8 | `48k_Drive_End_OR007@6/OR014@6/OR021@6_0_*.mat` | 外圈故障 @6点钟 | 24.4~24.6 万 |
| 9 | `normal_0_97.mat` | 正常 | 243,938 |

> ⚠️ `IR014` 点数不足：默认参数（`length=784, number=600, stride=150`）下它的 **180 个测试窗全部越界被跳过**，
> 于是该类不参与指标计算（`untested_labels` 会在产物 metrics 里显式列出来）。
> 这是数据本身的问题，不是 Bug——但如果不看这个字段，`accuracy` 会显得比实际好。

---

## 目录结构

```
D:\22project\
├─ testRestfulProject\                   后端
│  ├─ main.py                            唯一入口：注册两层路由 + 启动
│  ├─ model_service\                     业务包（11 个模块，见下）
│  │  ├─ api.py                          业务接口（裸 JSON）
│  │  ├─ dvadmin.py                      前端兼容层（{code,data,msg} 信封 + CORS）
│  │  ├─ training.py                     train() 入口 + 三个 trainer
│  │  ├─ inference.py                    推理 + 落库
│  │  ├─ datasets.py / tabular.py        两套数据源
│  │  ├─ registry.py                     产物管理（落盘/替换/删除）
│  │  ├─ db.py                           8 张表的读写
│  │  └─ figures.py / config.py
│  ├─ 1DCNN\  cwt_cnn\  adtk\            原始算法脚本 + vendored adtk 库
│  ├─ data\models\<模型>\                ★ 模型产物（一个模型一份，无版本号）
│  ├─ data\datasets\<数据集>\            ★ 上传的表格数据集
│  ├─ data\{figures,logs,uploads}\       图 / 训练日志 / 上传文件
│  ├─ sql\schema_mysql.sql               建表脚本
│  ├─ db.env.example                     数据库配置模板（db.env 已在 .gitignore）
│  └─ _selftest_upload.py                后端自测：模型探测/上传/改名
├─ frontend\22project\                   前端（Vue3 + Vite + Element Plus）
│  └─ src\{views\platform, api\platform, utils\platformRequest.ts}
├─ README.md  ·  项目交接文档.md  ·  项目技术详解.md
└─ _unused_dvadmin\                      dvadmin 模板里删掉的无用代码（可回滚，未入库）
```

---

## 接口与数据库

**业务接口**（裸 JSON，20+ 个）：`/health` `/models` `/models/upload` `/models/<名>/overview` `/datasets`
`/datasets/upload` `/train` `/trainings` `/predict` `/inference-tasks` `/figures` `/system` …

**兼容接口**（`{code,data,msg}` 信封）：登录、菜单、用户信息、字典、设置、部门、SSE 桩等 —— 只为让 dvadmin 前端跑起来。

**MySQL 8 张表**：`Datasets` → `Models` → `Trainings` / `ModelDeployments` / `InferenceTasks` → `InferenceResults`，
外键顺序严格（训练写库失败会降级但显式回报，绝不静默）。

完整的接口清单、字段表、外键关系见 [`项目交接文档.md`](项目交接文档.md) §3–§5。

---

## 自测与验证

```powershell
# 前端：5 个页面的 SFC 编译 + 全项目 import 解析 + 后端接口契约一致性
node D:\22project\frontend\22project\check-platform.cjs

# 后端：模型探测（按文件内容判断是不是模型）/ 上传 / 改名，跑完自动清理
cd D:\22project\testRestfulProject; venv\Scripts\python.exe _selftest_upload.py
```

`check-platform.cjs` 是在"本机跑不了 `vite build`"（沙箱限制）的情况下写的等价校验，能抓出模板/脚本语法错误与悬空 import。

---

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 页面能开但所有数据为空，控制台报 `非标准返回：[object Object]` | 平台接口走了框架的信封校验。已用 `utils/platformRequest.ts` 修好；若自行改接口请沿用该实例 |
| 跨域被拦：`CORS policy: preflight ... does not have HTTP ok status` | 兼容层已统一放行所有 OPTIONS 预检。若仍出现，先确认后端**重启过**（改路由注册必须重启，debug 自动重载不重注册蓝图） |
| 切页面很慢（3~10 秒） | `main.ts` 里为了让改动能立即生效，加了一段"切模块整页刷新"的代码，代价就是慢。不需要时删掉标注 ② 的那 10 行即可 |
| 上传数据集后列表里看不到新文件 | 已修（上传后主动清体检缓存）。若你用的是老版本，刷新或等 120 秒 TTL |
| 训练报 `数据集目录不存在` | `dataset_dir` 用工作区相对路径，例如 `1DCNN/0HP`；后端会按「工作区 → 项目目录」顺序解析 |
| 改了后端代码没生效 | `/train` 与产物注册相关改动**必须重启**后端；其余改动 debug 模式会自动重载 |

---

## 文档

| 文档 | 内容 |
|---|---|
| [`项目交接文档.md`](项目交接文档.md) | 上手第一份：环境、接口清单、8 张表、磁盘布局、14+ 条踩坑记录、遗留问题、命令速查 |
| [`项目技术详解.md`](项目技术详解.md) | 数据集格式细节、训练/推理/训练记录/推理任务四个模块逐步拆解、**30 条 Bug 台账**（位置 + 原因 + 修法 + 实测数据）、可读性改进清单 |
| [`testRestfulProject/model_service/README.md`](testRestfulProject/model_service/README.md) | 后端业务包：接口约定、产物约定、与原始脚本的关系 |

---

## 第三方依赖与致谢

- 前端基于 **[django-vue3-admin](https://github.com/dvadmin/django-vue3-admin)**（Vue3 + Element Plus 后台模板），已按本项目需要大幅精简：模板自带的组织/权限/日志/字典/消息等无后端支撑的页面均已移除
- 异常检测使用 **[adtk](https://github.com/arundo/adtk)**（源码内置于 `testRestfulProject/adtk/`，离线可用）
- 数据集：**Case Western Reserve University（CWRU）轴承数据集**
- 深度学习：TensorFlow / Keras、PyTorch、scikit-learn、pandas、NumPy、matplotlib

---

## 说明

本项目为教学/科研性质的**模型管理平台**，重点是"训练→产物→推理→落库→展示"这条链路的完整性与可追溯性，
而非追求单一模型的精度上限。各模型的指标、已知限制与未修项均在文档中如实记录。

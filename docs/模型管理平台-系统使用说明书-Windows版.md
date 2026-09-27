# 模型管理平台 · 系统使用说明书（Windows 版）

> **版本**：v1.0 ｜ **编写日期**：2026-09-23
>
> **适用场景**：实验室交付主机（Lenovo ThinkStation P360），**Windows 系统**
>
> **读者对象**：使用本平台的老师与同学、后续接手维护的人员
>
> **说明书定位**：本文是**操作手册**，回答三个问题 —— **怎么开机用**、**每个功能怎么点**、**出问题了怎么处理**。
> 全文截图均取自**真实运行的系统**；接口返回值均为**真实调用结果**。
> 凡是当前**尚未实现**的能力，本文都会明确写出，不做夸大。

---

## 0. 使用本机前必须先读：双系统说明

本实验室主机是 **Windows / Ubuntu 双系统**，开机时由 **GRUB 引导菜单**选择进入哪一个。
**两套系统彼此独立运行**，请注意以下三点：

### 0.1 两套系统各自独立

| 项目 | 说明 |
| --- | --- |
| **运行方式** | 同一时刻**只能进入一个系统**，另一个系统处于关闭状态 |
| **平台实例** | 两个系统里各有一套完整平台，**互不干扰** |
| **数据库** | 两套系统**各自拥有独立的 MySQL 数据库**，数据**不互通** |
| **数据可见性** | 在 Windows 里训练/上传的数据，**在 Ubuntu 里看不到**，反之亦然 |

> **这是双系统的固有特性，不是系统缺陷。**
> 如果确实需要在两套系统之间传递模型，请使用「模型发布 → 下载 `.zip` 包」
> 功能导出模型文件，再到另一系统上传使用（见 §4.6）。

### 0.2 两套系统的定位

| 对比项 | Ubuntu 版（**推荐主用**） | **Windows 版（本文）** |
| --- | --- | --- |
| 服务方式 | systemd 服务，开机自启、崩溃自动重启 | **NSSM 服务**，同样开机自启 |
| 运行方式 | 生产级 WSGI（waitress） | **Flask 内置服务器**（开发模式） |
| 端口 | 8080 | **5000** |
| 定位 | **正式使用 / 长期运行** | **备份与演示环境** |

> **建议**：日常使用优先选择 **Ubuntu 版**；Windows 版适合**演示、备份、或需要 Windows 环境时**使用。

### 0.3 开机进入系统

1. 按下主机电源键。
2. 出现 **GRUB 引导菜单**（停留约 10 秒）：
   - 选择 **`Ubuntu`** → 进入 Ubuntu 系统
   - 选择 **`Windows Boot Manager`** → **进入 Windows 系统（本文）**
   - 若 10 秒内未操作，**默认自动进入 Ubuntu**
3. 进入 Windows 后，无需输入密码即可进入桌面。

> **切换系统的三种方式**（由易到难）：
> 1. **GRUB 菜单选择**（推荐）：开机时在菜单里选 `Windows Boot Manager`
> 2. **启动菜单**：开机时按 `F12`，在弹出的设备列表里选 Windows
> 3. **BIOS 设置**：开机按 `F1` 进 BIOS 修改启动顺序（不推荐，较麻烦）

> **⚠️ 重要**：进入系统后**无需手动启动任何程序**。
> 本平台已注册为 Windows 服务，**开机后自动运行**，直接打开浏览器即可使用。

---

## 目录

- [0. 使用本机前必须先读：双系统说明](#0-使用本机前必须先读双系统说明)
- [1. 系统概览](#1-系统概览)
- [2. 开机与访问](#2-开机与访问)
- [3. 登录与账号](#3-登录与账号)
- [4. 全链路功能使用](#4-全链路功能使用)
- [5. 服务与日常运维](#5-服务与日常运维)
- [6. 常见问题与处理办法](#6-常见问题与处理办法)
- [7. 部署过程中遇到的问题与解决方法](#7-部署过程中遇到的问题与解决方法)
- [附录 A：关键路径与配置速查](#附录-a关键路径与配置速查)
- [附录 B：命令速查表](#附录-b命令速查表)
- [附录 C：账号与密码清单](#附录-c账号与密码清单)

---

## 1. 系统概览

### 1.1 这个系统能做什么

本平台把「轴承振动数据 → 模型训练 → 模型产物 → 在线推理 → 结果落库 → 打包发布」
串成一条**完整且可追溯**的链路。它不是只做界面展示的演示程序，
而是一条**有数据库、有产物管理、有权限控制、有审计记录、可离线部署**的真实通路。

| 能力 | 说明 |
| --- | --- |
| **数据集管理** | 上传、查看、删除数据集；内置 CWRU 轴承数据集 |
| **模型训练** | 界面配置超参数，启动 1DCNN / CWT-CNN 训练，查看训练曲线与指标 |
| **模型管理** | 查看模型指标与权重文件，支持上传外部模型、改名、删除 |
| **在线推理** | 选模型、选数据文件，一键推理并展示分类结果与概率分布 |
| **模型发布** | 把模型打包成 `.zip`（含权重、归一化参数、元信息、示例代码），供外部下载 |
| **用户与权限** | 三级角色（管理员 / 工程师 / 操作员），菜单与接口双重拦截 |
| **操作日志** | 关键业务动作全部落库，管理员可在界面查询 |

### 1.2 三个内置模型

平台开箱即带三个已训练好的模型，可直接用于推理演示：

| 模型 | 框架 | 输入长度 | 类别数 | 说明 |
| --- | --- | --- | --- | --- |
| `1dcnn` | TensorFlow / Keras | 784 | 10 | 一维卷积，直接输入原始振动信号 |
| `cwt_cnn` | PyTorch | 784 | 10 | 先做连续小波变换（CWT），再走卷积 |
| `adtk` | adtk（本地包） | 784 | — | 无监督异常检测，输出正常 / 异常判定 |

### 1.3 系统架构

采用**单端口部署**：前端构建产物由后端直接托管，
浏览器只需访问后端一个端口即可完成全部操作。

```
┌─────────────────────────────────────────────────┐
│  浏览器（本机或局域网内任意机器）                │
│  http://<本机IP>:5000                            │
└────────────────────┬────────────────────────────┘
                     │  单端口
                     ▼
┌─────────────────────────────────────────────────┐
│  Flask（单进程，同时托管前端与接口）             │
│  ├── /                → 前端页面（index.html）   │
│  ├── /api/login/      → 登录鉴权                 │
│  ├── /api/system/*    → 用户、菜单、操作日志     │
│  ├── /train           → 模型训练                 │
│  ├── /predict         → 在线推理                 │
│  └── /health          → 健康检查                 │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  MySQL 8.0（本机 3306）                          │
│  数据库：model_management                        │
└─────────────────────────────────────────────────┘
```

> **为什么只有一个端口**：前端打包产物由后端托管，
> 不需要额外安装 nginx，也不需要单独启动前端服务。
> 这对内网 / 离线环境非常重要 —— **只需运行一个服务**。

### 1.4 账号与密码

**本机（Windows 系统）相关账号一览**：

| 用途 | 账号 | 密码 | 说明 |
| --- | --- | --- | --- |
| **Windows 系统登录** | （无） | （无） | 本机未设置登录密码，开机直接进桌面 |
| **MySQL 数据库** | `root` | `123456` | 仅运维时使用 |
| **平台管理员** | `admin` | `Admin@2026` | 平台内全部功能 |
| **平台工程师** | `engineer` | `Engineer@2026` | 训练、推理、模型与数据集管理 |
| **平台操作员** | `operator` | `Operator@2026` | 只读浏览 |

> **⚠️ 交付后建议**：立即修改平台 `admin` 密码，停用或删除演示账号。
> 修改方式见 [§4.7 用户管理](#47-用户管理管理员专属)。

> **⚠️ 安全提示**：以上密码为本机当前配置。本机处于**实验室内网隔离环境**，
> 请勿将本机直接接入公网，也不要对外公开这些口令。

### 1.5 主机环境

| 项目 | 参数 |
| --- | --- |
| 机型 | Lenovo ThinkStation P360 Tower |
| CPU | 12th Gen Intel i9-12900K（16 核 24 线程） |
| 内存 | 32 GB |
| 系统盘 | SK Hynix 256GB SSD（**Windows 所在**） |
| 数据盘 | TOSHIBA 2TB HDD（Ubuntu 所在） |
| 操作系统 | Windows（64 位） |
| Python | 3.12（项目虚拟环境 `.venv`） |
| MySQL | 8.0.x（服务名 `MySQL80`） |
| 显示输出 | 主板 HDMI（BIOS 中 `Select Active Video = IGD`） |

---

## 2. 开机与访问

### 2.1 开机流程（从按电源键到能用）

**整个过程约 1-2 分钟，全程无需手动启动任何程序。**

| 步骤 | 屏幕表现 | 需要做什么 |
| --- | --- | --- |
| 1 | 开机自检（Lenovo 标志） | 等待 |
| 2 | **GRUB 引导菜单**（约 10 秒） | **选 `Windows Boot Manager`** |
| 3 | Windows 启动 | 等待 |
| 4 | 进入桌面（**无登录密码**） | **平台已自动运行**，打开浏览器即可 |

> **提示**：若菜单一闪而过，开机后立即按 **方向键 ↑/↓** 可唤出菜单。

### 2.2 打开平台（本机使用）

进入桌面后，打开浏览器（Edge / Chrome 均可），地址栏输入：

```
http://127.0.0.1:5000
```

即可看到登录页。

### 2.3 局域网访问（其他电脑 / 手机）

其他机器要访问本平台，需要两步：

**第一步：查本机 IP**

按 `Win + R`，输入 `cmd`，回车，然后执行：

```cmd
ipconfig
```

在输出中找到 **IPv4 地址**（形如 `192.168.1.100`）。**记下这个 IP**。

**第二步：在别的机器浏览器输入**

```
http://192.168.1.100:5000
```

> **前提**：两台机器必须处于**同一局域网 / 同一网段**。
> 若访问不了，按 [§6.2](#62-浏览器打不开页面) 排查（多半是防火墙或网段问题）。

### 2.4 访问地址一览

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:5000` | **平台主界面（日常操作入口）** |
| `http://<本机IP>:5000` | 局域网其他机器访问 |
| `http://127.0.0.1:5000/health` | 健康检查（含数据库连接状态） |
| `http://127.0.0.1:5000/api` | 接口索引（JSON 列表） |
| `http://127.0.0.1:5000/system` | 系统运行信息页 |

> **端口说明**：本平台在 Windows 上以 **5000** 部署（服务名 `ModelManageService` 与端口 5000 配套）。
> ⚠️ 若手工启动，**必须显式指定 `--port 5000`**，
> 因为 `serve.py` 的默认端口是 8080。

---

## 3. 登录与账号

### 3.1 登录界面

浏览器打开 `http://127.0.0.1:5000`，进入登录页：

![登录页](images/v2-01-登录页.png)

输入**用户名**与**密码**，点击「登录」。

登录成功后签发令牌（Token），有效期 **12 小时**，期间无需重复登录。

### 3.2 三个内置账号

数据表为空时，服务首次启动会自动创建三个账号：

| 用户名 | 初始密码 | 角色 | 权限范围 |
| --- | --- | --- | --- |
| `admin` | `Admin@2026` | 管理员 | 全部功能，含用户管理、操作日志 |
| `engineer` | `Engineer@2026` | 工程师 | 训练、推理、模型与数据集管理 |
| `operator` | `Operator@2026` | 操作员 | 只读浏览 |

### 3.3 密码安全说明

| 环节 | 做法 |
| --- | --- |
| **传输** | 前端以明文提交密码，依赖内网隔离保证链路安全 |
| **存储** | 后端使用 `pbkdf2:sha256` 加盐哈希，数据库中**不存明文** |
| **校验** | 登录时用同一算法校验，失败返回统一提示，不透露账号是否存在 |

> 数据库中的口令字段无法反推原文。若遗忘密码，由管理员在界面重置，
> 或用运维脚本重置（见 [§6.7](#67-账号无法登录)）。

### 3.4 令牌机制

| 项目 | 说明 |
| --- | --- |
| **令牌格式** | 基于 `itsdangerous` 的签名令牌 |
| **传递方式** | 请求头 `Authorization: Bearer <token>` |
| **有效期** | 12 小时（可通过 `MODEL_TOKEN_TTL_HOURS` 调整） |
| **签名密钥** | 由配置文件中的 `MODEL_SECRET_KEY` 固定 |

> **⚠️ `MODEL_SECRET_KEY` 必须配置固定值**。未配置时服务每次启动会生成随机密钥，
> 导致**重启后所有用户掉线**，演示时会被误认为系统不稳定。
> 本机已配置固定值（可用 `/health` 的 `auth.key_is_default` 字段验证，应为 `false`）。
---

## 4. 全链路功能使用

本章按**实际使用的先后顺序**介绍每个功能模块，即一条完整的链路：

```
登录 → 看数据集 → 训练模型 → 查看模型 → 在线推理 → 发布模型 → 下载使用 → 查日志
```

> **说明**：本章的操作步骤与《系统使用说明书（Ubuntu 版）》**完全一致** ——
> 两套系统的平台是同一套代码，界面与功能相同。
> 差异仅在**访问端口**（Windows 为 **5000**，Ubuntu 为 **8080**）。

### 4.1 首页（平台概览）

登录后进入首页，展示平台的关键指标与运行状态：

![首页](images/v2-02-首页.png)

| 区域 | 内容 |
| --- | --- |
| 顶部卡片 | 模型总数、数据集数、训练任务数、推理次数 |
| 模型清单 | 当前可用的模型及其框架、输入长度 |
| 系统状态 | 数据库连接、前端产物、图表目录 |

**用途**：一眼确认「系统是否正常、有哪些模型可用」。

---

### 4.2 数据集管理

**入口**：左侧菜单 →「数据集管理」

![数据集管理](images/v2-10-数据集管理.png)

| 操作 | 说明 |
| --- | --- |
| **上传数据集** | 支持 `.mat` / `.csv` / `.npy` / `.xlsx` 格式 |
| **查看** | 显示文件列表、大小、上传时间 |
| **删除** | 移除数据集及其文件 |

**内置 CWRU 数据集**位于项目目录下，平台启动时自动扫描并登记，
无需手动上传即可用于训练与推理。

---

### 4.3 模型训练（完整流程）

**入口**：左侧菜单 →「模型管理」→ 点击「训练」

![训练面板](images/v2-06-训练面板.png)

#### 4.3.1 参数配置

| 参数 | 说明 | 建议值 |
| --- | --- | --- |
| **模型类型** | `1dcnn`（TensorFlow）/ `cwt_cnn`（PyTorch） | 演示用 `1dcnn` |
| **数据集目录** | 从已登记的数据集中选择 | CWRU-0HP |
| **Epochs** | 训练轮数 | 演示 5-10；正式 10-50 |
| **Batch Size** | 批大小 | 32 / 64 |
| **学习率** | Learning Rate | 0.001 |

![训练参数弹窗](images/07-训练参数弹窗.png)

#### 4.3.2 提交与观察

填写完成后点击「开始训练」。提交后任务开始执行，可查看：

| 输出 | 位置 |
| --- | --- |
| **执行日志** | 页面下方日志区，逐轮输出 loss / accuracy |
| **训练曲线** | 训练完成后在「数据展示」页查看 |
| **训练记录** | 列表中显示状态（进行中 / 成功 / 失败） |

#### 4.3.3 训练注意事项

> **⚠️ 训练是同步阻塞的**：单个任务执行期间，服务仍可响应其他请求，
> 但**同一模型的并发训练会被拒绝**。

| 事项 | 说明 |
| --- | --- |
| **耗时** | 本机为 CPU 训练，10 轮约需数分钟，请耐心等待 |
| **算力** | 本机以 CPU 执行训练；如需 GPU 加速，需额外配置显卡驱动 |
| **中断** | 训练过程中不要关闭页面或重启服务，否则任务会失败 |
| **失败排查** | 若失败，页面会显示红色错误提示条，并给出具体原因；详见 [§6.5](#65-训练或推理报错) |

---

### 4.4 模型管理

**入口**：左侧菜单 →「模型管理」

![模型管理](images/03-模型管理.png)

| 操作 | 说明 |
| --- | --- |
| **上传模型** | 支持整个文件夹或单个文件，自动读取元信息 |
| **查看详情** | 展示训练指标、验证曲线、类别标签 |
| **改名** | 修改模型显示名称 |
| **删除** | 移除模型产物及其登记记录 |

上传模型时，系统会探测文件内容并给出格式提示：

![上传模型弹窗](images/09-上传模型弹窗.png)

**模型清单**页列出当前所有可发布模型的来源与状态：

![模型清单](images/v2-05-模型清单.png)

---

### 4.5 在线推理

**入口**：左侧菜单 →「模型管理」→ 点击「推理」

![推理面板](images/v2-07-推理面板.png)

#### 4.5.1 操作步骤

1. **选择模型**（`1dcnn` / `cwt_cnn` / `adtk`）
2. **选择要推理的数据文件**（**必选**，不选无法推理）
3. 可选：指定窗口索引、返回条数、Top-K
4. 点击「开始推理」

#### 4.5.2 结果展示

| 区域 | 内容 |
| --- | --- |
| **预测结果** | 每条样本的类别、置信度、Top-K 概率 |
| **概率分布图** | 各类别的概率柱状图 |
| **原始信号** | 输入波形预览 |

![推理结果](images/08-推理面板.png)

> **若推理失败**：页面会显示**红色错误提示条**，并给出后端返回的具体原因；
> 同时在浏览器控制台（`F12` → Console）会打印 traceback 片段，便于排查。

---

### 4.6 模型发布与下载（把模型交付给别人）

**入口**：左侧菜单 →「模型发布」

![模型发布页](images/v2-03-模型发布页.png)

#### 4.6.1 发布包内容

每个发布包都是一个 `.zip`，解压后包含：

```
<model_name>/
├── model.keras 或 model.pth    模型权重
├── scaler.npz                  归一化参数
├── meta.json                   模型元信息（输入长度、类别标签等）
├── README.md                   使用说明
├── requirements.txt            依赖清单
└── example_infer.py            示例推理脚本
```

![发布包内容](images/v2-04-发布包内容.png)

#### 4.6.2 外部使用方如何使用

拿到 `.zip` 包后，在**目标机器**上执行：

```bash
# 1. 解压
unzip 1dcnn-publish-*.zip && cd 1dcnn-publish-*

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行示例，验证环境
python example_infer.py
```

#### 4.6.3 在两套系统之间传递模型

由于 Windows / Ubuntu 数据不互通（见 [§0.1](#01-两套系统各自独立)），
如需跨系统使用模型，**通过发布包传递**：

1. 在系统 A 中「模型发布」→ 下载 `.zip` 包；
2. 把 `.zip` 复制到 U 盘，或复制到**两系统都能访问的分区**；
3. 在系统 B 中解压使用，或通过「模型管理 → 上传模型」导入平台。

---

### 4.7 用户管理（管理员专属）

**入口**：左侧菜单 →「系统管理」→「用户管理」

![用户管理页](images/v2-11-用户管理页.png)

| 操作 | 说明 |
| --- | --- |
| **新增用户** | 填写用户名、密码、角色 |
| **编辑用户** | 修改角色；密码留空表示不修改 |
| **重置密码** | 为该用户设置新密码 |
| **启用 / 禁用** | 禁用后该账号无法登录（**不物理删除，保留审计痕迹**） |
| **搜索** | 按用户名关键字过滤 |

**非管理员账号看不到该菜单**：

![非管理员不可见](images/v2-12-用户管理-非管理员不可见.png)

> 即使手动输入 URL 访问，前端会拦截跳转，后端接口也会返回无权限。
> **安全核心在后端校验**，前端隐藏只是体验优化。

---

### 4.8 操作日志（管理员专属）

**入口**：左侧菜单 →「系统管理」→「操作日志」

![操作日志页](images/v2-13-操作日志页.png)

| 功能 | 说明 |
| --- | --- |
| **指标卡** | 总操作数、今日操作、业务失败、登录失败 |
| **按动作筛选** | 模型增删改、发布、数据集、训练等 |
| **按结果筛选** | 成功 / 失败 |
| **关键字搜索** | 按用户名或操作对象搜索 |
| **详情展开** | 查看结构化 Detail 字段 |

**已埋点的业务动作**：

| 模块 | 动作值 |
| --- | --- |
| 模型管理 | `model_upload` / `model_delete` / `model_update` |
| 模型发布 | `model_publish` / `model_unpublish` |
| 数据集 | `dataset_upload` / `dataset_delete` |
| 训练 | `train_create` / `train_start` / `train_delete` |
| 模型部署 | `deploy_create` / `deploy_delete` |
| 账号 | `login` / `logout` / `user_create` / `user_update` / `user_reset_password` |

> **推理操作不做埋点**：推理是高频操作，全量记录会让日志表快速增长。
> 推理链路已由 `InferenceResults` 表完整记录，同样可追溯。

---

### 4.9 数据展示

**入口**：左侧菜单 →「数据展示」

![数据展示](images/05-数据展示.png)

展示训练与推理过程中自动生成的图表：

| 图表类型 | 来源 |
| --- | --- |
| 混淆矩阵 | 模型训练结束时生成 |
| 训练曲线 | 训练过程中的 loss / accuracy 变化 |
| 异常时序图 | `adtk` 异常检测推理结果 |
| 信号波形 | 输入信号的时域预览 |

---

## 5. 服务与日常运维

本章为 Windows 特有的运维操作。**日常使用不需要看本章**，
只有需要重启服务、排查问题、备份数据时才需要。

### 5.1 服务启停

服务以 Windows 服务的形式注册（服务名 **`ModelManageService`**），
由 NSSM 托管，**开机自启、崩溃自动重启**。

**方式一：命令行（推荐）**

```cmd
net start ModelManageService        :: 启动
net stop  ModelManageService        :: 停止
```

**PowerShell**：

```powershell
Get-Service ModelManageService                                   # 查看状态
Restart-Service ModelManageService                               # 重启
Get-Service ModelManageService | Format-Table Name, Status, StartType
```

**方式二：图形界面**

按 `Win + R` → 输入 `services.msc` → 回车 →
在列表中找到 **`ModelManageService`** → 右键可启动 / 停止 / 重启。

**正常状态**应为：

```
Name                  Status   StartType
----                  ------   ---------
ModelManageService    Running  Automatic
```

> `Status = Running` 且 `StartType = Automatic` 即为正常。

### 5.2 查看日志

NSSM 服务的日志需要查看服务的标准输出重定向文件。

```powershell
# 查看服务配置（含日志路径）
nssm.exe get ModelManageService AppStdout
nssm.exe get ModelManageService AppStderr
```

若未配置日志重定向，可使用**手工前台启动**方式查看实时日志（见 [§5.3](#53-手工启动调试用)）。

**应用层日志**位于项目目录下：

```powershell
# 项目日志目录
Get-ChildItem C:\22project\offline_package\04-program-code\testRestfulProject\data\logs

# 查看最近内容
Get-Content C:\22project\offline_package\04-program-code\testRestfulProject\data\logs\*.log -Tail 50
```

### 5.3 手工启动（调试用）

排查问题时，可以停掉服务、手工前台启动，这样日志直接打在终端上：

```powershell
# 先停服务，避免端口冲突
net stop ModelManageService

cd C:\22project\offline_package\04-program-code\testRestfulProject
.\.venv\Scripts\python.exe main.py
```

启动成功后终端会打印：

```
[前项] 已托管打包产物：C:\...\frontend\22project\dist（访问 / 即进入系统）
[启动] 未捕获异常会写入：C:\...\data\logs\error-YYYYMMDD.log
* Running on http://127.0.0.1:5000
```

调试完按 `Ctrl + C` 停止，再改回服务方式运行：

```cmd
net start ModelManageService
```

> **⚠️ 端口说明**：Windows 版的入口为 **`main.py`**，默认端口即为 **5000**。
> 若使用 `serve.py`，其默认端口为 **8080**，需显式指定 `--port 5000`。

### 5.4 健康检查

最常用的自检命令：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

或在浏览器中直接访问 `http://127.0.0.1:5000/health`。

**关键字段**：

| 字段 | 正常值 | 含义 |
| --- | --- | --- |
| `service` | `"ok"` | 服务正常 |
| `database.ok` | `true` | 数据库连接正常 |
| `auth.enabled` | `true` | 鉴权已开启 |
| `auth.key_is_default` | `false` | **密钥已固定**（为 `true` 表示未配置，重启会掉线） |

### 5.5 修改配置

配置文件为 `db.env`，位于项目根目录。

```powershell
cd C:\22project\offline_package\04-program-code\testRestfulProject
notepad db.env
```

**关键配置项**：

```bash
# ---- 数据库连接 ----
MODEL_DB_HOST=127.0.0.1
MODEL_DB_PORT=3306
MODEL_DB_USER=root
MODEL_DB_PASSWORD=123456
MODEL_DB_NAME=model_management

# ---- 令牌签名密钥（★ 必须配置固定值）----
MODEL_SECRET_KEY=<64 位十六进制字符串>

# ---- 令牌有效期（小时）----
MODEL_TOKEN_TTL_HOURS=12
```

> **⚠️ 注意**：配置文件中同一配置项**只有第一处生效**（源码逻辑为「已存在则跳过」）。
> 修改时请确认没有重复行，否则改了不生效。

**修改后必须重启服务**：

```cmd
net stop ModelManageService
net start ModelManageService
```

### 5.6 数据库维护

**登录数据库**：

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -p123456 model_management
```

**查看各表记录数**（在 MySQL 提示符下执行）：

```sql
SELECT 'Models' AS 表名, COUNT(*) AS 记录数 FROM Models
UNION ALL SELECT 'Datasets', COUNT(*) FROM Datasets
UNION ALL SELECT 'Trainings', COUNT(*) FROM Trainings
UNION ALL SELECT 'Users', COUNT(*) FROM Users
UNION ALL SELECT 'OperationLogs', COUNT(*) FROM OperationLogs;
```

**MySQL 开机自启**：

```powershell
Get-Service MySQL80 | Format-Table Name, Status, StartType
Set-Service MySQL80 -StartupType Automatic      # 设为开机自启
Start-Service MySQL80                            # 启动
```

### 5.7 数据备份

**需要备份的内容**：

| 内容 | 路径 | 说明 |
| --- | --- | --- |
| **数据库** | MySQL `model_management` | 用户、模型登记、训练记录、操作日志 |
| **模型产物** | `...\testRestfulProject\data\models\` | 训练输出的权重与元信息 |
| **上传数据集** | `...\testRestfulProject\data\datasets\` | 用户上传的数据 |
| **发布包** | `...\testRestfulProject\data\exports\` | 已发布的模型 zip |
| **配置** | `...\testRestfulProject\db.env` | 数据库口令与签名密钥 |

**备份命令**：

```powershell
$root = "C:\22project\offline_package\04-program-code\testRestfulProject"
$date = Get-Date -Format "yyyyMMdd"
mkdir C:\backup -Force

# 1. 数据库
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe" -uroot -p123456 model_management > "C:\backup\db-$date.sql"

# 2. 文件
Compress-Archive -Path "$root\data\models", "$root\data\datasets", "$root\data\exports", "$root\db.env" `
  -DestinationPath "C:\backup\data-$date.zip" -Force
```

**恢复**：

```powershell
# 数据库
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -p123456 model_management < "C:\backup\db-20260923.sql"

# 文件
Expand-Archive -Path "C:\backup\data-20260923.zip" -DestinationPath $root -Force
```

### 5.8 交付前自查清单

| 检查项 | 命令 | 预期结果 |
| --- | --- | --- |
| 服务运行中 | `Get-Service ModelManageService` | `Running` |
| 服务开机自启 | 同上，看 `StartType` | `Automatic` |
| MySQL 运行中 | `Get-Service MySQL80` | `Running` |
| 端口监听 | `netstat -ano \| findstr :5000` | 有 `LISTENING` |
| 健康检查 | `Invoke-RestMethod http://127.0.0.1:5000/health` | `service: ok` |
| 数据库连通 | 同上，看 `database.ok` | `true` |
| 密钥已固定 | 同上，看 `auth.key_is_default` | `false` |
| 防火墙放行 | `Get-NetFirewallRule -DisplayName "*5000*"` | 规则存在 |

---

## 6. 常见问题与处理办法

本章按**现象**组织，方便对照排查。**每一条都给出「原因 → 处理办法」。**

### 6.1 服务没起来 / 系统打不开

**现象**：浏览器显示「无法访问此网站」。

**排查顺序**：

```powershell
# 1. 服务是否在跑
Get-Service ModelManageService | Format-Table Name, Status, StartType

# 2. 端口有没有人在监听
netstat -ano | findstr :5000

# 3. 本机自测
Invoke-RestMethod http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
```

| 检查结果 | 原因 | 处理 |
| --- | --- | --- |
| 服务未运行 | 服务被停掉或启动失败 | `net start ModelManageService` |
| 服务运行但端口无监听 | 启动参数错误 | 手工前台启动查看报错（见 [§5.3](#53-手工启动调试用)） |
| 本机能通、别的机器不通 | 防火墙未放行 | 见 [§6.2](#62-浏览器打不开页面) |

### 6.2 浏览器打不开页面

**现象**：本机能打开，局域网其他机器打不开。

**原因**：Windows 防火墙未放行 5000 端口。

**处理**（**需要用管理员身份打开 PowerShell**）：

```powershell
# 放行 5000 端口
New-NetFirewallRule -DisplayName "ModelPlatform-5000" `
  -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow

# 确认规则已建立
Get-NetFirewallRule -DisplayName "ModelPlatform-5000"
```

**其他排查**：

```powershell
# 确认监听的是 0.0.0.0 而不是 127.0.0.1
netstat -ano | findstr :5000

# 确认本机 IP 与访问方在同一网段
ipconfig
```

### 6.3 更新代码后看不到新功能

**现象**：覆盖了文件、重启了服务，浏览器里还是旧界面。

**原因**：**浏览器缓存**了旧版前端资源。

**处理**：按 `Ctrl + Shift + R` 强制刷新。

若仍无效：
- 用无痕窗口验证（`Ctrl + Shift + N`）
- 或在开发者工具（`F12`）的 Network 标签中勾选「禁用缓存」后刷新

### 6.4 页面能打开但接口全报错

**现象**：页面显示出来了，但所有数据请求都失败。

**原因**：前端资源引用的接口地址与实际部署不符。

**排查**：浏览器按 `F12` →「网络」标签 → 查看失败请求的**完整 URL**。

| 请求 URL 特征 | 说明 |
| --- | --- |
| `/api/api/xxx` | **接口前缀重复**，前端构建时环境变量配置错误 |
| `/xxx` 缺少 `/api` | 前端构建模式不对 |
| `/api/xxx` | **正确** |

**处理**：前端必须使用 `npm run build:singleport` 构建
（该模式读取 `.env.singleport`，其中 `VITE_API_URL` 为空字符串）。
用 `npm run build` 会读取 `.env.production`（`VITE_API_URL='/api'`），导致前缀叠加。

### 6.5 训练或推理报错

**现象**：点击训练或推理，页面提示失败（HTTP 500）。

**排查**：

```powershell
# 方式一：手工前台启动，错误会直接打在终端上
net stop ModelManageService
cd C:\22project\offline_package\04-program-code\testRestfulProject
.\.venv\Scripts\python.exe main.py

# 方式二：查看应用日志目录
Get-Content C:\22project\offline_package\04-program-code\testRestfulProject\data\logs\*.log -Tail 50
```

**常见原因**：

| 原因 | 排查方式 |
| --- | --- |
| 数据库连接断开 | 访问 `/health` 看 `database.ok` |
| 模型文件缺失 | `dir C:\...\testRestfulProject\data\models` |
| 数据文件路径错误 | 确认选择的数据文件确实存在 |
| 推理参数非法 | 看终端输出的 traceback 最后一行 |
| 日志目录不可写 | `dir C:\...\testRestfulProject\data\logs`，见 [§7.5](#75-数据与业务功能类问题) |

**页面侧**：失败时前端会显示**红色提示条**，
并在浏览器控制台（`F12` → Console）打印后端返回的 traceback 片段。

### 6.6 重启服务后所有人掉线

**现象**：服务重启后，所有已登录用户需要重新登录。

**原因**：`MODEL_SECRET_KEY` 未配置固定值，服务每次启动生成随机密钥。

**排查**：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5 | Select-String key_is_default
```

- `false` → 密钥已固定，**正常**
- `true` → **密钥是默认值，需要配置**

**处理**：见 [§5.5 修改配置](#55-修改配置)。

### 6.7 账号无法登录

**现象**：输入正确密码仍提示「用户名或密码错误」。

**排查顺序**：

**1. 确认账号是否存在**

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -p123456 model_management `
  -e "SELECT UserID, Username, RoleID, IsActive FROM Users;"
```

**2. 确认账号是否被禁用**

`IsActive = 0` 表示已禁用，无法登录。由管理员在「用户管理」页启用。

**3. 确认密码是否正确**

初始密码见 [§3.2](#32-三个内置账号)。注意**大小写**与特殊字符。

**4. 重置密码（推荐用脚本，不要手工改库）**

```powershell
cd C:\22project\offline_package\04-program-code\testRestfulProject
.\.venv\Scripts\python.exe tools\reset-login-accounts.py
```

> **⚠️ 不要手工往数据库里插密码哈希**：哈希格式对空格、换行极其敏感，
> 手工插入极易出错且**没有任何明确报错**，会让人误以为系统坏了。

### 6.8 中文显示为乱码

**现象**：角色名、模型说明等中文显示成问号或方块。

**原因**：数据库字符集不是 `utf8mb4`。

**排查**：

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -p123456 `
  -e "SHOW CREATE DATABASE model_management\G" | Select-String charset
```

**处理**：

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -p123456 `
  -e "ALTER DATABASE model_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 6.9 开机进入「Recovery Menu」恢复菜单

**现象**：开机后没有进入桌面，而是一个白底黑字的 `Recovery Menu` 菜单。

**原因**：引导程序（GRUB）的上次启动记录被标记为「异常」，
系统出于保护而进入恢复模式。常见诱因是**非正常关机**（断电、强制重启）。

**处理**：

**方式一（最简单）**：
1. 用方向键选择 **`resume`**（Resume normal boot）
2. 回车，系统继续正常启动

**方式二（彻底修复）**：进入 Ubuntu 系统后（或在恢复模式的 root shell 中）执行：

```bash
sudo grub-editenv /boot/grub/grubenv set recordfail=0
sudo update-grub
sudo reboot
```

> **预防建议**：**请务必正常关机**（开始菜单 → 关机），
> 不要直接按电源键或拔电源。

### 6.10 开机后显示器无信号

**现象**：按下电源键后，显示器提示「无信号」，主机风扇在转。

**原因**：BIOS 的显示输出设置与**显示器实际插的接口**不匹配。

**本机的正确配置**：

| 显示器接法 | BIOS 设置（`Devices → Video Setup`） |
| --- | --- |
| **接主板 HDMI 口**（当前使用） | **`Select Active Video = IGD`** |
| 接独立显卡（DP 口） | `Select Active Video = AUTO` |

**⚠️ 绝对不能混搭**：

| 错误组合 | 结果 |
| --- | --- |
| `IGD` + 显示器插独显 | **无信号** |
| `AUTO` + 显示器插主板 HDMI | **无信号** |

**处理**：
1. 先**把显示器线插回主板 HDMI 口**（当前正确接法）
2. 若仍无信号，重启进 BIOS（开机按 `F1`），
   确认 `Devices → Video Setup → Select Active Video = IGD`
3. 保存退出（`F10`）

### 6.11 启动时提示端口被占用

**现象**：服务启动失败，提示端口 5000 被占用。

**原因**：有其他程序（如手工启动的 `serve.py`、旧的服务实例）占用了 5000。

**排查**：

```powershell
# 查看占用 5000 的进程
netstat -ano | findstr :5000
# 记下最后一列的 PID，然后查询进程名
Get-Process -Id <PID>
```

**处理**：

```powershell
# 停掉服务后重新启动
net stop ModelManageService
net start ModelManageService

# 若确认是遗留的手工进程，结束它
Stop-Process -Id <PID> -Force
```

> **提醒**：**不要同时注册两个服务抢同一个端口**。
> 服务名必须为 `ModelManageService`，参数为 `main.py`（端口 5000）。

### 6.12 页面样式错乱或白屏

**现象**：页面空白，或样式完全不对。

**原因**：前端静态资源路径配置错误，或产物不完整。

**排查**：浏览器 `F12` → Console 看是否有 `404` 资源加载失败。

```powershell
# 确认前端产物完整
dir C:\22project\offline_package\04-program-code\testRestfulProject\..\frontend\22project\dist
# 应有 index.html、assets/、favicon.ico
```

**处理**：重新拷贝**完整**的前端产物目录。
**不能只拷贝部分文件** —— 构建产物的各 chunk 之间有相互引用。

### 6.13 虚拟机环境工具提示

**现象**：某些安全软件或系统工具提示权限、驱动类告警。

**原因**：本机装有 TensorFlow / PyTorch 等科学计算库，会加载原生扩展（DLL）。

**处理**：**确认告警不影响功能即可忽略**。
若出现 `ImportError: DLL load failed` 之类的错误，见 [§7.1 问题 3](#问题-3tensorflow--pytorch-加载失败dll-相关)。

---

## 7. 部署过程中遇到的问题与解决方法

本章记录**部署本系统时实际遇到过的问题**及其解决方法，
供后续在其他机器上部署时参考。**系统日常使用不需要看本章。**

### 7.1 环境类问题

#### 问题 1：Python 版本过低或不满足依赖要求

**现象**：安装依赖时报错，提示需要 Python 3.10 或更高版本。

**原因**：部分依赖（如新版 TensorFlow）要求 Python 3.10+。

**解决方法**：

```powershell
python --version          # 确认版本
```

若版本过低，需安装 Python 3.10+ 并重建虚拟环境。

> 本机使用 **Python 3.12**，满足全部依赖要求。

#### 问题 2：虚拟环境随项目一起搬迁后失效

**现象**：把项目从 D 盘整体移动到其他位置后，
执行 `.\.venv\Scripts\python.exe` 报错或行为异常。

**原因**：Python 虚拟环境内部记录了**创建时的绝对路径**
（在 `.venv\pyvenv.cfg` 与服务脚本中）。
项目目录一经移动，这些记录的路径全部失效。

**排查**：

```powershell
Get-Content C:\22project\offline_package\04-program-code\testRestfulProject\.venv\pyvenv.cfg
```

若 `home =` 指向的路径已不存在，即为该问题。

**解决方法（二选一）**：

**方案 A：重建虚拟环境（推荐）**

```powershell
cd C:\22project\offline_package\04-program-code\testRestfulProject

# 备份后删除旧环境
Rename-Item .venv .venv.bak

# 重建
python -m venv .venv

# 重新安装依赖（离线环境请使用本地 wheel 目录）
.\.venv\Scripts\pip.exe install -r requirements.txt
# 若为离线包
.\.venv\Scripts\pip.exe install --no-index --find-links=<wheel目录> -r requirements.txt
```

**方案 B：修正环境内的绝对路径**

修改 `.venv\pyvenv.cfg` 中的 `home` 指向，以及
`.venv\Scripts\` 下 `*.exe` 内嵌的路径（较繁琐，不推荐）。

#### 问题 3：TensorFlow / PyTorch 加载失败（DLL 相关）

**现象**：导入 TensorFlow 或 PyTorch 时报错，涉及原生模块加载失败，
典型信息为 `ImportError: DLL load failed`。

**原因**：Python 科学计算库依赖 Windows 系统级的
**Microsoft Visual C++ Redistributable（运行库）**。
该运行库未被安装时，库无法加载。

**排查**：

```powershell
.\.venv\Scripts\python.exe -c "import tensorflow as tf; print(tf.__version__)"
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__)"
```

若报 DLL 相关错误，为缺少运行库。

**解决方法**：

1. 在部署包中查找 `vc_redist.x64.exe`
2. 以**管理员身份**运行安装
3. 安装完成后**重启系统**
4. 重新验证导入

> **说明**：该运行库是 Windows 上运行各类科学计算库的前置条件，
> **离线部署时必须一并携带**。

#### 问题 4：MySQL 用户认证插件不兼容

**现象**：后端启动时报数据库连接失败，错误信息涉及
`caching_sha2_password` 或 `Authentication plugin ... cannot be loaded`。

**原因**：MySQL 8 默认使用 `caching_sha2_password` 认证插件，
**旧版 PyMySQL 不带 `cryptography` 库时无法连接**。

**解决方法（二选一）**：

**方案 A：安装 `cryptography`（推荐）**

```powershell
.\.venv\Scripts\pip.exe install cryptography
```

本项目的 `requirements.txt` 中**已包含** `cryptography` 依赖。

**方案 B：把 MySQL 用户改为 `mysql_native_password`**

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot -p `
  -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '你的密码'; FLUSH PRIVILEGES;"
```

---

### 7.2 路径与目录类问题

#### 问题 5：项目目录搬迁后数据集与模型找不到

**现象**：项目从原位置移动到新位置后，
训练报「找不到数据集」，推理报「文件不存在」。

**原因**：项目移动后，**目录结构与代码期望不一致**，
或数据库中的登记记录仍指向旧路径。

**排查**：

```powershell
cd C:\22project\offline_package\04-program-code\testRestfulProject

# 查看健康检查报告的后端期望路径
Invoke-RestMethod http://127.0.0.1:5000/health | ConvertTo-Json -Depth 6
```

**解决方法**：

1. **对照 `/health` 输出的 `datasets` 字段**，确认后端期望的路径；
2. **把数据集目录放到期望的位置**；

```powershell
# 示例：若后端期望 datasets 在项目根，但实际在 data 下
Move-Item "data\1DCNN" "1DCNN" -Force
Move-Item "data\cwt_cnn" "cwt_cnn" -Force

# 验证
dir 1DCNN | Select-Object -First 5 Name
```

> **路径基准**：训练与推理中的相对路径均以**项目根目录**
> （即入口文件所在目录）为基准。

#### 问题 6：前端产物放错目录，后端报「未找到打包产物」

**现象**：服务能启动，但浏览器访问只看到一段提示，没有界面。

**原因**：前端构建产物不在后端探测的候选目录里。

**后端探测顺序**（依次尝试）：

```
frontend\22project\dist      （源码仓库布局）
frontend\dist                （打包分发布局）
data\web                     （部署布局）
```

**解决方法**：

```powershell
# 确认前端产物在哪
dir C:\22project\offline_package\04-program-code\frontend\22project\dist\index.html
```

启动时终端会打印「找过哪些位置」，按提示把 `dist` 放到位即可。

#### 问题 7：日志目录不可写

**现象**：训练或推理报 500，但项目日志目录下的错误日志是空的，
启动时终端提示 `Error opening file for writing`。

**原因**：日志目录权限不足，后端进程无法写入。

**解决方法**：

```powershell
$dir = "C:\22project\offline_package\04-program-code\testRestfulProject\data\logs"

# 授予写权限
icacls $dir /grant "Everyone:(OI)(CI)F" /T

# 测试
"test" | Out-File "$dir\test.txt"
Test-Path "$dir\test.txt"
```

> **说明**：日志写不进去会让排查变得困难（看不到 traceback），
> **部署完成后建议先验证日志目录可写**。

---

### 7.3 服务与启动类问题

#### 问题 8：NSSM 服务注册后反复重启

**现象**：服务状态在 `Running` 与 `Stopped` 之间反复切换，
或在服务管理器里看到不断重启。

**原因**：服务配置中的**应用路径或工作目录错误**，
或**启动参数不正确**导致进程启动即退出。

**排查**：

```powershell
# 查看服务配置（应用路径、参数、工作目录）
nssm.exe get ModelManageService Application
nssm.exe get ModelManageService AppDirectory
nssm.exe get ModelManageService AppParameters
```

**正确的配置应为**：

| 配置项 | 值 |
| --- | --- |
| **Application** | `<项目根>\.venv\Scripts\python.exe` |
| **AppDirectory** | `<项目根>` |
| **AppParameters** | `main.py`（Windows 版） |

**解决方法**：

```cmd
:: 停止并删除旧服务后重新注册
net stop ModelManageService
nssm.exe remove ModelManageService confirm

nssm.exe install ModelManageService "<项目根>\.venv\Scripts\python.exe" "main.py"
nssm.exe set ModelManageService AppDirectory "<项目根>"
nssm.exe set ModelManageService Start SERVICE_AUTO_START
net start ModelManageService
```

> **根本建议**：**项目目录移动后必须重新注册服务**，
> 因为服务配置里保存的是绝对路径。
> 本机项目最终路径为
> `C:\22project\offline_package\04-program-code\testRestfulProject`。

#### 问题 9：服务启动失败但看不到错误

**现象**：服务起不来，但服务管理器里没有明显报错。

**原因**：Windows 服务运行在无界面环境中，
标准输出不会被显示。

**解决方法**：**先手工前台启动**，让错误直接打在终端上：

```powershell
net stop ModelManageService
cd C:\22project\offline_package\04-program-code\testRestfulProject
.\.venv\Scripts\python.exe main.py
```

观察终端输出，错误会直接显示。修复后再启动服务：

```cmd
net start ModelManageService
```

> **另一种做法**：用 NSSM 把服务的输出重定向到文件：
> ```cmd
> nssm.exe set ModelManageService AppStdout "C:\logs\service-out.log"
> nssm.exe set ModelManageService AppStderr "C:\logs\service-err.log"
> ```

#### 问题 10：用 Flask 内置服务器运行（当前状态说明）

**现象**：启动时终端提示
`WARNING: This is a development server. Do not use it in a production deployment.`

**原因**：Windows 版当前使用 Flask 内置服务器（通过 `main.py` 启动），
这是**开发模式**服务器，并发能力弱于生产级 WSGI 服务器。

**说明与建议**：

| 项目 | 当前状态 | 说明 |
| --- | --- | --- |
| **运行方式** | Flask 内置服务器 | 由 `main.py` 启动，端口 5000 |
| **并发能力** | 较弱 | 适合单人或小规模使用 |
| **稳定性** | 可长期运行 | 已通过服务托管，崩溃自动重启 |
| **如需生产级** | 可改用 `serve.py` + waitress | 参考 Ubuntu 版的部署方式 |

> **重要**：该告警**不影响功能使用**。
> 本机（Windows 版）定位为**备份与演示环境**，
> 正式长期使用建议采用 **Ubuntu 版**（已使用 waitress 生产级服务器）。

---

### 7.4 显示与显卡类问题

#### 问题 11：BIOS 显示输出设置与接口不匹配

**现象**：调整 BIOS 设置或更换显示器接口后，开机完全无信号。

**原因**：BIOS 中的 `Select Active Video` 必须与**显示器实际插的物理接口**对应。

**本机的对应关系**（ThinkStation P360，`Devices → Video Setup`）：

| BIOS 设置 | 显示器应插 |
| --- | --- |
| **`IGD`**（核显优先） | **主板 HDMI / DP 口** ← **当前配置** |
| `AUTO` | 独立显卡的 DP 口 |

**解决方法**：

1. **改回匹配的组合**：显示器线**插主板 HDMI 口** + BIOS 设 **`IGD`**
2. 若无法进 BIOS（屏幕无信号），可**先换接口**再进 BIOS 调整
3. 若 BIOS 设置被改乱，可在 BIOS 中按 `F9` **恢复默认设置**，再按 `F10` 保存

> **重要提醒**：**不要随意更改这两项设置**。
> 本机交付时的正确配置为 **`IGD` + 主板 HDMI 接口**（显示器接主板 HDMI）。

#### 问题 12：开机时显示器无信号但主机在运行

**现象**：开机后显示器报「无信号」，主机风扇转动。

**原因**：本机同时具备核显与独立显卡，若 BIOS 设置了核显优先
（`IGD`）但显示器插在独显接口上，则独显不输出信号。

**解决方法**：

**第一步**：**把显示器线插到主板 HDMI 口**（当前正确接法）

**第二步**：若仍无信号，进 BIOS（开机按 `F1`）确认设置：

```
Devices → Video Setup → Select Active Video = IGD
```

**第三步**：`F10` 保存退出

> **快速判断**：如果**恢复模式能显示、正常启动无信号**，
> 那是内核显卡驱动的问题（见 [§7.5 问题 14](#问题-14正常启动无信号但恢复模式能显示)）；
> 如果**开机自检阶段就无信号**，则是接口 / BIOS 设置问题。

#### 问题 13：引导菜单停留时间过短，来不及选择系统

**现象**：开机时 GRUB 菜单一闪而过，来不及选择 Windows。

**原因**：`GRUB_TIMEOUT` 设置过短。

**解决方法**（需在 Ubuntu 系统中执行）：

```bash
sudo sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=10/' /etc/default/grub
sudo update-grub
```

本机已设置为 **10 秒**。

#### 问题 14：正常启动无信号，但恢复模式能显示

**现象**（此问题发生在 Ubuntu 侧，记录于此供参考）：
- 从 GRUB 选 `Ubuntu` 正常启动 → **显示器无信号**
- 从 `Advanced options` → `recovery mode` → `resume` → **能正常显示**

**原因**：内核对 NVIDIA 显卡的开源驱动（`nouveau`）支持不佳，
正常启动时内核尝试用 `nouveau` 接管显卡，初始化失败导致视频输出中断。
恢复模式默认带 `nomodeset` 参数，跳过内核模式设置，因此能正常显示。

**解决方法**（在 Ubuntu 系统中执行）：

```bash
sudo cp /etc/default/grub /etc/default/grub.bak
sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet nomodeset"/' /etc/default/grub
sudo update-grub
sudo reboot
```

> **说明**：`nomodeset` 只影响图形显示的初始化方式，**不影响 CPU 计算能力**。
> 本平台为 **CPU 计算**，不使用 GPU，因此无副作用。

---

### 7.5 数据与业务功能类问题

#### 问题 15：数据集目录结构与代码期望不一致

**现象**：训练报「找不到数据集」或「文件不存在」。

**原因**：数据集目录被移动后，与代码期望的路径不一致。

**解决方法**：

```powershell
# 1. 用健康检查看后端认为的数据集路径
Invoke-RestMethod http://127.0.0.1:5000/health | ConvertTo-Json -Depth 6 | Select-String -Context 0,5 datasets

# 2. 对照提示，把数据集放到期望的位置
dir C:\22project\offline_package\04-program-code\testRestfulProject
dir C:\22project\offline_package\04-program-code\testRestfulProject\data
```

#### 问题 16：模型发布包下载后无法使用

**现象**：外部机器解压发布包后，运行 `example_infer.py` 报错。

**排查清单**：

| 检查项 | 说明 |
| --- | --- |
| **依赖是否装全** | `pip install -r requirements.txt` |
| **Python 版本** | 需 3.10 以上 |
| **模型框架是否匹配** | `.keras` 需 TensorFlow；`.pth` 需 PyTorch |
| **示例脚本的路径** | 脚本中的模型文件名需与包内文件名一致 |
| **缺少 C++ 运行库** | 见 [§7.1 问题 3](#问题-3tensorflow--pytorch-加载失败dll-相关) |

#### 问题 17：Windows 与 Ubuntu 数据不互通

**现象**：在 Windows 里训练/上传的数据，切换到 Ubuntu 后看不到。

**原因**：这是**双系统的固有特性** ——
两套系统各自拥有独立的 MySQL 数据库与文件系统，
**同一时刻只有一个系统在运行**。

**解决方法**：

| 需求 | 做法 |
| --- | --- |
| **传递模型** | 通过「模型发布 → 下载 `.zip`」导出，复制到另一系统使用 |
| **传递数据集** | 把数据文件复制到**两系统都能访问的分区**，各自上传 |
| **统一工作环境** | **建议固定使用其中一个系统**（推荐 Ubuntu 版） |

> **建议**：不要试图让两套系统共享数据库 —— 这在双系统环境下
> 技术上不可靠（两系统不能同时运行，数据目录格式与权限也不同）。
> **固定使用一套系统**是最稳妥的做法。

---

## 附录 A：关键路径与配置速查

### A.1 目录结构

```
C:\22project\offline_package\04-program-code\
├── testRestfulProject\              后端（Flask）
│   ├── model_service\               业务代码
│   ├── sql\                         建库脚本
│   │   ├── schema_mysql.sql             表结构
│   │   └── auth-migration.sql           鉴权表迁移
│   ├── tools\                       运维脚本
│   ├── 1DCNN\ cwt_cnn\ adtk\        内置数据集与模型
│   ├── data\                        运行时数据
│   │   ├── models\                  模型产物
│   │   ├── datasets\                上传的数据集
│   │   ├── exports\                 模型发布包
│   │   ├── figures\                 训练曲线、推理图表
│   │   └── logs\                    运行日志
│   ├── .venv\                       Python 虚拟环境
│   ├── main.py                      启动入口
│   ├── serve.py                     备用启动入口（默认端口 8080）
│   ├── requirements.txt             Python 依赖清单
│   ├── db.env                       实际配置（含数据库口令）
│   └── db.env.example               配置模板
└── frontend\
    └── 22project\
        └── dist\                    前端已构建产物（由后端托管）
```

### A.2 关键配置速查

| 项目 | 值 |
| --- | --- |
| **平台访问地址** | `http://127.0.0.1:5000` |
| **服务名** | `ModelManageService` |
| **启动入口** | `main.py`（端口 5000） |
| **项目目录** | `C:\22project\offline_package\04-program-code\testRestfulProject` |
| **配置文件** | `...\testRestfulProject\db.env` |
| **虚拟环境** | `...\testRestfulProject\.venv` |
| **数据库** | `model_management` @ `127.0.0.1:3306` |
| **MySQL 服务名** | `MySQL80` |
| **前端产物** | `...\04-program-code\frontend\22project\dist` |
| **日志位置** | `...\testRestfulProject\data\logs\` |

---

## 附录 B：命令速查表

### B.1 服务管理

```cmd
net start ModelManageService        :: 启动
net stop  ModelManageService        :: 停止
```

```powershell
Get-Service ModelManageService | Format-Table Name, Status, StartType
Restart-Service ModelManageService
```

```cmd
:: NSSM 服务配置查看
nssm.exe get ModelManageService Application
nssm.exe get ModelManageService AppDirectory
nssm.exe get ModelManageService AppParameters
```

### B.2 健康检查与自检

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health | ConvertTo-Json -Depth 5
netstat -ano | findstr :5000
Get-Service MySQL80, ModelManageService | Format-Table Name, Status, StartType
ipconfig | Select-String "IPv4"
```

### B.3 手工启动（调试）

```powershell
net stop ModelManageService
cd C:\22project\offline_package\04-program-code\testRestfulProject
.\.venv\Scripts\python.exe main.py
```

### B.4 数据库操作

```powershell
$mysql = "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"

# 登录
& $mysql -uroot -p123456 model_management

# 备份
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe" -uroot -p123456 model_management > C:\backup\db.sql

# 恢复
& $mysql -uroot -p123456 model_management < C:\backup\db.sql
```

### B.5 账号维护

```powershell
cd C:\22project\offline_package\04-program-code\testRestfulProject
.\.venv\Scripts\python.exe tools\reset-login-accounts.py
```

### B.6 防火墙配置

```powershell
# 放行 5000 端口（需管理员权限）
New-NetFirewallRule -DisplayName "ModelPlatform-5000" `
  -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow

# 查看规则
Get-NetFirewallRule -DisplayName "ModelPlatform-5000"
```

### B.7 正常关机

```powershell
Stop-Computer           # 关机
Restart-Computer        # 重启
```

> **⚠️ 请勿强制断电关机**，否则可能触发文件系统自检或恢复模式。

---

## 附录 C：账号与密码清单

### C.1 系统账号

| 用途 | 账号 | 密码 |
| --- | --- | --- |
| Windows 系统登录 | （无） | （无，开机直接进桌面） |
| MySQL 数据库 | `root` | `123456` |

### C.2 平台账号

| 用户名 | 密码 | 角色 | 权限范围 |
| --- | --- | --- | --- |
| `admin` | `Admin@2026` | 管理员 | 全部功能（含用户管理、操作日志） |
| `engineer` | `Engineer@2026` | 工程师 | 训练、推理、模型与数据集管理 |
| `operator` | `Operator@2026` | 操作员 | 只读浏览 |

> **⚠️ 交付后请立即修改以上平台密码**（尤其 `admin`），
> 并停用或删除不再使用的演示账号。修改方式见 [§4.7](#47-用户管理管理员专属)。

### C.3 端口清单

| 端口 | 用途 |
| --- | --- |
| **5000** | **平台服务（对外唯一端口）** |
| 3306 | MySQL（仅本机访问） |

---

## 附录 D：文档版本记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v1.0 | 2026-09-23 | 首版。面向 Windows 交付主机，以**全链路使用**为主线；
补充双系统说明、服务运维（NSSM）、常见问题（13 条）、部署问题（17 条） |

---

> **配套文档**：
> - 本文档（Windows 版）
> - 《模型管理平台 · 系统使用说明书（Ubuntu 版）》
>
> 两份文档的**功能模块操作步骤完全一致**，
> 差异仅在**服务管理方式**（`NSSM` vs `systemd`）与**路径 / 端口**部分。


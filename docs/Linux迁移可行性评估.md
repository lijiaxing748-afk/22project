# 模型管理平台 · Linux 迁移可行性评估

> 版本：v1.0　编写日期：2026-09-21
> 文档性质：**可行性评估**（≠ 实施方案，≠ 已完成）
> 现状基线：系统当前在 Windows 10 上完整运行，本文评估的是「迁移到 Linux」需要付出什么代价。

---

## 一、结论摘要

| 问题 | 结论 |
|---|---|
| 后端代码能否直接在 Linux 上跑？ | **基本可以**。全项目用 `pathlib` 处理路径，无硬编码盘符；Flask + waitress 纯 Python |
| 需要改代码吗？ | **需要，但改动很小**：摘掉 1 个 Windows 专属依赖、补 1 个缺失依赖 |
| 主要的麻烦在哪？ | **不在代码，在环境**：约 1.2 GB 的 Windows 版离线依赖**全部作废**，需重新获取 Linux 版 |
| 工作量估算 | x86_64 且可联网：**1 天以内**；离线 + ARM 架构：**显著增加，且存在硬性阻塞风险** |
| 是否有硬性阻塞项？ | **取决于 CPU 架构与发行版**，见第四章「待确认事项」 |

**一句话概括**：这套系统的迁移难度**远低于一般预期**，真正的不确定性来自外部环境（架构 / 发行版 / 网络），而不是代码本身。

---

## 二、当前 Windows 部署形态（迁移基线）

以实验室交付主机为准，现状如下：

| 组成 | 当前实现 | Linux 上的对应方案 | 迁移性质 |
|---|---|---|---|
| 后端运行 | Python 3.12 + Flask + waitress | 完全一致 | **无需改代码** |
| 应用入口 | `serve.py --port 5000` | 完全一致 | **无需改代码** |
| 前端 | 已构建的静态 `dist`，由后端托管 | 完全一致 | **无需改代码** |
| 数据库 | MySQL 8（`model_management`） | MySQL 8 或 MariaDB | 需处理认证插件差异 |
| 后台服务 | NSSM 包装为 Windows 服务 | systemd unit | **需重写**，但更简单 |
| 离线依赖 | 629.8 MB Python wheel + 640.8 MB `node_modules` | **无法复用**，需 Linux 版 | **工作量主体** |
| 部署脚本 | PowerShell（10 个 `.ps1` + `run.bat`） | Bash / systemd | **需重写** |
| 前端构建 | 本机 `npm run build:singleport` | 不需要（沿用同一份 `dist`） | **无需重做** |

> 关键认知：**前端产物与操作系统无关**。`dist` 是纯静态文件，Windows 上构建的可以直接拿到 Linux 上用，不需要在 Linux 上装 Node.js。这一点能省掉 640.8 MB 的迁移量。

---

## 三、代码层面的实际差异（已逐项核查）

### 3.1 结论：代码几乎无需修改

| 核查项 | 核查结果 |
|---|---|
| 路径拼接方式 | `config.py`、`web.py` 全部使用 `pathlib.Path`，**未发现 `D:\` 等硬编码盘符** |
| 路径分隔符 | 通过 `Path / "x"` 运算符拼接，跨平台自动适配 |
| Web 框架 | Flask + Flask-RESTful + waitress，均为纯 Python 实现 |
| 数据库驱动 | PyMySQL（纯 Python），**不是需要编译的 `mysqlclient`** |
| WSGI 入口 | `serve.py` 为独立脚本，不依赖 Windows 命令行 |
| `main.py` 导入链 | 仅导入 Flask / flask_restful / model_service 内部模块，**不涉及任何 Windows API** |

### 3.2 需要修改的部分

#### （1）`pywin32` —— 必须摘除

`requirements.txt` 末尾有一行：

```
pywin32==312
```

该包**没有 Linux 版本**，在 Linux 上执行 `pip install -r requirements.txt` 会直接失败。

经核查，它**仅被一个文件使用**：

| 文件 | 用途 | 是否属于运行链路 |
|---|---|---|
| `createdoc.py` | 调用 `win32com` 驱动 Word 生成文档，路径为 `E:\zsd\zsd.txt` | **否**。明显是一次性辅助脚本，运行链路（`serve.py` → `main.py` → `model_service/*`）完全不导入它 |

**处理方式**：将依赖声明改为仅在 Windows 上安装——

```
pywin32==312; sys_platform == "win32"
```

Linux 上不安装，`createdoc.py` 亦不使用。**改动量：1 行。**

#### （2）`cryptography` —— 必须补充

经核查，**当前依赖清单中没有 `cryptography`**，且 `PyMySQL` 本身不携带它（`pip show PyMySQL` 的 `Requires` 为空）。

这在 Windows 上暂时没有暴露问题，原因是本机 MySQL 账号使用的是旧认证插件。但 **MySQL 8 在 Linux 上的默认认证插件是 `caching_sha2_password`**，PyMySQL 连接该插件时**强制要求 `cryptography` 包**，否则会抛出：

```
RuntimeError: 'cryptography' package is required for sha256_password
or caching_sha2_password auth methods
```

该报错信息较为隐晦，容易误判为密码错误或网络问题。

**处理方式**：在依赖清单中显式加入 `cryptography`。**改动量：1 行。**

#### （3）部署脚本 —— 需整体重写

现有 10 个 PowerShell 脚本 + `run.bat` + `nssm.exe` 在 Linux 上**全部不可用**。对应替代如下：

| 原 PowerShell 脚本 | Linux 对应方案 |
|---|---|
| `01-install-backend.ps1` | Bash 脚本 + `python -m venv` |
| `02-init-database.ps1` | Bash + `mysql < schema_mysql.sql` |
| `03-preflight-check.ps1` | Bash 环境检查 |
| `04-start-system.ps1` | systemd 启停 |
| `05-install-service.ps1` | systemd unit 文件 + `systemctl enable` |
| `06-uninstall-service.ps1` | `systemctl disable` + 清理 |
| `nssm.exe` | **不需要**，systemd 原生支持守护、自启、崩溃重启 |

> 注：`serve.py` 与 `sql/schema_mysql.sql` 可**原样复用**，无需修改。

### 3.3 依赖体量（工作量主体）

当前 Windows 离线包构成：

| 组件 | 体积 | Linux 上是否需要重做 |
|---|---|---|
| `01-安装程序` | 645.6 MB | **需要**（MySQL、Python 的 Linux 安装包） |
| `02-Python离线依赖` | 629.8 MB | **需要**（约 88 个 wheel，架构/平台均不通用） |
| `03-前端离线依赖` | 640.8 MB | **不需要**（Linux 直接使用已构建的 `dist`） |
| `04-项目源码` | 97.5 MB | 不需要 |
| `05-数据库` | 0 MB | — |
| `06-部署脚本` | 0.1 MB | **需要重写**（见 3.2-3） |

**核心工作量**：重新获取约 **630 MB 的 Linux 版 Python wheel**（其中 TensorFlow 约 200 MB、PyTorch CPU 版约 118 MB 占大头）。

> 注意：`node_modules` 的 640.8 MB **可以省掉**——Linux 服务器上不需要 Node.js，直接复用现有 `dist` 即可。这是本次迁移的一个重要减负点。

---

## 四、待确认事项（**决策关键，建议优先与老师确认**）

以下四项直接决定迁移难度，**在确认之前不建议动手实施**。

### 4.1 CPU 架构（最关键）

| 情况 | 影响 |
|---|---|
| **x86_64（Intel / AMD）** | 风险低。TensorFlow、PyTorch 均有官方 wheel，流程顺畅 |
| **ARM64 / aarch64**（如鲲鹏、飞腾、部分信创平台） | **风险高**。TensorFlow 的 ARM64 wheel 在 PyPI 上**并非所有版本都有**，`torch` 亦需专用源。若目标版本缺失，需自行编译，工作量会大幅上升 |
| 其他架构 | 需单独评估 |

**为什么最关键**：这一项可能把「1 天」变成「无法按期完成」。**建议首先确认。**

### 4.2 发行版

| 候选 | 影响 |
|---|---|
| Ubuntu 22.04 / 24.04 | 最顺畅，软件源齐全，社区资料最多 |
| CentOS 7 / Rocky / AlmaLinux | 系统 Python 版本可能偏低（CentOS 7 为 3.6），需另行安装 Python 3.12 |
| 麒麟 / 统信 UOS 等信创系统 | 软件源可能受限，需确认能否访问 pip 源 |
| Debian | 顺畅，但 Python 版本策略与 Ubuntu 略有差异 |

**需确认**：是否有指定发行版及版本号。

### 4.3 网络条件

| 情况 | 影响 |
|---|---|
| **可联网** | 可直接 `pip install`，最省事，约半天完成 |
| **离线（与实验室 Windows 主机相同）** | 需在联网机器上 `pip download` 出 Linux 版 wheel（约 630 MB），再离线安装 |

**需确认**：目标 Linux 机器能否访问外网。若不能，需明确允许的优盘传输方式。

### 4.4 目标机器与权限

**需确认**：
- 是迁到**实验室现有那台机器**（替换 Windows），还是**另一台独立服务器**？
  —— 若替换现有机器，Windows 版将不可用，存在演示风险。
- 是否具备 **root 权限 / sudo 权限**？
  —— 无 sudo 时无法用 `apt` 安装系统级依赖，需改为用户级安装方案。

---

## 五、建议实施路径

在获得第四章的明确答复后，建议按以下顺序推进：

### 阶段一：跨平台兼容改造（**不依赖外部答复，可立即进行**）

1. 摘除 `pywin32`，改为平台条件依赖
2. 补充 `cryptography` 依赖
3. 编写 systemd unit 文件与 Bash 部署脚本
4. 验证 Windows 环境**不受影响**（回归测试）

> 此阶段改动约 2 行依赖声明 + 新增脚本文件，**可随时回滚**，且不改变 Windows 现有行为。完成后代码即为跨平台状态。

### 阶段二：本地虚拟机验证（**建议在自有电脑上进行**）

在个人电脑上用虚拟机安装目标发行版，验证：
- 后端能否正常启动（`serve.py`）
- 能否连接 MySQL 8（重点验证 `caching_sha2_password` 认证）
- 前端 `dist` 能否正常托管（单端口 + SPA 兜底路由）
- 三条核心链路：模型训练、在线推理、结果落库

**优势**：虚拟机支持快照，失败可一键回滚，不影响实验室现有系统。

### 阶段三：目标机器部署

虚拟机验证通过后，再在目标机器上实施。

> **不建议跳过阶段二直接操作实验室机器**——该机器目前承载着唯一可演示的 Windows 环境。

---

## 六、风险登记

| 编号 | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| R1 | 目标为 ARM64 架构 | TensorFlow 可能无对应 wheel，迁移受阻 | **优先确认架构**；若为 ARM，提前查证 TF 版本支持情况 |
| R2 | 离线环境依赖获取不全 | 安装中途失败 | 在联网机器上完整 `pip download`，并执行 `pip check` 验证依赖完整性 |
| R3 | MySQL 认证插件不匹配 | 连接失败，报错隐晦 | 提前补充 `cryptography`；如仍失败，可考虑将账号改为 `mysql_native_password` |
| R4 | 动实验室现有机器导致演示环境失效 | 影响交付 | **先备份 / 先做快照 / 阶段二先行**；保留 Windows 部署能力 |
| R5 | 系统 Python 版本过低 | 依赖安装失败 | 使用 `pyenv` 或独立安装 Python 3.12，不依赖系统 Python |
| R6 | 中文字符集问题 | 界面或日志乱码 | 建库时确认 `utf8mb4`；服务端设置 `LANG=zh_CN.UTF-8` 或 `en_US.UTF-8` |

---

## 七、需要向老师确认的问题清单

可直接使用以下四条提问：

1. **目标机器是不是学校/实验室另外提供的服务器？还是把现在实验室那台机器系统换掉？**
   —— 用于判断是否需要保留现有 Windows 环境。

2. **对 Linux 发行版有要求吗？比如 Ubuntu、CentOS，或者麒麟、统信这类国产系统？**
   —— 用于确定软件源与部署脚本写法。

3. **如果是国产服务器，CPU 是 x86 架构还是 ARM 架构？**
   —— 用于判断深度学习框架是否有可用安装包，这是最关键的一项。

4. **这台机器能连外网吗？如果不能，安装包可以通过优盘拷贝进去吗？**
   —— 用于确定是否需要制作约 630 MB 的 Linux 离线依赖包。

---

## 八、附录：本次评估的核查依据

| 结论 | 核查方式 |
|---|---|
| 路径处理跨平台 | 检索 `model_service/*.py`，确认使用 `pathlib`，未发现硬编码盘符 |
| `pywin32` 仅用于辅助脚本 | 全项目检索 `win32`，命中仅 `createdoc.py`（`win32com`）。另有一处 `api.py` 的 `_PACKAGES` 常量含该名称，但经核查仅为**自检页的包清单字符串**（`/health` 用于报告各包版本），并非 import，缺失时仅返回空值，无功能影响 |
| `createdoc.py` 不在运行链路 | 全项目检索 `createdoc`，无任何文件引用它 |
| 导入链无 Windows 依赖 | 检查 `main.py`、`serve.py` 的 import 语句 |
| `cryptography` 缺失 | `pip show PyMySQL` 显示 `Requires` 为空；`pip show cryptography` 无结果 |
| 依赖体积 | 统计 `offline_package/02-Python离线依赖`，88 个文件 / 629.8 MB |
| 前端无需重做 | `dist` 为静态文件，后端经 `web.py` 以静态资源方式托管 |

> **附：迁移后的自检手段**
> 后端 `GET /system` 接口会返回真实运行环境信息，**该接口无需登录**，可用于快速确认迁移结果：
>
> | 字段 | 含义 | 用途 |
> |---|---|---|
> | `runtime.machine` | CPU 架构 | **可直接验证 4.1 节的架构结论**（如 `AMD64` / `aarch64`） |
> | `runtime.platform` | 操作系统与版本 | 确认发行版信息 |
> | `runtime.python` | Python 版本 | 确认是否满足 3.12 要求 |
> | `database.ok` | 数据库连通性 | 排查认证插件问题 |
> | `packages` | 各依赖版本 | 未安装的包显示为空，可用于核对依赖完整性 |
>
> 迁移后在浏览器直接访问 `http://<目标IP>:5000/system` 即可对照检查。

---

## 九、版本记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-09-21 | 首版。基于当前代码与实际依赖清单核查结果编写 |

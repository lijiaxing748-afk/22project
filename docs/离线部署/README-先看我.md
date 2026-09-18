# 模型管理平台 · 离线部署包

> 把本平台安装到**不能上网的实验室电脑**上。
> 全部内容已打包好，用优盘搬过去即可。

**打包日期**：2026-09-16
**来源机器**：Windows 10/11 x64，Python 3.12.4，Node.js 18.20.4，MySQL 8.0.34
**包体积**：约 1.0 GB（不含下面第 1 项里需要你自己下的 3 个安装包）

---

## 我是老师/验收方，只想装起来 —— 三步走

假设你已经把整个文件夹拷到实验室电脑的 `D:\模型管理平台-离线部署包\`：

| 步骤 | 做什么 | 怎么触发 |
|---|---|---|
| **①** | 装基础软件 | 双击 `01-安装程序\` 里的 Python、Node.js、MySQL（**需先自己下载，见下**） |
| **②** | 装后端依赖 + 建库 | 依次运行 `06-部署脚本\run.bat 01`、`run.bat 02` |
| **③** | 建前端产物 | 在 `04-项目源码\frontend\22project` 执行 `npm run build -- --mode singleport` |
| **④** | 检查并装成服务 | 运行 `run.bat 03` 自检，再运行 `run.bat 05` 装成服务 |
| **⑤** | 打开使用 | 浏览器打开 http://localhost:8080，用 `admin` / `Admin@2026` 登录 |

> **`run.bat` 怎么用**：打开 `06-部署脚本` 文件夹，在地址栏输入 `cmd` 回车，
> 然后敲 `run.bat 01`。或者直接右键对应的 `.ps1` 文件选「使用 PowerShell 运行」。
> 参数就是 `00` ~ `06` 七个步骤号。不带参数会打印帮助。

> **装成服务之后，以后开机就是跑着的**，不用再做任何操作。
> 想手动管理：`net start ModelPlatform` / `net stop ModelPlatform`。

**详细步骤、截图说明、以及出问题怎么排查，看 `文档\离线部署手册.md`（或 .docx）。**

---

## ⚠️ 唯一需要你手动准备的东西

`01-安装程序\` 目录里需要放这三个安装包（我没法替你下载）：

| 软件 | 推荐版本 | 下载地址 |
|---|---|---|
| Python | 3.12.4 (64-bit installer) | https://www.python.org/downloads/release/python-3124/ |
| Node.js | 18.20.4 LTS (.msi x64) | https://nodejs.org/dist/v18.20.4/ |
| MySQL | 8.0.34 ZIP 免安装版 | https://dev.mysql.com/downloads/mysql/8.0.html |

> **装 Python 时务必勾选 `Add python.exe to PATH`**，这是最常见的坑。

放进去之后，运行 `06-部署脚本\run.bat 00` 可以自检是否齐全。

---

## 目录说明

```
模型管理平台-离线部署包\
│
├─ 01-安装程序\          ← 【需你放入】Python / Node.js / MySQL 三个安装包
│
├─ 02-Python离线依赖\     ← 86 个 .whl，629 MB（含 TensorFlow 351MB）
│   ├─ requirements-offline.txt   离线依赖清单（77 个正式包）
│   └─ *.whl
│
├─ 03-前端离线依赖\
│   └─ node_modules\      ← 45,304 个文件，641 MB
│                           需复制到 04-项目源码\frontend\22project\ 下
│
├─ 04-项目源码\
│   ├─ testRestfulProject\   后端（Flask）—— 故意不含 venv
│   ├─ frontend\22project\   前端（Vue3+Vite）—— 故意不含 node_modules
│   ├─ docs\                 平台说明书与截图
│   └─ 会议讨论说明\
│
├─ 05-数据库\
│   └─ 01-建库建表.sql       建库 + 8 张表（可重复执行）
│
├─ 06-部署脚本\
│   ├─ run.bat                  统一入口：run.bat 00 ~ 06（不带参数看帮助）
│   ├─ 00-check-package.ps1     打包自检（在联网电脑上先跑一次）
│   ├─ 01-install-backend.ps1   建 venv + 离线装 wheels
│   ├─ 02-init-database.ps1     建库 + 建表
│   ├─ 03-preflight-check.ps1   部署前自检
│   ├─ 04-start-system.ps1      开发模式启动（两个窗口，5000 + 8080）
│   ├─ 05-install-service.ps1   生产模式：装成 Windows 服务（★推荐★）
│   ├─ 06-uninstall-service.ps1 卸载服务（保留全部数据）
│   ├─ elevate.ps1              提权辅助（05/06 自动调用，不用手动跑）
│   └─ nssm\nssm.exe            ←【需你放入】服务包装工具，见下
│
└─ 文档\
    ├─ 离线部署手册.md / .docx            怎么部署（本任务的核心文档）
    ├─ 升级到单端口版-迁移指南.md          已装过旧版？看这个
    └─ 模型管理平台-系统使用说明书.docx    平台怎么用
```

---

## 还需要你放进去的一个小工具：nssm

只有装成 Windows 服务（`run.bat 05`）才需要它。

| 工具 | 说明 | 下载地址 |
|---|---|---|
| nssm | 约 300 KB，免安装绿色单文件 | https://nssm.cc/download |

下载后解压，把 `win64\nssm.exe` 放到 `06-部署脚本\nssm\nssm.exe`。

> **它是干什么的**：Windows 不能直接把一个 Python 程序"变成服务"，
> nssm 就是那层包装 —— 它负责在后台启动进程、开机自动拉起、
> 进程崩了自动重启、把输出重定向到日志文件。
>
> **不想用它也行**：用系统自带的 `sc.exe` 也能注册服务，
> 但不会在崩溃后自动重启，出问题时要人工发现。演示场景下建议还是用 nssm。

---

## 两个最容易踩的坑（先看，能省很多时间）

### 坑 1：不要直接复制 `venv`

很多人会想「把装好的 `venv` 整个拷过去」——**不行**。

`venv` 里的 `pyvenv.cfg` 和 `activate.bat` 写死了本机的 Python 路径，
而且 `venv\Scripts\python.exe` 只有 264 KB，只是个**指向本机解释器的跳板**。
换一台电脑后这个跳板找不到目标，直接报错。

**正确做法**：在实验室电脑上重新 `python -m venv venv`，
然后用我们打包好的 wheel 装（`run.bat 01` 就是干这个的）。

> 这也是为什么 `04-项目源码\testRestfulProject\` 里**没有** `venv` 目录 —— 是有意排除的。

### 坑 2：前端跑到了 5173 端口

前端的端口由 `.env.development` 里的 `VITE_PORT = 8080` 决定。
这一行如果缺失，Vite 会静默回落到默认的 5173，
于是「按文档打开 8080」必然连不上。

`run.bat 03` 会专门检查这一项。

---

## 平台启动后

| 地址 | 用途 |
|---|---|
| http://localhost:8080 | 平台（日常入口，**前端后端都在这个端口**） |
| http://localhost:8080/health | 健康检查（服务 + 数据库 + 模型产物） |
| http://localhost:8080/api | 全部接口索引 |

登录账号：

| 账号 | 口令 | 权限 |
|---|---|---|
| `admin` | `Admin@2026` | 全部（含用户管理与操作日志） |
| `engineer` | `Engineer@2026` | 训练、推理、发布；不含用户管理 |
| `operator` | `Operator@2026` | 只能浏览和推理；不能训练/发布/删除 |

> ⚠️ 这三个是**公开的演示口令**，正式使用前请登录后改掉（系统管理 → 修改密码）。
> 演示时可以分别登录，直观展示"不同角色看到的按钮不一样"。

> 局域网里别的电脑访问：把 `localhost` 换成这台机器的 IP
> （`ipconfig` 能看到，装服务脚本结束时会打印）。

---

## 本包已经过实测

打包时在**干净的新 venv** 里用 `pip install --no-index`（模拟完全断网）装了全部依赖，
并实际启动了后端、访问 `/health` 返回 200。因此到实验室电脑上照步骤做，是可复现的。

唯一与实测环境的差异是操作系统的补丁版本，通常无影响。

# 模型管理平台 · Linux 部署指南

> 版本：v1.0　编写日期：2026-09-21
> 适用系统：**Ubuntu 24.04 LTS**（x86_64）
> 对应文档：Windows 版见 `docs/离线部署/`；迁移评估见 `docs/Linux迁移可行性评估.md`

---

## 一、目标环境

| 项目 | 要求 | 说明 |
|---|---|---|
| 系统 | Ubuntu 24.04 LTS | 自带 Python 3.12，与开发环境一致 |
| 架构 | x86_64 / AMD64 | ARM64 需另评估（见评估文档第 4.1 节） |
| 内存 | ≥ 8 GB | TensorFlow + PyTorch 加载即需数 GB |
| 磁盘 | ≥ 40 GB | 依赖装完约 4～5 GB |
| 网络 | 可联网 | 离线部署需另行准备 wheel |

---

## 二、脚本清单

本目录下的脚本，与 Windows 版一一对应：

| 本目录（Linux） | 对应 Windows 版 | 作用 |
|---|---|---|
| `install-backend.sh` | `01-install-backend.ps1` | 建 venv、装依赖（含 torch 特殊处理） |
| `init-database.sh` | `02-init-database.ps1` | 建库建表 + 鉴权表迁移 |
| `install-service.sh` | `05-install-service.ps1` | 装 systemd 服务、开机自启、崩溃重启 |
| `uninstall-service.sh` | `06-uninstall-service.ps1` | 卸载服务 |
| `model-platform.service` | `nssm.exe` + nssm 配置 | systemd 单元模板（由安装脚本填充） |

> **不需要** `preflight-check`（检查环境）和 `check-package`（校验离线包），
> 因为 Linux 侧依赖用 `apt` 统一管理，版本问题比 Windows 少得多。
>
> **也不需要** `run.bat` 这类菜单脚本——Linux 上用 `systemctl` 一条命令即可。

---

## 三、部署步骤

### 步骤 0：准备系统

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip mysql-server mysql-client \
                    curl git
```

> 若数据库不在本机，`mysql-server` 可改为只装 `mysql-client`。

### 步骤 1：放置代码

#### 1.1 先认清两种目录布局

脚本**不写死后端目录名**，会自动在根目录下按顺序探测 `./`、`./backend`、
`./testRestfulProject`、`./dist/backend`，命中含 `serve.py` 的那层就用它。
所以下面两种布局都能直接跑，不用改脚本：

**布局 A —— 代码包（`make-linux-package.ps1` 打出的 tar.gz，解压后就是这样）**

```
model-platform/
├── backend/                     # ← 含 serve.py，脚本认这个
│   ├── serve.py
│   ├── requirements.txt
│   ├── model_service/
│   ├── sql/
│   ├── 1DCNN/  cwt_cnn/  adtk/
│   ├── data/
│   └── db.env                   # 需自行创建
├── frontend/dist/               # 前端构建产物
└── docs/Linux部署/              # 脚本本体
```

**布局 B —— 源码仓库（从 Git 克隆，含源代码与 `node_modules`）**

```
/opt/model-platform/
├── testRestfulProject/          # ← 含 serve.py，脚本认这个
│   ├── serve.py
│   ├── requirements.txt
│   ├── sql/
│   └── db.env                   # 需自行创建
└── frontend/22project/dist/     # 前端构建产物
```

> 两种布局的差别**只影响脚本能不能自动找到后端**。如果都不匹配（比如自定义
> 了目录名），用环境变量显式指定即可：
>
> ```bash
> MODEL_APP_DIR=/你的/路径/含serve.py的目录 bash install-backend.sh
> ```

> ⚠️ **前端 dist 可以复用 Windows 上构建好的那份**——它是纯静态文件，
> 与操作系统无关，Linux 上**不需要**装 Node.js 重新构建。

### 步骤 2：配置数据库连接

以下命令按**布局 A** 书写；若用布局 B，把 `backend` 换成 `testRestfulProject` 即可。

```bash
cd /opt/model-platform/backend
cp db.env.example db.env
nano db.env
```

至少确认这几项：

```ini
MODEL_DB_HOST=127.0.0.1
MODEL_DB_PORT=3306
MODEL_DB_USER=root
MODEL_DB_PASSWORD=你的密码
MODEL_DB_NAME=model_management

# ⚠️ 必须固定，否则每次重启服务所有用户都会掉线
MODEL_SECRET_KEY=用 python3 -c "import secrets;print(secrets.token_hex(32))" 生成
```

> ⚠️ **不要**把 `MODEL_BOOTSTRAP_ADMIN_PASSWORD` 留空交给默认口令。
> 默认三个账号（admin/engineer/operator）是**公开口令**，交付现场前必须改掉。

### 步骤 3：安装后端依赖

```bash
cd /opt/model-platform/docs/Linux部署
chmod +x *.sh
./install-backend.sh
```

脚本会：
1. 找到 Python 3.12
2. 创建 `testRestfulProject/venv`
3. **先单独装 torch**（从 PyTorch 官方 CPU 源）
4. 再装 `requirements.txt` 其余依赖
5. 校验关键依赖是否可导入

> **为什么 torch 要单独装**：`requirements.txt` 写的是 `torch==2.14.0+cpu`，
> 带 `+cpu` 后缀的包**不在 PyPI 上**，只在 PyTorch 官方索引里。
> 直接 `pip install -r requirements.txt` 必然报
> `No matching distribution found for torch==2.14.0+cpu`——这是**预期行为**。

### 步骤 4：初始化数据库

```bash
./init-database.sh
```

会交互式询问 MySQL 密码（不写入任何文件、不留 shell 历史），然后：
1. 应用 `sql/schema_mysql.sql`（11 张表）
2. 应用 `sql/auth-migration.sql`（鉴权表）
3. 逐张校验表是否就位

> **账号不由 SQL 创建**：admin / engineer / operator 是后端**首次启动**时
> 由 `bootstrap_users()` 自动建立的，口令取自 `db.env`。

### 步骤 5：安装为系统服务

```bash
sudo ./install-service.sh
```

会：生成 systemd 单元 → 设为开机自启 → 启动 → 探测 `/health` → 放行防火墙。

完成后浏览器访问 `http://<本机IP>:8080`。

---

## 四、日常运维

```bash
# 状态
sudo systemctl status model-platform

# 启动 / 停止 / 重启
sudo systemctl start   model-platform
sudo systemctl stop    model-platform
sudo systemctl restart model-platform

# 实时日志
sudo journalctl -u model-platform -f

# 最近 100 行
sudo journalctl -u model-platform -n 100

# 只看错误
sudo journalctl -u model-platform -p err
```

### 系统自检接口

```
http://<本机IP>:8080/system
```

无需登录，返回真实运行环境：

| 字段 | 用途 |
|---|---|
| `runtime.machine` | **确认 CPU 架构**（x86_64 / aarch64） |
| `runtime.platform` | 确认发行版 |
| `runtime.python` | 确认 Python 版本 |
| `database.ok` | 数据库连通性 |
| `packages` | 各依赖版本（未装为 null） |

---

## 五、与 Windows 版的差异说明

| 方面 | Windows | Linux |
|---|---|---|
| 后台运行 | nssm 包装为服务 | systemd 原生 |
| 日志 | nssm 落文件 + 10MB 轮转 | journald 自动管理 |
| 崩溃重启 | nssm `AppExit Default Restart` | systemd `Restart=always` |
| 开机自启 | nssm `SERVICE_AUTO_START` | `systemctl enable` |
| 防火墙 | `New-NetFirewallRule` | `ufw allow`（Ubuntu 默认未启用） |
| 路径写法 | `D:\...` | `/opt/...` |
| 时区 | 系统设置 | `timedatectl set-timezone Asia/Shanghai` |

### 遗留的 Windows 专属文件

以下文件在 Linux 上**不需要**，可保留但不参与运行：

- `docs/离线部署/部署脚本/*.ps1`、`run.bat`、`nssm/nssm.exe`
- `testRestfulProject/createdoc.py`（用 `win32com` 调用 Word，Windows 专用）

---

## 六、常见问题

### 现象：`RuntimeError: 'cryptography' package is required for caching_sha2_password`

**原因**：Linux 上 MySQL 8 默认认证插件是 `caching_sha2_password`，
PyMySQL 连它必须依赖 `cryptography` 包。

**解决**：该包已在 `requirements.txt` 中显式声明（2026-09-21 补入），
重跑 `./install-backend.sh` 即可。若仍缺失：

```bash
testRestfulProject/venv/bin/pip install cryptography
```

> 补充：也可把账号改为 `mysql_native_password`，但**不推荐**——
> 那是 MySQL 8 中已废弃的插件，且会降低安全性。

### 现象：`No matching distribution found for torch==2.14.0+cpu`

**原因**：带 `+cpu` 后缀的包不在 PyPI 上。

**解决**：先单独装 torch，`install-backend.sh` 已自动处理：

```bash
venv/bin/pip install torch==2.14.0+cpu --index-url https://download.pytorch.org/whl/cpu
```

### 现象：服务启动失败，日志显示找不到路径

**原因**：手工复制了 `model-platform.service` 到 `/etc/systemd/system/`，
导致 `__APP_DIR__` 这类占位符没有被替换。

**解决**：不要手工复制，用 `sudo ./install-service.sh` 安装。

### 现象：能连上但训练/推理很慢

**原因**：TensorFlow 的线程数默认会占满所有核；也可能是内存不足在 swap。

**排查**：
```bash
free -h                    # 看内存与 swap
top -o %MEM                # 看谁在吃内存
```

给虚拟机的内存不要低于 8 GB。

### 现象：中文文件名/日志乱码

**原因**：系统 locale 不是 UTF-8。

**解决**：
```bash
sudo locale-gen zh_CN.UTF-8
sudo timedatectl set-timezone Asia/Shanghai
```
systemd 单元里已设置 `LANG=zh_CN.UTF-8`，但系统需先安装该 locale。

### 现象：局域网其他电脑访问不了

**排查顺序**：
1. 服务是否监听 `0.0.0.0`：`sudo ss -ltnp | grep 8080`
2. 防火墙：`sudo ufw status`（若 active，需 `sudo ufw allow 8080/tcp`）
3. 本机自测：`curl http://127.0.0.1:8080/health`

---

## 七、离线部署（待补充）

若目标机器不能联网，需在联网机器上预先下载 Linux 版依赖：

```bash
pip download -r requirements.txt -d ./wheels
pip download torch==2.14.0+cpu --index-url https://download.pytorch.org/whl/cpu -d ./wheels
```

> ⚠️ **必须在与目标机器相同架构、相同 Python 版本的环境下下载**，
> 否则 wheel 不通用。Windows 版离线包（约 630 MB）**完全不能用于 Linux**。

这部分尚未实施，待确认目标环境后补充具体步骤。

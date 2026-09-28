# make-linux-package.ps1
# 用途：把项目核心内容打成一个 tar.gz，供 Linux 虚拟机 / 离线机部署使用。
# 排除 venv（Windows 二进制）、node_modules、__pycache__、测试残留、旧日志、db.env（含明文口令）。
#
# 用法（在仓库根 D:\HUAT\22project 下运行）：
#   powershell -ExecutionPolicy Bypass -File tools\make-linux-package.ps1
#
# 产物：dist-linux\model-platform-linux-<时间戳>.tar.gz
#       dist-linux\model-platform-linux-<时间戳>.manifest.txt  （清单，核对用）

if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) { $PSNativeCommandUseErrorActionPreference = $false }
$ErrorActionPreference = 'Continue'   # 不能 Stop：Stop 下原生命令的 stderr（如 sc.exe/nssm 的提示）会变成终止性错误、直接杀掉脚本
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot 'testRestfulProject'))) {
    $RepoRoot = (Get-Location).Path
}

$SrcRoot = Join-Path $RepoRoot 'testRestfulProject'
$OutDir  = Join-Path $RepoRoot 'dist-linux'
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

$Stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$StageName = "model-platform"
$StageDir  = Join-Path $env:TEMP "$StageName-$Stamp"
$TarName   = "model-platform-linux-$Stamp.tar.gz"
$TarPath   = Join-Path $OutDir $TarName

Write-Host "仓库根目录 : $RepoRoot"
Write-Host "后端源码   : $SrcRoot"
Write-Host "输出目录   : $OutDir"
Write-Host ""

# ---------- 1. 准备暂存目录 ----------
if (Test-Path $StageDir) { Remove-Item $StageDir -Recurse -Force }
New-Item -ItemType Directory -Path $StageDir | Out-Null

function Copy-Tree {
    param(
        [string]$From,
        [string]$To,
        [string[]]$ExcludeDirs  = @(),
        [string[]]$ExcludeFiles = @()
    )
    if (-not (Test-Path $From)) { Write-Host "  [跳过] 不存在：$From"; return }

    $robolog = @()
    $xd = @()
    foreach ($d in $ExcludeDirs)  { $xd += $d }
    $xf = @()
    foreach ($f in $ExcludeFiles) { $xf += $f }

    New-Item -ItemType Directory -Path $To -Force | Out-Null

    $args = @($From, $To, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
    if ($xd.Count -gt 0) { $args += '/XD'; $args += $xd }
    if ($xf.Count -gt 0) { $args += '/XF'; $args += $xf }

    & robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败（exit=$LASTEXITCODE）：$From -> $To" }
}

Write-Host "=== 1/3 复制后端与脚本 ==="
# 后端代码包
Copy-Tree -From (Join-Path $SrcRoot 'model_service') -To (Join-Path $StageDir 'backend/model_service') -ExcludeDirs @('__pycache__')
# 建库 SQL
Copy-Tree -From (Join-Path $SrcRoot 'sql')           -To (Join-Path $StageDir 'backend/sql')
# 运维脚本（重置口令等）
# ⚠️ 两个 Windows 专用的检查脚本不打进 Linux 包：它们硬编码 venv/Lib/site-packages（Windows 布局）
#    并用 ctypes.WinDLL / PE 解析，在 Linux 上必然报错，留在包里只会让人以为"包里的脚本坏了"。
Copy-Tree -From (Join-Path $SrcRoot 'tools')         -To (Join-Path $StageDir 'backend/tools') -ExcludeDirs @('__pycache__') -ExcludeFiles @('check-vcruntime.py','check-dll-deps.py')

# 入口文件
foreach ($f in @('serve.py','main.py','requirements.txt','db.env.example')) {
    $p = Join-Path $SrcRoot $f
    if (Test-Path $p) {
        Copy-Item $p (Join-Path $StageDir 'backend') -Force
        Write-Host "  [OK] backend/$f"
    } else {
        Write-Host "  [缺失] $f"
    }
}

Write-Host ""
Write-Host "=== 2/3 复制数据集 / 模型 / 前端产物 ==="
foreach ($d in @('1DCNN','cwt_cnn','adtk')) {
    Copy-Tree -From (Join-Path $SrcRoot $d) -To (Join-Path $StageDir "backend/$d") -ExcludeDirs @('__pycache__')
}
Write-Host "  [OK] 1DCNN / cwt_cnn / adtk（数据集与内置模型）"

# data 目录：保留 datasets/models/exports/figures，排除 logs 与 .cache
Copy-Tree -From (Join-Path $SrcRoot 'data') -To (Join-Path $StageDir 'backend/data') -ExcludeDirs @('logs','.cache','__pycache__')
Write-Host "  [OK] data（已排除 logs / .cache）"

# 前端产物
$Dist = Join-Path $RepoRoot 'frontend\22project\dist'
if (Test-Path (Join-Path $Dist 'index.html')) {
    Copy-Tree -From $Dist -To (Join-Path $StageDir 'frontend/dist')
    Write-Host "  [OK] frontend/dist"
} else {
    # ⚠️ 这里原先只打印"[缺失]"然后继续打包 —— 结果产出一个"没有前端"的包，装完访问只有说明页，
    #    而打包日志看起来是"完成"。缺前端就不该产出可交付的包，直接失败让人先构建。
    Write-Host "  [错误] 找不到前端产物：$Dist\index.html"
    Write-Host "         请先在 frontend\22project 下执行：npm run build:singleport（或 npm run build）"
    throw "打包中止：前端产物缺失（缺了它部署后访问首页只会看到说明页）"
}

# Linux 部署脚本与文档
$LinuxDocs = Join-Path $RepoRoot 'docs\Linux部署'
if (Test-Path $LinuxDocs) {
    Copy-Tree -From $LinuxDocs -To (Join-Path $StageDir 'docs/Linux部署')
    Write-Host "  [OK] docs/Linux部署"
}

# ---------- 2. 生成说明与清单 ----------
$Readme = @'
模型管理平台 —— Linux 部署包
================================================================

目录结构
--------
  backend/                  后端（Flask + waitress）
    model_service/          业务代码
    sql/                    建库脚本（schema_mysql.sql / auth-migration.sql）
    tools/                  运维脚本（重置口令等）
    1DCNN/ cwt_cnn/ adtk/   内置数据集与模型
    data/                   运行时数据（模型、数据集、导出、图表）
    serve.py                生产启动入口
    requirements.txt        Python 依赖
    db.env.example          配置模板（**需要自己复制成 db.env 并填值**）
  frontend/dist/            前端已构建产物（由后端单端口托管）
  docs/Linux部署/           部署脚本与说明

部署步骤（详见 docs/Linux部署/README-Linux部署.md）
--------
  1. 安装系统依赖：
       sudo apt update
       sudo apt install -y python3 python3-venv python3-pip mysql-server

  2. 初始化数据库：
       mysql -uroot -p < backend/sql/schema_mysql.sql
       mysql -uroot -p model_management < backend/sql/auth-migration.sql

  3. 配置：
       cp backend/db.env.example backend/db.env
       # 编辑 backend/db.env，填入 MySQL 口令
       # 并设置 MODEL_SECRET_KEY（否则每次重启用户都要重新登录）

  4. 安装后端依赖：
       cd backend && bash ../docs/Linux部署/install-backend.sh

  5. 注册开机自启服务：
       sudo bash docs/Linux部署/install-service.sh

  6. 浏览器访问：http://<本机IP>:8080
       （单端口：后端同时托管接口与前端。端口由 serve.py 的 --port / MODEL_PORT 决定，默认 8080）

初始账号
--------
  Users 表为空时，首次启动自动创建**两个**账号（只有两种身份：管理员 / 普通用户）：
    admin / Admin@2026      管理员（多两项权限：用户管理、查看操作日志）
    user  / User@2026       普通用户
  ⚠️ 早期的 engineer / operator 已废弃并归一到 user；老库里若还有这两个角色键，
     启动时会由 migrate_legacy_roles() 自动迁移。
  **交付现场前请至少修改 admin 口令**（或用 MODEL_BOOTSTRAP_ADMIN_PASSWORD 指定）。

注意
----
  * 本包**不含 venv**：依赖由 install-backend.sh 现装。
  * ⚠️ install-backend.sh 走的是**联网 pip**（torch 还需 download.pytorch.org）。纯离线目标机
    请自备 wheel 目录并改用 `pip install --no-index --find-links=<wheel目录> -r requirements.txt`
    （详见 docs/Linux部署/ 与 docs/离线部署/ 的说明）。
  * 本包**不含 db.env**（真实口令不进包），请从 db.env.example 复制。
  * 建库脚本里的库名写死为 `model_management`；若要用别的库名，请让
    docs/Linux部署/init-database.sh 执行（它会按 db.env 的 MODEL_DB_NAME 替换），
    或手工把 sql/schema_mysql.sql、sql/auth-migration.sql 里的库名改掉。
  * 前端已构建，无需在 Linux 上装 Node.js。
'@
Set-Content -Path (Join-Path $StageDir 'README-部署包说明.txt') -Value $Readme -Encoding UTF8

# 清单
$Manifest = @()
$Manifest += "生成时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$Manifest += "来源仓库: $RepoRoot"
$Manifest += ""
Get-ChildItem $StageDir -File -Recurse | ForEach-Object {
    $rel = $_.FullName.Substring($StageDir.Length + 1).Replace('\','/')
    $Manifest += ("{0,10}  {1}" -f $_.Length, $rel)
}
$ManifestPath = Join-Path $OutDir "model-platform-linux-$Stamp.manifest.txt"
Set-Content -Path $ManifestPath -Value $Manifest -Encoding UTF8

# ---------- 3. 打包 ----------
Write-Host ""
Write-Host "=== 3/3 打包 tar.gz ==="
if (Test-Path $TarPath) { Remove-Item $TarPath -Force }

$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path $tarExe)) { $tarExe = 'tar' }

Push-Location $StageDir
try {
    & $tarExe -czf $TarPath .
    if ($LASTEXITCODE -ne 0) { throw "tar 打包失败（exit=$LASTEXITCODE）" }
} finally {
    Pop-Location
}

Remove-Item $StageDir -Recurse -Force

$mb = [math]::Round((Get-Item $TarPath).Length / 1MB, 2)
$cnt = (Get-ChildItem $OutDir -Filter "model-platform-linux-$Stamp.manifest.txt" | Get-Content | Measure-Object -Line).Lines - 3

Write-Host ""
Write-Host "完成。"
Write-Host "  压缩包 : $TarPath"
Write-Host "  大小   : $mb MB"
Write-Host "  文件数 : $cnt"
Write-Host "  清单   : $ManifestPath"

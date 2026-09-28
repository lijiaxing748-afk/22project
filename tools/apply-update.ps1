# =====================================================================
#  应用代码更新（在**实验室电脑**上运行）
#
#  配合 tools\make-update-package.ps1 使用：
#      笔记本  -> 生成 code-update-<时间戳> 文件夹
#      优盘    -> 拷到实验室电脑
#      实验室  -> 运行本脚本，自动找到项目目录并覆盖代码
#
#  本脚本**只覆盖代码**，绝不动：
#      venv / node_modules / db.env / data\logs / 数据库
#
#  用法：
#      右键本文件 ->「使用 PowerShell 运行」
# =====================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "   [OK]   $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "   [提示] $m" -ForegroundColor Yellow }
function Err  ($m) { Write-Host "   [错误] $m" -ForegroundColor Red }

$Pkg = $PSScriptRoot

Say "============================================================"
Say "  应用代码更新"
Say "============================================================"
Say "  更新包: $Pkg"
Say ""

# ---------------------------------------------------------------- 1 找目标
Say "[1] 定位实验室电脑上的项目目录"

# 常见位置：优先读环境变量，其次猜几个常见路径
$candidates = @()
if ($env:MODEL_PLATFORM_DIR) { $candidates += $env:MODEL_PLATFORM_DIR }
$candidates += @(
    "D:\模型管理平台-离线部署包\04-项目源码",
    "D:\offline_package\04-项目源码",
    "C:\模型管理平台-离线部署包\04-项目源码",
    (Join-Path (Split-Path $Pkg -Parent) "04-项目源码")
)

$target = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path (Join-Path $c 'testRestfulProject'))) {
        $target = $c
        break
    }
}

if (-not $target) {
    Say "   自动查找没找到，请手动输入项目源码目录。"
    Say "   就是要包含 testRestfulProject 和 frontend 的那个目录，"
    Say "   例如： D:\模型管理平台-离线部署包\04-项目源码"
    Say ""
    $typed = Read-Host "   请粘贴路径（直接回车取消）"
    if ($typed -and (Test-Path (Join-Path $typed 'testRestfulProject'))) {
        $target = $typed
    } else {
        Err "路径无效，退出。"
        Read-Host "按回车退出"
        exit 1
    }
}
Ok "项目目录: $target"
Say ""

# ---------------------------------------------------------------- 2 检查服务
Say "[2] 检查服务是否已停止"
# ⚠️ 两种启动方式都要认：
#    · 生产模式 = Windows 服务 ModelPlatform（05-install-service.ps1 注册的，端口 8080）
#    · 开发模式 = 两个 PowerShell 窗口（main.py:5000 + vite:8080）
#    只探端口、不认服务的话，服务模式下会提示用户"去关那两个 PowerShell 窗口"（根本没有那两个窗口），
#    运维就卡在第一步（实测被指出过）。这里先处理服务，再兜底看端口。
$svcName = 'ModelPlatform'
$svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
$restartService = $false
if ($svc) {
    if ($svc.Status -ne 'Stopped') {
        Warn "检测到 Windows 服务 $svcName 正在运行（$($svc.Status)）。"
        $go = Read-Host "   现在停掉它并继续更新？输入 y 停止服务并继续，其他键退出"
        if ($go -ne 'y') { exit 0 }
        Stop-Service -Name $svcName -Force -ErrorAction SilentlyContinue
        try { (Get-Service $svcName).WaitForStatus('Stopped', '00:00:30') } catch { }
        Ok "服务 $svcName 已停止"
    } else {
        Ok "服务 $svcName 已停止"
    }
    # 更新完要把它拉起来（原来没有这一步，服务模式下更新完系统是停着的）
    $restartService = $true
} else {
    Say "   （本机没有注册 $svcName 服务 → 按开发模式处理）"
}

$busy = @()
foreach ($p in @(5000, 8080)) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    if ($c) { $busy += $p }
}
if ($busy.Count -gt 0) {
    Warn "端口 $($busy -join ', ') 还在监听 —— 还有进程在跑（开发模式下就是那两个 PowerShell 窗口）。"
    Warn "请先关掉它们，然后重新运行本脚本。"
    Say ""
    $go = Read-Host "   已经关了？输入 y 继续，其他键退出"
    if ($go -ne 'y') { exit 0 }
} else {
    Ok "5000 / 8080 都没在监听"
}
Say ""

# ---------------------------------------------------------------- 3 备份
Say "[3] 备份将被覆盖的代码"
$backup = Join-Path $target "..\_backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$backup = [System.IO.Path]::GetFullPath($backup)
New-Item -ItemType Directory -Force -Path $backup | Out-Null

$beSrc = Join-Path $Pkg 'testRestfulProject'
$feSrc = Join-Path $Pkg 'frontend\22project'

# 备份时只备份"会被覆盖的那些文件"，别把 venv / data 产物也复制一遍
# （那些几十 GB 的东西本来就不会被覆盖，备份它们是纯浪费）
$bakSkip = {
    param($full)
    $full -match '\\venv\\'           -or
    $full -match '\\node_modules\\'   -or
    $full -match '__pycache__'        -or
    $full -match '\\data\\logs\\'     -or
    $full -match '\\data\\figures\\'  -or
    $full -match '\\data\\tmp\\'      -or
    $full -match '\\data\\archive\\'  -or
    $full -match '\\data\\uploads\\'
}

function Backup-Dir {
    param($From, $To)
    if (-not (Test-Path $From)) { return 0 }
    $c = 0
    Get-ChildItem $From -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        if (& $bakSkip $_.FullName) { return }
        $rel = $_.FullName.Substring($From.Length).TrimStart('\')
        $dst = Join-Path $To $rel
        $d = Split-Path $dst -Parent
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        Copy-Item $_.FullName $dst -Force
        $c++
    }
    return $c
}

$n1 = Backup-Dir -From (Join-Path $target 'testRestfulProject') -To (Join-Path $backup 'testRestfulProject')
$n2 = Backup-Dir -From (Join-Path $target 'frontend\22project\src') -To (Join-Path $backup 'frontend-src')
# ⚠️ dist 也必须备份：更新会**覆盖** dist（见下面 Apply-Dir），而它由构建机产出、
#    目标机上没装 Node 重建 —— 不备份就等于"前端出问题回不去"，而脚本结尾却承诺可以回滚（实测被指出过）。
$n3 = Backup-Dir -From (Join-Path $target 'frontend\22project\dist') -To (Join-Path $backup 'frontend-dist')
Ok "已备份 $($n1 + $n2 + $n3) 个文件到:"
Say "       $backup"
Say ""

# ⚠️ 备份不再无限累积：每次更新都会新建一个 _backup-<时间戳>，目标机跑几次就堆一大堆。
#    保留最近 5 份（含刚建这份），更早的删掉并打印出来，别让磁盘悄悄被吃满。
$bakRoot = [System.IO.Path]::GetFullPath((Join-Path $target '..'))
$oldBaks = Get-ChildItem $bakRoot -Directory -Filter '_backup-*' -ErrorAction SilentlyContinue |
           Sort-Object Name -Descending | Select-Object -Skip 5
foreach ($b in $oldBaks) {
    try { Remove-Item $b.FullName -Recurse -Force; Say "   已清理旧备份：$($b.Name)" } catch { Warn "旧备份清理失败（可手工删）：$($b.FullName)" }
}
Say ""

# ---------------------------------------------------------------- 4 覆盖
Say "[4] 覆盖代码"

function Apply-Dir {
    param($From, $To, $SkipPattern)
    if (-not (Test-Path $From)) { return 0 }
    $c = 0
    Get-ChildItem $From -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $full = $_.FullName
        if ($SkipPattern -and $full -match $SkipPattern) { return }
        $rel = $full.Substring($From.Length).TrimStart('\')
        $dst = Join-Path $To $rel
        $d = Split-Path $dst -Parent
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        Copy-Item $full $dst -Force
        $c++
    }
    return $c
}

if (Test-Path $beSrc) {
    $n = Apply-Dir -From $beSrc -To (Join-Path $target 'testRestfulProject') `
                   -SkipPattern '\\venv\\|__pycache__|\.pyc$'
    Ok "后端覆盖 $n 个文件"
} else {
    Warn "更新包里没有后端代码，跳过"
}

if (Test-Path $feSrc) {
    # ⚠️ 这里原来还跳过 `\dist\`（SkipPattern 是 '\\node_modules\\|\\dist\\'）。
    #    当时的前提是"包里只有源码，dist 由实验室自己 build"——但实验室机器上
    #    **没有 Node.js 构建环境也能跑**（部署手册的生产模式就是直接托管 dist），
    #    于是前端修复永远覆盖不进去，表现为"代码明明改了、页面还是老样子"。
    #    现在打包脚本会把已构建好的 dist 一起带过来，所以这里必须放行 dist。
    #    仍然跳过 node_modules（几百 MB，且不需要重建）。
    $n = Apply-Dir -From $feSrc -To (Join-Path $target 'frontend\22project') `
                   -SkipPattern '\\node_modules\\'
    Ok "前端覆盖 $n 个文件"
    if (Test-Path (Join-Path $feSrc 'dist\index.html')) {
        Ok "前端构建产物 dist 已同步（浏览器请按 Ctrl+F5 强刷）"
    }
} else {
    Warn "更新包里没有前端代码，跳过"
}
Say ""

# ---------------------------------------------------------------- 5 完整性
Say "[5] 更新后完整性检查"
$problems = 0

$vpy = Join-Path $target 'testRestfulProject\venv\Scripts\python.exe'
if (Test-Path $vpy) {
    Ok "venv 还在（没被破坏）"
    # 试着 import 一下关键模块，看代码有没有语法错误
    Push-Location (Join-Path $target 'testRestfulProject')
    $r = & $vpy -c "from model_service import api, training, inference, registry; print('ok')" 2>&1
    Pop-Location
    if ($LASTEXITCODE -eq 0) {
        Ok "后端代码可正常导入（无语法错误）"
    } else {
        Err "后端代码导入失败，可能改坏了："
        $r | Select-Object -First 6 | ForEach-Object { Err "   $_" }
        Err "回滚办法：把备份目录 $backup 覆盖回去"
        $problems++
    }
} else {
    Err "venv 不见了！更新包可能覆盖错了目录"
    Err "请用备份回滚: $backup"
    $problems++
}

$dbEnv = Join-Path $target 'testRestfulProject\db.env'
if (Test-Path $dbEnv) {
    Ok "db.env 还在（数据库配置未被覆盖）"
} else {
    Warn "db.env 不见了 —— 需要手动重建（填入数据库账号密码）"
}

$nm = Join-Path $target 'frontend\22project\node_modules'
$feApplied = Test-Path $feSrc
if (-not $feApplied) {
    # 更新包里没有前端代码，就不用提 node_modules 的事
    Say "   （本次未更新前端，跳过 node_modules 检查）"
} elseif (Test-Path $nm) {
    Ok "node_modules 还在（前端依赖未被破坏）"
} else {
    Warn "node_modules 不见了 —— 需要重新复制前端依赖"
}
Say ""

# ---------------------------------------------------------------- 结果
Say "============================================================"
if ($problems -eq 0) {
    Say "  更新完成！" -ForegroundColor Green
    Say ""
    if ($restartService) {
        Say "  正在重新启动服务 $svcName ..."
        try { Start-Service -Name $svcName; Ok "服务 $svcName 已启动" }
        catch { Warn "服务启动失败，请手工执行：net start $svcName" }
    } else {
        Say "  下一步：运行 06-部署脚本\run.bat 04 重新启动系统（单端口模式用 run.bat 05 的服务）"
    }
    Say ""
    Say "  如果代码改动后行为异常，可以回滚（备份目录：$backup）："
    Say "    testRestfulProject\  → 覆盖回 $target\testRestfulProject"
    Say "    frontend-src\        → 覆盖回 $target\frontend\22project\src"
    Say "    frontend-dist\       → 覆盖回 $target\frontend\22project\dist"
} else {
    Say "  更新过程中发现 $problems 个问题，请看上面的 [错误]。" -ForegroundColor Red
    Say "  回滚：把 $backup 下的三个目录按上面列的一一对应覆盖回 $target。"
}
Say "============================================================"
Read-Host "按回车退出"

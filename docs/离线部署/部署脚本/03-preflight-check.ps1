# =====================================================================
#  03 - 部署前自检
#
#  作用：在正式启动前把常见的坑一次性排掉，
#        避免"网页打不开却不知道哪里错了"。
#  用法：右键 ->「使用 PowerShell 运行」
# =====================================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "   [OK]   $m" -ForegroundColor Green }
function Err  ($m) { Write-Host "   [错误] $m" -ForegroundColor Red }
function Warn ($m) { Write-Host "   [提示] $m" -ForegroundColor Yellow }

$Pkg = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Pkg '04-项目源码'))) { $Pkg = $PSScriptRoot }

$Src  = Join-Path $Pkg '04-项目源码\testRestfulProject'
$Fe   = Join-Path $Pkg '04-项目源码\frontend\22project'
$Venv = Join-Path $Src 'venv'

Say "============================================================"
Say "  步骤 3/4：部署前自检"
Say "============================================================"
Say ""

$problem = 0

# ---------------------------------------------------------------- 1 db.env
Say "[1] 数据库配置 db.env"
$dbEnv = Join-Path $Src 'db.env'
if (Test-Path $dbEnv) {
    Get-Content $dbEnv | ForEach-Object { Say "     $_" }
    $cfg = Get-Content $dbEnv -Raw
    if ($cfg -match 'MODEL_DB_DIALECT\s*=\s*mysql') {
        Ok "MODEL_DB_DIALECT = mysql"
    } else {
        Err "MODEL_DB_DIALECT 不是 mysql —— 本平台只连 MySQL"
        $problem++
    }
    if ($cfg -match 'MODEL_DB_PASSWORD\s*=\s*(\S+)') {
        Ok "密码已设置（$($Matches[1].Length) 个字符）"
    } else {
        Warn "MODEL_DB_PASSWORD 看起来是空的"
    }
} else {
    Err "缺少 $dbEnv"
    Err "请把 db.env.example 复制成 db.env，并填入数据库账号密码"
    $problem++
}
Say ""

# ---------------------------------------------------------------- 2 venv
Say "[2] Python 虚拟环境与依赖"
$vpy = Join-Path $Venv 'Scripts\python.exe'
if (Test-Path $vpy) {
    Ok "venv 存在"
    $mods = 'flask,pymysql,numpy,pandas,matplotlib,sklearn,statsmodels,tabulate'
    $r = & $vpy -c "import $mods; print('ok')" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Ok "基础依赖导入正常"
    } else {
        Err "基础依赖不完整，请重新运行 01-安装后端依赖.ps1"
        $r | ForEach-Object { Err "   $_" }
        $problem++
    }
    foreach ($m in @('tensorflow', 'torch')) {
        & $vpy -c "import $m" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok "$m 可用" }
        else { Err "$m 不可用（1DCNN/cwt_cnn 会跑不起来）"; $problem++ }
    }
} else {
    Err "未找到 venv —— 请先运行 01-安装后端依赖.ps1"
    $problem++
}
Say ""

# ---------------------------------------------------------------- 3 模型产物
Say "[3] 模型产物（推理必需）"
foreach ($m in @('1dcnn', 'cwt_cnn', 'adtk')) {
    $meta = Join-Path $Src "data\models\$m\meta.json"
    if (Test-Path $meta) { Ok "$m 产物存在" }
    else { Warn "$m 没有产物 —— 需要在平台「模型管理-训练」里训练一次" }
}
Say ""

# ---------------------------------------------------------------- 4 前端
Say "[4] 前端"
$nm = Join-Path $Fe 'node_modules'
if (Test-Path $nm) {
    $cnt = (Get-ChildItem $nm -Directory -ErrorAction SilentlyContinue).Count
    Ok "node_modules 存在（$cnt 个包）"
} else {
    Err "缺少 node_modules"
    Err "请把 03-前端离线依赖\node_modules 整个复制到："
    Err "   $Fe\"
    $problem++
}

$envDev = Join-Path $Fe '.env.development'
if (Test-Path $envDev) {
    $devTxt = Get-Content $envDev -Raw
    if ($devTxt -match 'VITE_PORT\s*=\s*8080') {
        Ok "VITE_PORT = 8080 已配置"
    } else {
        Err ".env.development 里没有 VITE_PORT = 8080"
        Err "缺这一行时前端会跑到 5173，按文档访问 8080 必然连不上"
        Err "请在 $envDev 里加一行：VITE_PORT = 8080"
        $problem++
    }
    if ($devTxt -match 'VITE_API_URL\s*=\s*[''""]?(http[^\s''""]+)') {
        Ok "VITE_API_URL = $($Matches[1])"
    }
} else {
    Err "缺少 $envDev"
    $problem++
}
Say ""

# ---------------------------------------------------------------- 5 Node
Say "[5] Node.js"
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    Ok "node $(& node -v)"
    Ok "npm  $(& npm -v)"
} else {
    Err "找不到 node 命令 —— 请先安装 Node.js（见 01-安装程序）"
    $problem++
}
Say ""

# ---------------------------------------------------------------- 6 MySQL 服务
Say "[6] MySQL 服务状态"
$svc = Get-Service -Name '*mysql*' -ErrorAction SilentlyContinue
if ($svc) {
    foreach ($s in $svc) {
        if ($s.Status -eq 'Running') { Ok "$($s.Name) 正在运行" }
        else { Err "$($s.Name) 状态是 $($s.Status) —— 需启动（管理员命令行: net start $($s.Name)）"; $problem++ }
    }
} else {
    Warn "没找到 MySQL 服务。若你用免安装版且未注册服务，可手动启动 mysqld"
}
Say ""

# ---------------------------------------------------------------- 7 端口
Say "[7] 端口占用检查"
foreach ($p in @(5000, 8080)) {
    $inUse = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    if ($inUse) { Warn "端口 $p 已被占用（可能服务已在运行，或与其他软件冲突）" }
    else { Ok "端口 $p 空闲" }
}
Say ""

# ---------------------------------------------------------------- 结论
Say "============================================================"
if ($problem -eq 0) {
    Say "  自检通过。接下来运行：04-启动系统.ps1" -ForegroundColor Green
} else {
    Say "  发现 $problem 个问题，请按上面的 [错误] 提示处理后再继续。" -ForegroundColor Red
}
Say "============================================================"
Read-Host "按回车退出"

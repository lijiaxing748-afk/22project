# =====================================================================
#  01 - 安装后端依赖（离线）
#
#  前提：已装好 Python 3.12.x，安装时勾选了 "Add python.exe to PATH"
#  用法：右键 ->「使用 PowerShell 运行」
#        （若提示脚本被禁止，用命令行执行：
#          powershell -ExecutionPolicy Bypass -File "本文件路径"）
# =====================================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "   [OK]   $m" -ForegroundColor Green }
function Err  ($m) { Write-Host "   [错误] $m" -ForegroundColor Red }
function Warn ($m) { Write-Host "   [警告] $m" -ForegroundColor Yellow }

$Pkg = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Pkg '04-项目源码'))) { $Pkg = $PSScriptRoot }

$Src    = Join-Path $Pkg '04-项目源码\testRestfulProject'
$WhlDir = Join-Path $Pkg '02-Python离线依赖'
$Venv   = Join-Path $Src 'venv'

Say "============================================================"
Say "  步骤 1/4：创建虚拟环境 + 安装后端依赖（离线）"
Say "============================================================"
Say "  包根目录 : $Pkg"
Say "  源码目录 : $Src"
Say "  wheel目录: $WhlDir"
Say ""

# ---------------------------------------------------------------- 前置检查
if (-not (Test-Path (Join-Path $Src 'main.py'))) {
    Err "找不到 $Src\main.py"
    Err "请确认没有移动或改名 04-项目源码 文件夹。"
    Read-Host "按回车退出"; exit 1
}
if (-not (Test-Path $WhlDir)) {
    Err "找不到 wheel 目录：$WhlDir"
    Read-Host "按回车退出"; exit 1
}

# ---------------------------------------------------------------- 找 Python
Say "[1/4] 检查 Python ..."
$python = $null
foreach ($cmd in @('python', 'py')) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source; break }
}
if (-not $python) {
    Err "系统里找不到 python 命令。"
    Err "请先安装 01-安装程序 里的 Python，安装时务必勾选"
    Err '"Add python.exe to PATH"，装完重开一个 PowerShell 再试。'
    Read-Host "按回车退出"; exit 1
}

$verOut = & $python --version 2>&1
Say "   $verOut"
Say "   路径: $python"

# 版本必须 3.12：本包里的 wheel 全是 cp312
if ($verOut -match '3\.(\d+)\.') {
    $minor = [int]$Matches[1]
    if ($minor -ne 12) {
        Warn "检测到 Python 3.$minor，但本包的 wheel 是为 Python 3.12 (cp312) 准备的。"
        Warn "继续下去大概率会报「找不到满足要求的版本」。"
        $ans = Read-Host "   仍要继续吗？(y/N)"
        if ($ans -ne 'y') { exit 1 }
    }
}
Say ""

# ---------------------------------------------------------------- 建 venv
Say "[2/4] 创建虚拟环境 ..."
if (Test-Path (Join-Path $Venv 'Scripts\python.exe')) {
    Ok "已存在 venv，跳过创建"
} else {
    & $python -m venv $Venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
        Err "创建虚拟环境失败。"
        Read-Host "按回车退出"; exit 1
    }
    Ok "venv 已创建: $Venv"
}
$vpy = Join-Path $Venv 'Scripts\python.exe'
Say ""

# ---------------------------------------------------------------- 装依赖
Say "[3/4] 安装依赖（约 2.6 GB，需要 5~10 分钟，请勿关闭窗口）..."
Say ""

# 先升级 pip（离线升，失败也不致命）
& $vpy -m pip install --no-index --find-links="$WhlDir" --upgrade pip 2>&1 |
    Where-Object { $_ -match 'Successfully|already satisfied|ERROR' } | ForEach-Object { Say "   $_" }

$reqFile = Join-Path $WhlDir 'requirements-offline.txt'
if (-not (Test-Path $reqFile)) {
    Err "找不到 $reqFile"
    Err "请确认 02-Python离线依赖 目录里有 requirements-offline.txt"
    Read-Host "按回车退出"; exit 1
}

Say ""
Say "   开始安装 76 个包 ...（下面的输出很长，最后会给出结论）"
Say ""

& $vpy -m pip install --no-index --find-links="$WhlDir" -r $reqFile 2>&1 |
    Tee-Object -Variable pipOut | Out-Null

# 只回显有意义的两类行：正在装谁、以及最终结论
$pipOut | Where-Object { $_ -match '^Successfully installed|^ERROR|error:' } | ForEach-Object {
    if ($_ -match '^Successfully') { Ok $_ } else { Err $_ }
}

if ($LASTEXITCODE -ne 0) {
    Say ""
    Err "依赖安装失败。常见原因："
    Err "   1) wheel 目录不完整 —— 从优盘完整重新复制一次；"
    Err "   2) Python 版本不是 3.12.x —— 本包 wheel 都是 cp312 的；"
    Err "   3) 磁盘空间不足 —— 需要至少 3 GB 空闲。"
    Read-Host "按回车退出"; exit 1
}
Say ""

# ---------------------------------------------------------------- 验证
Say "[4/4] 验证关键依赖 ..."
$checks = @(
    @{ n = 'Flask / PyMySQL / numpy / pandas / matplotlib / sklearn / statsmodels / tabulate';
       c = 'import flask, pymysql, numpy, pandas, matplotlib, sklearn, statsmodels, tabulate' },
    @{ n = 'torch';       c = 'import torch; print("      torch", torch.__version__)' },
    @{ n = 'tensorflow';  c = 'import tensorflow as tf; print("      tensorflow", tf.__version__)' }
)
$allOk = $true
foreach ($chk in $checks) {
    $r = & $vpy -c $chk.c 2>&1
    if ($LASTEXITCODE -eq 0) {
        Ok $chk.n
        $r | Where-Object { $_ -match '^\s+(torch|tensorflow)' } | ForEach-Object { Say $_ }
    } else {
        Err "$($chk.n) 导入失败"
        $allOk = $false
    }
}

Say ""
Say "============================================================"
if ($allOk) {
    Say "  步骤 1 完成。接下来运行：02-初始化数据库.ps1" -ForegroundColor Green
} else {
    Say "  有依赖导入失败，请把上面的报错发给维护者。" -ForegroundColor Red
}
Say "============================================================"
Read-Host "按回车退出"

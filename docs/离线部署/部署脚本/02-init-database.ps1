# =====================================================================
#  02 - 初始化 MySQL 数据库（建库 + 建表）
#
#  前提：MySQL 服务已启动；账号密码与 testRestfulProject\db.env 一致
#  用法：右键 ->「使用 PowerShell 运行」
# =====================================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "   [OK]   $m" -ForegroundColor Green }
function Err  ($m) { Write-Host "   [错误] $m" -ForegroundColor Red }
function Warn ($m) { Write-Host "   [警告] $m" -ForegroundColor Yellow }

$Pkg = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Pkg '04-项目源码'))) { $Pkg = $PSScriptRoot }

$SqlFile = Join-Path $Pkg '05-数据库\01-建库建表.sql'
$DbEnv   = Join-Path $Pkg '04-项目源码\testRestfulProject\db.env'

Say "============================================================"
Say "  步骤 2/4：初始化数据库 model_management"
Say "============================================================"
Say ""

if (-not (Test-Path $SqlFile)) {
    Err "找不到建表脚本：$SqlFile"
    Read-Host "按回车退出"; exit 1
}

# ---------------------------------------------------------------- 找 mysql.exe
Say "[1] 定位 mysql 客户端 ..."
$mysqlExe = (Get-Command mysql -ErrorAction SilentlyContinue).Source

if (-not $mysqlExe) {
    $cands = @(
        'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
        'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe'
        'C:\Program Files\MySQL\MySQL Server 9.0\bin\mysql.exe'
        'D:\mysql\bin\mysql.exe'
        'D:\mysql-8.0.34\bin\mysql.exe'
    )
    # 再扫一遍常见盘的顶层目录，找 mysql* 文件夹
    foreach ($root in @('C:\', 'D:\')) {
        Get-ChildItem $root -Directory -Filter 'mysql*' -ErrorAction SilentlyContinue | ForEach-Object {
            $try = Join-Path $_.FullName 'bin\mysql.exe'
            if (Test-Path $try) { $cands += $try }
            $try2 = Join-Path $_.FullName 'mysql-8.0.34-winx64\bin\mysql.exe'
            if (Test-Path $try2) { $cands += $try2 }
        }
    }
    $mysqlExe = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $mysqlExe) {
    Err "找不到 mysql.exe。"
    Err "解决办法（任选其一）："
    Err "  1) 把 MySQL 的 bin 目录加入系统 PATH 后重开窗口；"
    Err "  2) 手工用 Navicat / MySQL Workbench 执行："
    Err "     $SqlFile"
    Read-Host "按回车退出"; exit 1
}
Ok "使用 $mysqlExe"
Say ""

# ---------------------------------------------------------------- 读 db.env 作为默认值
$defUser = 'root'
$defPass = '1006'
$defHost = '127.0.0.1'
$defPort = '3306'
if (Test-Path $DbEnv) {
    Get-Content $DbEnv | ForEach-Object {
        if ($_ -match '^\s*MODEL_DB_USER\s*=\s*(.+?)\s*$')     { $defUser = $Matches[1] }
        if ($_ -match '^\s*MODEL_DB_PASSWORD\s*=\s*(.+?)\s*$') { $defPass = $Matches[1] }
        if ($_ -match '^\s*MODEL_DB_HOST\s*=\s*(.+?)\s*$')     { $defHost = $Matches[1] }
        if ($_ -match '^\s*MODEL_DB_PORT\s*=\s*(.+?)\s*$')     { $defPort = $Matches[1] }
    }
    Say "   已从 db.env 读到默认连接信息（主机 $defHost : $defPort，账号 $defUser）"
}
Say ""

# ---------------------------------------------------------------- 询问连接信息
Say "[2] 确认 MySQL 连接信息（直接回车用方括号里的默认值）"
$inUser = Read-Host "   MySQL 账号 [$defUser]"
if ([string]::IsNullOrWhiteSpace($inUser)) { $inUser = $defUser }

$inPass = Read-Host "   MySQL 密码 [$defPass]"
if ([string]::IsNullOrWhiteSpace($inPass)) { $inPass = $defPass }

$inHost = Read-Host "   主机 [$defHost]"
if ([string]::IsNullOrWhiteSpace($inHost)) { $inHost = $defHost }

$inPort = Read-Host "   端口 [$defPort]"
if ([string]::IsNullOrWhiteSpace($inPort)) { $inPort = $defPort }
Say ""

# ---------------------------------------------------------------- 测试连通性
Say "[3] 测试连接 ..."
$testArgs = @(
    "-h", $inHost, "-P", $inPort, "-u", $inUser, "-p$inPass",
    "--ssl-mode=DISABLED", "-e", "SELECT VERSION();"
)
$testOut = & $mysqlExe @testArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    Err "连接 MySQL 失败："
    $testOut | ForEach-Object { Err "   $_" }
    Say ""
    Err "常见原因："
    Err "   1) MySQL 服务没启动 —— 到「服务」里启动 MySQL，或管理员命令行执行 net start MySQL"
    Err "   2) 账号或密码不对"
    Err "   3) 端口不是 $inPort —— 检查 MySQL 的 my.ini"
    Read-Host "按回车退出"; exit 1
}
Ok "连接成功：$($testOut -join ' ')"
Say ""

# ---------------------------------------------------------------- 执行建表
Say "[4] 执行建库建表脚本 ..."
Say "    脚本: $SqlFile"

# 用 cmd 的输入重定向把 sql 喂给 mysql（PowerShell 的 < 不支持）
$execArgs = @(
    "-h", $inHost, "-P", $inPort, "-u", $inUser, "-p$inPass",
    "--default-character-set=utf8mb4", "--ssl-mode=DISABLED"
)
$sqlText = Get-Content $SqlFile -Raw -Encoding UTF8
$sqlText | & $mysqlExe @execArgs 2>&1 | ForEach-Object {
    if ($_ -match 'ERROR') { Err $_ } else { Say "   $_" }
}

if ($LASTEXITCODE -ne 0) {
    Err "建库建表失败。也可以手工执行：把 $SqlFile 拖进 Navicat 里运行。"
    Read-Host "按回车退出"; exit 1
}
Ok "脚本执行完成"
Say ""

# ---------------------------------------------------------------- 校验
Say "[5] 校验表结构 ..."
$showArgs = @(
    "-h", $inHost, "-P", $inPort, "-u", $inUser, "-p$inPass",
    "--ssl-mode=DISABLED", "-e", "USE model_management; SHOW TABLES;"
)
$tables = & $mysqlExe @showArgs 2>&1
$tables | ForEach-Object { Say "   $_" }

$expect = @('Datasets','Models','EdgeDevices','Trainings','ModelInvocations',
            'ModelDeployments','InferenceTasks','InferenceResults')
$missing = $expect | Where-Object { $tables -notcontains $_ }
Say ""
if ($missing.Count -eq 0) {
    Ok "8 张表全部就位"
    Say ""
    Say "============================================================"
    Say "  步骤 2 完成。接下来运行：03-检查配置.ps1" -ForegroundColor Green
    Say "============================================================"
} else {
    Err "缺少这些表：$($missing -join ', ')"
}
Read-Host "按回车退出"

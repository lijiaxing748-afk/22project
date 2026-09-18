# =====================================================================
#  00 - 打包完整性自检
#
#  在"有网的电脑"上、准备把优盘送去实验室之前运行。
#  目的：提前发现缺文件，免得跑到离线电脑上才发现又要跑回来拷。
#
#  用法：
#    右键本文件 ->「使用 PowerShell 运行」
#    或者命令行：  powershell -ExecutionPolicy Bypass -File "本文件路径"
#
#  注：为什么用 .ps1 而不是 .bat —— 见《离线部署手册》附录 C。
#      简单说：cmd.exe 只认 GBK，写中文批处理极易乱码且难排查；
#      PowerShell 原生支持 UTF-8，稳得多。
# =====================================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say    ($m) { Write-Host $m }
function Ok     ($m) { Write-Host "   [OK]   $m"   -ForegroundColor Green }
function Miss   ($m) { Write-Host "   [缺失] $m"   -ForegroundColor Red }
function Warn   ($m) { Write-Host "   [提示] $m"   -ForegroundColor Yellow }

# --- 定位包根目录（本脚本在 06-部署脚本\ 下，上一级即根）---
$Pkg = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Pkg '04-项目源码'))) {
    # 兼容"脚本被单独拷出来"的情况：以脚本所在目录为根
    $Pkg = $PSScriptRoot
}

Say "============================================================"
Say "  离线部署包 · 完整性自检"
Say "============================================================"
Say "  包位置: $Pkg"
Say ""

$problem = 0
$warn = 0

# ---------------------------------------------------------------- 1
Say "[1] 部署脚本"
$scripts = @(
    '00-check-package.ps1'
    '01-install-backend.ps1'
    '02-init-database.ps1'
    '03-preflight-check.ps1'
    '04-start-system.ps1'
    '05-install-service.ps1'      # 装成 Windows 服务（生产模式）
    '06-uninstall-service.ps1'
    'elevate.ps1'                 # 05/06 的提权辅助
    '90-build-update-package.ps1' # 打代码更新包
    '91-apply-update.ps1'         # 应用代码更新包
    'run.bat'
)
foreach ($s in $scripts) {
    if (Test-Path (Join-Path $Pkg "06-部署脚本\$s")) { Ok $s } else { Miss "06-部署脚本\$s"; $problem++ }
}
Say ""

# ---------------------------------------------------------------- 2
Say "[2] Python 离线依赖"
$whlDir = Join-Path $Pkg '02-Python离线依赖'
if (Test-Path $whlDir) {
    $whls = Get-ChildItem $whlDir -Filter '*.whl' -File -ErrorAction SilentlyContinue
    Say "   wheel 文件数: $($whls.Count)"
    if ($whls.Count -lt 70) { Warn "数量偏少（预期 74 个左右）"; $warn++ }

    # 逐个确认关键包（用 -like 匹配，避免版本号写死）
    $need = @{
        'tensorflow'    = 'tensorflow*'
        'torch'         = 'torch-*'
        'numpy'         = 'numpy*'
        'scipy'         = 'scipy*'
        'pandas'        = 'pandas*'
        'matplotlib'    = 'matplotlib*'
        'scikit-learn'  = 'scikit_learn*'
        'statsmodels'   = 'statsmodels*'
        'tabulate'      = 'tabulate*'
        'Flask'         = 'flask-*'
        'PyMySQL'       = 'pymysql*'
        'keras'         = 'keras-*'
        # 生产 WSGI 服务器（serve.py 用；纯 Python，Windows 免编译）
        'waitress'      = 'waitress*'
    }
    foreach ($k in $need.Keys | Sort-Object) {
        $hit = Get-ChildItem $whlDir -Filter $need[$k] -File -ErrorAction SilentlyContinue
        if ($hit) { Ok $k } else { Miss "$k  (匹配 $($need[$k]))"; $problem++ }
    }

    if (Test-Path (Join-Path $whlDir 'requirements-offline.txt')) {
        Ok 'requirements-offline.txt'
    } else {
        Miss 'requirements-offline.txt'
        $problem++
    }
} else {
    Miss "整个目录不存在：$whlDir"
    $problem++
}
Say ""

# ---------------------------------------------------------------- 3
Say "[3] 前端离线依赖"
$nm = Join-Path $Pkg '03-前端离线依赖\node_modules'
foreach ($pkgName in @('vite', 'vue', 'element-plus', 'axios')) {
    if (Test-Path (Join-Path $nm $pkgName)) { Ok "node_modules\$pkgName" }
    else { Miss "node_modules\$pkgName"; $problem++ }
}
Say ""

# ---------------------------------------------------------------- 4
Say "[4] 项目源码"
$src = Join-Path $Pkg '04-项目源码'
$must = @(
    'testRestfulProject\main.py'
    'testRestfulProject\requirements.txt'
    'testRestfulProject\db.env'
    'testRestfulProject\data\models\1dcnn\model.keras'
    'testRestfulProject\data\models\adtk\detector.pkl'
    'testRestfulProject\sql\schema_mysql.sql'
    'frontend\22project\package.json'
    'frontend\22project\.env.development'
)
foreach ($f in $must) {
    if (Test-Path (Join-Path $src $f)) { Ok $f } else { Miss $f; $problem++ }
}
# venv 不该被打进去
if (Test-Path (Join-Path $src 'testRestfulProject\venv')) {
    Warn '源码里含 venv —— 不该带（换机器会坏），请删除'
    $warn++
} else {
    Ok '源码不含 venv（正确）'
}
Say ""

# ---------------------------------------------------------------- 5
Say "[5] 数据库脚本"
$sql = Join-Path $Pkg '05-数据库\01-建库建表.sql'
if (Test-Path $sql) {
    Ok '01-建库建表.sql'
    $txt = Get-Content $sql -Raw -Encoding UTF8
    if ($txt -match 'CREATE DATABASE') { Ok '含 CREATE DATABASE（可独立建库）' }
    else { Warn '脚本里没有 CREATE DATABASE' }
    if ($txt -match 'CREATE TABLE') { Ok '含 CREATE TABLE' } else { Warn '脚本里没有 CREATE TABLE' }
    # ⚠️ 鉴权三表必须在这个脚本里，否则装出来的库登录会直接报错
    #    （dvadmin.login 一查 Users 表就 Table doesn't exist）
    foreach ($t in @('`Users`', '`Roles`', '`OperationLogs`')) {
        if ($txt -match [regex]::Escape($t)) { Ok "含鉴权表 $t" }
        else { Miss "缺少鉴权表 $t（登录会报 Table doesn't exist）"; $problem++ }
    }
} else {
    Miss '05-数据库\01-建库建表.sql'
    $problem++
}

# 旧库升级要用的增量脚本。**缺了不算致命**（后端 ensure_schema 会自动补），
# 但交付时应该带上，免得人工在旧库上跑全量脚本心里没底。
$mig = Join-Path $Pkg '05-数据库\02-鉴权迁移-旧库升级用.sql'
if (Test-Path $mig) { Ok '02-鉴权迁移-旧库升级用.sql（旧库升级用）' }
else { Warn '没有 02-鉴权迁移-旧库升级用.sql（只影响旧库升级，新装不受影响）' }
Say ""

# ---------------------------------------------------------------- 6
Say "[6] 安装程序（这三个需要手动下载放入）"
$inst = Join-Path $Pkg '01-安装程序'
$found = 0
$checks = @(
    @{ n = 'Python 安装包';  pat = 'python*.exe' },
    @{ n = 'Node.js 安装包'; pat = 'node*.msi'   },
    @{ n = 'MySQL 安装包';   pat = '*mysql*.zip' }
)
foreach ($c in $checks) {
    if (Test-Path $inst) {
        $hit = Get-ChildItem $inst -Filter $c.pat -File -ErrorAction SilentlyContinue
    } else { $hit = $null }
    if ($hit) { Ok "$($c.n)  ->  $($hit[0].Name)"; $found++ }
    else      { Warn "$($c.n) 未放入" }
}
if ($found -lt 3) {
    Warn "还差 $((3 - $found)) 个（共需 3 个）。下载地址见《离线部署手册》1.1 节"
    $warn++
}
Say ""

# ---------------------------------------------------------------- 7
Say "[7] 包体积统计"
$files = Get-ChildItem $Pkg -Recurse -File -ErrorAction SilentlyContinue
$totalMB = [math]::Round((($files | Measure-Object -Property Length -Sum).Sum / 1MB), 0)
Say "   文件总数: $($files.Count)"
Say "   总体积  : $totalMB MB"
Say ""

# ---------------------------------------------------------------- 结论
Say "============================================================"
if ($problem -eq 0) {
    Say "  结论：必需文件齐全，可以拷到优盘送去实验室了。" -ForegroundColor Green
    if ($warn -gt 0) { Warn "还有 $warn 项提醒，见上面的 [提示]" }
} else {
    Say "  结论：发现 $problem 个必需文件缺失，请补齐后再拷贝。" -ForegroundColor Red
}
Say "============================================================"
Say ""
Read-Host "按回车键退出"

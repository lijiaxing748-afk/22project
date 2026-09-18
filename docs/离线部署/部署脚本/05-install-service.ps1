# =====================================================================
#  05 - 安装为 Windows 服务（后台运行 / 开机自启 / 崩溃自动重启）
#
#  做完这一步，系统就从「要开一个黑窗口、关了窗口服务就停」
#  变成「开机自动运行，浏览器输 IP 就能用」。
#
#  用法：右键 ->「使用 PowerShell 运行」   （需要**管理员**权限）
#
#  ⚠️ 前置条件：
#     1. 已经跑过 01-install-backend.ps1（venv 建好、依赖装好）
#     2. 已经跑过 02-init-database.ps1（库和表建好）
#     3. 已执行过前端构建（frontend\22project 下执行 npm run build）
#        否则服务起来了但打开是「后端已启动，但还没有前端页面」
#     4. 把 06-工具\nssm\nssm.exe 放进本脚本同级的 nssm\ 目录
#        （nssm 是绿色免安装的单文件工具，见下方说明）
# =====================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "   [OK]   $m" -ForegroundColor Green }
function Err  ($m) { Write-Host "   [错误] $m" -ForegroundColor Red }
function Warn ($m) { Write-Host "   [提示] $m" -ForegroundColor Yellow }
function Info ($m) { Write-Host "   [信息] $m" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 配置
$ServiceName = 'ModelPlatform'
$DisplayName = '模型管理平台'
$Description = '模型管理平台（Flask + waitress）。前端由后端同端口托管，浏览器访问本机 8080 端口。'

$Pkg = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Pkg '04-项目源码'))) { $Pkg = $PSScriptRoot }
$Src  = Join-Path $Pkg '04-项目源码\testRestfulProject'
$Venv = Join-Path $Src 'venv'
$vpy  = Join-Path $Venv 'Scripts\python.exe'
$Nssm = Join-Path $PSScriptRoot 'nssm\nssm.exe'

Say "============================================================"
Say "  步骤 5：把平台安装为 Windows 服务"
Say "============================================================"
Say ""

# ---------------------------------------------------------------- 管理员检查
$isAdmin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Err "本脚本必须以**管理员**身份运行（安装/启动服务需要提权）。"
    Err "做法：右键 PowerShell ->「以管理员身份运行」，再执行本脚本。"
    Read-Host "按回车退出"; exit 1
}
Ok "已获得管理员权限"

# ---------------------------------------------------------------- 前置检查
if (-not (Test-Path $vpy)) {
    Err "没找到 venv：$vpy"
    Err "请先运行 01-install-backend.ps1"
    Read-Host "按回车退出"; exit 1
}
Ok "找到 Python 虚拟环境"

$ServePy = Join-Path $Src 'serve.py'
if (-not (Test-Path $ServePy)) {
    Err "没找到 serve.py：$ServePy"
    Err "请确认 04-项目源码 是最新版本（服务模式靠 serve.py 启动）"
    Read-Host "按回车退出"; exit 1
}
Ok "找到生产启动脚本 serve.py"

if (-not (Test-Path $Nssm)) {
    Err "没找到 nssm.exe：$Nssm"
    Say ""
    Info "nssm 是一个免费的 Windows 服务包装工具（单文件、免安装、绿色）。"
    Info "获取方式（在能上网的电脑上下载，再拷过来）："
    Info "    https://nssm.cc/download    -> 解压 -> win64\nssm.exe"
    Info "把它复制到： $PSScriptRoot\nssm\nssm.exe"
    Say ""
    Warn "如果实在拿不到 nssm，也可以用 Windows 自带的 sc.exe 注册："
    Warn "    sc.exe create $ServiceName binPath= \"`\"$Nssm`\" $ServePy\" start= auto"
    Warn "但 sc.exe 不会在崩溃后自动重启，也不方便改工作目录，所以首选 nssm。"
    Read-Host "按回车退出"; exit 1
}
Ok "找到 nssm.exe"

if (-not (Test-Path (Join-Path $Src 'db.env'))) {
    Warn "没有找到 db.env —— 服务启动后会连不上数据库。"
    Warn "请把 04-项目源码\testRestfulProject\db.env.example 复制为 db.env 并填好连接信息。"
}

# ---------------------------------------------------------------- 端口占用检查
$port = 8080
$busy = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($busy) {
    $owner = Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue
    Warn "端口 $port 已被占用：$($owner.ProcessName) (PID=$($busy[0].OwningProcess))"
    Warn "服务虽然能装，但启动时会因端口冲突失败。"
    Warn "多半是你之前手动开着的服务 —— 先关掉它，或改 serve.py 的 --port。"
    if ((Read-Host "仍要继续安装？(y/N)") -ne 'y') { exit 1 }
}

# ---------------------------------------------------------------- 处理已存在的服务
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Warn "服务 $ServiceName 已存在（状态：$($existing.Status)）"
    $ans = Read-Host "要覆盖重装吗？会先停止并删除旧服务 (y/N)"
    if ($ans -ne 'y') { Info "已取消。"; exit 0 }
    if ($existing.Status -eq 'Running') {
        Info "停止旧服务 ..."
        & $Nssm stop $ServiceName | Out-Null
        Start-Sleep -Seconds 3
    }
    Info "删除旧服务 ..."
    & $Nssm remove $ServiceName confirm | Out-Null
    Start-Sleep -Seconds 2
    Ok "旧服务已清除"
}

# ---------------------------------------------------------------- 安装
Say ""
Say "[1/4] 注册服务 ..."
& $Nssm install $ServiceName $vpy | Out-Null
Ok "已注册：$ServiceName"

Say "[2/4] 配置启动参数 ..."
# ⚠️ AppDirectory 必须显式设成项目根：不设的话服务工作目录是 system32，
#    serve.py 里虽然加了 sys.path，但 db.env 是按相对路径找的，会读不到。
& $Nssm set $ServiceName AppDirectory $Src | Out-Null
& $Nssm set $ServiceName AppParameters 'serve.py --host 0.0.0.0 --port 8080 --threads 4' | Out-Null
& $Nssm set $ServiceName DisplayName $DisplayName | Out-Null
& $Nssm set $ServiceName Description $Description | Out-Null
& $Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
Ok "已配置（0.0.0.0:8080，4 线程，开机自启）"

Say "[3/4] 配置日志与崩溃重启 ..."
# ⚠️ 把 stdout/stderr 落到文件，否则服务在后台跑、报错全丢了，
#    出问题时会完全没有线索（比"能看到的报错"难查得多）。
$logDir = Join-Path $Src 'data\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
& $Nssm set $ServiceName AppStdout (Join-Path $logDir 'service-out.log') | Out-Null
& $Nssm set $ServiceName AppStderr (Join-Path $logDir 'service-err.log') | Out-Null
# 日志按大小轮转，避免跑几个月后把磁盘写满
& $Nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $Nssm set $ServiceName AppRotateOnline 1 | Out-Null
& $Nssm set $ServiceName AppRotateBytes 10485760 | Out-Null   # 10 MB 一个文件
# 崩溃自动重启：15 秒后拉起，启动失败也算（训练崩了不该让整个平台停摆）
& $Nssm set $ServiceName AppExit Default Restart | Out-Null
& $Nssm set $ServiceName AppRestartDelay 15000 | Out-Null
# 给足优雅退出时间：正在跑的推理/训练请求不该被立刻砍断
& $Nssm set $ServiceName AppStopMethodConsole 10000 | Out-Null
Ok "已配置（日志轮转 + 崩溃自动重启 + 15 秒延迟）"

Say "[4/4] 启动服务 ..."
& $Nssm start $ServiceName | Out-Null
Start-Sleep -Seconds 8

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq 'Running') {
    Ok "服务正在运行"
} else {
    Err "服务没有跑起来（状态：$($svc.Status)）"
    Err "去看日志：$logDir\service-err.log"
    Read-Host "按回车退出"; exit 1
}

# ---------------------------------------------------------------- 就绪探测
Say ""
Say "等待服务响应 /health ..."
$ready = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/health' -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if ($ready) {
    Ok "服务已响应 /health"
} else {
    Warn "45 秒内没等到响应。最可能的原因："
    Warn "  1) db.env 里的数据库连接信息不对 -> 看 $logDir\service-err.log"
    Warn "  2) 8080 端口被别的程序占用"
}

# ---------------------------------------------------------------- 本机 IP 提示
Say ""
Say "============================================================"
Say "  安装完成"
Say "============================================================"
$ips = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -ExpandProperty IPAddress)
Say ""
Say "  本机访问：  http://localhost:8080"
if ($ips) {
    Say "  局域网访问："
    foreach ($ip in $ips) { Say "      http://${ip}:8080" }
    Say ""
    Say "  ⚠️ 别的电脑连不上时，先检查防火墙是否放行了 8080："
    Say "     本脚本已尝试自动放行；若仍不通，手动执行："
    Say "     New-NetFirewallRule -DisplayName '模型管理平台' -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow"
} else {
    Warn "没探测到局域网 IP —— 这台机器可能没连网线。"
}
Say ""
Say "  常用服务命令（在管理员 PowerShell 里）："
Say "     启动： net start $ServiceName     或  nssm start $ServiceName"
Say "     停止： net stop  $ServiceName     或  nssm stop  $ServiceName"
Say "     重启： Restart-Service $ServiceName"
Say "     看日志： Get-Content '$logDir\service-err.log' -Tail 50"
Say "     卸载： 运行同目录的 06-uninstall-service.ps1"
Say ""
Say "  登录账号：admin / Admin@2026    （第一次登录后请尽快改掉）"
Say "============================================================"

# ---------------------------------------------------------------- 放行防火墙
try {
    $rule = Get-NetFirewallRule -DisplayName '模型管理平台' -ErrorAction SilentlyContinue
    if (-not $rule) {
        New-NetFirewallRule -DisplayName '模型管理平台' -Direction Inbound `
            -LocalPort 8080 -Protocol TCP -Action Allow -Profile Any | Out-Null
        Ok "已放行防火墙 8080 端口"
    } else {
        Ok "防火墙规则已存在，跳过"
    }
} catch {
    Warn "防火墙规则设置失败（$($_.Exception.Message)）—— 局域网访问可能不通，请手动放行 8080"
}

Say ""
Read-Host "按回车退出"

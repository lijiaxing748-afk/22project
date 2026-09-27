# =====================================================================
#  04 - 启动系统
#
#  会开两个窗口：后端 Flask (:5000) + 前端 Vite (:8080)
#  关闭：直接关掉那两个窗口即可
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
$vpy  = Join-Path $Venv 'Scripts\python.exe'

Say "============================================================"
Say "  步骤 4/4：启动模型管理平台"
Say "============================================================"
Say ""

# ---------------------------------------------------------------- 前置检查
if (-not (Test-Path $vpy)) {
    Err "没有找到 venv，请先运行 01-安装后端依赖.ps1"
    Read-Host "按回车退出"; exit 1
}
if (-not (Test-Path (Join-Path $Fe 'node_modules'))) {
    Err "前端缺少 node_modules"
    Err "请把 03-前端离线依赖\node_modules 复制到 $Fe\"
    Read-Host "按回车退出"; exit 1
}

# ---------------------------------------------------------------- 端口检查
foreach ($p in @(5000, 8080)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) {
        Warn "端口 $p 已被占用 —— 如果系统已经在跑，就不需要再启动一次。"
    }
}

# ---------------------------------------------------------------- 启动后端
Say "[1/2] 启动后端（新窗口）..."
$backendCmd = "`$host.UI.RawUI.WindowTitle='模型管理平台-后端(勿关)'; " +
              "Set-Location '$Src'; " +
              "Write-Host '=== 后端 Flask  http://127.0.0.1:5000 ===' -ForegroundColor Cyan; " +
              "& '$vpy' main.py"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $backendCmd
Ok "后端窗口已打开"

# 等后端把端口占起来，避免前端首屏请求全部 404
Say "       等待后端就绪 ..."
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/health' -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    if ($i % 5 -eq 4) { Say "       ... 已等 $($i + 1) 秒" }
}

if ($ready) {
    Ok "后端已响应 /health"
} else {
    Warn "30 秒内没等到后端响应。先看后端窗口里的报错，多半是数据库连不上。"
}
Say ""

# ---------------------------------------------------------------- 启动前端
Say "[2/2] 启动前端（新窗口）..."
$frontendCmd = "`$host.UI.RawUI.WindowTitle='模型管理平台-前端(勿关)'; " +
               "Set-Location '$Fe'; " +
               "Write-Host '=== 前端 Vite  http://localhost:8080 ===' -ForegroundColor Cyan; " +
               "npx vite --host"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $frontendCmd
Ok "前端窗口已打开"
Say ""

Say "============================================================"
Say "  两个服务正在启动，请再等 10~20 秒。"
Say ""
Say "  然后打开浏览器访问："
Say "      http://localhost:8080"
Say "  账号密码随便填（例如 admin / 123456）"
Say ""
Say "  后端健康检查："
Say "      http://127.0.0.1:5000/health"
Say "============================================================"
Say ""
Warn "那两个新打开的窗口不要关，最小化即可。"
Warn "如果浏览器打不开，先看那两个窗口里有没有红色报错。"
Say ""
Read-Host "按回车退出"

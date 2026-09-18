# =====================================================================
#  06 - 卸载 Windows 服务
#
#  只删掉「服务注册」，**不动任何数据**：
#     · 数据库里的表和数据都保留
#     · data\ 下的模型产物、发布包、日志都保留
#     · venv 和源码都保留
#  所以卸载之后想恢复，重新跑 05-install-service.ps1 就行。
#
#  用法：右键 ->「使用 PowerShell 运行」   （需要**管理员**权限）
# =====================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "   [OK]   $m" -ForegroundColor Green }
function Err  ($m) { Write-Host "   [错误] $m" -ForegroundColor Red }
function Warn ($m) { Write-Host "   [提示] $m" -ForegroundColor Yellow }
function Info ($m) { Write-Host "   [信息] $m" -ForegroundColor Cyan }

$ServiceName = 'ModelPlatform'
$Nssm = Join-Path $PSScriptRoot 'nssm\nssm.exe'

Say "============================================================"
Say "  卸载模型管理平台服务"
Say "============================================================"
Say ""

$isAdmin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Err "本脚本必须以**管理员**身份运行。"
    Read-Host "按回车退出"; exit 1
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Info "服务 $ServiceName 不存在，无需卸载。"
    Read-Host "按回车退出"; exit 0
}

Warn "即将停止并删除服务 $ServiceName（当前状态：$($svc.Status)）"
Warn "数据库和 data\ 下的文件**不会**被删除。"
if ((Read-Host "确认继续？(y/N)") -ne 'y') { Info "已取消。"; exit 0 }

if ($svc.Status -eq 'Running') {
    Say "[1/2] 停止服务 ..."
    if (Test-Path $Nssm) {
        & $Nssm stop $ServiceName | Out-Null
    } else {
        Stop-Service -Name $ServiceName -Force
    }
    Start-Sleep -Seconds 3
    Ok "已停止"
} else {
    Info "服务当前未运行，跳过停止"
}

Say "[2/2] 删除服务注册 ..."
if (Test-Path $Nssm) {
    & $Nssm remove $ServiceName confirm | Out-Null
} else {
    # nssm 丢了也能卸：用系统自带的 sc.exe
    Warn "没找到 nssm.exe，改用系统 sc.exe 删除"
    & sc.exe delete $ServiceName | Out-Null
}
Start-Sleep -Seconds 2

if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Err "删除失败 —— 可能还有进程占着。手动执行： sc.exe delete $ServiceName"
} else {
    Ok "服务已删除"
}

# 防火墙规则也一并撤掉（只撤我们自己建的那条）
try {
    $rule = Get-NetFirewallRule -DisplayName '模型管理平台' -ErrorAction SilentlyContinue
    if ($rule) {
        Remove-NetFirewallRule -DisplayName '模型管理平台'
        Ok "已移除防火墙规则"
    }
} catch {
    Warn "防火墙规则移除失败（可忽略）：$($_.Exception.Message)"
}

Say ""
Say "卸载完成。数据库数据、模型产物、日志均保留。"
Say "如需恢复，重新运行 05-install-service.ps1 即可。"
Say ""
Read-Host "按回车退出"

# =====================================================================
#  elevate.ps1 —— 以管理员身份运行同目录下的某个脚本
#
#  为什么单独做一个文件：
#   原来想在 run.bat 里用一行 PowerShell 判断管理员 + 提权，结果那段
#   跨行 `^` 续行 + 中文 + 引号嵌套让 cmd.exe 的解析彻底乱掉
#   （报错 "'TEPs00' is not recognized"）。抽成独立的 .ps1 之后，
#   run.bat 里只剩一行普通调用，不再有引号地狱。
#
#  用法（一般由 run.bat 05 / 06 调用，不需要手动执行）：
#     powershell -File elevate.ps1 -Script 05-install-service.ps1
# =====================================================================
param(
    [Parameter(Mandatory = $true)]
    [string]$Script
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$target = Join-Path $PSScriptRoot $Script

if (-not (Test-Path $target)) {
    Write-Host "   [错误] 找不到脚本：$target" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

$isAdmin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    # 已经是管理员，直接在当前窗口跑
    & $target
    exit $LASTEXITCODE
}

# 不是管理员：拉起一个提权的 PowerShell 去跑目标脚本。
# ⚠️ -Wait 是必须的：不等待的话本进程会立刻退出，
#    用户看到的是"一闪而过"，以为脚本没跑。
Write-Host "   本步骤需要管理员权限，正在申请提权..." -ForegroundColor Yellow
Write-Host "   （会弹出 UAC 确认框，请点「是」）" -ForegroundColor Yellow
Write-Host ""

try {
    $p = Start-Process powershell -Verb RunAs -PassThru -Wait -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        # ⚠️ 提权后的新窗口**不会**自己暂停，脚本跑完就消失，
        #    用户来不及看结果。所以外面再套一层：
        #    执行目标脚本，结束前 Read-Host 停一下。
        '-Command',
        "& '$target'; Write-Host ''; Read-Host '按回车关闭此窗口'"
    )
    exit $p.ExitCode
} catch {
    # 用户点了 UAC 的「否」，Start-Process -Verb RunAs 会抛异常
    Write-Host "   [错误] 提权被取消或失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   请右键 PowerShell ->「以管理员身份运行」，然后手动执行：" -ForegroundColor Yellow
    Write-Host "       $target" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 1
}

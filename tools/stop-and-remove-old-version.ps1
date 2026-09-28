﻿# 模型管理平台 · 诊断并停止/移除"旧版部署"
#
# 【在目标机器上用「管理员」PowerShell 运行】
#
#   powershell -ExecutionPolicy Bypass -File stop-and-remove-old-version.ps1 -Path "D:\22project"
#       只诊断：列出相关进程 / 服务 / 计划任务 / 启动项，并说明该怎么停（不动手）
#   ... -Path "D:\22project" -Stop
#       停：停服务（含取消自动重启）→ 关计划任务 → 杀进程树
#   ... -Path "D:\22project" -Stop -Remove
#       停完再删目录（删不掉会给出下一步办法）
#
# 为什么"进程停不掉、目录删不掉"（这台项目上前前后后踩过的原因，脚本按顺序处理）：
#   1) 旧版是用【Windows 服务】或【计划任务】拉起来的 → 杀掉 exe，服务/任务立刻又拉一个；
#      必须先停服务并取消自动重启，再杀进程；
#   2) 进程属于 SYSTEM/其他用户 → 普通权限的"结束任务"会被拒 → 必须以管理员运行；
#   3) venv 的 python.exe 只是个"转启动器"，真正的解释器是它的**子进程** → 要按进程树杀（/T）；
#   4) 旧版可能用 pythonw.exe（无窗口）跑 → 进程列表里不容易发现；
#   5) 旧版的 Windows 手册里出现过服务名 ModelManageService（本项目早期版本用过这个名字）；
#   6) 目录删不掉却看不到占用进程 → 常见是"某个 cmd/PowerShell 窗口 cd 在里面"，
#      或资源监视器里能看到句柄；实在不行就重启后立刻删。
#
# 安全说明：本脚本只处理
#   · 可执行文件路径或命令行里包含 -Path 的进程；
#   · 名称/路径匹配 Model / 22project / 模型管理 的服务、计划任务、启动项。
#   其它进程一律不碰。想先看不动手，加 -WhatIf 或不加 -Stop。

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [switch]$Stop,
    [switch]$Remove,
    [switch]$WhatIf
)

$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue)
if (-not $Root) { $Root = $Path } else { $Root = $Root.Path }
$Dry = $WhatIf -or (-not $Stop)

function Head([string]$t) { Write-Host ''; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Ok([string]$t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Info([string]$t) { Write-Host "      $t" }
function Warn([string]$t) { Write-Host "  [注意] $t" -ForegroundColor Yellow }

# 管理员检查
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Warn '当前不是管理员：停服务/杀 SYSTEM 进程会失败。请用「以管理员身份运行」重开 PowerShell。' }

Write-Host ''
Write-Host "目标目录：$Root"
Write-Host ("模式：" + $(if ($Dry) { '只诊断（不动手）' } elseif ($Remove) { '停止 + 删除' } else { '仅停止' }))

# 排除项：本脚本自身 + 调用它的进程链（PowerShell/cmd/终端）。
# ⚠️ 实测踩到：若用 `powershell -Command "cd D:\22project; ..."` 这种方式调用，命令行里会带这个目录，
#    于是「命令行包含 -Path」这条规则会把**你自己这个终端**也匹配上 —— 绝不能把它杀掉。
$selfIds = New-Object 'System.Collections.Generic.HashSet[int]'
$curId = $PID
while ($curId -and $curId -ne 0 -and -not $selfIds.Contains([int]$curId)) {
    [void]$selfIds.Add([int]$curId)
    $curId = (Get-CimInstance Win32_Process -Filter "ProcessId=$curId" -ErrorAction SilentlyContinue).ParentProcessId
}
$SelfIds = $selfIds

# ⚠️ 只按"程序本体（ExecutablePath）在目标目录里"判定，**不**按命令行匹配 ——
#    实测踩过：用 `powershell -Command "cd <目录>; ..."` 这类方式调用时，命令行里会带该目录，
#    按命令行匹配会把调用者的终端乃至兄弟进程一起杀掉。命令行里提到目录的进程只**报告**不杀。
function Get-SuspectProcess {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $id = [int]$_.ProcessId
        if ($SelfIds.Contains($id)) { return $false }
        ($_.ExecutablePath -and $_.ExecutablePath -like "$Root*")
    }
}

function Get-MentioningProcess {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $id = [int]$_.ProcessId
        if ($SelfIds.Contains($id)) { return $false }
        -not ($_.ExecutablePath -and $_.ExecutablePath -like "$Root*") -and
        ($_.CommandLine -and $_.CommandLine -like "*$Root*")
    }
}

# ---------------------------------------------------------------- 1) 进程
Head '1) 相关进程（可执行路径或命令行里带这个目录；已排除本脚本与调用它的终端）'
$procs = @()
try {
    $procs = Get-SuspectProcess
} catch { Warn "查询进程失败：$($_.Exception.Message)" }

if (-not $procs) {
    Ok '没有进程占用这个目录'
} else {
    foreach ($p in $procs) {
        $owner = ''
        try { $owner = (Invoke-CimMethod -InputObject $p -MethodName GetOwner -ErrorAction Stop).User } catch {}
        Info ("PID {0,-7} 父 {1,-7} {2,-16} 属主 {3}" -f $p.ProcessId, $p.ParentProcessId, $p.Name, ($owner -replace '.*\\', ''))
        if ($p.ExecutablePath) { Info "         $($p.ExecutablePath)" }
        if ($p.CommandLine)    { Info "         $($p.CommandLine)" }
    }
    $pw = $procs | Where-Object { $_.Name -match 'pythonw|node|nssm' }
    if ($pw) { Warn "其中有 pythonw/node/nssm —— 旧版可能是无窗口进程或被服务托管的子进程，必须按进程树停" }
}

# ---------------------------------------------------------------- 2) 端口
Head '2) 相关端口（旧版可能在 5000/8080/8081 上）'
foreach ($port in 5000, 8080, 8081, 8000) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($c) {
        $pr = Get-Process -Id $c[0].OwningProcess -ErrorAction SilentlyContinue
        Info "$port 正在监听 → PID $($c[0].OwningProcess) $($pr.ProcessName) $($pr.Path)"
    }
}

# ---------------------------------------------------------------- 3) 服务
Head '3) 相关服务'
$svcMatch = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'Model|22project|model-platform|ModelManage' -or $_.DisplayName -match '模型|Model' }
if (-not $svcMatch) {
    Info '（没有名字匹配的服务）'
} else {
    foreach ($s in $svcMatch) {
        $wmi = Get-CimInstance Win32_Service -Filter "Name='$($s.Name)'" -ErrorAction SilentlyContinue
        Info ("$($s.Name)  状态=$($s.Status)  启动=$($s.StartType)  路径=$($wmi.PathName)")
    }
}
# 旧版手册里出现过的服务名，单独查一下（可能已不存在但残留在注册表）
foreach ($legacy in 'ModelManageService', 'ModelPlatform') {
    if (Get-Service -Name $legacy -ErrorAction SilentlyContinue) { Warn "存在旧版服务名：$legacy（下面会停掉并删除）" }
}

# ---------------------------------------------------------------- 4) 计划任务
Head '4) 相关计划任务'
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -match 'Model|22project|模型' -or ($_.Actions.Execute -join ' ') -like "*$Root*" }
if (-not $tasks) { Info '（没有）' } else { $tasks | ForEach-Object { Info "$($_.TaskName)  状态=$($_.State)  执行=$($_.Actions.Execute -join ';')" } }

# ---------------------------------------------------------------- 5) 启动项
Head '5) 启动项（开机自启的另一种藏法）'
$startup = Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue | Where-Object { $_.Command -like "*$Root*" -or $_.Name -match 'Model|模型' }
if (-not $startup) { Info '（没有）' } else { $startup | ForEach-Object { Info "$($_.Name) → $($_.Command)" } }

# ---------------------------------------------------------------- 6) 处置
if ($Dry) {
    Head '6) 处置建议（本次只诊断，未动手）'
    Info "1. 先停服务：      Stop-Service <服务名> -Force；若它自动重启，再执行 sc.exe config <服务名> start= disabled"
    Info "2. 取消计划任务：  Disable-ScheduledTask -TaskName <名>; Unregister-ScheduledTask -TaskName <名> -Confirm:`$false"
    Info "3. 再杀进程树：    taskkill /PID <上面列出的 PID> /T /F   （/T 连子进程一起杀；需管理员）"
    Info "4. 全都停掉后再删目录；本脚本加 -Stop -Remove 会自动按这个顺序做。"
    exit 0
}

Head '6) 开始处置（顺序：停服务 → 关计划任务 → 杀进程树）'

# 6.1 服务
foreach ($s in $svcMatch) {
    try {
        if ($s.Status -ne 'Stopped') { Stop-Service -Name $s.Name -Force -ErrorAction Stop; Ok "已停服务 $($s.Name)" }
        else { Info "服务 $($s.Name) 本来就是停止的" }
    } catch { Warn "停服务 $($s.Name) 失败：$($_.Exception.Message)" }
    # 自动重启是"杀完又起来"的根因，必须先禁用
    & sc.exe config $s.Name start= disabled | Out-Null
    Ok "已把 $($s.Name) 设为「不再自动启动」（要恢复：sc.exe config $($s.Name) start= auto）"
}
foreach ($legacy in 'ModelManageService') {
    if (Get-Service -Name $legacy -ErrorAction SilentlyContinue) {
        Stop-Service -Name $legacy -Force -ErrorAction SilentlyContinue
        & sc.exe delete $legacy | Out-Null
        Ok "已停止并删除旧版服务 $legacy"
    }
}

# 6.2 计划任务
foreach ($t in $tasks) {
    try {
        if ($t.State -eq 'Running') { Stop-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue }
        Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false -ErrorAction Stop
        Ok "已注销计划任务 $($t.TaskName)"
    } catch { Warn "处理计划任务 $($t.TaskName) 失败：$($_.Exception.Message)" }
}

# 6.3 进程树（先子孙后父，避免父进程重启子进程）
Start-Sleep -Milliseconds 500
$remaining = Get-SuspectProcess
foreach ($p in ($remaining | Sort-Object ProcessId -Descending)) {
    $r = & taskkill /PID $p.ProcessId /T /F 2>&1
    if ($LASTEXITCODE -eq 0) { Ok "已结束进程树 PID $($p.ProcessId)（$($p.Name)）" }
    else { Warn "结束 PID $($p.ProcessId) 失败：$r —— 若属主是 SYSTEM/其它用户，请以管理员运行" }
}

Start-Sleep -Seconds 1
$still = Get-SuspectProcess
if ($still) {
    Warn "还有进程没停掉："
    $still | ForEach-Object { Info "PID $($_.ProcessId) $($_.Name) 属主 $((Invoke-CimMethod -InputObject $_ -MethodName GetOwner).User)" }
    Info '对策（按顺序试）：'
    Info '  a) 确认是管理员窗口；b) 资源监视器 resmon → CPU → 关联的句柄 → 搜目录名，看是谁；'
    Info '  c) 重启这台机器，**开机后立刻**再跑本脚本（此时还没被拉起）。'
} else {
    Ok '相关进程已全部停止'
}

# ---------------------------------------------------------------- 7) 删除目录
if ($Remove) {
    Head '7) 删除旧版目录'
    if (Test-Path -LiteralPath $Root) {
        try {
            Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction Stop
            Ok "已删除 $Root"
        } catch {
            Warn "删除失败：$($_.Exception.Message)"
            Info '常见原因与对策：'
            Info '  · 还有窗口 cd 在这个目录里 → 关掉那个 cmd/PowerShell 窗口（或 cd 到别处）再删；'
            Info '  · Defender/杀软正在扫描 → 稍等或临时关闭实时防护；'
            Info '  · 资源监视器 resmon → CPU → 关联的句柄 → 搜目录名，找到真正占用的进程；'
            Info '  · 权限不足 → 用管理员执行：takeown /F "<目录>" /R /D Y  &&  icacls "<目录>" /grant Administrators:F /T';
            Info '  · 都不行 → 重启后立刻删（开机时旧版还没被拉起）。'
        }
    } else { Info "目录已不存在：$Root" }
} else {
    Head '7) 下一步'
    Info "进程/服务都已处理后，再执行一次本脚本并加 -Remove 即可删除目录："
    Info "  powershell -ExecutionPolicy Bypass -File stop-and-remove-old-version.ps1 -Path `"$Root`" -Stop -Remove"
}

Write-Host ''

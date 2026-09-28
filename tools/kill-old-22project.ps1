# =====================================================================
#  杀干净 C:\Users\Lenovo\22project 上的旧版部署（Windows，管理员 PowerShell）
#
#  整段复制到「以管理员身份运行」的 PowerShell 窗口里粘贴，回车即可。
#
#  ⚠️ 运行前先看清第 0 步的备份提醒：
#      · testRestfulProject\data     ← 训练好的模型/图片/数据集，删了就没了
#      · testRestfulProject\db.env   ← 数据库账号口令；删了新版会自己重建
#      · MySQL 服务**不动**（新版还要用它）
#
#  想连目录一起删：把下面的 $Delete 改成 $true
#
#  【安全边界（重要）】只结束两类进程：
#      ① 程序本体（ExecutablePath）就在这个目录里的 —— 例如 venv\Scripts\python.exe、目录里的 node.exe；
#      ② 正在占用本项目端口 5000/8080/8081 的 —— 覆盖"用系统 Python 跑旧代码"的情况。
#    而"命令行里只是**提到**这个路径"的进程**一律不杀**，只列出来给你看 ——
#    否则会误杀你自己的终端/编辑器/构建进程（实测踩过：一条 `cd <目录>; ...` 的命令，
#    让脚本把调用它的进程连同兄弟进程一起杀了）。
# =====================================================================

$Root   = 'C:\Users\Lenovo\22project'
$Delete = $false        # ← 备份好了改成 $true，脚本最后会删目录

$ErrorActionPreference = 'Continue'
function Say($t)  { Write-Host $t }
function Ok($t)   { Write-Host "[OK] $t"   -ForegroundColor Green }
function Info($t) { Write-Host "     $t" }
function Warn($t) { Write-Host "[注意] $t" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Warn '当前不是管理员：停服务/结束他人进程会失败。请关掉，重开「以管理员身份运行」的 PowerShell，再粘贴本段。'; return }

# 自身 + 调用链排除
$selfIds = New-Object 'System.Collections.Generic.HashSet[int]'
$cur = $PID
while ($cur -and $cur -ne 0 -and -not $selfIds.Contains([int]$cur)) {
    [void]$selfIds.Add([int]$cur)
    $cur = (Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue).ParentProcessId
}
$Ports = 5000, 8080, 8081
function Owned {        # ① 程序本体在目录里
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        -not $selfIds.Contains([int]$_.ProcessId) -and $_.ExecutablePath -and $_.ExecutablePath -like "$Root*"
    }
}
function PortOwners {   # ② 占着本项目端口
    $ids = @()
    foreach ($port in $Ports) {
        $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if ($c) { $ids += $c[0].OwningProcess }
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $ids -contains [int]$_.ProcessId -and -not $selfIds.Contains([int]$_.ProcessId)
    }
}
function Mentioning {   # 只报告：命令行里提到目录，但程序本体不在目录里
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        -not $selfIds.Contains([int]$_.ProcessId) -and $_.CommandLine -and $_.CommandLine -like "*$Root*" -and
        -not ($_.ExecutablePath -and $_.ExecutablePath -like "$Root*")
    }
}
function KillSet {
    $all = @()
    $all += @(Owned)
    $all += @(PortOwners)
    $all | Sort-Object ProcessId -Unique
}

Say ''
Say "==================== 清理 $Root ===================="
if (-not (Test-Path -LiteralPath $Root)) { Warn "目录不存在：$Root（路径对不对？）" }

# ---------- 0) 备份提醒 ----------
Say ''
Say '=== 0) 先确认要保留的东西 ==='
if (Test-Path -LiteralPath "$Root\testRestfulProject\data")   { Info "保留：$Root\testRestfulProject\data" }
if (Test-Path -LiteralPath "$Root\testRestfulProject\db.env") { Info "保留：$Root\testRestfulProject\db.env" }
Info "建议先拷走（尤其 data）："
Info "  Copy-Item -Recurse -Force '$Root\testRestfulProject\data' `"`$env:USERPROFILE\Desktop\22project-data-backup`""

# ---------- 1) 服务 ----------
Say ''
Say '=== 1) 相关 Windows 服务（旧版最可能就是服务拉起来的）==='
$svc = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object {
    ($_.PathName -and $_.PathName -like "*$Root*") -or $_.Name -match 'ModelManage|ModelPlatform|22project'
}
if (-not $svc) { Info '（没有）' }
foreach ($s in $svc) {
    Info "$($s.Name)  状态=$($s.State)  启动=$($s.StartMode)"
    Info "     $($s.PathName)"
    try { Stop-Service -Name $s.Name -Force -ErrorAction Stop; Ok "已停止服务 $($s.Name)" } catch { Warn "停 $($s.Name) 失败：$($_.Exception.Message)" }
    & sc.exe config $s.Name start= disabled | Out-Null     # 关键：不禁用自动重启，杀了还会被拉起来
    & sc.exe delete $s.Name | Out-Null
    Ok "已禁用自动启动并删除服务注册 $($s.Name)"
}

# ---------- 2) 计划任务 ----------
Say ''
Say '=== 2) 相关计划任务 ==='
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.TaskName -match 'Model|22project|模型' -or (($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' ') -like "*$Root*"
}
if (-not $tasks) { Info '（没有）' }
foreach ($t in $tasks) {
    Info "$($t.TaskName)  状态=$($t.State)"
    Stop-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
    try { Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false -ErrorAction Stop; Ok "已注销 $($t.TaskName)" }
    catch { Warn "注销 $($t.TaskName) 失败：$($_.Exception.Message)" }
}

# ---------- 3) 防火墙规则 ----------
Say ''
Say '=== 3) 部署时加的防火墙规则（新版会自己再加）==='
$rules = Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match 'Model|22project|模型' }
if (-not $rules) { Info '（没有）' }
foreach ($r in $rules) {
    Info "移除规则：$($r.DisplayName)"
    Remove-NetFirewallRule -DisplayName $r.DisplayName -ErrorAction SilentlyContinue
}

# ---------- 4) 开机启动项 ----------
Say ''
Say '=== 4) 开机启动项（指向这个目录的，自己删掉）==='
$startup = Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue | Where-Object { $_.Command -like "*$Root*" -or $_.Name -match 'Model|模型' }
if (-not $startup) { Info '（没有）' } else { $startup | ForEach-Object { Warn "$($_.Name) → $($_.Command)" } }

# ---------- 5) 结束进程 ----------
Say ''
Say '=== 5) 结束"属于旧版"的进程（连子进程一起）==='
for ($pass = 1; $pass -le 3; $pass++) {
    $ps = @(KillSet)
    if (-not $ps) { break }
    foreach ($p in ($ps | Sort-Object ProcessId -Descending)) {
        $owner = ''; try { $owner = (Invoke-CimMethod -InputObject $p -MethodName GetOwner).User } catch {}
        Info "PID $($p.ProcessId)（父 $($p.ParentProcessId)）$($p.Name) 属主 $owner"
        if ($p.ExecutablePath) { Info "     $($p.ExecutablePath)" }
        & taskkill /PID $p.ProcessId /T /F 2>&1 | ForEach-Object { Info $_ }
    }
    Start-Sleep -Milliseconds 800
}
$left = @(KillSet)
if ($left) {
    Warn '还有属于旧版的进程没停掉：'
    $left | ForEach-Object { Info "PID $($_.ProcessId) $($_.Name) $($_.ExecutablePath)" }
    Info '对策：① 确认是管理员窗口；② resmon → CPU → 关联的句柄 → 搜 22project；③ 重启后立刻再跑本段。'
} else { Ok '属于旧版的进程已全部结束' }

# ---------- 6) 只在"命令行里提到目录"的进程：只报告 ----------
Say ''
Say '=== 6) 仅供参考：命令行里提到这个目录的进程（**不会**被本脚本结束）==='
$men = @(Mentioning)
if (-not $men) { Info '（没有）' }
foreach ($p in $men | Select-Object -First 12) {
    Info "PID $($p.ProcessId)  $($p.Name)"
    Info "     $($p.CommandLine)"
}
if ($men) { Warn '如果其中有旧版的启动窗口（cmd/run.bat 那类），手工关掉它；不确定的别动。' }

# ---------- 7) 端口 ----------
Say ''
Say '=== 7) 端口检查 ==='
$busy = $false
foreach ($port in $Ports) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($c) { $busy = $true; $pr = Get-Process -Id $c[0].OwningProcess -ErrorAction SilentlyContinue; Warn "$port 仍在监听 → PID $($c[0].OwningProcess) $($pr.ProcessName) $($pr.Path)" }
}
if (-not $busy) { Ok '5000/8080/8081 都没有监听' }

# ---------- 8) 删目录 ----------
Say ''
if ($Delete) {
    Say '=== 8) 删除目录 ==='
    try { Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction Stop; Ok "已删除 $Root" }
    catch {
        Warn "删除失败：$($_.Exception.Message)"
        Info '依次试：'
        Info '  · 关掉任何 cd 在这个目录里的 cmd/PowerShell 窗口；'
        Info "  · takeown /F `"$Root`" /R /D Y   然后   icacls `"$Root`" /grant Administrators:F /T  （再删）"
        Info '  · resmon → CPU → 关联的句柄 → 搜 22project，找出真正占用的进程；'
        Info '  · 还不行 → 重启，开机后立刻再跑本段（此时旧版还没被拉起）。'
    }
} else {
    Say '=== 8) 未删目录（$Delete = $false）==='
    Info '确认 data / db.env 备份好了，把开头的 $Delete 改成 $true 再跑一次；或手工执行：'
    Info "  Remove-Item -LiteralPath '$Root' -Recurse -Force"
}

Say ''
Say '==================== 收尾 ===================='
Ok '旧版已清理（MySQL 服务未动，数据库里的表和数据都还在）'
Info '装新版：把新代码放到一个**新目录**（例如 C:\22project），然后'
Info '  · 有网：git clone https://github.com/lijiaxing748-afk/22project.git  →  cd 22project  →  start.bat'
Info '  · 无网：拷整个项目（**不用**带 venv/node_modules）→ 双击 start.bat'
Info '新版会自动配好数据库、db.env、开机自启服务。'
Say ''

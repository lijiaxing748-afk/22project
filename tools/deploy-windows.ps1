# =====================================================================
#  模型管理平台 · 服务器部署（一条命令，Windows）
#
#  由仓库根的 deploy.bat 调用，也可以直接用 PowerShell 跑：
#     powershell -ExecutionPolicy Bypass -File tools\deploy-windows.ps1 install
#
#  做了什么（幂等，可以反复跑）：
#     1) 检查/创建 venv 并安装依赖
#     2) 准备前端产物 frontend\22project\dist（缺且本机有 npm 就自动构建）
#     3) 读 testRestfulProject\db.env 建库建表（库名按配置替换）+ 鉴权表 + 校验 11 张表
#        ⚠️ MODEL_SECRET_KEY 为空会自动生成并写回 db.env（否则每次重启所有人都要重新登录）
#     4) 注册成**开机自启**的常驻服务：
#          · 有 nssm.exe  → 装成真正的 Windows 服务（可配崩溃自动重启、日志轮转）
#          · 没有 nssm    → 退化为"计划任务（开机启动、以 SYSTEM 运行、立即启动）"，
#                           同样满足"开机就在跑、局域网可访问"
#     5) 放行防火墙端口，打印**局域网访问地址**
#
#  用法：
#     deploy.bat                安装/更新并启动（默认 install）
#     deploy.bat status         状态（服务 + 端口 + 最近日志）
#     deploy.bat logs           看日志
#     deploy.bat restart        重启
#     deploy.bat upgrade        更新代码后重启（会重建前端）
#     deploy.bat uninstall      卸载服务（不动数据库与 data 目录）
#     deploy.bat -Port 8081     换端口
#     deploy.bat -DryRun        只打印将要做什么，不真改系统
# =====================================================================
param(
    [Parameter(Position = 0)][string]$Action = 'install',
    [int]$Port = 0,
    [int]$Threads = 6,
    [string]$DbUser = '',
    [string]$DbPassword = '',
    [string]$MysqlZip = '',          # 离线安装包（mysql-*-winx64.zip）；不填则先找仓库里有没有，再尝试下载
    [string]$MysqlUrl = '',          # 自定义下载地址
    [string]$MysqlDir = '',          # 安装目录，默认 C:\mysql
    [switch]$SkipMysqlInstall,       # 本机没有 MySQL 时不要自动装（只报错提示）
    [string]$PythonInstaller = '',   # 离线：python-3.12*.exe 路径（不填则先找仓库里的，再尝试下载）
    [string]$PythonUrl = '',         # 自定义 Python 安装包下载地址
    [switch]$SkipPythonInstall,      # 本机没有 Python 3.12 时不要自动装（只报错提示）
    [switch]$RecreateVenv,           # 现有 venv 的 Python 版本不对时，自动删掉重建（要求 3.12）
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot          # 仓库根（脚本在 tools\ 下）
$Srv = Join-Path $Root 'testRestfulProject'
$Fe = Join-Path $Root 'frontend\22project'
$Py = Join-Path $Srv 'venv\Scripts\python.exe'
$Port = if ($Port -gt 0) { $Port } elseif ($env:MODEL_PORT) { [int]$env:MODEL_PORT } else { 8080 }
$SvcName = 'ModelPlatform'
$Rebuild = $false
$Foreground = $false          # start.bat run：本机前台跑（不装服务）
$TaskName = 'ModelPlatform'
$LogFile = Join-Path $Srv 'data\logs\service-out.log'

function Ok($m) { Write-Host "[OK] $m" -ForegroundColor Green }
function Info($m) { Write-Host "     $m" }
function Warn($m) { Write-Host "[警告] $m" -ForegroundColor Yellow }
function Die($m) { Write-Host "[错误] $m" -ForegroundColor Red; exit 1 }
function Step($m) { if ($DryRun) { Write-Host "     [dry-run] $m" } else { Invoke-Expression $m } }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Need-Admin {
    if ($DryRun) { return }
    if (-not (Test-Admin)) { Die "这个动作需要**管理员**权限：右键「命令提示符/PowerShell」→ 以管理员身份运行，再执行 deploy.bat $Action" }
}
# 从 db.env 读一个键（去引号；MODEL_DB_* / MODEL_SECRET_KEY 都在这里）
# ⚠️ 写文件一律 UTF-8 **无 BOM**：Windows PowerShell 5.1 的 `-Encoding UTF8` 会加 BOM，
#    而 db.env 带 BOM 会让第一行变成 "\ufeffMODEL_DB_DIALECT"（键名多一个看不见的字符）→ 配置读不到；
#    SQL 临时文件与 my.ini 同理。
# ⚠️ 但**本脚本自身**必须带 BOM —— 否则 5.1 会按 GBK 读，脚本里的中文全变乱码（这是另一回事，别混）。
function Write-Text([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}
function Read-Env([string]$Key, [string]$Default = '') {
    $path = Join-Path $Srv 'db.env'
    if (-not (Test-Path $path)) { return $Default }
    foreach ($line in Get-Content $path -Encoding UTF8) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=\s*(.*)$") {
            return ($Matches[1].Trim().Trim("'").Trim('"'))
        }
    }
    return $Default
}
function Find-Nssm {
    foreach ($c in @((Join-Path $Root 'tools\nssm.exe'), (Join-Path $Root 'nssm.exe'))) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $hit = Get-ChildItem $Root -Recurse -Filter 'nssm.exe' -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return ''
}
function Find-Mysql {
    $cmd = Get-Command mysql.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in (Get-ChildItem 'C:\Program Files\MySQL' -Directory -ErrorAction SilentlyContinue |
                    Sort-Object Name -Descending)) {
        $try = Join-Path $c.FullName 'bin\mysql.exe'
        if (Test-Path $try) { return $try }
    }
    return ''
}
function Get-LanIp {
    # ⚠️ 不能只取"第一个非 127 的地址"：本机装了代理/虚拟网卡时会拿到假网段（实测取到 198.18.0.1，
    #    那是 198.18.0.0/15 基准测试网段，发给同事根本连不上）。优先取**有默认网关**的物理网卡，
    #    并排掉已知虚拟/保留网段。
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|198\.1[89]\.|0\.)' }
    $withGw = $candidates | Where-Object {
        $iface = Get-NetIPConfiguration -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
        $iface.IPv4DefaultGateway -ne $null
    } | Sort-Object InterfaceMetric | Select-Object -First 1
    if ($withGw) { return $withGw.IPAddress }
    $any = $candidates | Sort-Object InterfaceMetric | Select-Object -First 1
    if ($any) { return $any.IPAddress }
    return ''
}
function Get-ServiceMode {
    if (Get-Service -Name $SvcName -ErrorAction SilentlyContinue) { return 'service' }
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { return 'task' }
    return ''
}

# 「把属于本项目的进程收干净」—— stop / uninstall 时调用，让**整个目录可以直接删除**。
# ⚠️ 只按两类判定：① 程序本体（ExecutablePath）在项目目录里；② 正在监听本项目端口。
#    命令行里只是"提到"该项目路径的进程**一律不动** ——
#    实测踩过：按命令行匹配会误杀调用它的终端乃至兄弟进程（把 dsh 的作业运行器都杀退了）。
function Stop-OwnedProcesses {
    $selfIds = New-Object 'System.Collections.Generic.HashSet[int]'
    $c = $PID
    while ($c -and $c -ne 0 -and -not $selfIds.Contains([int]$c)) {
        [void]$selfIds.Add([int]$c)
        $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$c" -ErrorAction SilentlyContinue).ParentProcessId
    }
    $portIds = @()
    foreach ($p in @($Port)) {
        $x = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
        if ($x) { $portIds += $x[0].OwningProcess }
    }
    $targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        if ($selfIds.Contains([int]$_.ProcessId)) { return $false }
        ($_.ExecutablePath -and $_.ExecutablePath -like "$Root*") -or ($portIds -contains [int]$_.ProcessId)
    }
    $n = 0
    foreach ($t in ($targets | Sort-Object ProcessId -Descending)) {
        Info "结束残留进程 PID $($t.ProcessId)  $($t.Name)  $($t.ExecutablePath)"
        & taskkill /PID $t.ProcessId /T /F 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $n++ }
    }
    if ($n -gt 0) { Start-Sleep -Milliseconds 600 }
    return $n
}

function Show-FolderFree {
    $left = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath -like "$Root*"
    }
    $listen = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $left -and -not $listen) {
        Ok "整个目录已不被任何进程占用 —— 现在可以直接把 $Root 删掉了"
        Info "（数据库与 $Srv\data 不受影响；只是想删文件夹的话不用管它们）"
        Info "万一还是删不掉：多半是有个 cmd/PowerShell 窗口 cd 在里面，关掉它即可"
    } else {
        if ($left) { $left | ForEach-Object { Warn "仍在运行：PID $($_.ProcessId) $($_.Name) $($_.ExecutablePath)" } }
        if ($listen) { Warn "端口 $Port 仍在监听：PID $($listen[0].OwningProcess)" }
        Warn '先处理上面这些再删目录；若属主是 SYSTEM，请确认本窗口是管理员'
    }
}

# ---------------------------------------------------------------- 子命令
# ⚠️ 每个子命令都必须是**幂等**的：没装/重复跑都不该"报错退出"，只提示 —— 否则运维会以为坏了。
switch ($Action.ToLower()) {
    'status' {
        $mode = Get-ServiceMode
        if ($mode -eq 'service') {
            Get-Service $SvcName | Format-Table Name, Status, StartType -AutoSize | Out-String | Write-Host
        } elseif ($mode -eq 'task') {
            Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-Table -AutoSize | Out-String | Write-Host
        } else { Warn '还没安装（执行 start.bat 安装并启动；只想本机跑就 start.bat run）' }
        $listen = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        if ($listen) { Ok "端口 $Port 正在监听（PID $($listen[0].OwningProcess)）" } else { Warn "端口 $Port 没有监听" }
        if (Test-Path $LogFile) { Info '最近日志：'; Get-Content $LogFile -Tail 12 | ForEach-Object { Info $_ } }
        exit 0
    }
    'logs' {
        if (-not (Test-Path $LogFile)) { Warn "还没有日志文件：$LogFile（服务没跑过？前台跑的话直接看那个窗口）"; exit 0 }
        Get-Content $LogFile -Tail 60 -Wait
        exit 0
    }
    'restart' {
        Need-Admin
        $mode = Get-ServiceMode
        if ($mode -eq 'service') { Restart-Service $SvcName -Force; Ok "已重启（$SvcName）" }
        elseif ($mode -eq 'task') { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName $TaskName; Ok "已重启（计划任务 $TaskName）" }
        else { Warn '服务还没安装 —— 直接执行 start.bat 即可（装好并启动）' }
        exit 0
    }
    'start' {
        Need-Admin
        $mode = Get-ServiceMode
        if ($mode -eq 'service') { Start-Service $SvcName -ErrorAction SilentlyContinue; Ok "已启动（$SvcName）" }
        elseif ($mode -eq 'task') { Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Ok "已启动（$TaskName）" }
        else { Warn '服务还没安装 —— 直接执行 start.bat 即可' }
        exit 0
    }
    'stop' {
        Need-Admin
        $mode = Get-ServiceMode
        if ($mode -eq 'service') { Stop-Service $SvcName -Force -ErrorAction SilentlyContinue; Ok "已停止（$SvcName）" }
        elseif ($mode -eq 'task') { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Ok "已停止（$TaskName）" }
        else { Warn '服务本来就没安装/没在跑' }
        # 服务停了不等于进程都没了（可能是 start.bat run 的前台实例、或残留子进程）
        $k = if ($DryRun) { 0 } else { Stop-OwnedProcesses }
        if ($k -gt 0) { Ok "另外结束了 $k 个残留进程" }
        Show-FolderFree
        exit 0
    }
    'update' {
        # 「更新到仓库最新代码」：拉代码 → 重建前端 → 重启服务
        # ⚠️ --ff-only --autostash：本地改动（训练产物 data/models/* 是被 git 跟踪的）先自动暂存再放回；
        #    真冲突就明确报错让人处理，绝不硬覆盖别人机器上的东西。
        Need-Admin
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die '本机没有 git，无法自动更新：请手动覆盖代码后执行 start.bat upgrade' }
        Info '拉取仓库最新代码...'
        Step "git -C '$Root' fetch --all --prune"
        Step "git -C '$Root' pull --ff-only --autostash"
        if (-not $DryRun) {
            & git -C $Root fetch --all --prune | Out-Null
            & git -C $Root pull --ff-only --autostash
            if ($LASTEXITCODE -ne 0) {
                Die "更新失败：多半是本地改动与远端冲突。请手工处理（git -C $Root status）后重跑；只重建前端+重启可用： start.bat upgrade"
            }
            Ok "代码已更新到 $(& git -C $Root rev-parse --short HEAD)（$(& git -C $Root log -1 --format=%s)）"
        }
        $Action = 'install'; $Rebuild = $true; $Foreground = $false
    }
    'run' { $Foreground = $true; $Action = 'install'; $Rebuild = $true }
    'uninstall' {
        Need-Admin
        Info '卸载服务（数据库与 data 目录一概不动）—— 目标是让整个文件夹可以直接删除'
        $mode = Get-ServiceMode
        if ($mode -eq 'service') {
            $nssm = Find-Nssm
            if ($nssm) {
                Step "& '$nssm' stop $SvcName"
                Step "& '$nssm' set $SvcName AppExit Default Exit"      # 先掐掉"退出即重启"，否则进程杀了又被拉起来
                Step "& '$nssm' remove $SvcName confirm"
            } else {
                Step "Stop-Service $SvcName -Force -ErrorAction SilentlyContinue"
                Step "sc.exe config $SvcName start= disabled"          # ⚠️ 关键：不禁用自动启动，删目录时它还会启动
                Step "sc.exe delete $SvcName"
            }
        } elseif ($mode -eq 'task') {
            Step "Stop-ScheduledTask -TaskName '$TaskName' -ErrorAction SilentlyContinue"
            Step "Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
        } else { Warn '没找到已安装的服务/计划任务（那更好，说明没有开机自启的东西）' }
        Step "Remove-NetFirewallRule -DisplayName 'ModelPlatform $Port' -ErrorAction SilentlyContinue"
        # 收掉所有"本体在项目目录里 / 占着本项目端口"的进程
        $k = if ($DryRun) { 0 } else { Stop-OwnedProcesses }
        if ($k -gt 0) { Ok "结束了 $k 个仍在运行的进程" }
        Show-FolderFree
        Ok "已卸载。数据库与 $Srv\data 一概未动"
        exit 0
    }
    'upgrade' { $Action = 'install'; $Rebuild = $true }
    'install' { $Rebuild = $false }
    default { Die "未知动作：$Action（可用：install / status / logs / restart / start / stop / upgrade / uninstall）" }
}

Write-Host '============================================================'
Write-Host '  模型管理平台 · 服务器部署（Windows）'
Write-Host '------------------------------------------------------------'
Write-Host "  项目目录 : $Root"
Write-Host "  监听端口 : $Port（-Port 或 MODEL_PORT 可改）   线程 $Threads"
Write-Host "  服务名   : $SvcName"
if ($DryRun) { Write-Host '  模式     : DRY-RUN（只打印，不改系统）' }
Write-Host '============================================================'
Write-Host ''
Need-Admin

# ---------------------------------------------------------------- 1.0) 没有 Python 3.12 就自动装
# 与 MySQL 同款思路：找不到就下载官方安装包静默装（仅当前用户，不需要管理员）。
function Install-Python312 {
    $exe = $PythonInstaller
    if (-not $exe) {
        $found = Get-ChildItem -Path @($Root, (Join-Path $Root 'tools'), (Join-Path $Root 'docs\离线部署')) `
                    -Recurse -Filter 'python-3.12*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $exe = $found.FullName; Info "使用本机已有的安装包：$exe" }
    }
    if (-not $exe) {
        $target = Join-Path $env:TEMP 'python-3.12-amd64.exe'
        $urls = @()
        if ($PythonUrl) { $urls += $PythonUrl }
        $urls += @(
            'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe',
            'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe',
            'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe'
        )
        foreach ($u in $urls) {
            try {
                Info "下载 $u （约 26 MB）..."
                Invoke-WebRequest -Uri $u -OutFile $target -UseBasicParsing -TimeoutSec 900
                $exe = $target; break
            } catch { Warn "下载失败：$($_.Exception.Message)" }
        }
    }
    if (-not $exe -or -not (Test-Path $exe)) {
        Die "没能获得 Python 3.12 安装包。离线机器：把 python-3.12*.exe 放到 tools\ 下（或用 -PythonInstaller 指定路径）后重跑"
    }
    Info '静默安装 Python 3.12（仅当前用户，不需要管理员；约 1~3 分钟）...'
    $argList = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_pip=1', 'Include_test=0')
    $proc = Start-Process -FilePath $exe -ArgumentList $argList -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Warn "安装程序返回码 $($proc.ExitCode)（1602 = 用户取消；3010 = 需要重启；其它见 python.org 文档）"
    } else { Ok 'Python 3.12 已安装' }
}
# ---------------------------------------------------------------- 1) Python 环境
# ⚠️ 必须 Python **3.12**：requirements.txt 里 numpy==2.5.3 要求 >=3.12、tensorflow 2.21 也只有 3.12 的轮子。
#    实测踩过（用户现场）：机器上 PATH 里排前面的 python 是 **3.11**，脚本"拿到哪个用哪个"→ 装依赖时报
#    "No matching distribution found for numpy==2.5.3 (from versions: ...2.4.6)"（cp311 上根本没有 2.5.3）。
#    所以这里**校验版本**，并优先用 py -3.12 找解释器。
function Get-PyVer([string]$Exe) {
    if (-not $Exe -or -not (Test-Path $Exe)) { return '' }
    try { return ("$(& $Exe -c 'import sys;print(str(sys.version_info[0]) + chr(46) + str(sys.version_info[1]))' 2>$null)").Trim() }
    catch { return '' }
}
function Find-Python312 {
    # ① py 启动器最可靠（装了 3.12 就能找到，不必进 PATH）
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        try {
            $exe = ("$(& py -3.12 -c 'import sys;print(sys.executable)' 2>$null | Select-Object -First 1)").Trim()
            if ((Get-PyVer $exe) -eq '3.12') { return $exe }
        } catch {}
    }
    # ② 常见安装位置
    foreach ($p in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
                     'C:\Python312\python.exe', 'C:\Program Files\Python312\python.exe',
                     'D:\Python312\python.exe', 'D:\python\Python312\python.exe')) {
        if ((Get-PyVer $p) -eq '3.12') { return $p }
    }
    # ③ PATH 里的 python / python3（只有版本正好 3.12 才用）
    foreach ($cmd in 'python.exe', 'python3.exe') {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c -and (Get-PyVer $c.Source) -eq '3.12') { return $c.Source }
    }
    return ''
}
$PyHint = '本平台要求 Python 3.12（requirements.txt 里 numpy==2.5.3 需 >=3.12、tensorflow 2.21 只有 3.12 的轮子）。' +
          "`n        装一个：https://www.python.org/downloads/release/python-31210/  （安装时勾不勾 Add to PATH 都行，脚本会用 py -3.12 找）"
if (Test-Path $Py) {
    $curVer = Get-PyVer $Py
    if ($curVer -ne '3.12') {
        if ($RecreateVenv -and -not $DryRun) {
            Warn "现有 venv 是 Python $curVer（要求 3.12）→ 按 -RecreateVenv 重建"
            Remove-Item -Recurse -Force (Join-Path $Srv 'venv')
        } else {
            Die "现有 venv 用的是 Python $curVer，但要求 3.12 —— 继续装会在 numpy==2.5.3 上失败。`n        修：删掉 $(Join-Path $Srv 'venv') 后重跑；或执行  start.bat -RecreateVenv  （自动重建）"
        }
    }
}
if (-not (Test-Path $Py)) {
    $PyExe = Find-Python312
    Info '缺少 venv，创建并安装依赖（需联网；内网请用 docs\离线部署\ 的离线 wheel 方案）...'
    if (-not $PyExe) {
        Warn '本机没有 Python 3.12 —— 自动下载并静默安装（约 26MB；仅当前用户，不需要管理员）'
        Info '  （离线机器：把 python-3.12*.exe 放到 tools\ 下，或用 -PythonInstaller 指定路径）'
        if ($SkipPythonInstall) { Die "指定了 -SkipPythonInstall，但本机没有 Python 3.12。$PyHint" }
        if (-not $DryRun) { Install-Python312; $PyExe = Find-Python312 }
    }
    Info "会用的解释器：$(if ($PyExe) { $PyExe } else { '（dry-run：本机没有 3.12，真实运行会自动下载安装）' })"
    if (-not $PyExe -and -not $DryRun) { Die "装完仍找不到 Python 3.12。$PyHint" }
    if ($DryRun) { Info '[dry-run] 会创建 venv 并 pip install -r requirements.txt' }
    else {
        & $PyExe -m venv (Join-Path $Srv 'venv')
        if (-not (Test-Path $Py)) { Die '创建 venv 失败' }
        & $Py -m pip install --upgrade pip
        & $Py -m pip install -r (Join-Path $Srv 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { Die "依赖安装失败（看上面的 pip 报错；常见原因：Python 版本不是 3.12、或内网拉不到包 → 用 docs\离线部署\ 的离线 wheel）" }
    }
}
if (Test-Path $Py) { Ok "Python 环境：$(& $Py -V 2>&1)（$(Get-PyVer $Py)）" } else { Info '（dry-run：跳过 Python 环境检查）' }

# ---------------------------------------------------------------- 2) db.env（含密钥生成）
# ---------------------------------------------------------------- 2) 数据库与 db.env（**自动配置**）
# ⚠️ 目标：正常路径下**不需要人工填任何东西**。脚本自己找 MySQL 管理员 → 建库 → 建应用账号
#    （随机口令）→ 写 db.env（含随机 MODEL_SECRET_KEY）。要改（口令/库名/端口）时直接编辑
#    testRestfulProject\db.env 再重跑本脚本即可 —— 已配置好且能连上时**不会覆盖**你的改动。
$DbEnv = Join-Path $Srv 'db.env'
$DbHost = if ($env:MODEL_DB_HOST) { $env:MODEL_DB_HOST } else { '127.0.0.1' }
$DbPort = if ($env:MODEL_DB_PORT) { $env:MODEL_DB_PORT } else { '3306' }
$DbName = Read-Env 'MODEL_DB_NAME' 'model_management'
$AppUser = 'model_app'
$Mysql = Find-Mysql
$NewRootPass = ''

# ---------------------------------------------------------------- 1.5) MySQL：检测 → 没有就下载安装 → 有就查配置
$MysqlSvc = Get-Service -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(MySQL|MariaDB)' } | Select-Object -First 1
$PortListening = Get-NetTCPConnection -State Listen -LocalPort $DbPort -ErrorAction SilentlyContinue
if ($MysqlSvc) {
    Ok "检测到 MySQL 服务：$($MysqlSvc.Name)（$($MysqlSvc.Status)）"
    if (-not $DryRun -and $MysqlSvc.Status -ne 'Running') {
        Info '服务没在跑，启动它...'
        Start-Service $MysqlSvc.Name
    }
} elseif ($Mysql -and (Test-Path $Mysql)) {
    Ok "检测到 MySQL 客户端（未注册成服务）：$Mysql"
} elseif ($PortListening) {
    Ok "检测到端口 $DbPort 在监听（MySQL 在跑，按现有库处理）"
} else {
    Warn '没有检测到 MySQL —— 现在自动下载并静默安装（官方 ZIP，约 200~300MB，需要外网）'
    Info '  离线机器：把 mysql-*-winx64.zip 放到 tools\ 下（或加 -MysqlZip "路径"）再重跑'
    if ($DryRun) {
        Info '[dry-run] 会下载/解压/初始化数据目录/注册服务 MySQL/启动，然后建库建账号写 db.env'
    } elseif ($SkipMysqlInstall) {
        Die '指定了 -SkipMysqlInstall，但本机没有 MySQL：请手工安装 MySQL 后重跑'
    } else {
        $zip = $MysqlZip
        if (-not $zip) {
            $found = Get-ChildItem -Path @($Root, (Join-Path $Root 'tools'), (Join-Path $Root 'docs\离线部署')) `
                        -Recurse -Filter 'mysql-*-winx64.zip' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { $zip = $found.FullName; Info "使用本机已有的安装包：$zip" }
        }
        if (-not $zip) {
            $target = Join-Path $env:TEMP 'mysql-winx64.zip'
            $urls = @()
            if ($MysqlUrl) { $urls += $MysqlUrl }
            $urls += @(
                'https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-8.0.43-winx64.zip',
                'https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-8.0.42-winx64.zip',
                'https://cdn.mysql.com/Downloads/MySQL-8.0/mysql-8.0.43-winx64.zip'
            )
            foreach ($u in $urls) {
                try {
                    Info "下载 $u （可能较慢）..."
                    Invoke-WebRequest -Uri $u -OutFile $target -UseBasicParsing -TimeoutSec 1800
                    $zip = $target; break
                } catch { Warn "下载失败：$($_.Exception.Message)" }
            }
        }
        if (-not $zip -or -not (Test-Path $zip)) {
            Die '没能获得 MySQL 安装包（离线机器请把 mysql-*-winx64.zip 放到 tools\ 下再重跑）'
        }
        $installDir = if ($MysqlDir) { $MysqlDir } else { 'C:\mysql' }
        New-Item -ItemType Directory -Force -Path $installDir | Out-Null
        Info "解压到 $installDir ..."
        Expand-Archive -Path $zip -DestinationPath $installDir -Force
        $base = Get-ChildItem $installDir -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like 'mysql-*winx64*' } | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $base) { Die "解压后没找到 mysql-*-winx64 目录：$installDir" }
        $mysqld = Join-Path $base.FullName 'bin\mysqld.exe'
        $dataDir = Join-Path $base.FullName 'data'
        $ini = Join-Path $base.FullName 'my.ini'
        if (-not (Test-Path $dataDir)) {
            Info '初始化数据目录（此时 root@localhost 无口令）...'
            & $mysqld --initialize-insecure --basedir="$($base.FullName)" --datadir="$dataDir"
            if ($LASTEXITCODE -ne 0) { Die 'mysqld --initialize-insecure 失败（看上面的报错）' }
        }
        @"
[mysqld]
basedir=$($base.FullName)
datadir=$dataDir
port=$DbPort
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
"@ | ForEach-Object { Write-Text $ini $_ }
        Info '注册并启动 Windows 服务 MySQL ...'
        & $mysqld --install MySQL --defaults-file="$ini"
        Start-Service MySQL
        # root 置一个随机口令（本机专用），并记进 db.env 的注释里方便以后管理
        $NewRootPass = New-Secret 12
        $mysqlClient = Join-Path $base.FullName 'bin\mysql.exe'
        & $mysqlClient -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '$NewRootPass'; FLUSH PRIVILEGES;"
        $Mysql = $mysqlClient
        Ok 'MySQL 已安装并启动（服务名 MySQL）'
    }
}
if (-not $Mysql -and -not $DryRun) {
    Die '找不到 mysql.exe：请安装 MySQL（或把它的 bin 加进 PATH）后重跑'
}

function New-Secret([int]$Bytes = 32) {
    $b = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    -join ($b | ForEach-Object { $_.ToString('x2') })
}
function Test-Mysql([string]$User, [string]$Pass) {
    if ($DryRun -or -not $Mysql) { return $false }
    $env:MYSQL_PWD = $Pass
    & $Mysql -h $DbHost -P $DbPort -u $User --connect-timeout=5 -N -B -e 'SELECT 1' 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function Invoke-Sql([string]$User, [string]$Pass, [string]$Sql) {
    $env:MYSQL_PWD = $Pass
    return (& $Mysql -h $DbHost -P $DbPort -u $User --default-character-set=utf8mb4 -e $Sql 2>&1 | Out-String)
}

$CurUser = Read-Env 'MODEL_DB_USER' ''
$CurPass = Read-Env 'MODEL_DB_PASSWORD' ''
$Configured = $false
if ($DryRun -and $CurUser -and (Test-Path $DbEnv)) {
    # dry-run 里不真连库：已有 db.env 且写了账号，就按"沿用"来播报（更贴近真实行为）
    $Configured = $true
    Ok "检测到现有 db.env（${CurUser}@${DbHost}:${DbPort}/${DbName}）—— 真实运行时能连上就沿用，不会覆盖"
} elseif ($CurUser -and (Test-Mysql $CurUser $CurPass)) {
    $Configured = $true
    Ok "数据库已配置好（${CurUser}@${DbHost}:${DbPort}/${DbName}），沿用现有 db.env"
    $Secret = Read-Env 'MODEL_SECRET_KEY' ''
    if ([string]::IsNullOrWhiteSpace($Secret)) {
        if ($DryRun) { Info '[dry-run] 会补一个 MODEL_SECRET_KEY 写回 db.env' }
        else {
            $Secret = New-Secret 32
            $text = Get-Content $DbEnv -Raw -Encoding UTF8
            if ($text -match '(?m)^\s*MODEL_SECRET_KEY\s*=') {
                $text = $text -replace '(?m)^\s*MODEL_SECRET_KEY\s*=.*$', "MODEL_SECRET_KEY=$Secret"
            } else { $text = $text.TrimEnd() + "`r`nMODEL_SECRET_KEY=$Secret`r`n" }
            Write-Text $DbEnv $text
            Ok '已补写 MODEL_SECRET_KEY（Token 不会因重启失效）'
        }
    }
} else {
    Info '正在自动配置数据库（建库 → 建应用账号 → 写 db.env）...'
    # 找有建库权限的账号：命令行参数 → 现有 db.env → 常见默认 → 交互询问（只在都失败时问一次）
    $cands = @()
    if ($DbUser) { $cands += , @($DbUser, $DbPassword) }
    if ($NewRootPass) { $cands += , @('root', $NewRootPass) }   # 刚自动装好的 MySQL：root 用这次生成的口令
    if ($CurUser) { $cands += , @($CurUser, $CurPass) }
    foreach ($p in @('', 'root', '123456', 'Admin@2026')) { $cands += , @('root', $p) }
    $Admin = $null
    if ($DryRun) { $Admin = @('root', '（dry-run）') }
    else {
        foreach ($c in $cands) { if ($c[0] -and (Test-Mysql $c[0] $c[1])) { $Admin = $c; break } }
    }
    if (-not $Admin -and -not $DryRun) {
        Warn '常见账号都没连上 MySQL。请输入一个**有建库权限**的账号（例如 root）：'
        $u = Read-Host '  MySQL 账号 [root]'; if (-not $u) { $u = 'root' }
        $sec = Read-Host "  MySQL 口令（$u）" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
        if (Test-Mysql $u $plain) { $Admin = @($u, $plain) }
    }
    if (-not $Admin) {
        if ($DryRun) { Info '[dry-run] 会用管理员账号执行建库/建账号/授权，并写 db.env' }
        else { Die "连不上 MySQL（${DbHost}:${DbPort}）。请确认 MySQL 服务已启动、账号口令正确后重跑；也可以手工填好 $DbEnv 再重跑" }
    }
    $AppPass = New-Secret 16
    $Secret = New-Secret 32
    if (-not $DryRun) {
        $null = Invoke-Sql $Admin[0] $Admin[1] "CREATE DATABASE IF NOT EXISTS $DbName DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        $null = Invoke-Sql $Admin[0] $Admin[1] "CREATE USER IF NOT EXISTS '$AppUser'@'localhost' IDENTIFIED BY '$AppPass';"
        $null = Invoke-Sql $Admin[0] $Admin[1] "GRANT ALL PRIVILEGES ON $DbName.* TO '$AppUser'@'localhost'; FLUSH PRIVILEGES;"
        if (-not (Test-Mysql $AppUser $AppPass)) {
            # 账号已存在但口令不是这次的（这个账号是本项目专用的，重置成新口令最省事）
            $null = Invoke-Sql $Admin[0] $Admin[1] "ALTER USER '$AppUser'@'localhost' IDENTIFIED BY '$AppPass'; FLUSH PRIVILEGES;"
        }
        if (-not (Test-Mysql $AppUser $AppPass)) { Die "应用账号 $AppUser 已创建但连不上：检查 MySQL 的认证插件与权限" }
        $text = @"
# 由 deploy 脚本自动生成（$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')）
# 要改口令 / 库名 / 端口：直接编辑本文件，再重跑一次 deploy 即可（脚本不会覆盖能连上的配置）。
$(if ($NewRootPass) { "# MySQL 管理员（root@localhost）口令 = $NewRootPass  —— 本机专用，装 MySQL 时自动生成`r`n" })
MODEL_DB_DIALECT=mysql
MODEL_DB_HOST=$DbHost
MODEL_DB_PORT=$DbPort
MODEL_DB_USER=$AppUser
MODEL_DB_PASSWORD=$AppPass
MODEL_DB_NAME=$DbName
MODEL_SECRET_KEY=$Secret
MODEL_TOKEN_TTL_HOURS=12
MODEL_BOOTSTRAP_ADMIN_PASSWORD=
"@
        if (Test-Path $DbEnv) { Copy-Item $DbEnv "$DbEnv.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')" -Force }
        Write-Text $DbEnv $text
        $CurUser = $AppUser; $CurPass = $AppPass; $Configured = $true
        Ok "已建库 $DbName、建账号 $AppUser（随机口令），并写好 $DbEnv"
        Info "  账号口令与 MODEL_SECRET_KEY 都在这个文件里；要改就编辑它再重跑"
    }
}
$DbUser = $CurUser; $DbPass = $CurPass
if (-not $DryRun -and -not $Configured) { Die '数据库配置未完成' }
Info "数据库：${DbUser}@${DbHost}:${DbPort}/${DbName}"

# 「查配置」：连上之后问服务端**真实的端口与版本**，写进 db.env 的是实际值而不是我们的猜测
if (-not $DryRun -and $Configured) {
    $env:MYSQL_PWD = $DbPass
    $srvInfo = (& $Mysql -h $DbHost -P $DbPort -u $DbUser -N -B -e 'SELECT CONCAT(@@port, " ", @@version)' 2>$null |
                Out-String).Trim()
    if ($srvInfo) {
        $parts = $srvInfo -split '\s+', 2
        if ($parts[0] -match '^\d+$' -and $parts[0] -ne $DbPort) {
            Info "服务端报告实际端口是 $($parts[0])（配置里写的是 $DbPort），按实际值更新 db.env"
            ((Get-Content $DbEnv -Raw -Encoding UTF8) -replace '(?m)^\s*MODEL_DB_PORT\s*=.*$', "MODEL_DB_PORT=$($parts[0])") |
                ForEach-Object { Write-Text $DbEnv $_ }
            $DbPort = $parts[0]
        }
        if ($parts.Count -gt 1) { Ok "MySQL 版本：$($parts[1])（端口 $DbPort）" }
    }
}

# ---------------------------------------------------------------- 3) 前端产物
$Dist = Join-Path $Fe 'dist\index.html'
if ((-not (Test-Path $Dist)) -or $Rebuild) {
    if ($DryRun) { Info "[dry-run] 会构建前端产物：cd $Fe; npm install; npm run build" }
    elseif (Get-Command npm -ErrorAction SilentlyContinue) {
        Info '构建前端产物（首次约 1 分钟）...'
        $hadDist = Test-Path $Dist
        Push-Location $Fe
        if (-not (Test-Path (Join-Path $Fe 'node_modules'))) { npm install }
        npm run build
        Pop-Location
        # ⚠️ 构建失败时不要把整条命令弄挂：只要之前已有旧产物就继续用旧的（网站不能停在半更新状态）
        if (Test-Path $Dist) { Ok '前端产物已生成' }
        elseif ($hadDist) { Warn '前端构建失败，但之前已有产物 —— 本次继续用旧的；修好上面的报错再重跑' }
        else { Die "前端构建失败且没有旧产物：在 $Fe 里跑 npm install && npm run build" }
    } else {
        Die "缺少 $Dist 且本机没有 npm —— 请在有 Node.js 的机器上构建后把 dist 拷过来（单端口模式必须有它）"
    }
}
if (Test-Path $Dist) { Ok "前端产物：$Fe\dist" } else { Info '（dry-run：前端产物尚未生成）' }

# ---------------------------------------------------------------- 4) 建库建表（用刚配好的应用账号）
Info '应用表结构（库名按 MODEL_DB_NAME 替换）...'
$env:MYSQL_PWD = $DbPass          # ⚠️ 口令走环境变量，不出现在命令行里
$mysqlArgs = @("-h", $DbHost, "-P", $DbPort, "-u", $DbUser, "--default-character-set=utf8mb4")
function Apply-Sql([string]$File) {
    if ($DryRun) { Info "[dry-run] 会执行：$File（库名按 MODEL_DB_NAME 替换）"; return }
    $sql = Get-Content $File -Raw -Encoding UTF8
    if ($DbName -ne 'model_management') {
        # 反引号用 [char]96 拼，别在双引号里玩转义（容易把 SQL 里的反引号吃掉）
        $bt = [char]96
        $sql = $sql.Replace(($bt + 'model_management' + $bt), ($bt + $DbName + $bt))
    }
    $tmp = [System.IO.Path]::GetTempFileName()
    Write-Text $tmp $sql
    Get-Content $tmp -Raw -Encoding UTF8 | & $Mysql @mysqlArgs
    $code = $LASTEXITCODE
    Remove-Item $tmp -Force
    if ($code -ne 0) { Die "执行失败：$File" }
}
Apply-Sql (Join-Path $Srv 'sql\schema_mysql.sql')
$auth = Join-Path $Srv 'sql\auth-migration.sql'
if (Test-Path $auth) { Apply-Sql $auth }
if ($DryRun) { Info "[dry-run] 会校验库 $DbName 里有 11 张表" }
else {
    $tables = (& $Mysql @mysqlArgs -N -B -e "SHOW TABLES FROM ``$DbName``" 2>$null) |
              ForEach-Object { $_.ToString().ToLower() }
    $expect = @('datasets','models','edgedevices','trainings','modelinvocations','modeldeployments',
                'inferencetasks','inferenceresults','roles','users','operationlogs')
    $missing = $expect | Where-Object { $tables -notcontains $_ }
    if ($missing.Count -gt 0) {
        Warn "库里缺这些表：$($missing -join ', ') —— 检查上面的报错"
    } else { Ok "库表就位：$($tables.Count) 张" }
}
Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- 5) 前台跑（start.bat run：不装服务）
$serveArgs = "serve.py --host 0.0.0.0 --port $Port --threads $Threads"
if ($Foreground) {
    if (-not (Test-Path $Py)) { Die '还没有 venv：先执行 start.bat（不带参数）装依赖' }
    Write-Host ''
    Write-Host '============================================================'
    Write-Host "  前台运行（不装服务）：按 Ctrl+C 停止"
    Write-Host "  本机访问   : http://127.0.0.1:$Port/"
    Write-Host '  初始账号   : admin / Admin@2026'
    Write-Host '============================================================'
    Write-Host ''
    if (-not $env:NO_BROWSER) {
        Start-Process -WindowStyle Hidden powershell -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', (Join-Path $Root 'tools\open-when-ready.ps1'),
            '-Url', "http://127.0.0.1:$Port/", '-Health', "http://127.0.0.1:$Port/health")
    }
    Push-Location $Srv
    & $Py (Join-Path $Srv 'serve.py') --host 0.0.0.0 --port $Port --threads $Threads
    Pop-Location
    exit 0
}

# ---------------------------------------------------------------- 6) 注册成开机自启的常驻服务（**幂等：已存在就更新配置再重启**）
$Nssm = Find-Nssm
if ($Nssm) {
    $svcExists = [bool](Get-Service -Name $SvcName -ErrorAction SilentlyContinue)
    Info "用 nssm 装成 Windows 服务：$Nssm$(if ($svcExists) { '（服务已存在 → 只更新配置并重启）' } else { '' })"
    Step "& '$Nssm' install $SvcName '$Py' '$serveArgs'"
    Step "& '$Nssm' set $SvcName AppDirectory '$Srv'"
    Step "& '$Nssm' set $SvcName AppStdout '$LogFile'"
    Step "& '$Nssm' set $SvcName AppStderr '$LogFile'"
    Step "& '$Nssm' set $SvcName AppRotateFiles 1"
    Step "& '$Nssm' set $SvcName AppRotateBytes 10485760"
    Step "& '$Nssm' set $SvcName AppExit Default Restart"
    Step "& '$Nssm' set $SvcName AppRestartDelay 15000"
    Step "& '$Nssm' set $SvcName Start SERVICE_AUTO_START"
    Step "& '$Nssm' restart $SvcName"
} else {
    Warn '没找到 nssm.exe → 退化为「计划任务（开机启动、以 SYSTEM 运行）」方式，效果一致'
    Info '（想用真正的 Windows 服务：把 nssm.exe 放到 tools\ 下再跑一次即可升级）'
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
    $tr = "cmd /c cd /d `"$Srv`" && `"$Py`" $serveArgs >> `"$LogFile`" 2>&1"
    # /F = 已存在就覆盖（幂等）；/Run 在已在运行时会给非零退出码 → 忽略即可
    Step "schtasks /Create /TN $TaskName /SC ONSTART /RU SYSTEM /RL HIGHEST /F /TR `"$tr`""
    Step "schtasks /Run /TN $TaskName"
    if (-not $DryRun) {
        & schtasks /Create /TN $TaskName /SC ONSTART /RU SYSTEM /RL HIGHEST /F /TR $tr | Out-Null
        & schtasks /Run /TN $TaskName 2>$null | Out-Null
    }
}
if ($DryRun) { Info '[dry-run] 会注册/更新开机自启服务' } else { Ok '服务已注册为开机自启（重复执行不会报错）' }

# ---------------------------------------------------------------- 7) 防火墙（已放行不重复添加）
$rule = "ModelPlatform $Port"
if (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue) {
    Info "防火墙规则已存在：$rule（无需重复添加）"
} else {
    Step "New-NetFirewallRule -DisplayName '$rule' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null"
    if ($DryRun) { Info "[dry-run] 会放行防火墙 $Port/tcp" } else { Ok "已放行防火墙 $Port/tcp" }
}

# ---------------------------------------------------------------- 8) 结果
$lan = Get-LanIp
Write-Host ''
Write-Host '============================================================'
Write-Host "  本机访问   : http://127.0.0.1:$Port/"
if ($lan) { Write-Host "  局域网访问 : http://${lan}:$Port/     ← 把这个地址发给同事" -ForegroundColor Cyan }
Write-Host '  初始账号   : admin / Admin@2026（交付现场请立刻改口令）'
Write-Host '  更新代码   : update.bat    （或 start.bat update）'
Write-Host '  停止 / 其它: stop.bat / end.bat   |   start.bat status logs restart uninstall'
Write-Host '============================================================'

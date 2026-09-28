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

# ---------------------------------------------------------------- 子命令
switch ($Action.ToLower()) {
    'status' {
        $mode = Get-ServiceMode
        if ($mode -eq 'service') {
            Get-Service $SvcName | Format-Table Name, Status, StartType -AutoSize | Out-String | Write-Host
        } elseif ($mode -eq 'task') {
            Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-Table -AutoSize | Out-String | Write-Host
        } else { Warn "还没安装（先执行 deploy.bat）" }
        $listen = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        if ($listen) { Ok "端口 $Port 正在监听（PID $($listen[0].OwningProcess)）" } else { Warn "端口 $Port 没有监听" }
        if (Test-Path $LogFile) { Info "最近日志："; Get-Content $LogFile -Tail 12 | ForEach-Object { Info $_ } }
        exit 0
    }
    'logs' {
        if (-not (Test-Path $LogFile)) { Die "还没有日志文件：$LogFile（服务没跑过？）" }
        Get-Content $LogFile -Tail 60 -Wait
        exit 0
    }
    'restart' { Need-Admin; if ((Get-ServiceMode) -eq 'service') { Restart-Service $SvcName -Force } else { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName $TaskName }; Ok '已重启'; exit 0 }
    'start'   { Need-Admin; if ((Get-ServiceMode) -eq 'service') { Start-Service $SvcName } else { Start-ScheduledTask -TaskName $TaskName }; Ok '已启动'; exit 0 }
    'stop'    { Need-Admin; if ((Get-ServiceMode) -eq 'service') { Stop-Service $SvcName -Force } else { Stop-ScheduledTask -TaskName $TaskName }; Ok '已停止'; exit 0 }
    'uninstall' {
        Need-Admin
        $mode = Get-ServiceMode
        if ($mode -eq 'service') {
            $nssm = Find-Nssm
            if ($nssm) { Step "& '$nssm' stop $SvcName"; Step "& '$nssm' remove $SvcName confirm" }
            else { Step "Stop-Service $SvcName -Force"; Step "sc.exe delete $SvcName" }
        } elseif ($mode -eq 'task') {
            Step "Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
        } else { Warn '没找到已安装的服务/计划任务' }
        Step "Remove-NetFirewallRule -DisplayName 'ModelPlatform $Port' -ErrorAction SilentlyContinue"
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

# ---------------------------------------------------------------- 1) Python 环境
if (-not (Test-Path $Py)) {
    Info '缺少 venv，创建并安装依赖（需联网；内网请用 docs\离线部署\ 的离线 wheel 方案）...'
    if ($DryRun) { Info '[dry-run] 会创建 venv 并 pip install -r requirements.txt' }
    else {
        $base = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $base) { Die '找不到 python.exe：请先安装 Python 3.12/3.14 并勾选 Add to PATH' }
        & $base.Source -m venv (Join-Path $Srv 'venv')
        if (-not (Test-Path $Py)) { Die '创建 venv 失败' }
        & $Py -m pip install --upgrade pip
        & $Py -m pip install -r (Join-Path $Srv 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { Die '依赖安装失败' }
    }
}
if (Test-Path $Py) { Ok "Python 环境：$(& $Py -V 2>&1)" } else { Info '（dry-run：跳过 Python 环境检查）' }

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
if (-not $Mysql -and -not $DryRun) { Die '找不到 mysql.exe：请安装 MySQL（或把它的 bin 加进 PATH）后重跑' }

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
            Set-Content -Path $DbEnv -Value $text -Encoding UTF8 -NoNewline
            Ok '已补写 MODEL_SECRET_KEY（Token 不会因重启失效）'
        }
    }
} else {
    Info '正在自动配置数据库（建库 → 建应用账号 → 写 db.env）...'
    # 找有建库权限的账号：命令行参数 → 现有 db.env → 常见默认 → 交互询问（只在都失败时问一次）
    $cands = @()
    if ($DbUser) { $cands += , @($DbUser, $DbPassword) }
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
        Set-Content -Path $DbEnv -Value $text -Encoding UTF8 -NoNewline
        $CurUser = $AppUser; $CurPass = $AppPass; $Configured = $true
        Ok "已建库 $DbName、建账号 $AppUser（随机口令），并写好 $DbEnv"
        Info "  账号口令与 MODEL_SECRET_KEY 都在这个文件里；要改就编辑它再重跑"
    }
}
$DbUser = $CurUser; $DbPass = $CurPass
if (-not $DryRun -and -not $Configured) { Die '数据库配置未完成' }
Info "数据库：${DbUser}@${DbHost}:${DbPort}/${DbName}"

# ---------------------------------------------------------------- 3) 前端产物
$Dist = Join-Path $Fe 'dist\index.html'
if ((-not (Test-Path $Dist)) -or $Rebuild) {
    if ($DryRun) { Info "[dry-run] 会构建前端产物：cd $Fe; npm install; npm run build" }
    elseif (Get-Command npm -ErrorAction SilentlyContinue) {
        Info '构建前端产物（首次约 1 分钟）...'
        Push-Location $Fe
        if (-not (Test-Path (Join-Path $Fe 'node_modules'))) { npm install }
        npm run build
        Pop-Location
        if (-not (Test-Path $Dist)) { Die "前端构建失败：在 $Fe 里跑 npm install && npm run build" }
        Ok '前端产物已生成'
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
    Set-Content -Path $tmp -Value $sql -Encoding UTF8 -NoNewline
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

# ---------------------------------------------------------------- 5) 注册成开机自启的常驻服务
$serveArgs = "serve.py --host 0.0.0.0 --port $Port --threads $Threads"
$Nssm = Find-Nssm
if ($Nssm) {
    Info "用 nssm 装成 Windows 服务：$Nssm"
    Step "& '$Nssm' install $SvcName '$Py' '$serveArgs'"
    Step "& '$Nssm' set $SvcName AppDirectory '$Srv'"
    Step "& '$Nssm' set $SvcName AppStdout '$LogFile'"
    Step "& '$Nssm' set $SvcName AppStderr '$LogFile'"
    Step "& '$Nssm' set $SvcName AppRotateFiles 1"
    Step "& '$Nssm' set $SvcName AppRotateBytes 10485760"
    Step "& '$Nssm' set $SvcName AppExit Default Restart"
    Step "& '$Nssm' set $SvcName AppRestartDelay 15000"
    Step "& '$Nssm' set $SvcName Start SERVICE_AUTO_START"
    Step "Start-Service $SvcName"
} else {
    Warn '没找到 nssm.exe → 退化为「计划任务（开机启动、以 SYSTEM 运行）」方式，效果一致'
    Info '（想用真正的 Windows 服务：把 nssm.exe 放到 tools\ 下再跑一次本脚本即可升级）'
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
    $tr = "cmd /c cd /d `"$Srv`" && `"$Py`" $serveArgs >> `"$LogFile`" 2>&1"
    Step "schtasks /Create /TN $TaskName /SC ONSTART /RU SYSTEM /RL HIGHEST /F /TR `"$tr`""
    Step "schtasks /Run /TN $TaskName"
}
if ($DryRun) { Info '[dry-run] 会注册开机自启服务' } else { Ok '服务已注册为开机自启' }

# ---------------------------------------------------------------- 6) 防火墙
$rule = "ModelPlatform $Port"
if (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue) {
    Info "防火墙规则已存在：$rule"
} else {
    Step "New-NetFirewallRule -DisplayName '$rule' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null"
    if ($DryRun) { Info "[dry-run] 会放行防火墙 $Port/tcp" } else { Ok "已放行防火墙 $Port/tcp" }
}

# ---------------------------------------------------------------- 7) 结果
$lan = Get-LanIp
Write-Host ''
Write-Host '============================================================'
Write-Host "  本机访问   : http://127.0.0.1:$Port/"
if ($lan) { Write-Host "  局域网访问 : http://${lan}:$Port/     ← 把这个地址发给同事" -ForegroundColor Cyan }
Write-Host '  初始账号   : admin / Admin@2026（交付现场请立刻改口令）'
Write-Host '  常用命令   : deploy.bat status | logs | restart | upgrade | uninstall'
Write-Host '============================================================'

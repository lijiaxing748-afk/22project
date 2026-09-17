# =====================================================================
#  代码更新包制作脚本（在**你自己的笔记本**上运行）
#
#  用途：代码改完之后，打一个"只含代码"的小包，用优盘拷到实验室电脑覆盖，
#        不用重装环境、不用重装依赖。
#
#  核心认知：实验室电脑上只有两类东西
#      ① 环境（装一次就不动）: Python / Node.js / MySQL / VC++ 运行库 / venv / node_modules
#      ② 代码（改了就要更新）: .py / .vue / .ts / .html / .sql / .json 配置
#
#    本脚本只打包 ②，所以很小（通常几 MB），而且**永远不会破坏环境**。
#
#  用法：
#      右键本文件 ->「使用 PowerShell 运行」
#      或命令行： powershell -ExecutionPolicy Bypass -File "本文件路径"
# =====================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "   [OK]   $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "   [提示] $m" -ForegroundColor Yellow }
function Err  ($m) { Write-Host "   [错误] $m" -ForegroundColor Red }

# 项目根目录：本脚本在 tools/ 下，所以往上一级就是项目根；
# 但也要兼容"把脚本单独拷到项目根运行"的情况，所以两种都试。
$Root = $PSScriptRoot
if (-not (Test-Path (Join-Path $Root 'testRestfulProject'))) {
    $parent = Split-Path $Root -Parent
    if (Test-Path (Join-Path $parent 'testRestfulProject')) {
        $Root = $parent
    }
}

Say "============================================================"
Say "  制作代码更新包"
Say "============================================================"
Say "  项目根目录: $Root"
Say ""

# ---------------------------------------------------------------- 1 检查
Say "[1] 检查项目结构"
$be = Join-Path $Root 'testRestfulProject'
$fe = Join-Path $Root 'frontend\22project'
$miss = 0
foreach ($p in @($be, $fe)) {
    if (Test-Path $p) { Ok "找到 $(Split-Path $p -Leaf)" }
    else { Err "找不到 $p"; $miss++ }
}
if ($miss -gt 0) {
    Err "请在项目根目录（含 testRestfulProject 和 frontend 的那个目录）里运行本脚本"
    Read-Host "按回车退出"
    exit 1
}
Say ""

# ---------------------------------------------------------------- 2 目标位置
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outName = "code-update-$stamp"
$out = Join-Path $Root $outName
New-Item -ItemType Directory -Force -Path $out | Out-Null
Ok "输出目录: $outName"
Say ""

# ---------------------------------------------------------------- 3 复制后端代码
Say "[2] 打包后端代码 testRestfulProject\"

function Copy-Filtered {
    param($Src, $Dst, [scriptblock]$Skip)

    if (-not (Test-Path $Src)) { return 0 }
    $count = 0
    Get-ChildItem $Src -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $full = $_.FullName
        if ($Skip -and (& $Skip $full $_)) { return }
        $rel = $full.Substring($Src.Length).TrimStart('\')
        $target = Join-Path $Dst $rel
        $dir = Split-Path $target -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        Copy-Item $full $target -Force
        $count++
    }
    return $count
}

# 后端：排除环境和运行期产物
# ⚠️ 数据集（.mat/.csv）也排除：它们是**输入数据**不是代码，几十 MB 且几乎不变。
#    真要更新数据集，单独拷贝对应目录即可（README 里会说明）。
$beSkip = {
    param($full, $item)
    $full -match '\\venv\\'            -or
    $full -match '__pycache__'         -or
    $full -match '\.pyc$'              -or
    $full -match '\\data\\logs\\'      -or
    $full -match '\\data\\figures\\'   -or
    $full -match '\\data\\tmp\\'       -or
    $full -match '\\data\\uploads\\'   -or
    $full -match '\\data\\archive\\'   -or
    $full -match '\\data\\datasets\\'  -or
    # 模型发布包（data/exports/）：运行期产物，离线机自己发布会生成，不需要随代码更新传
    $full -match '\\data\\exports\\'   -or
    # 训练产物（data/models/）：**必须排除**。
    #   它跟"代码"不是一回事：模型是在哪台机器上训出来的，就归哪台机器。
    #   带上它的后果是——实验室上次训好的模型会被你笔记本上的版本悄悄覆盖，
    #   而且 meta.json 里还留着你本机的绝对路径（如 D:\HUAT\22project\...），
    #   显示出来很费解。体积也不小（1~2 MB，且每次重训都变，白白撑大更新包）。
    #   ⚠️ 如果**确实想**把本机模型同步过去（比如你重训出一个更好的），
    #      不要改这里，单独拷 data\models\<模型名>\ 覆盖过去即可。
    $full -match '\\data\\models\\'    -or
    $full -match '\.mat$'              -or    # CWRU 数据集（几十 MB）
    $full -match '\\1DCNN\\0HP\\'      -or
    $full -match '\\cwt_cnn\\0HP\\'    -or
    $full -match '\.egg-info\\'        -or
    $full -match '\\\.git\\'
}
$beDst = Join-Path $out 'testRestfulProject'
$n = Copy-Filtered -Src $be -Dst $beDst -Skip $beSkip
Ok "后端 $n 个文件"

# 特别提示：db.env 是**本机配置**，不能覆盖实验室的
Say ""
Warn "注意：db.env 不做覆盖（实验室的数据库密码可能与本机不同）"
$labDbEnv = Join-Path $beDst 'db.env'
if (Test-Path $labDbEnv) { Remove-Item $labDbEnv -Force }
Ok "已从更新包里剔除 db.env"
Say ""

# ---------------------------------------------------------------- 4 复制前端代码
Say "[3] 打包前端代码 frontend\22project\src\"
$feSkip = {
    param($full, $item)
    $full -match '\\node_modules\\' -or
    $full -match '\\dist\\'         -or
    $full -match '\\\.vite\\'       -or
    $full -match '\\\.git\\'
}
$feDst = Join-Path $out 'frontend\22project'
# 只拷 src，加上几个配置文件
$n = Copy-Filtered -Src (Join-Path $fe 'src') -Dst (Join-Path $feDst 'src') -Skip $feSkip
Ok "前端 src $n 个文件"

# 前端配置类文件（改了也要同步）
$feFiles = @('package.json', 'package-lock.json', 'index.html',
             '.env.development', 'vite.config.ts', 'tsconfig.json',
             'postcss.config.cjs', 'tailwind.config.js')
foreach ($f in $feFiles) {
    $src = Join-Path $fe $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $feDst $f) -Force
        Ok "  $f"
    }
}
Say ""

# ---------------------------------------------------------------- 5 统计
Say "[4] 更新包内容"

# 统计体积（排除 .mat / 模型权重这类大产物，它们本来就极少变）
$files = Get-ChildItem $out -Recurse -File -Force
$total = ($files | Measure-Object Length -Sum).Sum
"     文件数: $($files.Count)"
"     总体积: $([math]::Round($total/1MB, 1)) MB"

# ⚠️ 如果这里突然变成几十 MB，八成是不小心带上了 .mat 数据集或训练产物。
#    正常情况下代码包只有几 MB；超大就说明排除规则漏了东西，先查再拷。
if ($total/1MB -gt 20) {
    Warn "更新包体积偏大（$([math]::Round($total/1MB, 1)) MB），下面列出的文件里找找有没有不该带的"
}

# 把最大的几个文件列出来，防止意外带上大文件
$big = $files | Sort-Object Length -Descending | Select-Object -First 5
if ($big.Count -gt 0) {
    Say ""
    Say "     最大的 5 个文件（确认没有意外的大文件）："
    foreach ($b in $big) {
        $rel = $b.FullName.Substring($out.Length).TrimStart('\')
        "       {0,8:N2} MB  {1}" -f ($b.Length/1MB), $rel
    }
}
Say ""

# ---------------------------------------------------------------- 6 写说明
$readme = @"
# 代码更新包 $stamp

## 怎么用（在实验室电脑上）

1. 把本文件夹整个拷到实验室电脑（优盘/网线都行，通常只有几 MB）
2. **先关掉后端和前端那两个窗口**
3. 在实验室电脑上运行 ``应用更新.ps1``（右键 ->「使用 PowerShell 运行」）
   或者手动把这两个目录覆盖过去：
       code-update-*/testRestfulProject/     ->  04-项目源码/testRestfulProject/
       code-update-*/frontend/22project/     ->  04-项目源码/frontend/22project/
4. 重新运行 ``06-部署脚本/run.bat 04`` 启动

## 为什么这么快

实验室电脑上这些东西**不用重装**（装一次就够了）：
    Python / Node.js / MySQL / VC++ 运行库
    testRestfulProject/venv          （Python 依赖）
    frontend/22project/node_modules  （前端依赖）

本包**只含代码**，所以覆盖完直接就能跑。

## 什么情况下才需要重装依赖

只有改了依赖清单才需要（很少见）：

- 后端加了新的 pip 包  -> 改了 requirements.txt
      处理：在笔记本上 ``pip download`` 新包 -> 拷过去 -> ``pip install --no-index``
- 前端加了新的 npm 包   -> 改了 package.json
      处理：在笔记本上拷贝更新后的 node_modules -> 覆盖过去

如果只是改 .py / .vue / .ts 这些代码，**永远不需要重装依赖**。
"@
$readme | Out-File -FilePath (Join-Path $out 'README-更新说明.md') -Encoding UTF8
Ok "已写入 README-更新说明.md"
Say ""

Say "============================================================"
Say "  完成！更新包位置：" -ForegroundColor Green
Say "    $out" -ForegroundColor Green
Say ""
Say "  下一步：把上面这个文件夹拷到优盘，带去实验室覆盖即可。"
Say "============================================================"
Read-Host "按回车退出"

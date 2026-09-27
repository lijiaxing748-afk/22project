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
    # 缓存类产物（如 data\.cache\matplotlib\fontlist-*.json）：
    # 体积很小、无害，但属于本机运行期缓存，没必要随代码更新传过去，
    # 覆盖过去反而可能让实验室机器的字体缓存与它的 matplotlib 版本对不上。
    $full -match '\\data\\\.cache\\'   -or
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

# ---------------------------------------------------------------- 4a 带上前端构建产物 dist
# ⚠️ 这一步以前**不存在**，是"改了前端却看不到效果"的根因：
#    .env / .ts / .vue 这些**源码**改了，但实验室机器上跑的是 `npm run build`
#    出来的 dist/（纯静态文件）。只覆盖源码、不覆盖 dist，等于没改 ——
#    浏览器加载的还是旧 JS。而且 apply-update.ps1 复制时会显式跳过 \dist\，
#    两件事叠加，前端修复永远到不了实验室机器。
#    所以这里把**当前已构建好的 dist** 一起打进去，覆盖后立即生效，
#    实验室机器不需要装 Node、也不需要重新 build。
$distSrc = Join-Path $fe 'dist'
if (Test-Path (Join-Path $distSrc 'index.html')) {
    $distDst = Join-Path $feDst 'dist'
    Copy-Item $distSrc $distDst -Recurse -Force
    $dc = (Get-ChildItem $distDst -Recurse -File | Measure-Object).Count
    $dm = [math]::Round((Get-ChildItem $distDst -Recurse -File | Measure-Object Length -Sum).Sum/1MB, 1)
    Ok "已带上前端构建产物 dist（$dc 个文件，$dm MB）"
} else {
    # 没构建过就别硬塞：提示先去 build，否则前端改动不会生效
    Warn "没找到 frontend\22project\dist（前端未构建）"
    Warn "前端改动不会生效！请先执行： npm run build:singleport"
}

# ---------------------------------------------------------------- 4b 带上应用脚本
# ⚠️ 这一步以前**不存在**，是个会让更新流程走不通的漏洞：
#    下面生成的 README 让用户在实验室电脑上运行「应用更新.ps1」，
#    但打包时从来没把这个脚本放进包里 —— 结果包内一个 .ps1 都没有，
#    用户照着 README 做会发现文件不存在，只能手动复制目录（README 里的备选路径）。
#    现在把它一起打进去，README 的主路径才真正可用。
$applySrc = Join-Path $Root 'tools\apply-update.ps1'
if (Test-Path $applySrc) {
    # 包内改名为「应用更新.ps1」，与 README 的措辞一致（中文名对用户更直观）
    $applyDst = Join-Path $out '应用更新.ps1'
    Copy-Item $applySrc $applyDst -Force

    # ⚠️ 必须写成 **UTF-8 with BOM**，否则实验室机器上跑不起来。
    #    踩过的坑：Windows PowerShell 5.1（"右键 → 使用 PowerShell 运行"默认用它）
    #    对**无 BOM** 的文件按系统 ANSI 代码页（中文机器是 GBK）解码。
    #    本脚本注释里有大量中文，被按 GBK 误读后会产出乱码字节，
    #    其中某些字节会把行尾吃掉、把注释和下一行连起来，
    #    最终报出「Unexpected token '}'」「Missing closing '}'」这种
    #    **看起来像大括号不配对、实际文件完全没问题**的假故障。
    #    加了 BOM，PowerShell 才认得这是 UTF-8。
    $utf8bom = New-Object System.Text.UTF8Encoding($true)
    $bytes = [System.IO.File]::ReadAllBytes($applyDst)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    if ($hasBom) {
        Ok "已带上应用脚本 -> 应用更新.ps1（UTF-8 BOM）"
    } else {
        $text = [System.IO.File]::ReadAllText($applyDst, (New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllText($applyDst, $text, $utf8bom)
        Ok "已带上应用脚本 -> 应用更新.ps1（已补 UTF-8 BOM，防中文被 GBK 误读）"
    }
} else {
    Warn "没找到 tools\apply-update.ps1 —— 包里将缺少一键应用脚本"
    Warn "用户需要照 README 的手动复制方式操作"
}

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
   （如果系统已装成 Windows 服务，改成停止服务：``net stop ModelPlatform``）
3. 在本文件夹里运行 ``应用更新.ps1``（右键 ->「使用 PowerShell 运行」）
   脚本会自动找到实验室电脑上的项目目录并覆盖代码。
   如果不想用脚本，也可以手动覆盖这两个目录：
       <本包>/testRestfulProject/     ->  04-项目源码/testRestfulProject/
       <本包>/frontend/22project/     ->  04-项目源码/frontend/22project/
4. 启动（二选一）：
   生产模式（单端口，已装服务）: ``net start ModelPlatform``，然后浏览器开 http://本机IP:8080
   开发模式（两个窗口）        : ``06-部署脚本/run.bat 04``

## ⚠️ 本次更新说明（登录页文案精简）

本次改动很小，**不涉及数据库、不需要迁移、不用重装依赖**：

1. **登录页底部**的「Copyright © … 版权所有」和「备案号 | 帮助 | 隐私 | 条款」两行已删除
2. **登录页左上角** logo 下方的副标题「轴承故障诊断模型管理平台」已删除
3. 页面源码中移除了**百度统计脚本**（离线环境用不上，且会在控制台报错）
4. 页面 SEO 关键词中的旧名「轴承故障诊断」已统一为「模型管理平台」

覆盖步骤：

- 停止服务（或关掉前后端窗口）
- 运行 ``应用更新.ps1``
- 启动服务
- **浏览器按 ``Ctrl + F5`` 强制刷新**（否则会加载缓存里的旧 JS，看着"没生效"）

> 说明：本包同时含 ``frontend\22project\dist``（已重新构建的前端产物）。
> 实验室机器**不需要装 Node、也不需要重新 build**，覆盖后直接生效。

## 登录不上时的修复办法（重要）

实验室机器上如果出现「用户名或密码错误」，**先确认口令，别急着怀疑哈希算法**：

1. **默认口令不是 ``123456``，而是**：

   | 账号 | 口令 |
   |---|---|
   | ``admin`` | ``Admin@2026`` |
   | ``engineer`` | ``Engineer@2026`` |
   | ``operator`` | ``Operator@2026`` |

   账号不是 SQL 脚本建的，是后端**首次启动**时由 ``bootstrap_users()``
   用配置里的口令**现算哈希**插入的（见 ``main.py``）。

2. **口令确实忘了，或者手工改哈希改坏了**，用本包自带的修复脚本
   （它自己调 ``hash_password()`` 生成哈希并直接写库，**不需要手工粘贴哈希**）：

   ```powershell
   cd <项目目录>\testRestfulProject
   venv\Scripts\python.exe tools\reset-login-accounts.py
   ```

   指定新口令：

   ```powershell
   venv\Scripts\python.exe tools\reset-login-accounts.py --admin-password "你的新口令"
   ```

   只想看会改什么、不真改：加 ``--dry-run``。

   > ⚠️ **为什么不能靠重启服务修复**：``bootstrap_users()`` 第一行是
   > ``if count_users() > 0: return 0`` —— 只要 Users 表非空（比如你手工插过账号），
   > 它**永远不会**再去修正那行哈希。必须在库里直接改对，本脚本做的就是这件事。
   >
   > ⚠️ **手工 UPDATE 极易失败且是静默的**：``check_password_hash()`` 遇到
   > 前后空格会抛 ValueError（被吞掉当失败）、末尾换行或 ``$`` 被客户端吃掉会
   > 直接返回 False。列宽不是问题（``PasswordHash`` 是 VARCHAR(255)，
   > 哈希约 103 字符）。所以请用脚本，别手工复制粘贴哈希。

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

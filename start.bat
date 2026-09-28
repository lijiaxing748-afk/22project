@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 模型管理平台 - 一键启动
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SRV=%ROOT%\testRestfulProject"
set "FE=%ROOT%\frontend\22project"
set "PY=%SRV%\venv\Scripts\python.exe"
if not defined MODEL_PORT set "MODEL_PORT=8080"
set "PORT=%MODEL_PORT%"
set "MODE=%~1"

echo ============================================================
echo   模型管理平台 · 一键启动（单端口：后端同时托管前端）
echo ------------------------------------------------------------
echo   项目目录 : %ROOT%
echo   访问地址 : http://127.0.0.1:%PORT%/
echo   换端口   : set MODEL_PORT=8081   然后重新运行本脚本
echo ============================================================
echo.

if /i "%MODE%"=="setup" goto setup
if /i "%MODE%"=="build" goto build

rem ---------------------------------------------------------------- 1) Python 环境
if not exist "%PY%" goto no_venv

rem ---------------------------------------------------------------- 2) 数据库配置
if not exist "%SRV%\db.env" (
    if exist "%SRV%\db.env.example" (
        copy /y "%SRV%\db.env.example" "%SRV%\db.env" >nul
        echo [提示] 已从 db.env.example 生成 %SRV%\db.env
        echo        请打开它填 MySQL 账号/口令与 MODEL_SECRET_KEY，然后重新运行本脚本。
    ) else (
        echo [错误] 缺少 %SRV%\db.env（数据库配置），且找不到 db.env.example。
    )
    echo.
    pause
    exit /b 1
)

rem ---------------------------------------------------------------- 3) 前端产物
if not exist "%FE%\dist\index.html" (
    echo [提示] 还没有前端产物 frontend\22project\dist —— 单端口模式下必须有它。
    where npm >nul 2>nul
    if errorlevel 1 (
        echo        本机没有 npm：请在有 Node.js 的机器上执行
        echo            cd /d "%FE%"  ^&^&  npm install  ^&^&  npm run build
        echo        然后把 frontend\22project\dist 整个目录拷到这台机器。
        echo        也可以临时用开发模式：run.bat 04（在 docs\离线部署\部署脚本\）
        echo.
        pause
        exit /b 1
    )
    echo        本机有 npm，现在自动构建（首次约 1 分钟，需要 node_modules）...
    pushd "%FE%"
    if not exist "node_modules" call npm install
    call npm run build
    popd
    if not exist "%FE%\dist\index.html" (
        echo [错误] 构建后仍然找不到 dist\index.html，请看上面的报错。
        echo.
        pause
        exit /b 1
    )
    echo [OK] 前端产物已生成
    echo.
)

rem ---------------------------------------------------------------- 4) 端口占用
set "BUSY="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr /c:":%PORT% "') do set "BUSY=%%P"
if defined BUSY (
    echo [提示] 端口 %PORT% 已被占用（PID !BUSY!）—— 可能平台/前端已经在跑。
    echo        直接打开看看： http://127.0.0.1:%PORT%/
    echo        要另起一个实例就换端口：set MODEL_PORT=8081
    echo.
    choice /c YN /n /m "现在就打开浏览器？[Y/N] "
    if errorlevel 2 goto end
    start "" "http://127.0.0.1:%PORT%/"
    goto end
)

rem ---------------------------------------------------------------- 5) 启动 + 自动开浏览器
echo [1/2] 启动服务（waitress 单端口 %PORT%）... 按 Ctrl+C 停止
if not defined NO_BROWSER start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\open-when-ready.ps1" -Url "http://127.0.0.1:%PORT%/" -Health "http://127.0.0.1:%PORT%/health"
echo [2/2] 浏览器会自动打开；没弹出来就手动访问 http://127.0.0.1:%PORT%/
echo       初始账号： admin / Admin@2026   （交付现场请先改口令）
echo.
"%PY%" "%SRV%\serve.py" --host 0.0.0.0 --port %PORT% --threads 6
echo.
echo 服务已退出。
pause
goto end

rem ---------------------------------------------------------------- setup
:setup
echo [setup] 创建虚拟环境并安装依赖（需要联网；离线包请用 docs\离线部署\ 里的脚本）
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到 python。请先安装 Python 3.12/3.14 并勾选 Add to PATH。
    pause
    exit /b 1
)
if not exist "%PY%" (
    python -m venv "%SRV%\venv"
    if errorlevel 1 ( echo [错误] 创建 venv 失败。 & pause & exit /b 1 )
)
echo       安装 requirements.txt ...
"%SRV%\venv\Scripts\python.exe" -m pip install --upgrade pip
"%SRV%\venv\Scripts\python.exe" -m pip install -r "%SRV%\requirements.txt"
echo.
echo [OK] 依赖装好了。若要用单端口跑，再执行一次本脚本即可（会自动构建前端）。
pause
goto end

rem ---------------------------------------------------------------- build
:build
echo [build] 构建前端产物（frontend\22project\dist）
where npm >nul 2>nul
if errorlevel 1 ( echo [错误] 本机没有 npm / Node.js。 & pause & exit /b 1 )
pushd "%FE%"
if not exist "node_modules" call npm install
call npm run build
popd
if exist "%FE%\dist\index.html" ( echo [OK] 前端产物已生成：%FE%\dist ) else ( echo [错误] 构建失败，请看上面报错。 )
pause
goto end

rem ---------------------------------------------------------------- 缺 venv
:no_venv
echo [缺少] 虚拟环境：%SRV%\venv
echo.
echo   首次使用请在**本目录**执行下面任一条：
echo       start.bat setup        （自动建 venv 并装依赖，需联网）
echo   或手工：
echo       cd /d "%SRV%"
echo       python -m venv venv
echo       venv\Scripts\pip install -r requirements.txt
echo.
echo   离线/内网机器请改用 docs\离线部署\ 里的整套脚本（带离线 wheel）。
echo.
pause
goto end

:end
endlocal

@echo off
chcp 65001 >nul
setlocal

rem =====================================================================
rem  Model Management Platform - deployment entry point
rem
rem  Usage:  run.bat 00     package self-check
rem          run.bat 01     install backend deps (venv + wheels)
rem          run.bat 02     init database
rem          run.bat 03     preflight check
rem          run.bat 04     start (dev mode: two windows, 5000 + 8080)
rem          run.bat 05     install as Windows service (single port 8080)
rem          run.bat 06     uninstall the service
rem          run.bat 90     build a code-update package (for an already-installed machine)
rem          run.bat 91     apply a code-update package
rem
rem  NOTE: keep this file ASCII-only. cmd.exe parses .bat files using the OEM
rem  code page; UTF-8 Chinese characters are multi-byte and desync the parser,
rem  producing garbage like "'TEPs00' is not recognized". The .ps1 scripts it
rem  calls are UTF-8 and display Chinese correctly.
rem =====================================================================

set "DIR=%~dp0"
set "STEP=%~1"

if /i "%STEP%"=="00" goto s00
if /i "%STEP%"=="01" goto s01
if /i "%STEP%"=="02" goto s02
if /i "%STEP%"=="03" goto s03
if /i "%STEP%"=="04" goto s04
if /i "%STEP%"=="05" goto s05
if /i "%STEP%"=="06" goto s06
rem 90/91 were advertised in the help text but NEVER dispatched here --
rem the :s90 / :s91 labels below were unreachable dead code, so
rem "run.bat 90" silently fell through to the help screen.
if /i "%STEP%"=="90" goto s90
if /i "%STEP%"=="91" goto s91
goto help

:s00
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%00-check-package.ps1"
goto end

:s01
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%01-install-backend.ps1"
goto end

:s02
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%02-init-database.ps1"
goto end

:s03
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%03-preflight-check.ps1"
goto end

:s04
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%04-start-system.ps1"
goto end

:s05
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%elevate.ps1" -Script "05-install-service.ps1"
goto end

:s06
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%elevate.ps1" -Script "06-uninstall-service.ps1"
goto end

:s90
rem Update-package scripts live in TWO possible layouts; try both.
rem   1) offline package layout : <this dir>\90-build-update-package.ps1
rem      (00-check-package.ps1 validates exactly this name)
rem   2) repo layout            : <repo root>\tools\make-update-package.ps1
rem This block used to reference only "%DIR%90-build-update-package.ps1",
rem which never existed in the repo, so "run.bat 90" just failed with
rem "file not found". Both layouts are handled now.
if exist "%DIR%90-build-update-package.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%90-build-update-package.ps1"
) else if exist "%DIR%..\..\..\tools\make-update-package.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%..\..\..\tools\make-update-package.ps1"
) else (
    echo [ERROR] Cannot find the update-package script. Looked for:
    echo           %DIR%90-build-update-package.ps1
    echo           %DIR%..\..\..\tools\make-update-package.ps1
)
goto end

:s91
rem Same two-layout fallback for applying an update package.
if exist "%DIR%91-apply-update.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%91-apply-update.ps1"
) else if exist "%DIR%..\..\..\tools\apply-update.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%..\..\..\tools\apply-update.ps1"
) else (
    echo [ERROR] Cannot find the apply-update script. Looked for:
    echo           %DIR%91-apply-update.ps1
    echo           %DIR%..\..\..\tools\apply-update.ps1
)
goto end

:help
echo.
echo =====================================================================
echo   Model Management Platform - deployment scripts
echo =====================================================================
echo.
echo   Usage:  run.bat  ^<step^>
echo.
echo     00    package self-check  (run once on the online machine first)
echo     01    install backend deps (venv + offline wheels)
echo     02    init database (create db + tables + verify connection)
echo     03    preflight check
echo     04    start (DEV mode: backend 5000 + frontend 8080, two windows)
echo     05    install as Windows service (PROD: single port 8080)  [RECOMMENDED]
echo     06    uninstall the service (keeps all data)
echo.
echo     90    build a code-update package (for a machine already installed)
echo     91    apply a code-update package
echo.
echo   ------------------------------------------------------------------
echo   First-time deployment order:
echo.
echo       run.bat 01                  install backend deps
echo       run.bat 02                  init database
echo       npm run build               (in 04-project source/frontend/22project)
echo       run.bat 03                  preflight check
echo       run.bat 05                  install as service - done, auto-starts
echo.
echo   For daily debugging use: run.bat 04
echo   (after changing frontend code, rebuild with npm run build)
echo =====================================================================
echo.

:end
endlocal

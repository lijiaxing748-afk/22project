@echo off
chcp 65001 >nul
rem 模型管理平台 · 更新到仓库最新代码（Windows）。等价于 start.bat update
rem git pull → 重建前端 → 重启服务。内网拉不到 GitHub 时：覆盖代码后跑 start.bat upgrade
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" update %*
endlocal
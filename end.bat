@echo off
chcp 65001 >nul
rem 模型管理平台 · 结束运行（end 别名，等价于 stop.bat）
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" stop %*
endlocal
@echo off
chcp 65001 >nul
rem 模型管理平台 · 停止运行（Windows）。等价于 end.bat / start.bat stop
rem 只是停掉服务：卸载用 start.bat uninstall，数据库与 data 目录一概不动。
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" stop %*
endlocal
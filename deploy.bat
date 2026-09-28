@echo off
chcp 65001 >nul
rem 模型管理平台 · deploy 已改名为 start（保留一层转发，老命令/老文档不至于失效）
echo [提示] deploy.bat 已改名为 start.bat，本次自动转发（建议以后直接用 start.bat）。
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" %*
endlocal
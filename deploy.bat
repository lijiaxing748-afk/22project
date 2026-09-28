@echo off
chcp 65001 >nul
rem =====================================================================
rem  模型管理平台 · 服务器部署（Windows 的一条命令入口）
rem
rem  常用：
rem      deploy.bat                  安装成开机自启服务并启动（默认）
rem      deploy.bat status           状态 + 端口 + 最近日志
rem      deploy.bat logs             看日志（Ctrl+C 退出）
rem      deploy.bat restart          重启
rem      deploy.bat upgrade          更新代码后重启（会重建前端）
rem      deploy.bat uninstall        卸载服务（数据库与 data 目录不动）
rem      deploy.bat -Port 8081       换端口
rem      deploy.bat -DryRun          只打印将要做什么，不改系统
rem
rem  ⚠️ 安装/卸载/重启需要**管理员**：右键「以管理员身份运行」再执行。
rem  真正的逻辑在 tools\deploy-windows.ps1 里（便于阅读与修改）。
rem =====================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" %*
endlocal

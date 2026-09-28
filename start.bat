@echo off
chcp 65001 >nul
rem =====================================================================
rem  模型管理平台 · 一条命令部署 / 更新 / 运行（Windows）
rem
rem    start.bat                 安装/更新并启动（默认；需管理员）
rem    start.bat update          拉取仓库最新代码 → 重建前端 → 重启服务（需管理员）
rem    start.bat status          状态 + 端口 + 最近日志
rem    start.bat logs            看日志（Ctrl+C 退出）
rem    start.bat run             本机前台跑（自动开浏览器，关窗口即停；不装服务）
rem    start.bat uninstall       卸载服务（数据库与 data 目录不动；需管理员）
rem    stop.bat                  停止运行（等价 end.bat / start.bat stop）
rem    update.bat                等价 start.bat update
rem    -Port 8081 换端口   -DryRun 只演练不改系统   -SkipMysqlInstall 不自动装 MySQL
rem
rem  ⚠️ 安装/卸载/更新需要**管理员**：右键「以管理员身份运行」再执行。
rem  ⚠️ 早期版本这个名字叫 deploy.bat（deploy.bat 仍保留为一层转发）。
rem  ⚠️ 直接敲 "start" 会命中 cmd 自带的 start 命令，请敲 start.bat 或 .\start.bat。
rem =====================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" %*
endlocal
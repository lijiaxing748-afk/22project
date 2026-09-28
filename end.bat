@echo off
chcp 65001 >nul
rem 模型管理平台 · 结束运行（stop 的别名）
rem 该动作需要管理员：不是管理员会弹 UAC 请求提升（点「是」）
if not defined MP_NO_ELEVATE (
  net session >nul 2>&1
  if errorlevel 1 (
    echo 需要管理员权限，正在请求提升（会弹 UAC 窗口，点「是」）...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
  )
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" stop
echo.
pause
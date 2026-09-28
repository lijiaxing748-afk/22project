@echo off
chcp 65001 >nul
setlocal EnableExtensions
title 模型管理平台 - 卸载 / 删除

rem ===== 内部模式：被复制到临时目录后，回来删除原目录 =====
if /i "%~1"=="--delete-only" goto DO_DELETE

rem ===== 需要管理员：不是管理员就用 UAC 自我提升 =====
if not defined MP_NO_ELEVATE (
  net session >nul 2>&1
  if errorlevel 1 (
    echo 需要管理员权限，正在请求提升（会弹 UAC 窗口，点「是」）...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
  )
)

echo ============================================================
echo   卸载模型管理平台
echo   （取消开机自启 + 停服务/计划任务 + 收掉占用该目录的进程）
echo   数据库、以及 testRestfulProject\data 都不会被删除
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\deploy-windows.ps1" uninstall
if errorlevel 1 echo [注意] 上面的卸载步骤有报错，请看输出。
echo [重要] 选择 Y 会把整个文件夹删掉 —— 包括 testRestfulProject\data（训练好的模型/图片/数据集）！
echo        要保留这些，请选 N（只卸载），然后自己备份并删除。
echo.
choice /c YN /n /m "是否连整个文件夹一起删除？(Y=删除 / N=先留着，稍后自己删) "
if errorlevel 2 goto DONE

set "CONFIRM="
set /p "CONFIRM=真的要删除整个文件夹吗？输入 DELETE 再回车确认（直接回车=取消）: "
if /i not "%CONFIRM%"=="DELETE" (
  echo 已取消，文件夹保留。
  goto DONE
)

rem ===== 复制自身到临时目录再回来删（否则删的是自己所在的目录，删不干净）=====
copy /y "%~f0" "%TEMP%\mp-delete-folder.bat" >nul
echo.
echo 正在删除 %~dp0 ...（本窗口会自动关闭）
start "" /min cmd /c ""%TEMP%\mp-delete-folder.bat" --delete-only "%~dp0""
exit /b

:DONE
echo.
echo 卸载完成。现在可以直接删除本文件夹了（在资源管理器里删即可）。
pause
exit /b

:DO_DELETE
cd /d "%TEMP%"
set "TARGET=%~2"
if "%TARGET%"=="" ( echo 没有指定要删除的目录。& pause & exit /b 1 )
echo 正在删除 %TARGET% ...
rmdir /s /q "%TARGET%" 2>nul
if exist "%TARGET%" (
  echo.
  echo [注意] 删除失败：还有东西占着它。按顺序试：
  echo   1^) 关掉任何 cd 在该目录里的 cmd / PowerShell 窗口，然后重跑本脚本
  echo   2^) resmon -^> CPU -^> 关联的句柄 -^> 搜索该目录名，看是哪个进程占用
  echo   3^) 用 tools\kill-old-22project.ps1 清残留服务/进程
  echo   4^) 重启后立刻重跑本脚本
) else (
  echo.
  echo [OK] 已删除 %TARGET%
)
del /f /q "%TEMP%\mp-delete-folder.bat" >nul 2>&1
pause
exit /b
# 等后端真正能响应之后再打开浏览器 —— 否则 serve.py 还在导入 tensorflow（首次 20~40 秒），
# 浏览器会先看到"无法访问此网站"，用户以为启动失败。
#
# 由 start.bat / start.sh 调用：
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\open-when-ready.ps1 ^
#       -Url "http://127.0.0.1:8080/" -Health "http://127.0.0.1:8080/health"
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [string]$Health = "",
    [int]$TimeoutSec = 180
)
$ErrorActionPreference = 'SilentlyContinue'
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$probe = if ($Health) { $Health } else { $Url }
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri $probe -TimeoutSec 3
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) { break }
    } catch { }
    Start-Sleep -Milliseconds 700
}
Start-Process $Url

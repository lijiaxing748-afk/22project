#!/usr/bin/env bash
# 模型管理平台 · 停止运行（Linux）
#
#   bash stop.sh          停止常驻服务（systemd 服务 model-platform）
#   sudo bash stop.sh     同上（需要 root）
#   bash end.sh           等价别名
#
# 只是**停掉进程**：卸载用 sudo bash start.sh uninstall，数据库与 data 目录一概不动。
# 幂等：本来就没装/没在跑时不报错，只提示。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="model-platform"
if ! systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}\.service"; then
    printf '\033[33m[提示]\033[0m 服务还没安装/没在跑，无需停止。\n'
    printf '        想本机前台试跑： bash start.sh run\n'
    exit 0
fi
if [[ "$(id -u)" -ne 0 ]]; then
    printf '\033[31m[错误]\033[0m 需要 root：请用  sudo bash stop.sh\n'
    exit 1
fi
systemctl stop "$SERVICE" && printf '\033[32m[OK]\033[0m 已停止 %s（数据与数据库未动）\n' "$SERVICE"
printf '        重新启动： sudo bash start.sh\n'

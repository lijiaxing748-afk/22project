#!/usr/bin/env bash
# 模型管理平台 · deploy 已改名为 start（保留一层转发，老命令/老文档不至于失效）
#
#   bash deploy.sh          →  bash start.sh
#   bash deploy.sh update   →  bash start.sh update
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[提示] deploy.sh 已改名为 start.sh，本次自动转发（建议以后直接用 start.sh）。"
exec bash "$ROOT/start.sh" "$@"
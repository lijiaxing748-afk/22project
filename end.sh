#!/usr/bin/env bash
# 模型管理平台 · 结束运行（end 别名，等价于 stop.sh）
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/stop.sh" "$@"

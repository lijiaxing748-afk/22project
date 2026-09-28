#!/usr/bin/env bash
# 模型管理平台 · 更新到仓库最新代码（Linux）
#
#   sudo bash update.sh
#
# 做的事：git fetch + pull --ff-only --autostash（本地改动自动暂存再放回）
#         → 重建前端产物 → 重启服务。等价于： sudo bash start.sh update
#
# ⚠️ 内网机器拉不到 GitHub 时：把新代码覆盖过来，然后 sudo bash start.sh upgrade（只重建+重启）。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/start.sh" update "$@"

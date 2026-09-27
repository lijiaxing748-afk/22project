#!/usr/bin/env bash
# =====================================================================
#  模型管理平台 · 卸载服务脚本（Linux）
#
#  对应 Windows 版的 06-uninstall-service.ps1。
#  停止并移除 systemd 服务。**不会删除项目文件、venv、数据库**，
#  只解除"开机自启 + 后台常驻"的注册关系，随时可以再装回来。
#
#  用法：
#      chmod +x uninstall-service.sh
#      sudo ./uninstall-service.sh
# =====================================================================

set -euo pipefail

SERVICE_NAME="model-platform"

C_OK=$'\033[32m'; C_ERR=$'\033[31m'; C_WARN=$'\033[33m'; C_END=$'\033[0m'
ok()   { echo "   ${C_OK}[OK]${C_END}   $1"; }
err()  { echo "   ${C_ERR}[错误]${C_END} $1"; }
warn() { echo "   ${C_WARN}[提示]${C_END} $1"; }

echo "============================================================"
echo "  卸载模型管理平台服务"
echo "============================================================"
echo ""

if [[ "$(id -u)" -ne 0 ]]; then
    err "本脚本需要 root 权限： sudo ./uninstall-service.sh"
    exit 1
fi

if ! systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
    warn "服务 $SERVICE_NAME 不存在，无需卸载。"
    exit 0
fi

echo "  即将停止并移除服务 $SERVICE_NAME。"
echo "  ${C_WARN}注意：项目代码、venv、数据库都不会被删除。${C_END}"
echo ""
read -r -p "  确认继续？(y/N) " ans
[[ "$ans" == "y" ]] || { echo "  已取消。"; exit 0; }
echo ""

systemctl stop "$SERVICE_NAME" 2>/dev/null && ok "已停止服务" || warn "停止时返回错误（可能本就未运行）"
systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 && ok "已取消开机自启" || warn "取消自启时返回错误"

rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
ok "已移除单元文件"

echo ""
echo "============================================================"
echo "  卸载完成"
echo "============================================================"
echo ""
echo "  如需手动前台启动（排查问题时用）："
echo "      cd <项目根>/testRestfulProject"
echo "      venv/bin/python serve.py --port 8080"
echo ""
echo "  重新安装： sudo ./install-service.sh"
echo "============================================================"

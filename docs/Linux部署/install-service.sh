#!/usr/bin/env bash
# =====================================================================
#  模型管理平台 · Linux 服务安装脚本
#
#  对应 Windows 版的 05-install-service.ps1，职责完全一致：
#      注册服务 -> 配置启动参数 -> 配置日志 -> 启动 -> 就绪探测 -> 放行防火墙
#
#  用法：
#      chmod +x install-service.sh
#      sudo ./install-service.sh
#
#  前置条件：
#      1. 已装好 Python 3.12 并在项目目录建好 venv、装好依赖
#         （见 install-backend.sh）
#      2. 已初始化数据库（见 init-database.sh）
#      3. 前端 dist 已就位（frontend/22project/dist/index.html 存在）
#         没有的话服务能起来，但浏览器打开是"还没有前端页面"提示
# =====================================================================

set -euo pipefail

# ---------------------------------------------------------------- 配置
SERVICE_NAME="model-platform"
DISPLAY_NAME="模型管理平台"
PORT="${MODEL_PORT:-8080}"
THREADS="${MODEL_THREADS:-4}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------- 输出
C_OK=$'\033[32m'; C_ERR=$'\033[31m'; C_WARN=$'\033[33m'; C_INFO=$'\033[36m'; C_END=$'\033[0m'
say()  { echo "$1"; }
ok()   { echo "   ${C_OK}[OK]${C_END}   $1"; }
err()  { echo "   ${C_ERR}[错误]${C_END} $1"; }
warn() { echo "   ${C_WARN}[提示]${C_END} $1"; }
info() { echo "   ${C_INFO}[信息]${C_END} $1"; }
die()  { err "$1"; exit 1; }

say "============================================================"
say "  安装模型管理平台为 systemd 服务"
say "============================================================"
say ""

# ---------------------------------------------------------------- 1 定位项目根
# 脚本位于 <项目根>/docs/Linux部署/ 下，所以往上三级是项目根。
# 但也兼容"被单独拷到别处运行"的情况：用 MODEL_APP_DIR 显式指定。
if [[ -n "${MODEL_APP_DIR:-}" ]]; then
    APP_DIR="$MODEL_APP_DIR"
else
    APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi

# ⚠️ 同 backend/database 两个脚本：打包方式不同，serve.py 可能落在
#    根、根/backend、根/testRestfulProject …… 所以按候选列表探测，不写死目录名。
SRV_DIR=""
PROBED=()
for cand in "." "backend" "testRestfulProject" "dist/backend"; do
    PROBED+=("$APP_DIR/$cand")
    if [[ -f "$APP_DIR/$cand/serve.py" ]]; then
        SRV_DIR="$(cd "$APP_DIR/$cand" && pwd)"
        break
    fi
done
if [[ -z "$SRV_DIR" ]]; then
    err "在 $APP_DIR 下没找到 serve.py，已查找过："
    for p in "${PROBED[@]}"; do echo "         $p"; done
    die "请把 MODEL_APP_DIR 指向含 serve.py 的目录，例如：
       sudo MODEL_APP_DIR=/opt/model-platform/backend ./install-service.sh"
fi
VENV_PY="$SRV_DIR/venv/bin/python"

say "[1/6] 检查前置条件"
ok "后端目录：$SRV_DIR"

# ---------------------------------------------------------------- 2 前置检查
if [[ "$(id -u)" -ne 0 ]]; then
    die "本脚本需要 root 权限（安装 systemd 服务、放行防火墙都需要）。
       做法：sudo ./install-service.sh"
fi
ok "已获得 root 权限"

[[ -x "$VENV_PY" ]] || die "找不到虚拟环境 Python：$VENV_PY
       请先运行 install-backend.sh 创建 venv 并安装依赖。"
ok "找到虚拟环境：$VENV_PY"

PYVER="$("$VENV_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?")"
if [[ "$PYVER" != "3.12" ]]; then
    warn "虚拟环境 Python 版本为 $PYVER（建议 3.12，与开发环境一致）。"
    warn "版本不同通常也能跑，但依赖 wheel 可能有差异。"
else
    ok "Python 版本：$PYVER"
fi

[[ -f "$SRV_DIR/db.env" ]] || die "找不到 db.env：$SRV_DIR/db.env
       请先复制 db.env.example 为 db.env 并填好数据库连接信息。"
ok "找到 db.env"

if [[ -f "$SRV_DIR/frontend_dist_check" ]]; then :; fi
DIST_DIR="$APP_DIR/frontend/22project/dist"
if [[ -f "$DIST_DIR/index.html" ]]; then
    ok "找到前端产物：$DIST_DIR"
else
    warn "没找到前端产物（$DIST_DIR/index.html）。"
    warn "服务能起来，但浏览器访问会看到「后端已启动，还没有前端页面」。"
    warn "请把构建好的 dist 目录放到位，或在此机器上执行 npm run build:singleport。"
fi
say ""

# ---------------------------------------------------------------- 3 端口占用检查
say "[2/6] 检查端口"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
    warn "端口 $PORT 已被占用。服务虽然能装，但启动时会因端口冲突失败。"
    warn "查看占用者： sudo ss -ltnp | grep :$PORT"
    read -r -p "   仍要继续安装？(y/N) " ans
    [[ "$ans" == "y" ]] || { info "已取消。"; exit 0; }
else
    ok "端口 $PORT 空闲"
fi
say ""

# ---------------------------------------------------------------- 4 处理已存在的服务
say "[3/6] 处理已存在的服务"
if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
    warn "服务 $SERVICE_NAME 已存在"
    read -r -p "   要覆盖重装吗？会先停止并删除旧服务 (y/N) " ans
    if [[ "$ans" != "y" ]]; then info "已取消。"; exit 0; fi
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    ok "旧服务已清除"
else
    ok "无同名服务，直接安装"
fi
say ""

# ---------------------------------------------------------------- 5 生成并安装 unit
say "[4/6] 生成 systemd 单元文件"

UNIT_SRC="$SCRIPT_DIR/model-platform.service"
[[ -f "$UNIT_SRC" ]] || die "找不到模板文件：$UNIT_SRC"

# ⚠️ 用 python 做占位符替换而不是 sed：
#    项目路径里可能含 `/`、`&`、`\` 等 sed 的敏感字符
#    （例如上面的 install-service.sh 路径就带 /），
#    用 sed 极易替换出错或报 "bad substitution"，且很难排查。
RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_GROUP="$(id -gn "$RUN_USER" 2>/dev/null || echo "$RUN_USER")"

UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
"$VENV_PY" - "$UNIT_SRC" "$UNIT_DST" "$APP_DIR" "$VENV_PY" "$RUN_USER" "$RUN_GROUP" "$PORT" "$THREADS" <<'PYEOF'
import sys
src, dst, app_dir, venv_py, run_user, run_group, port, threads = sys.argv[1:9]
text = open(src, encoding="utf-8").read()
repl = {
    "__APP_DIR__": app_dir,
    "__VENV_PY__": venv_py,
    "__RUN_USER__": run_user,
    "__RUN_GROUP__": run_group,
    "__PORT__": port,
    "__THREADS__": threads,
}
for k, v in repl.items():
    text = text.replace(k, v)

# ⚠️ 校验"是否还有未替换的占位符"时，有**两个**坑，都踩过：
#
#  坑1：不能连注释一起查。本模板的说明注释里就写着 `__XXX__` 字样
#       （用来解释占位符机制），若查注释会误报，安装脚本直接失败——而文件是好的。
#
#  坑2：不能只遍历 repl 的键。若模板里新增了占位符、却忘了在 repl 里加条目，
#       "只查已知键"的写法**根本看不到它**，占位符会静默残留在生成的 unit 文件里，
#       systemd 随后报一个难以理解的路径错误。
#       所以这里用**正向扫描**：任何形如 __ABC__ 的残留都算问题，
#       而不是"只检查我认识的那几个"。
import re

leftover = []
for lineno, line in enumerate(text.splitlines(), 1):
    stripped = line.strip()
    # 跳过注释行：模板里用注释解释占位符机制，注释中的 __XXX__ 不是问题
    if stripped.startswith("#"):
        continue
    for token in re.findall(r"__[A-Z][A-Z0-9_]*__", line):
        leftover.append(f"第 {lineno} 行: {token}")

if leftover:
    sys.exit("以下占位符未被替换（模板与替换字典不一致）:\n  " + "\n  ".join(leftover))

open(dst, "w", encoding="utf-8").write(text)
PYEOF

ok "已写入 $UNIT_DST（运行用户：$RUN_USER，端口：$PORT，线程：$THREADS）"
say ""

# ---------------------------------------------------------------- 6 启动服务
say "[5/6] 启动服务"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
ok "已设为开机自启"

systemctl start "$SERVICE_NAME"
info "等待服务就绪 ..."
sleep 8

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "服务正在运行"
else
    err "服务没有跑起来，最近日志："
    echo "----------------------------------------"
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
    echo "----------------------------------------"
    die "请根据上面的日志排查。常见原因：db.env 数据库信息不对、端口被占用。"
fi
say ""

# ---------------------------------------------------------------- 7 就绪探测
say "[6/6] 就绪探测"
READY=0
for i in $(seq 1 45); do
    if command -v curl >/dev/null 2>&1; then
        if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then READY=1; break; fi
    else
        if "$VENV_PY" -c "
import urllib.request,sys
try:
    urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=2)
except Exception:
    sys.exit(1)
" 2>/dev/null; then READY=1; break; fi
    fi
    sleep 1
done

if [[ "$READY" -eq 1 ]]; then
    ok "服务已响应 /health"
else
    warn "45 秒内没等到响应。最可能的原因："
    warn "  1) db.env 里的数据库连接信息不对 -> journalctl -u $SERVICE_NAME -n 50"
    warn "  2) $PORT 端口被别的程序占用"
fi
say ""

# ---------------------------------------------------------------- 8 防火墙
# Ubuntu 默认没开 ufw；开了才需要放行，否则同局域网连不上。
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "^Status: active"; then
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 && ok "已放行防火墙 ${PORT}/tcp" || warn "ufw 放行失败，请手动执行： sudo ufw allow ${PORT}/tcp"
else
    info "ufw 未启用（或未安装），跳过防火墙配置"
    info "若实验室其他电脑连不上，检查： sudo ufw status"
fi
say ""

# ---------------------------------------------------------------- 完成提示
say "============================================================"
say "  安装完成"
say "============================================================"
IP_LIST="$(hostname -I 2>/dev/null || true)"
say ""
say "  本机访问：   http://localhost:${PORT}"
if [[ -n "$IP_LIST" ]]; then
    say "  局域网访问："
    for ip in $IP_LIST; do say "      http://${ip}:${PORT}"; done
else
    warn "  没探测到局域网 IP —— 这台机器可能没连网线。"
fi
say ""
say "  常用命令："
say "     状态： sudo systemctl status $SERVICE_NAME"
say "     启动： sudo systemctl start $SERVICE_NAME"
say "     停止： sudo systemctl stop $SERVICE_NAME"
say "     重启： sudo systemctl restart $SERVICE_NAME"
say "     看日志： sudo journalctl -u $SERVICE_NAME -f"
say "     最近50行： sudo journalctl -u $SERVICE_NAME -n 50"
say "     卸载： sudo ./uninstall-service.sh"
say ""
say "  登录账号：admin / Admin@2026    （第一次登录后请尽快改掉）"
say "============================================================"

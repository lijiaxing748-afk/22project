#!/usr/bin/env bash
# =====================================================================
#  模型管理平台 · 服务器部署（一条命令，Linux）
#
#  做了什么（幂等，可以反复跑）：
#     1) 检查并准备好 Python venv 与依赖（缺才装；有离线 wheel 目录就用它）
#     2) 准备前端产物 frontend/22project/dist（缺且本机有 npm 就自动构建）
#     3) 读 testRestfulProject/db.env 建库建表（库名按配置替换）+ 鉴权表 + 校验 11 张表
#       ⚠️ MODEL_SECRET_KEY 为空会自动生成并写回 db.env（否则每次重启所有人都要重新登录）
#     4) 装成 systemd 服务：开机自启、崩溃自动重启、日志进 journald
#     5) 放行防火墙端口，打印**局域网访问地址**
#
#  用法（在项目根目录）：
#     sudo bash deploy.sh                 安装/更新并启动（默认动作）
#     sudo bash deploy.sh status          看状态 + 最近日志
#     sudo bash deploy.sh restart         重启
#     sudo bash deploy.sh logs            跟踪日志（Ctrl+C 退出）
#     sudo bash deploy.sh upgrade         更新代码后重启（会自动重建前端）
#     sudo bash deploy.sh uninstall       卸载服务（不动数据库与 data 目录）
#     MODEL_PORT=8081 sudo bash deploy.sh 换端口部署
#     DRY_RUN=1 bash deploy.sh            只打印将要做什么，不真改系统（排查用）
# =====================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRV="$ROOT/testRestfulProject"
FE="$ROOT/frontend/22project"
SERVICE="model-platform"
UNIT="/etc/systemd/system/${SERVICE}.service"
PORT="${MODEL_PORT:-8080}"
THREADS="${MODEL_THREADS:-6}"
MODE="${1:-install}"
DRY="${DRY_RUN:-}"
SYSTEMD_DIR="/etc/systemd/system"

ok()   { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info() { printf '     %s\n' "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[错误]\033[0m %s\n' "$*"; exit 1; }

# 真正执行（DRY_RUN 时只打印）
run() {
    if [[ -n "$DRY" ]]; then printf '     [dry-run] %s\n' "$*"; return 0; fi
    eval "$@"
}
need_root() {
    [[ -n "$DRY" ]] && return 0
    [[ "$(id -u)" -eq 0 ]] || die "需要 root：请用  sudo bash deploy.sh ${MODE}"
}

# ---------------------------------------------------------------- 读 db.env
read_env() {   # read_env KEY DEFAULT
    local key="$1" def="${2:-}"
    local line
    line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$SRV/db.env" 2>/dev/null | tail -n1 || true)"
    [[ -z "$line" ]] && { printf '%s' "$def"; return; }
    local val="${line#*=}"
    val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^['\"]//" -e "s/['\"]$//")"
    printf '%s' "$val"
}

# ---------------------------------------------------------------- 子命令
case "$MODE" in
    status)
        systemctl status "$SERVICE" --no-pager -l 2>/dev/null || warn "服务未安装（先执行 sudo bash deploy.sh）"
        exit 0 ;;
    logs)
        journalctl -u "$SERVICE" -f -n 80 ;;
    restart)
        need_root; run "systemctl restart '$SERVICE'"; run "systemctl is-active --quiet '$SERVICE' && echo '     服务已重启'"; exit $? ;;
    start)
        need_root; run "systemctl start '$SERVICE'"; exit $? ;;
    stop)
        need_root; run "systemctl stop '$SERVICE'"; exit $? ;;
    uninstall)
        need_root
        info "卸载 systemd 服务（数据库与 $SRV/data 一概不动）"
        run "systemctl stop '$SERVICE' 2>/dev/null || true"
        run "systemctl disable '$SERVICE' 2>/dev/null || true"
        run "rm -f '$UNIT'"
        run "systemctl daemon-reload"
        ok "已卸载。数据目录与数据库保留：$SRV/data"
        exit 0 ;;
    upgrade)
        MODE="install"; UPGRADE=1 ;;
    install) UPGRADE="${UPGRADE:-}" ;;
    *) die "未知动作：$MODE（可用：install / status / logs / restart / start / stop / upgrade / uninstall）" ;;
esac

printf '%s\n' '============================================================'
printf '  模型管理平台 · 服务器部署\n'
printf '%s\n' '------------------------------------------------------------'
printf '  项目目录 : %s\n' "$ROOT"
printf '  监听端口 : %s（MODEL_PORT 可改）   线程 %s\n' "$PORT" "$THREADS"
printf '  服务名   : %s（systemd）\n' "$SERVICE"
[[ -n "$DRY" ]] && printf '  模式     : DRY-RUN（只打印，不改系统）\n'
printf '============================================================\n\n'
need_root

# ---------------------------------------------------------------- 1) Python 环境
PY="$SRV/venv/bin/python"
if [[ ! -x "$PY" ]]; then
    info "缺少 venv，创建并安装依赖（有 wheels/ 或 dist-linux 里的离线 wheel 会优先用）..."
    if [[ -n "$DRY" ]]; then
        info "[dry-run] 会创建 venv 并安装 requirements.txt"
    else
    command -v python3 >/dev/null || die "找不到 python3：sudo apt install -y python3 python3-venv python3-pip"
    run "python3 -m venv '$SRV/venv'" || die "创建 venv 失败"
    WHEELS=""
    for d in "$ROOT/wheels" "$ROOT/offline_wheels" "$SRV/wheels"; do
        [[ -d "$d" ]] && WHEELS="$d" && break
    done
    if [[ -n "$WHEELS" ]]; then
        info "使用离线 wheel 目录：$WHEELS"
        run "'$PY' -m pip install --no-index --find-links='$WHEELS' -r '$SRV/requirements.txt'" \
            || die "离线安装失败：检查 wheels 目录里是否缺包、Python 版本是否匹配"
    else
        warn "没有离线 wheel 目录 → 走联网 pip（torch 需要 pytorch cpu 源，见 requirements.txt 开头）"
        run "'$PY' -m pip install --upgrade pip"
        run "'$PY' -m pip install -r '$SRV/requirements.txt'" || die "依赖安装失败（内网机器请看 docs/离线部署/README-先看我.md）"
    fi
    fi
fi
if [[ -x "$PY" ]]; then ok "Python 环境：$("$PY" -V 2>/dev/null | tr -d '\r')"; else info "（dry-run：跳过 Python 环境检查）"; fi

# ---------------------------------------------------------------- 2) db.env（含密钥生成）
if [[ ! -f "$SRV/db.env" ]]; then
    [[ -f "$SRV/db.env.example" ]] || die "缺少 $SRV/db.env 与 db.env.example"
    run "cp '$SRV/db.env.example' '$SRV/db.env'"
    warn "已从 db.env.example 生成 db.env —— 请填 MySQL 账号/口令后重新运行（本次先继续，连接失败会报出来）"
fi
SECRET="$(read_env MODEL_SECRET_KEY '')"
if [[ -z "$SECRET" ]]; then
    if [[ -n "$DRY" ]]; then
        info "[dry-run] 会生成 MODEL_SECRET_KEY 并写回 db.env"
    else
        SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
        cp "$SRV/db.env" "$SRV/db.env.bak-$(date +%Y%m%d-%H%M%S)"
        if grep -qE '^[[:space:]]*MODEL_SECRET_KEY[[:space:]]*=' "$SRV/db.env"; then
            sed -i "s|^[[:space:]]*MODEL_SECRET_KEY[[:space:]]*=.*|MODEL_SECRET_KEY=${SECRET}|" "$SRV/db.env"
        else
            printf '\nMODEL_SECRET_KEY=%s\n' "$SECRET" >> "$SRV/db.env"
        fi
        ok "已生成并写入 MODEL_SECRET_KEY（Token 不会因重启失效）"
    fi
fi
DB_HOST="$(read_env MODEL_DB_HOST 127.0.0.1)"
DB_PORT="$(read_env MODEL_DB_PORT 3306)"
DB_USER="$(read_env MODEL_DB_USER root)"
DB_PASS="$(read_env MODEL_DB_PASSWORD '')"
DB_NAME="$(read_env MODEL_DB_NAME model_management)"
info "数据库：${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

# ---------------------------------------------------------------- 3) 前端产物
NEED_BUILD=""
[[ ! -f "$FE/dist/index.html" ]] && NEED_BUILD=1
[[ -n "$UPGRADE" ]] && NEED_BUILD=1          # upgrade 时无条件重建，否则前端改动不会生效
if [[ -n "$NEED_BUILD" ]]; then
    if [[ -n "$DRY" ]]; then
        info "[dry-run] 会构建前端产物：cd $FE && npm install && npm run build"
    elif command -v npm >/dev/null; then
        info "构建前端产物（首次约 1 分钟）..."
        ( cd "$FE" && { [[ -d node_modules ]] || npm install; } && npm run build ) || true
        [[ -f "$FE/dist/index.html" ]] || die "前端构建失败：cd $FE && npm install && npm run build"
        ok "前端产物已生成"
    else
        die "缺少 $FE/dist/index.html 且本机没有 npm —— 请在有 Node.js 的机器上构建后把 dist 拷过来（单端口模式必须有它）"
    fi
fi
if [[ -f "$FE/dist/index.html" ]]; then ok "前端产物：$FE/dist"; else info "（dry-run：前端产物尚未生成）"; fi

# ---------------------------------------------------------------- 4) 建库建表
MYSQL_BIN="$(command -v mysql || true)"
if [[ -z "$MYSQL_BIN" ]]; then
    [[ -n "$DRY" ]] && info "[dry-run] 找不到 mysql 客户端（真实环境下需要：apt install -y mysql-client）" \
                    || die "找不到 mysql 客户端：sudo apt install -y mysql-client（或 mariadb-client）"
fi
info "应用表结构（库名按 MODEL_DB_NAME 替换）..."
export MYSQL_PWD="$DB_PASS"    # ⚠️ 用环境变量传口令，不写在命令行里（否则同机 ps 能看到）
MYSQL_ARGS=(-h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" --default-character-set=utf8mb4)
apply_sql() {
    local f="$1"
    if [[ "$DB_NAME" == "model_management" ]]; then
        run "'$MYSQL_BIN' ${MYSQL_ARGS[*]} < '$f'"
    else
        run "sed 's/\`model_management\`/\`$DB_NAME\`/g' '$f' | '$MYSQL_BIN' ${MYSQL_ARGS[*]}"
    fi
}
apply_sql "$SRV/sql/schema_mysql.sql" || die "建表失败：检查 db.env 里的账号/口令与 MySQL 是否在跑"
[[ -f "$SRV/sql/auth-migration.sql" ]] && apply_sql "$SRV/sql/auth-migration.sql" || true
if [[ -n "$DRY" ]]; then
    info "[dry-run] 会校验库 \`$DB_NAME\` 里有 11 张表"
else
    TABLES="$("$MYSQL_BIN" "${MYSQL_ARGS[@]}" -N -B -e "SHOW TABLES FROM \`$DB_NAME\`" 2>/dev/null | tr 'A-Z' 'a-z' | sort | tr '\n' ' ')"
    COUNT="$(printf '%s' "$TABLES" | wc -w)"
    if [[ "$COUNT" -lt 11 ]]; then
        warn "库里有 $COUNT 张表（期望 11）：$TABLES"
        warn "缺的可能是鉴权三表（Roles/Users/OperationLogs）—— 请检查上面的报错"
    else
        ok "库表就位：$COUNT 张"
    fi
fi
unset MYSQL_PWD

# ---------------------------------------------------------------- 5) systemd 服务
TEMPLATE="$ROOT/docs/Linux部署/model-platform.service"
[[ -f "$TEMPLATE" ]] || die "找不到 systemd 模板：$TEMPLATE"
RUN_USER="${SUDO_USER:-$(id -un)}"; RUN_USER="${RUN_USER%%:*}"     # 去掉 "user:uid" 之类的尾巴
RUN_GROUP="$(id -gn "$RUN_USER" 2>/dev/null || echo "$RUN_USER")"; RUN_GROUP="${RUN_GROUP%%:*}"
info "服务将以 $RUN_USER:$RUN_GROUP 运行；工作目录 $SRV"
if [[ -n "$DRY" ]]; then
    info "[dry-run] 会写入 $UNIT 并 systemctl enable --now $SERVICE"
else
    sed -e "s|__APP_DIR__|$SRV|g" \
        -e "s|__VENV_PY__|$PY|g" \
        -e "s|__RUN_USER__|$RUN_USER|g" \
        -e "s|__RUN_GROUP__|$RUN_GROUP|g" \
        -e "s|__PORT__|$PORT|g" \
        -e "s|__THREADS__|$THREADS|g" "$TEMPLATE" > "$UNIT" || die "写 unit 失败"
    ok "已写入 $UNIT"
fi
run "systemctl daemon-reload"
run "systemctl enable '$SERVICE' >/dev/null 2>&1"
# 升级模式下先停再起，避免旧进程占着端口
[[ -n "$UPGRADE" ]] && run "systemctl stop '$SERVICE' 2>/dev/null || true"
run "systemctl restart '$SERVICE'"

# ---------------------------------------------------------------- 6) 防火墙
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
    run "ufw allow ${PORT}/tcp >/dev/null 2>&1" && ok "ufw 已放行 ${PORT}/tcp"
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    run "firewall-cmd --permanent --add-port=${PORT}/tcp >/dev/null 2>&1 && firewall-cmd --reload >/dev/null 2>&1" \
        && ok "firewalld 已放行 ${PORT}/tcp"
else
    info "未检测到启用的 ufw/firewalld —— 若局域网访问不通，请手工放行 ${PORT}/tcp"
fi

# ---------------------------------------------------------------- 7) 结果
# ⚠️ 优先用"默认路由所在网卡的地址"：装了代理/虚拟网卡时 hostname -I 的第一项可能是假网段
#    （实测在装了代理的机器上会拿到 198.18.x.x，那种地址发给同事是连不上的）。
LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{print $7; exit}')"
if [[ -z "$LAN_IP" ]]; then
    LAN_IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^(127\.|169\.254\.|198\.1[89]\.)' | head -n1)"
fi
printf '\n============================================================\n'
if [[ -z "$DRY" ]]; then
    systemctl is-active --quiet "$SERVICE" && ok "服务已启动，开机自启已开启" || warn "服务没起来：看日志 journalctl -u $SERVICE -n 50"
fi
printf '  本机访问   : http://127.0.0.1:%s/\n' "$PORT"
[[ -n "$LAN_IP" ]] && printf '  局域网访问 : http://%s:%s/     ← 把这个地址发给同事\n' "$LAN_IP" "$PORT"
printf '  初始账号   : admin / Admin@2026（交付现场请立刻改口令）\n'
printf '  常用命令   : sudo bash deploy.sh status | logs | restart | upgrade | uninstall\n'
printf '%s\n' '============================================================'

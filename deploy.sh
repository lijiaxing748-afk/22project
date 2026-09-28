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

# ---------------------------------------------------------------- 1.5) MySQL：检测 → 没有就装 → 有就查配置
# ⚠️ 这里要用到 DB_HOST/DB_PORT/DB_NAME 与 mysql 客户端路径，所以**先算好**再检测（之前写在下面，
#    结果 set -u 下碰出 "unbound variable"，脚本在检测那一步就断了）。
DB_HOST="${MODEL_DB_HOST:-$(read_env MODEL_DB_HOST 127.0.0.1)}"
DB_PORT="${MODEL_DB_PORT:-$(read_env MODEL_DB_PORT 3306)}"
DB_NAME="$(read_env MODEL_DB_NAME model_management)"
MYSQL_BIN="$(command -v mysql || true)"
MYSQL_SVC=""
if command -v systemctl >/dev/null; then
    for s in mysql mysqld mariadb; do
        if systemctl list-unit-files 2>/dev/null | grep -q "^${s}\.service"; then MYSQL_SVC="$s"; break; fi
    done
fi
PORT_LISTENING=""
if (command -v ss >/dev/null && ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -qE ":$DB_PORT\b"; then
    PORT_LISTENING=1
fi
if [[ -n "$MYSQL_SVC" ]]; then
    ok "检测到 MySQL 服务：$MYSQL_SVC（$(systemctl is-active "$MYSQL_SVC" 2>/dev/null || echo '未知')）"
    if [[ -z "$DRY" ]] && ! systemctl is-active --quiet "$MYSQL_SVC"; then
        info "服务没在跑，启动它..."
        systemctl start "$MYSQL_SVC" && ok "已启动 $MYSQL_SVC" || warn "启动失败：systemctl status $MYSQL_SVC"
    fi
elif [[ -n "$MYSQL_BIN" || -n "$(command -v mysqld || true)" ]]; then
    ok "检测到 MySQL 程序（未注册成 systemd 服务）$([[ -n "$PORT_LISTENING" ]] && echo "，且 $DB_PORT 在监听")"
elif [[ -n "$PORT_LISTENING" ]]; then
    ok "检测到 $DB_PORT 端口在监听（MySQL 在别处跑着，按远程库处理）"
else
    warn "没有检测到 MySQL —— 现在自动安装（需要联网；离线机器请看 docs/离线部署/）"
    if [[ -n "$DRY" ]]; then
        info "[dry-run] 会执行：apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server"
        info "[dry-run] 然后 systemctl enable --now mysql，再回来建库/建账号/写 db.env"
    elif command -v apt-get >/dev/null; then
        apt-get update -y || warn "apt-get update 失败（离线？继续试装）"
        DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server \
            || die "安装 mysql-server 失败。离线机器请用 docs/离线部署/ 的离线包，或手工装好 MySQL 后重跑本脚本"
        systemctl enable --now mysql 2>/dev/null || systemctl start mysql 2>/dev/null || true
        MYSQL_BIN="$(command -v mysql || true)"
        MYSQL_SVC="mysql"
        ok "MySQL 已安装并启动"
    else
        die "本机既没有 MySQL 也没有 apt-get：请手工安装 MySQL/MariaDB 后重跑（或见 docs/离线部署/）"
    fi
fi

# ---------------------------------------------------------------- 2) 数据库与 db.env（**自动配置**）
# ⚠️ 目标：正常路径下**不需要人工填任何东西**。脚本自己找 MySQL 管理员（本机 root 走 socket 最常见）
#    → 建库 → 建应用账号 model_app（随机口令）→ 写 db.env（含随机 MODEL_SECRET_KEY）。
#    要改（口令/库名/端口）时直接编辑 testRestfulProject/db.env 再重跑 —— 能连上就**不会覆盖**你的改动。
#    （DB_HOST/DB_PORT/DB_NAME/MYSQL_BIN 已在上面 1.5 检测那一步算好）
APP_USER="model_app"
DB_ENV_FILE="$SRV/db.env"

if [[ -z "$MYSQL_BIN" && -z "$DRY" ]]; then
    die "找不到 mysql 客户端：sudo apt install -y mysql-client（或 mariadb-client）"
fi
try_conn() {   # try_conn 用户 口令
    [[ -z "$MYSQL_BIN" ]] && return 1
    MYSQL_PWD="$2" "$MYSQL_BIN" -h "$DB_HOST" -P "$DB_PORT" -u "$1" --connect-timeout=5 -N -B -e 'SELECT 1' >/dev/null 2>&1
}
try_socket() {  # 以当前身份（脚本要求 root）走 unix socket —— Ubuntu 上 root@localhost 默认是 auth_socket
    [[ -z "$MYSQL_BIN" ]] && return 1
    "$MYSQL_BIN" -N -B -e 'SELECT 1' >/dev/null 2>&1
}
CUR_USER="$(read_env MODEL_DB_USER '')"
CUR_PASS="$(read_env MODEL_DB_PASSWORD '')"
CONFIGURED=""
ADMIN_MODE=""        # socket | tcp
ADMIN_ARGS=(); ADMIN_USER=""; ADMIN_PASS=""
if [[ -n "$CUR_USER" ]] && try_conn "$CUR_USER" "$CUR_PASS"; then
    CONFIGURED=1
    DB_USER="$CUR_USER"; DB_PASS="$CUR_PASS"
    ok "数据库已配置好（${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}），沿用现有 db.env"
    SECRET="$(read_env MODEL_SECRET_KEY '')"
    if [[ -z "$SECRET" ]]; then
        if [[ -n "$DRY" ]]; then info "[dry-run] 会补一个 MODEL_SECRET_KEY 写回 db.env"
        else
            SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))' 2>/dev/null || openssl rand -hex 32)"
            cp "$DB_ENV_FILE" "$DB_ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
            if grep -qE '^[[:space:]]*MODEL_SECRET_KEY[[:space:]]*=' "$DB_ENV_FILE"; then
                sed -i "s|^[[:space:]]*MODEL_SECRET_KEY[[:space:]]*=.*|MODEL_SECRET_KEY=${SECRET}|" "$DB_ENV_FILE"
            else
                printf '\nMODEL_SECRET_KEY=%s\n' "$SECRET" >> "$DB_ENV_FILE"
            fi
            ok "已补写 MODEL_SECRET_KEY（Token 不会因重启失效）"
        fi
    fi
else
    info "正在自动配置数据库（建库 → 建应用账号 → 写 db.env）..."
    if [[ -n "$DRY" ]]; then
        ADMIN_MODE="socket"
    else
        if try_socket; then
            ADMIN_MODE="socket"
            info "以 root（unix socket）身份连接 MySQL 成功"
        else
            for cand in "${MODEL_DB_ADMIN_USER:-}:${MODEL_DB_ADMIN_PASSWORD:-}" "$CUR_USER:$CUR_PASS" \
                        "root:" "root:root" "root:123456" "root:Admin@2026"; do
                u="${cand%%:*}"; p="${cand#*:}"
                [[ -z "$u" ]] && continue
                if try_conn "$u" "$p"; then ADMIN_MODE="tcp"; ADMIN_USER="$u"; ADMIN_PASS="$p"; break; fi
            done
        fi
    fi
    if [[ -z "$ADMIN_MODE" ]]; then
        warn "常见账号都没连上 MySQL。请输入一个**有建库权限**的账号（例如 root）："
        read -r -p "  MySQL 账号 [root]: " u; u="${u:-root}"
        read -r -s -p "  MySQL 口令（$u，不回显）: " p; echo
        try_conn "$u" "$p" || die "连不上 MySQL（${DB_HOST}:${DB_PORT}）。确认服务已启动、口令正确后重跑；也可手工填好 $DB_ENV_FILE 再重跑"
        ADMIN_MODE="tcp"; ADMIN_USER="$u"; ADMIN_PASS="$p"
    fi
    APP_PASS="$(python3 -c 'import secrets;print(secrets.token_hex(16))' 2>/dev/null || openssl rand -hex 16)"
    SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))' 2>/dev/null || openssl rand -hex 32)"
    admin_sql() {   # 以管理员身份执行一句 SQL
        if [[ -n "$DRY" ]]; then info "[dry-run] $1"; return 0; fi
        if [[ "$ADMIN_MODE" == "socket" ]]; then
            "$MYSQL_BIN" --default-character-set=utf8mb4 -e "$1"
        else
            MYSQL_PWD="$ADMIN_PASS" "$MYSQL_BIN" -h "$DB_HOST" -P "$DB_PORT" -u "$ADMIN_USER" \
                --default-character-set=utf8mb4 -e "$1"
        fi
    }
    set +e
    admin_sql "CREATE DATABASE IF NOT EXISTS $DB_NAME DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    admin_sql "CREATE USER IF NOT EXISTS '$APP_USER'@'localhost' IDENTIFIED BY '$APP_PASS';"
    admin_sql "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$APP_USER'@'localhost'; FLUSH PRIVILEGES;"
    if [[ -z "$DRY" ]] && ! try_conn "$APP_USER" "$APP_PASS"; then
        # 账号已存在但口令不是这次的（本项目专用账号，重置成新口令最省事）
        admin_sql "ALTER USER '$APP_USER'@'localhost' IDENTIFIED BY '$APP_PASS'; FLUSH PRIVILEGES;"
    fi
    set -e
    if [[ -z "$DRY" ]] && ! try_conn "$APP_USER" "$APP_PASS"; then
        die "应用账号 $APP_USER 已创建但连不上：检查 MySQL 的认证插件与权限"
    fi
    DB_USER="$APP_USER"; DB_PASS="$APP_PASS"; CONFIGURED=1
    if [[ -n "$DRY" ]]; then
        info "[dry-run] 会写 db.env（$APP_USER + 随机口令 + 随机 MODEL_SECRET_KEY）"
    else
        [[ -f "$DB_ENV_FILE" ]] && cp "$DB_ENV_FILE" "$DB_ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
        cat > "$DB_ENV_FILE" <<EOF
# 由 deploy 脚本自动生成（$(date '+%Y-%m-%d %H:%M:%S')）
# 要改口令 / 库名 / 端口：直接编辑本文件，再重跑一次 deploy 即可（脚本不会覆盖能连上的配置）。
MODEL_DB_DIALECT=mysql
MODEL_DB_HOST=$DB_HOST
MODEL_DB_PORT=$DB_PORT
MODEL_DB_USER=$APP_USER
MODEL_DB_PASSWORD=$APP_PASS
MODEL_DB_NAME=$DB_NAME
MODEL_SECRET_KEY=$SECRET
MODEL_TOKEN_TTL_HOURS=12
MODEL_BOOTSTRAP_ADMIN_PASSWORD=
EOF
        chmod 600 "$DB_ENV_FILE" 2>/dev/null || true
        ok "已建库 $DB_NAME、建账号 $APP_USER（随机口令），并写好 $DB_ENV_FILE"
        info "  账号口令与 MODEL_SECRET_KEY 都在这个文件里；要改就编辑它再重跑"
    fi
fi
[[ -z "$DRY" && -z "$CONFIGURED" ]] && die "数据库配置未完成"
info "数据库：${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

# 「查配置」：连着之后问一下服务端真实的端口/版本，写进 db.env 的就是**实际值**而不是我们的猜测
if [[ -z "$DRY" && -n "$CONFIGURED" ]]; then
    REAL_INFO="$(MYSQL_PWD="$DB_PASS" "$MYSQL_BIN" -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -N -B \
                 -e "SELECT CONCAT(@@port, ' ', @@version)" 2>/dev/null || true)"
    REAL_PORT="${REAL_INFO%% *}"; REAL_VER="${REAL_INFO#* }"
    if [[ -n "$REAL_PORT" && "$REAL_PORT" =~ ^[0-9]+$ && "$REAL_PORT" != "$DB_PORT" ]]; then
        info "服务端报告实际端口是 $REAL_PORT（配置里写的是 $DB_PORT），按实际值更新 db.env"
        sed -i "s|^[[:space:]]*MODEL_DB_PORT[[:space:]]*=.*|MODEL_DB_PORT=$REAL_PORT|" "$DB_ENV_FILE" 2>/dev/null || true
        DB_PORT="$REAL_PORT"
    fi
    [[ -n "$REAL_VER" ]] && ok "MySQL 版本：$REAL_VER（端口 ${REAL_PORT:-$DB_PORT}）"
fi

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

# ---------------------------------------------------------------- 4) 建库建表（用刚配好的应用账号）
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
# ⚠️ 只取第一行、并在冒号处截断：某些环境（如 Git Bash）里 id 的输出可能带 "名字:uid" 或多行，
#    直接塞进 systemd 的 User=/Group= 会让服务启动失败（systemd 报 "Invalid user/group"）。
RUN_USER="$(printf '%s' "${SUDO_USER:-$(id -un)}" | head -n1 | cut -d: -f1)"
RUN_GROUP="$(printf '%s' "$(id -gn "$RUN_USER" 2>/dev/null || echo "$RUN_USER")" | head -n1 | cut -d: -f1)"
[[ -n "$RUN_GROUP" ]] || RUN_GROUP="$RUN_USER"
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

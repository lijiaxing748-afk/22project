#!/usr/bin/env bash
# =====================================================================
#  模型管理平台 · 一条命令部署 / 更新 / 运行（Linux）
#
#  做了什么（幂等，可以反复跑）：
#     1) 检查并准备好 Python venv 与依赖（缺才装；有离线 wheel 目录就用它）
#     2) 探测 MySQL：没有就自动安装（apt）；有就查它的实际端口/版本
#     3) 自动配置数据库：建库 + 建专用账号 model_app（随机口令）+ 写 db.env（含随机密钥）
#     4) 准备前端产物 frontend/22project/dist（缺且本机有 npm 就自动构建）
#     5) 装成 systemd 服务：开机自启、崩溃自动重启、日志进 journald
#     6) 放行防火墙端口，打印**局域网访问地址**
#
#  用法（在项目根目录）：
#     sudo bash start.sh                安装/更新并启动（默认动作）
#     sudo bash start.sh update         拉取仓库最新代码 → 重建前端 → 重启服务
#     sudo bash start.sh status         看状态 + 最近日志
#     sudo bash start.sh logs           跟踪日志（Ctrl+C 退出）
#     sudo bash start.sh restart        重启
#     bash start.sh run                 本机前台跑（自动开浏览器，关窗口即停；不装服务）
#     sudo bash start.sh uninstall      卸载服务（不动数据库与 data 目录）
#     bash stop.sh                      停止服务（等价：sudo bash start.sh stop；end.sh 也可以）
#     MODEL_PORT=8081 sudo bash start.sh   换端口部署
#     DRY_RUN=1 bash start.sh           只打印将要做什么，不真改系统（排查用）
#
#  ⚠️ 早期版本的这个脚本叫 deploy.sh，现已改名为 start.sh（deploy.sh 仍保留为一层转发）。
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
FOREGROUND=""
PY="$SRV/venv/bin/python"

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
# ⚠️ 这里每个子命令都必须是**幂等**的：没装/重复跑都不该"报错退出"，只提示 —— 否则运维会以为坏了。
svc_installed() { systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}\.service"; }

# 「把属于本项目的进程收干净」——stop/uninstall 时调用，让**整个目录可以直接删除**。
# ⚠️ 只按两类判定：① 程序本体（/proc/PID/exe）在项目目录里；② 占着本项目端口。
#    命令行里只是"提到"项目路径的进程**一律不动**（避免误杀调用它的终端）。
stop_owned_processes() {
    local pids=() pid exe d n=0
    for d in /proc/[0-9]*; do
        pid="${d#/proc/}"
        exe="$(readlink -f "$d/exe" 2>/dev/null || true)"
        if [[ -n "$exe" && ( "$exe" == "$ROOT"/* || "$exe" == "$SRV"/* ) ]]; then pids+=("$pid"); fi
    done
    if command -v ss >/dev/null; then
        while read -r pid; do [[ -n "$pid" ]] && pids+=("$pid"); done < <(
            ss -ltnpH 2>/dev/null | awk -v pat=":$PORT\$" '$4 ~ pat {print}' | grep -oE 'pid=[0-9]+' | cut -d= -f2)
    fi
    for pid in $(printf '%s\n' "${pids[@]:-}" | grep -E '^[0-9]+$' | sort -unr); do
        [[ "$pid" == "$$" ]] && continue
        run "kill -TERM '$pid' 2>/dev/null || true"
        n=$((n+1))
    done
    [[ "$n" -gt 0 ]] && sleep 1
    info "结束了 $n 个残留进程"
}
show_folder_free() {
    local left="" d exe
    for d in /proc/[0-9]*; do
        exe="$(readlink -f "$d/exe" 2>/dev/null || true)"
        if [[ -n "$exe" && ( "$exe" == "$ROOT"/* || "$exe" == "$SRV"/* ) ]]; then left="$left ${d#/proc/}"; fi
    done
    if [[ -z "$left" ]] && ! (command -v ss >/dev/null && ss -ltnH 2>/dev/null | grep -q ":${PORT}\$"); then
        ok "整个目录已不被任何进程占用 —— 现在可以直接删除 $ROOT"
        info "（数据库与 $SRV/data 不受影响；只是想删文件夹的话不用管它们）"
        info "万一还是删不掉：多半是有个终端 cd 在里面，关掉它即可"
    else
        warn "仍在运行/占用：${left:-端口 $PORT} —— 先处理这些再删目录"
    fi
}
case "$MODE" in
    status)
        if svc_installed; then
            systemctl status "$SERVICE" --no-pager -l 2>/dev/null || true
            systemctl is-enabled "$SERVICE" 2>/dev/null | sed 's/^/     开机自启: /' || true
        else
            warn "服务还没安装（执行 sudo bash start.sh 安装并启动；只想本机跑就 bash start.sh run）"
        fi
        exit 0 ;;
    logs)
        if svc_installed; then journalctl -u "$SERVICE" -f -n 80
        else warn "服务还没安装，没有 journald 日志；前台跑（bash start.sh run）时直接看那个终端"; exit 0; fi ;;
    restart)
        need_root
        if svc_installed; then run "systemctl restart '$SERVICE'"; ok "已重启（$SERVICE）"
        else warn "服务还没安装 —— 直接执行 sudo bash start.sh 即可（装好并启动）"; fi
        exit 0 ;;
    start)
        need_root
        if svc_installed; then run "systemctl start '$SERVICE'"; ok "已启动（$SERVICE）"
        else warn "服务还没安装 —— 直接执行 sudo bash start.sh 即可"; fi
        exit 0 ;;
    stop)
        need_root
        if svc_installed; then run "systemctl stop '$SERVICE'"; ok "已停止（$SERVICE）"
        else warn "服务本来就没安装/没在跑"; fi
        # 服务停了不等于进程都没了（可能是 bash start.sh run 的前台实例或残留子进程）
        stop_owned_processes
        show_folder_free
        exit 0 ;;
    uninstall)
        need_root
        info "卸载 systemd 服务（数据库与 $SRV/data 一概不动）——目标是让整个目录可以直接删"
        run "systemctl stop '$SERVICE' 2>/dev/null || true"
        run "systemctl disable '$SERVICE' 2>/dev/null || true"      # ⚠️ 关键：不禁用开机自启，删目录时它还会起来
        run "rm -f '$UNIT'"
        run "systemctl daemon-reload"
        stop_owned_processes
        show_folder_free
        ok "已卸载。数据目录与数据库保留：$SRV/data"
        exit 0 ;;
    update)
        # 「更新到仓库最新代码」：拉代码 → 重建前端 → 重启服务。
        # ⚠️ 用 --ff-only --autostash：本地有改动（比如训练产物 data/models/* 是被 git 跟踪的）
        #    先自动暂存再拉，拉完再放回来；真冲突了就明确报错让人处理，绝不硬覆盖别人机器上的东西。
        need_root
        command -v git >/dev/null || die "本机没有 git，无法自动更新：请手动覆盖代码后执行 sudo bash start.sh upgrade"
        info "拉取仓库最新代码..."
        run "git -C '$ROOT' fetch --all --prune"
        if [[ -z "$DRY" ]]; then
            if ! git -C "$ROOT" pull --ff-only --autostash; then
                die "更新失败：多半是本地改动与远端冲突。请手工处理（git -C $ROOT status）后重跑；只重建前端+重启可用： sudo bash start.sh upgrade"
            fi
            ok "代码已更新到 $(git -C "$ROOT" rev-parse --short HEAD)（$(git -C "$ROOT" log -1 --format=%s)）"
        else
            info "[dry-run] git -C '$ROOT' pull --ff-only --autostash"
        fi
        MODE="install"; UPGRADE=1 ;;
    upgrade)
        MODE="install"; UPGRADE=1 ;;
    run|foreground|dev)
        # 本机前台跑（不装服务）：自动开浏览器，Ctrl+C / 关窗口即停
        FOREGROUND=1; MODE="install" ;;
    install) UPGRADE="${UPGRADE:-}" ;;
    *) die "未知动作：$MODE（可用：install / update / run / status / logs / restart / start / stop / upgrade / uninstall）" ;;
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
# ⚠️ 必须 Python **3.12**：requirements.txt 里 numpy==2.5.3 要求 >=3.12、tensorflow 2.21 也只有 3.12 的轮子。
#    实测踩过：机器上 `python3` 是 3.11，脚本"拿到哪个用哪个" → 装依赖时报
#    "No matching distribution found for numpy==2.5.3"（cp311 上根本没有 2.5.3）。所以这里**校验版本**。
PY="$SRV/venv/bin/python"
py_ver_of() { "$1" -c 'import sys;print("%d.%d" % sys.version_info[:2])' 2>/dev/null | tr -d '\r'; }
find_py312() {
    for c in python3.12 python3; do
        if command -v "$c" >/dev/null 2>&1; then
            v="$(py_ver_of "$(command -v "$c")")"
            [[ "$v" == "3.12" ]] && { command -v "$c"; return 0; }
        fi
    done
    for p in /usr/bin/python3.12 /usr/local/bin/python3.12; do
        [[ -x "$p" && "$(py_ver_of "$p")" == "3.12" ]] && { echo "$p"; return 0; }
    done
    return 1
}
if [[ -x "$PY" ]]; then
    CUR_VER="$(py_ver_of "$PY")"
    if [[ "$CUR_VER" != "3.12" ]]; then
        die "现有 venv 用的是 Python ${CUR_VER:-未知}，但 requirements.txt 要求 3.12（numpy==2.5.3 需 >=3.12）。
        修：rm -rf '$SRV/venv' 后重跑；或加 RECREATE_VENV=1 让它自动重建：
            RECREATE_VENV=1 sudo bash start.sh"
    fi
    ok "Python 环境：$("$PY" -V 2>/dev/null | tr -d '\r')"
elif [[ ! -x "$PY" ]]; then
    info "缺少 venv，创建并安装依赖（有 wheels/ 或 dist-linux 里的离线 wheel 会优先用）..."
    PY312="$(find_py312 || true)"
    if [[ -n "$DRY" ]]; then
        info "会用的解释器：${PY312:-（本机没找到 3.12，真实运行会报错并给出安装命令）}"
        info "[dry-run] 会创建 venv 并安装 requirements.txt"
    else
        if [[ -z "$PY312" ]]; then
            die "没找到 Python 3.12（本平台要求 3.12：numpy==2.5.3 需 >=3.12、tensorflow 2.21 只有 3.12 的轮子）。
        装一个： sudo apt update && sudo apt install -y python3.12 python3.12-venv python3.12-dev"
        fi
        # 已存在但版本不对的 venv（上面已拦）—— 这里处理"存在同名的空 venv"或 RECREATE_VENV
        if [[ -d "$SRV/venv" && -n "${RECREATE_VENV:-}" ]]; then
            warn "按 RECREATE_VENV=1 重建 venv"
            rm -rf "$SRV/venv"
        fi
        info "用 $PY312 创建 venv"
        run "'$PY312' -m venv '$SRV/venv'" || die "创建 venv 失败"
        WHEELS=""
        for d in "$ROOT/wheels" "$ROOT/offline_wheels" "$SRV/wheels"; do
            [[ -d "$d" ]] && WHEELS="$d" && break
        done
        if [[ -n "$WHEELS" ]]; then
            info "使用离线 wheel 目录：$WHEELS"
            run "'$PY' -m pip install --no-index --find-links='$WHEELS' -r '$SRV/requirements.txt'" \
                || die "离线安装失败：检查 wheels 目录里是否缺包、Python 版本是否匹配（必须是 3.12 的轮子）"
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
        # ⚠️ 构建失败时**不要**让整条命令挂掉：只要已经有旧的 dist，就继续用旧的（网站不会因为
        #    一次前端构建失败而停在"半更新"状态），把报错留给用户看。
        if ( cd "$FE" && { [[ -d node_modules ]] || npm install; } && npm run build ); then
            ok "前端产物已生成"
        elif [[ -f "$FE/dist/index.html" ]]; then
            warn "前端构建失败，但已有旧产物 —— 本次继续用旧的；修好上面的报错再重跑即可"
        else
            die "前端构建失败：cd $FE && npm install && npm run build"
        fi
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

# ---------------------------------------------------------------- 5) 前台跑（run 子命令，不装服务）
if [[ -n "$FOREGROUND" ]]; then
    [[ -x "$PY" ]] || die "还没有 venv：先执行 bash start.sh（不带参数）装依赖，或 bash start.sh setup"
    printf '\n%s\n' '============================================================'
    printf '  前台运行（不装服务）：Ctrl+C 停止\n'
    printf '  本机访问   : http://127.0.0.1:%s/\n' "$PORT"
    printf '  初始账号   : admin / Admin@2026\n'
    printf '%s\n\n' '============================================================'
    if [[ -z "${NO_BROWSER:-}" ]]; then
        ( for _ in $(seq 1 240); do
              if command -v curl >/dev/null && curl -fsS -m 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then break; fi
              sleep 0.7
          done
          if   command -v xdg-open >/dev/null; then xdg-open "http://127.0.0.1:$PORT/" >/dev/null 2>&1 &
          elif command -v open     >/dev/null; then open     "http://127.0.0.1:$PORT/" >/dev/null 2>&1 &
          fi ) &
    fi
    exec "$PY" "$SRV/serve.py" --host 0.0.0.0 --port "$PORT" --threads "$THREADS"
fi

# ---------------------------------------------------------------- 6) systemd 服务（**幂等：已装就更新配置再重启**）
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
# enable 重复执行本来就不报错；restart 在"服务还没装过"时会失败 → 退回 start（幂等）
run "systemctl enable '$SERVICE' >/dev/null 2>&1"
[[ -n "$UPGRADE" ]] && run "systemctl stop '$SERVICE' 2>/dev/null || true"
run "systemctl restart '$SERVICE' 2>/dev/null || systemctl start '$SERVICE' 2>/dev/null || true"

# ---------------------------------------------------------------- 7) 防火墙（已放行不报错）
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
    if ufw status 2>/dev/null | grep -q "${PORT}/tcp"; then
        info "ufw 已放行 ${PORT}/tcp（无需重复添加）"
    else
        run "ufw allow ${PORT}/tcp >/dev/null 2>&1" && ok "ufw 已放行 ${PORT}/tcp"
    fi
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    if firewall-cmd --list-ports 2>/dev/null | grep -q "${PORT}/tcp"; then
        info "firewalld 已放行 ${PORT}/tcp（无需重复添加）"
    else
        run "firewall-cmd --permanent --add-port=${PORT}/tcp >/dev/null 2>&1 && firewall-cmd --reload >/dev/null 2>&1" \
            && ok "firewalld 已放行 ${PORT}/tcp"
    fi
else
    info "未检测到启用的 ufw/firewalld —— 若局域网访问不通，请手工放行 ${PORT}/tcp"
fi

# ---------------------------------------------------------------- 8) 结果
# ⚠️ 优先用"默认路由所在网卡的地址"：装了代理/虚拟网卡时 hostname -I 的第一项可能是假网段
#    （实测在装了代理的机器上会拿到 198.18.x.x，那种地址发给同事是连不上的）。
LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{print $7; exit}')"
if [[ -z "$LAN_IP" ]]; then
    LAN_IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^(127\.|169\.254\.|198\.1[89]\.)' | head -n1)"
fi
printf '\n%s\n' '============================================================'
if [[ -z "$DRY" ]]; then
    if systemctl is-active --quiet "$SERVICE"; then
        ok "服务已启动，开机自启已开启（服务名 $SERVICE）"
    else
        warn "服务没起来：journalctl -u $SERVICE -n 50 看日志"
    fi
fi
printf '  本机访问   : http://127.0.0.1:%s/\n' "$PORT"
[[ -n "$LAN_IP" ]] && printf '  局域网访问 : http://%s:%s/     ← 把这个地址发给同事\n' "$LAN_IP" "$PORT"
printf '  初始账号   : admin / Admin@2026（交付现场请立刻改口令）\n'
printf '  更新代码   : sudo bash start.sh update\n'
printf '  停止 / 其它: bash stop.sh   |   sudo bash start.sh status logs restart uninstall\n'
printf '%s\n' '============================================================'

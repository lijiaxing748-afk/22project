#!/usr/bin/env bash
# =====================================================================
#  模型管理平台 · 数据库初始化脚本（Linux）
#
#  对应 Windows 版的 02-init-database.ps1。
#  做两件事：建库建表（schema_mysql.sql）-> 应用鉴权表迁移（auth-migration.sql）
#
#  用法：
#      chmod +x init-database.sh
#      ./init-database.sh
#
#  会交互式询问 MySQL 密码，**不会把密码写进任何文件或历史记录**。
# =====================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

C_OK=$'\033[32m'; C_ERR=$'\033[31m'; C_WARN=$'\033[33m'; C_INFO=$'\033[36m'; C_END=$'\033[0m'
say()  { echo "$1"; }
ok()   { echo "   ${C_OK}[OK]${C_END}   $1"; }
err()  { echo "   ${C_ERR}[错误]${C_END} $1"; }
warn() { echo "   ${C_WARN}[提示]${C_END} $1"; }
info() { echo "   ${C_INFO}[信息]${C_END} $1"; }
die()  { err "$1"; exit 1; }

# ---------------------------------------------------------------- 定位目录
# 同 install-backend.sh：按候选列表探测 serve.py，不写死目录名。
if [[ -n "${MODEL_APP_DIR:-}" ]]; then
    APP_DIR="$MODEL_APP_DIR"
else
    APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi

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
       MODEL_APP_DIR=/opt/model-platform/backend ./init-database.sh"
fi

say "============================================================"
say "  模型管理平台 · 初始化数据库"
say "============================================================"
say ""

# ---------------------------------------------------------------- 1 读取配置
# 从 db.env 读连接信息，但**只读非敏感项用于显示**；
# 密码一律交互输入，不从文件里取，也不回显。
ENV_FILE="$SRV_DIR/db.env"
[[ -f "$ENV_FILE" ]] || die "找不到 $ENV_FILE
       请先复制 db.env.example 为 db.env 并填好连接信息。"

get_env() {
    # 取 KEY=VALUE 形式的值，忽略注释行与空行
    local key="$1" default="${2:-}"
    local v
    v="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' || true)"
    echo "${v:-$default}"
}

DB_HOST="$(get_env MODEL_DB_HOST 127.0.0.1)"
DB_PORT="$(get_env MODEL_DB_PORT 3306)"
DB_USER="$(get_env MODEL_DB_USER root)"
DB_NAME="$(get_env MODEL_DB_NAME model_management)"

ok "读取配置：$DB_USER@$DB_HOST:$DB_PORT / $DB_NAME"
say ""

# ---------------------------------------------------------------- 2 检查 mysql 客户端
say "[1/5] 检查 MySQL 客户端"
if ! command -v mysql >/dev/null 2>&1; then
    die "找不到 mysql 客户端。请先安装：
           sudo apt update && sudo apt install -y mysql-client
       若本机就是数据库服务器，装完整服务端：
           sudo apt install -y mysql-server"
fi
ok "mysql 客户端：$(command -v mysql)"
say ""

# ---------------------------------------------------------------- 3 确认密码
say "[2/5] 连接数据库"
say ""
say "   请输入 MySQL 中 [$DB_USER] 账号的密码。"
say "   （输入时不会显示，这是正常现象）"
say "   ${C_WARN}注意：这里的密码应与 db.env 中 MODEL_DB_PASSWORD 完全一致。${C_END}"
say ""
read -r -s -p "   密码: " DB_PASS
echo ""

MYSQL_ARGS=(-h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" --default-character-set=utf8mb4)

# ⚠️ 用 MYSQL_PWD 而不是命令行 -p：
#    `mysql -p<密码>` 会把密码暴露在 `ps` 的进程列表里，同机器其他用户可见。
export MYSQL_PWD="$DB_PASS"

if ! mysql "${MYSQL_ARGS[@]}" -e "SELECT 1" >/dev/null 2>&1; then
    unset MYSQL_PWD
    err "连接失败。请检查："
    err "  1) 密码是否正确（与 db.env 的 MODEL_DB_PASSWORD 一致）"
    err "  2) MySQL 是否在运行： sudo systemctl status mysql"
    err "  3) 账号是否有权限从 $DB_HOST 连接"
    err "  4) 若报 \"'cryptography' package is required\"，说明缺少 python 的"
    err "     cryptography 包（PyMySQL 连 MySQL8 的 caching_sha2_password 需要它），"
    err "     执行： ./install-backend.sh 重装依赖即可补上。"
    exit 1
fi

MYSQL_VER="$(mysql "${MYSQL_ARGS[@]}" -N -B -e "SELECT VERSION()" 2>/dev/null || echo '?')"
ok "连接成功，MySQL 版本：$MYSQL_VER"
say ""

# ---------------------------------------------------------------- 4 建表
say "[3/5] 应用表结构（schema_mysql.sql）"
SCHEMA="$SRV_DIR/sql/schema_mysql.sql"
if [[ ! -f "$SCHEMA" ]]; then
    die "找不到建表脚本：$SCHEMA"
fi

if mysql "${MYSQL_ARGS[@]}" < "$SCHEMA"; then
    ok "表结构已应用"
else
    die "表结构应用失败。请检查上面的报错。"
fi
say ""

# ---------------------------------------------------------------- 5 鉴权迁移
# ⚠️ 与 Windows 版同样的顺序要求：必须先有基础表，再谈鉴权三表。
say "[4/5] 应用鉴权表（auth-migration.sql）"
AUTH_SQL="$SRV_DIR/sql/auth-migration.sql"
if [[ -f "$AUTH_SQL" ]]; then
    if mysql "${MYSQL_ARGS[@]}" < "$AUTH_SQL" 2>/dev/null; then
        ok "鉴权表已应用"
    else
        # 该脚本用 CREATE TABLE IF NOT EXISTS，重复执行是安全的；
        # 失败多半是权限或字符集问题，但不该中断后续校验。
        warn "鉴权迁移返回了错误（可能是表已存在，属正常）。"
        warn "手动确认： mysql ... -e \"SHOW TABLES FROM $DB_NAME LIKE '%'\""
    fi
else
    warn "找不到 auth-migration.sql —— 登录功能会报数据库错误。"
fi
say ""

# ---------------------------------------------------------------- 6 校验
say "[5/5] 校验关键表"
TABLES="$(mysql "${MYSQL_ARGS[@]}" -N -B -e "SHOW TABLES FROM \`$DB_NAME\`" 2>/dev/null || true)"

if [[ -z "$TABLES" ]]; then
    unset MYSQL_PWD
    die "库 $DB_NAME 里没有任何表 —— 建表可能没成功，请检查 schema_mysql.sql 的内容。"
fi

MISSING=0
for t in Datasets Models Trainings ModelInvocations ModelDeployments \
         InferenceTasks InferenceResults EdgeDevices Roles Users OperationLogs; do
    if echo "$TABLES" | grep -qx "$t"; then
        ok "$t"
    else
        err "缺少表：$t"
        MISSING=$((MISSING+1))
    fi
done

if [[ "$MISSING" -gt 0 ]]; then
    warn "有 $MISSING 张表缺失。"
    warn "其中 Roles / Users / OperationLogs 属于鉴权模块，缺失会导致无法登录。"
    warn "请确认 auth-migration.sql 已成功执行。"
else
    ok "全部 11 张表就位"
fi

unset MYSQL_PWD
say ""
say "============================================================"
say "  数据库初始化完成"
say "============================================================"
say ""
say "  说明：账号（admin / engineer / operator）**不由 SQL 创建**，"
say "        而是后端**首次启动**时通过 bootstrap_users() 自动建好，"
say "        口令取自 db.env 的 MODEL_BOOTSTRAP_ADMIN_PASSWORD。"
say ""
say "  下一步： sudo ./install-service.sh 安装为系统服务"
say "============================================================"

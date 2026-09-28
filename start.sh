#!/usr/bin/env bash
# 模型管理平台 · 一键启动（Linux / macOS）
#
# 用法：
#     bash start.sh               启动并自动打开浏览器（单端口，后端同时托管前端）
#     bash start.sh setup         首次：创建 venv 并安装依赖（需联网）
#     bash start.sh build         只构建前端产物（frontend/22project/dist）
#     MODEL_PORT=8081 bash start.sh     换端口
#     NO_BROWSER=1 bash start.sh        不自动开浏览器
#
# 与 Windows 的 start.bat 行为一致：缺什么就提示什么，能自动做的就自动做。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRV="$ROOT/testRestfulProject"
FE="$ROOT/frontend/22project"
PORT="${MODEL_PORT:-8080}"
MODE="${1:-run}"

say()  { printf '%s\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*"; exit 1; }

# Python 解释器：优先 venv（Linux 是 bin/，Windows 的 Git Bash 下是 Scripts/）
PY=""
for cand in "$SRV/venv/bin/python" "$SRV/venv/Scripts/python.exe"; do
    [[ -x "$cand" ]] && PY="$cand" && break
done

say "============================================================"
say "  模型管理平台 · 一键启动（单端口：后端同时托管前端）"
say "------------------------------------------------------------"
say "  项目目录 : $ROOT"
say "  访问地址 : http://127.0.0.1:$PORT/"
say "  换端口   : MODEL_PORT=8081 bash start.sh"
say "============================================================"
say ""

# ---------------------------------------------------------------- setup
if [[ "$MODE" == "setup" ]]; then
    command -v python3 >/dev/null || die "[错误] 找不到 python3。请先 apt install -y python3 python3-venv python3-pip"
    if [[ -z "$PY" ]]; then
        python3 -m venv "$SRV/venv" || die "[错误] 创建 venv 失败"
        PY="$SRV/venv/bin/python"
    fi
    say "      安装 requirements.txt（torch 需要 pytorch 的 cpu 源，见文件开头说明）..."
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r "$SRV/requirements.txt"
    say ""
    say "[OK] 依赖装好了。要用单端口跑，再执行一次 bash start.sh（会自动构建前端）。"
    exit 0
fi

# ---------------------------------------------------------------- build
if [[ "$MODE" == "build" ]]; then
    command -v npm >/dev/null || die "[错误] 本机没有 npm / Node.js。"
    cd "$FE" || die "[错误] 找不到 $FE"
    [[ -d node_modules ]] || npm install
    npm run build
    [[ -f "$FE/dist/index.html" ]] && say "[OK] 前端产物已生成：$FE/dist" || die "[错误] 构建失败，请看上面报错。"
    exit 0
fi

# ---------------------------------------------------------------- 1) Python 环境
if [[ -z "$PY" ]]; then
    warn "[缺少] 虚拟环境：$SRV/venv"
    say  ""
    say  "  首次使用执行： bash start.sh setup     （自动建 venv 并装依赖，需联网）"
    say  "  或手工："
    say  "      cd $SRV && python3 -m venv venv"
    say  "      venv/bin/pip install -r requirements.txt"
    say  ""
    say  "  离线/内网机器请用 docs/离线部署/ 或 docs/Linux部署/ 里的整套脚本（带离线 wheel）。"
    exit 1
fi

# ---------------------------------------------------------------- 2) 数据库配置
if [[ ! -f "$SRV/db.env" ]]; then
    if [[ -f "$SRV/db.env.example" ]]; then
        cp "$SRV/db.env.example" "$SRV/db.env"
        warn "[提示] 已从 db.env.example 生成 $SRV/db.env"
        say  "       请填好 MySQL 账号/口令与 MODEL_SECRET_KEY 后重新运行。"
    else
        warn "[错误] 缺少 $SRV/db.env（数据库配置），且找不到 db.env.example。"
    fi
    exit 1
fi

# ---------------------------------------------------------------- 3) 前端产物
if [[ ! -f "$FE/dist/index.html" ]]; then
    warn "[提示] 还没有前端产物 frontend/22project/dist —— 单端口模式下必须有它。"
    if command -v npm >/dev/null; then
        say  "       本机有 npm，现在自动构建（首次约 1 分钟）..."
        ( cd "$FE" && { [[ -d node_modules ]] || npm install; } && npm run build ) || true
        if [[ ! -f "$FE/dist/index.html" ]]; then
            die "[错误] 构建后仍然找不到 dist/index.html，请看上面的报错。"
        fi
        say  "[OK] 前端产物已生成"
    else
        say  "       本机没有 npm：请在有 Node.js 的机器上执行"
        say  "           cd $FE && npm install && npm run build"
        say  "       然后把 frontend/22project/dist 整个目录拷过来。"
        exit 1
    fi
    say ""
fi

# ---------------------------------------------------------------- 4) 端口占用
port_busy() {
    if command -v ss >/dev/null; then ss -ltn 2>/dev/null | grep -q ":$1 "; return $?; fi
    if command -v netstat >/dev/null; then netstat -ltn 2>/dev/null | grep -q ":$1 "; return $?; fi
    return 1
}
if port_busy "$PORT"; then
    warn "[提示] 端口 $PORT 已被占用 —— 可能平台/前端已经在跑。"
    say  "       直接打开看看： http://127.0.0.1:$PORT/"
    say  "       要另起一个实例就换端口： MODEL_PORT=8081 bash start.sh"
    exit 0
fi

# ---------------------------------------------------------------- 5) 启动 + 自动开浏览器
say "[1/2] 启动服务（waitress 单端口 $PORT）... 按 Ctrl+C 停止"
if [[ -z "${NO_BROWSER:-}" ]]; then
    (
        for _ in $(seq 1 240); do
            if command -v curl >/dev/null && curl -fsS -m 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then break; fi
            sleep 0.7
        done
        if   command -v xdg-open >/dev/null; then xdg-open "http://127.0.0.1:$PORT/" >/dev/null 2>&1 &
        elif command -v open     >/dev/null; then open     "http://127.0.0.1:$PORT/" >/dev/null 2>&1 &
        fi
    ) &
fi
say "[2/2] 浏览器会自动打开；没弹出来就手动访问 http://127.0.0.1:$PORT/"
say "      初始账号： admin / Admin@2026   （交付现场请先改口令）"
say ""
exec "$PY" "$SRV/serve.py" --host 0.0.0.0 --port "$PORT" --threads 6

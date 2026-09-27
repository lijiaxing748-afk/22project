#!/usr/bin/env bash
# =====================================================================
#  模型管理平台 · 后端依赖安装脚本（Linux）
#
#  对应 Windows 版的 01-install-backend.ps1。
#  做三件事：创建 venv -> 装 torch（特殊源）-> 装其余依赖
#
#  用法：
#      chmod +x install-backend.sh
#      ./install-backend.sh
#      （不需要 sudo：全部装在项目内的 venv 里，不碰系统环境）
#
#  ⚠️ 关于 torch 为什么单独装：
#      requirements.txt 里写的是 torch==2.14.0+cpu，带 "+cpu" 后缀的包
#      **不在 PyPI 上**，只在 PyTorch 官方 CPU 索引里。直接
#      `pip install -r requirements.txt` 会报：
#          ERROR: No matching distribution found for torch==2.14.0+cpu
#      这是**预期行为**，不是依赖清单写错了 —— 必须先从官方源单独装 torch，
#      再装其余依赖。Windows 版同样如此。
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
# ⚠️ 不写死"后端就在根下"或"叫 testRestfulProject"：打包方式不同，
#    serve.py 可能落在根、根/backend、根/testRestfulProject …… 都可能。
#    所以这里按**候选列表**逐个探测，命中即用；都不中才报错并列出找过的位置。
#    可用 MODEL_APP_DIR 显式指定根目录（适用于完全自定的布局）。
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
       MODEL_APP_DIR=/opt/model-platform/backend bash install-backend.sh"
fi

say "============================================================"
say "  模型管理平台 · 安装后端依赖"
say "============================================================"
say "  后端目录：$SRV_DIR"
say ""

# ---------------------------------------------------------------- 1 Python 检查
say "[1/4] 检查 Python"

# ⚠️ 优先用 python3.12：Ubuntu 24.04 自带 3.12，但若系统里装了多个版本，
#    裸 `python3` 未必是 3.12。这里逐个候选探测，找到第一个 >= 3.10 的。
PY=""
for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        v="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")"
        major="${v%%.*}"; minor="${v##*.}"
        if [[ "$major" -eq 3 && "$minor" -ge 10 ]]; then
            PY="$(command -v "$cand")"
            ok "使用 $cand（$v）-> $PY"
            break
        fi
    fi
done

[[ -n "$PY" ]] || die "没找到 Python 3.10+。
       Ubuntu 24.04 自带 3.12，若缺失请执行：
           sudo apt update && sudo apt install -y python3 python3-venv python3-pip"

PYVER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [[ "$PYVER" != "3.12" ]]; then
    warn "当前是 Python $PYVER，建议 3.12（与开发环境一致）。"
    warn "继续安装，但个别依赖的 wheel 版本可能有差异。"
fi

# venv 模块是单独的系统包，Ubuntu 上默认可能没装
if ! "$PY" -c "import venv" >/dev/null 2>&1; then
    die "缺少 venv 模块。请执行：
           sudo apt install -y python3-venv"
fi
say ""

# ---------------------------------------------------------------- 2 创建 venv
say "[2/4] 创建虚拟环境"
VENV_DIR="$SRV_DIR/venv"
if [[ -x "$VENV_DIR/bin/python" ]]; then
    ok "venv 已存在，跳过创建（如需重建请先删除 $VENV_DIR）"
else
    "$PY" -m venv "$VENV_DIR"
    ok "已创建 $VENV_DIR"
fi
VPY="$VENV_DIR/bin/python"
"$VPY" -m pip install --upgrade pip --quiet
ok "pip 已更新（$("$VPY" -m pip --version | awk '{print $2}')）"
say ""

# ---------------------------------------------------------------- 3 装依赖
REQ="$SRV_DIR/requirements.txt"
[[ -f "$REQ" ]] || die "找不到 $REQ"

say "[3/4] 安装依赖（这一步最慢，TensorFlow 约 200MB，请耐心等待）"

info "[3.1] 先装 torch（走 PyTorch 官方 CPU 源）"
if "$VPY" -c "import torch" >/dev/null 2>&1; then
    ok "torch 已安装（$("$VPY" -c 'import torch; print(torch.__version__)')），跳过"
else
    # ⚠️ 故意不用 `grep -oP`：-P（PCRE）在部分环境（BusyBox、macOS、老版 grep）不可用，
    #    会导致脚本在这些机器上直接报错。改用 sed，可移植性最好。
    TORCH_VER="$(sed -n 's/^torch==\([0-9][0-9.]*\).*/\1/p' "$REQ" | head -1)"
    TORCH_VER="${TORCH_VER:-2.14.0}"
    info "目标版本：${TORCH_VER}+cpu"
    if ! "$VPY" -m pip install "torch==${TORCH_VER}+cpu" \
            --index-url https://download.pytorch.org/whl/cpu; then
        warn "torch 安装失败。若目标机器**离线**，请在本脚本外先准备好 wheel："
        warn "    pip download torch==${TORCH_VER}+cpu --index-url https://download.pytorch.org/whl/cpu -d ./wheels"
        warn "然后： $VPY -m pip install --no-index --find-links=./wheels torch==${TORCH_VER}+cpu"
        warn "其余依赖仍会继续安装。"
    else
        ok "torch 安装完成"
    fi
fi

info "[3.2] 安装其余依赖（-r requirements.txt）"
# ⚠️ torch 已在上面单独装好，这里 pip 会因"已满足"而快速跳过它；
#    若不加下面的容错，一旦 torch 装失败，整条命令会中断，后面全装不上。
if ! "$VPY" -m pip install -r "$REQ"; then
    warn "直接安装依赖失败，尝试跳过 torch 行后重试 ..."
    # 生成一份剔除了 torch 行的临时清单（torch 已在 3.1 单独处理过）
    TMP_REQ="$(mktemp)"
    grep -v '^torch==' "$REQ" > "$TMP_REQ"
    "$VPY" -m pip install -r "$TMP_REQ" || die "依赖安装失败，请检查上面的报错。"
    rm -f "$TMP_REQ"
fi
ok "依赖安装完成"
say ""

# ---------------------------------------------------------------- 4 校验
say "[4/4] 校验关键依赖"
MISSING=0
for mod in flask waitress pymysql numpy pandas tensorflow keras sklearn matplotlib cryptography; do
    if "$VPY" -c "import $mod" >/dev/null 2>&1; then
        ver="$("$VPY" -c "import $mod; print(getattr($mod,'__version__','?'))" 2>/dev/null || echo '?')"
        ok "$mod ($ver)"
    else
        err "缺少 $mod"
        MISSING=$((MISSING+1))
    fi
done

# torch 单独报：它可能因离线而没装上，但其余功能不受影响
if "$VPY" -c "import torch" >/dev/null 2>&1; then
    ok "torch ($("$VPY" -c 'import torch; print(torch.__version__)'))"
else
    warn "torch 未安装 —— cwt_cnn 模型将无法训练/推理，其余功能正常"
fi

if [[ "$MISSING" -gt 0 ]]; then
    die "有 $MISSING 个关键依赖缺失，请查看上面的报错。"
fi
say ""

say "============================================================"
say "  后端依赖安装完成"
say "============================================================"
say ""
say "  下一步："
say "     1. 确认 db.env 已填好数据库连接信息"
say "     2. 执行 ./init-database.sh 初始化数据库"
say "     3. 执行 sudo ./install-service.sh 安装为系统服务"
say "============================================================"

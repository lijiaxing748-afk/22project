#!/usr/bin/env bash
# =====================================================================
#  fix-net.sh —— 一键排查/修复「国内 + 代理(fake-ip)」环境下的外网访问
#
#  典型症状（我这次遇到的）：apt/curl 上不了网，报
#      Could not handshake: The TLS connection was non-properly terminated. [IP: 198.18.0.145 443]
#      E: The repository '... focal Release' no longer has a Release file.
#  而 198.18.0.0/15 正是 Clash / sing-box 这类代理 **fake-ip** 模式的默认网段：
#  域名没被解析成真实 IP，而是被代理伪造成 198.18.x，流量又没被正确转发 → TLS 直接断。
#
#  关键认知：**走代理时不需要本地 DNS**（DNS 由代理完成），所以"配好代理"就能绕过 fake-ip。
#           本脚本会：① 诊断 → ② 自动找可用代理（含宿主机上的常见端口）→ ③ 写进 apt/pip/环境变量
#                    → ④ 代理不通时逐个试国内镜像并改 apt 源 → ⑤ 验证并打印结论。
#
#  用法：
#      sudo bash fix-net.sh            # 修复（改 apt/pip/环境变量，会先备份）
#      bash fix-net.sh --dry-run       # 只诊断，什么都不改
#      bash fix-net.sh --proxy http://192.168.1.5:7890    # 手工指定代理
#
#  ⚠️ 它**不能**修的情况：代理本身没开、或宿主机（Windows）防火墙没放行代理端口 ——
#     这时只能去宿主机上改（脚本末尾会打印清单）。
# =====================================================================
set -u
DRY=0
PROXY_MANUAL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --proxy)   PROXY_MANUAL="${2:-}"; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    esac
    shift
done

say()  { printf '%s\n' "$*"; }
ok()   { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info() { printf '     %s\n' "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[错误]\033[0m %s\n' "$*"; }
step() { printf '\n\033[36m== %s ==\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 0) 环境
step '0) 环境识别'
DISTRO="$(. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-unknown}")"
PRETTY="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}")"
IS_WSL=0; grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1
info "系统      : $PRETTY（代号 $DISTRO）"
info "是否 WSL  : $( [[ $IS_WSL -eq 1 ]] && echo 是 || echo 否 )"
info "当前用户  : $(id -un)（改 apt/pip 配置需要 root）"

HOST_IP=""
if [[ $IS_WSL -eq 1 ]]; then
    HOST_IP="$(ip route show default 2>/dev/null | awk '/^default/{print $3; exit}')"
    [[ -z "$HOST_IP" ]] && HOST_IP="$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf 2>/dev/null)"
fi
info "宿主机/网关 IP: ${HOST_IP:-（未知）}"
command -v curl >/dev/null || { err '需要 curl：sudo apt install -y curl（若 apt 也不通，先看下面的镜像测试）'; }

# ---------------------------------------------------------------- 1) DNS 诊断
step '1) DNS 诊断（看域名有没有被 fake-ip 接管）'
for d in mirrors.tuna.tsinghua.edu.cn pypi.org; do
    ip="$(getent hosts "$d" 2>/dev/null | awk '{print $1; exit}')"
    info "$d → ${ip:-解析失败}"
    case "$ip" in
        198.18.*|198.19.*) warn "$ip 属于 fake-ip 网段（代理伪造），本机 DNS 已被代理接管" ;;
    esac
done
info "本机 resolv.conf："
awk '/^nameserver/{printf "       nameserver %s\n", $2}' /etc/resolv.conf 2>/dev/null

# ---------------------------------------------------------------- 2) 找可用代理
step '2) 找可用代理（环境变量 → 宿主机常见端口 → 手工指定）'
test_proxy() {   # $1 = proxy url
    [[ -z "$1" ]] && return 1
    curl -fsS -m 8 -x "$1" -o /dev/null https://www.baidu.com 2>/dev/null
}
PROXY=""
if [[ -n "$PROXY_MANUAL" ]]; then
    if test_proxy "$PROXY_MANUAL"; then PROXY="$PROXY_MANUAL"; ok "手工指定的代理可用：$PROXY"
    else warn "手工指定的代理 $PROXY_MANUAL 连不通"; fi
fi
if [[ -z "$PROXY" ]]; then
    for v in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY; do
        val="${!v:-}"
        if [[ -n "$val" ]] && test_proxy "$val"; then PROXY="$val"; ok "环境变量里的代理可用（\$$v）：$PROXY"; break; fi
    done
fi
if [[ -z "$PROXY" && -n "$HOST_IP" ]]; then
    info "在宿主机 $HOST_IP 上探测常见代理端口（Clash 7890/7897、v2ray 10809、通用 1080/2080...）"
    found=""
    for port in 7890 7897 10809 1080 2080 8889 7891 8118; do
        for cand in "http://$HOST_IP:$port" "socks5h://$HOST_IP:$port"; do
            if test_proxy "$cand"; then found="$cand"; break 2; fi
        done
    done
    [[ -n "$found" ]] && { PROXY="$found"; ok "找到可用代理：$PROXY"; }
fi
[[ -z "$PROXY" ]] && warn '没有找到可用代理'

# ---------------------------------------------------------------- 3) 写配置
step '3) 应用配置（apt / pip / 环境变量）'
if [[ -z "$PROXY" ]]; then
    info '跳过（没有可用代理）'
elif [[ $DRY -eq 1 ]]; then
    info "[dry-run] 会写 /etc/apt/apt.conf.d/99model-proxy、~/ 的 pip.conf 与 profile.d，内容指向：$PROXY"
else
    if [[ "$(id -u)" -ne 0 ]]; then
        warn '当前不是 root：apt 配置写不了，只设置当前 shell 的环境变量'
    else
        f=/etc/apt/apt.conf.d/99model-proxy
        [[ -f $f ]] && cp -a "$f" "$f.bak-$(date +%s)"
        printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$PROXY" "$PROXY" > "$f"
        ok "已写 $f（删掉它即可恢复直连）"
    fi
    if [[ "$(id -u)" -eq 0 ]]; then
        cat > /etc/profile.d/99-model-proxy.sh <<EOF
# 由 fix-net.sh 生成：让登录 shell 自动带上代理（删掉本文件即恢复）
export http_proxy="$PROXY"
export https_proxy="$PROXY"
export all_proxy="$PROXY"
export no_proxy="localhost,127.0.0.1,::1,${HOST_IP:-}"
EOF
        ok '已写 /etc/profile.d/99-model-proxy.sh（新开的 shell 自动生效）'
    else
        warn '不是 root：跳过 /etc/profile.d（可在自己的 ~/.bashrc 里加同样几行）'
    fi
    mkdir -p "${HOME}/.config/pip"
    cat > "${HOME}/.config/pip/pip.conf" <<EOF
[global]
proxy = $PROXY
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF
    ok "已写 ${HOME}/.config/pip/pip.conf（pip 走代理 + 国内源）"
    export http_proxy="$PROXY" https_proxy="$PROXY" all_proxy="$PROXY"
fi

# ---------------------------------------------------------------- 4) 镜像测试 + apt 源
step '4) 直连镜像测试（代理不通时的兜底：换一个能连上的源）'
DISTRO_OK="$DISTRO"
[[ "$DISTRO" == "unknown" ]] && { DISTRO_OK="focal"; warn "认不出代号，镜像测试按 focal 试"; }
MIRRORS=(
  "https://mirrors.tuna.tsinghua.edu.cn/ubuntu"
  "https://mirrors.aliyun.com/ubuntu"
  "https://mirrors.ustc.edu.cn/ubuntu"
  "https://repo.huaweicloud.com/ubuntu"
  "http://mirrors.163.com/ubuntu"
)
WORK=""
for m in "${MIRRORS[@]}"; do
    if curl -fsS -m 12 -o /dev/null "$m/dists/$DISTRO_OK/Release" 2>/dev/null; then WORK="$m"; ok "可用镜像：$m"; break; fi
    info "不通：$m"
done
if [[ -z "$WORK" ]]; then
    warn '所有镜像都连不通 —— 说明这台机器当前确实上不了外网（见最后的宿主机清单）'
elif [[ $DRY -eq 1 ]]; then
    info "[dry-run] 会把 apt 源改成 $WORK 并执行 apt-get update"
else
    if [[ "$(id -u)" -ne 0 ]]; then
        warn '不是 root，跳过改 apt 源'
    else
        src=/etc/apt/sources.list
        if [[ -f $src ]]; then
            cp -a "$src" "$src.bak-$(date +%s)" 2>/dev/null
            if grep -qE '^deb ' "$src"; then
                sed -i.bak-fixnet -E "s#https?://[^ ]+/ubuntu#${WORK}#g" "$src"
                ok "已把 $src 里的镜像地址换成 $WORK（备份同目录 *.bak-*）"
            else
                info "$src 不是传统 one-line 格式（可能是 deb822），未改动；如需换源请手工处理"
            fi
        fi
        for f in /etc/apt/sources.list.d/*.list; do
            [[ -f "$f" ]] || continue
            grep -qE '^deb ' "$f" 2>/dev/null || continue
            cp -a "$f" "$f.bak-$(date +%s)" 2>/dev/null
            sed -i -E "s#https?://[^ ]+/ubuntu#${WORK}#g" "$f"
            info "已处理 $f"
        done
    fi
    info '执行 apt-get update ...'
    apt-get update -y 2>&1 | tail -n 5 | sed 's/^/       /'
fi

# ---------------------------------------------------------------- 5) 验证
step '5) 验证'
if [[ $DRY -eq 0 ]]; then
    curl -fsS -m 10 -o /dev/null -w '      访问 baidu: HTTP %{http_code}\n' https://www.baidu.com 2>/dev/null \
        || warn 'baidu 都访问不了'
    if curl -fsS -m 12 -o /dev/null https://pypi.tuna.tsinghua.edu.cn/simple/ 2>/dev/null; then
        ok 'PyPI 国内源可达'
    else
        warn 'PyPI 国内源不可达'
    fi
    if [[ "$DISTRO" == "focal" ]]; then
        warn '注意：Ubuntu 20.04(focal) 官方源里**没有 python3.12** —— 网络修好后，start.sh 会走 deadsnakes PPA；'
        info '      PPA 里若也没有 focal 的 3.12，就只能换 Ubuntu 24.04 或离线安装。'
    fi
fi

# ---------------------------------------------------------------- 6) 还不行时
step '6) 如果上面仍然不通：去**宿主机（Windows）**上检查'
cat <<'EOF'
      · 代理软件是否在运行（Clash / v2rayN / sing-box …），有没有开「允许局域网连接 / Allow LAN」；
      · Windows 防火墙是否放行代理端口（Clash 默认 7890；有的版本是 7897）；
      · 若代理是 TUN 模式：WSL/虚拟机 的流量不一定被接管 —— 更稳的是关掉 TUN、
        改用「系统代理 + Allow LAN」，再让 Linux 这边走 http://<宿主机IP>:端口；
      · 在 Windows 上验证端口：   Test-NetConnection <宿主机IP> -Port 7890
      · 本机再验一次代理：        curl -x http://<宿主机IP>:7890 -I https://www.baidu.com
      · 想恢复本脚本的改动：      删 /etc/apt/apt.conf.d/99model-proxy、/etc/profile.d/99-model-proxy.sh，
                                 以及 /etc/apt/sources.list 同目录的 *.bak-* 覆盖回去
EOF
say ''
ok '完成。新开一个 shell（或 source /etc/profile.d/99-model-proxy.sh）后再跑 apt/pip/start.sh'

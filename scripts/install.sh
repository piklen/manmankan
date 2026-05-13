#!/usr/bin/env bash
# manmankan 一键安装脚本 · mac / Linux
#
# 调用方式（用户复制粘贴一行）：
#   curl -LsSf https://raw.githubusercontent.com/piklen/manmankan/main/scripts/install.sh | bash
#
# 想自己看完再装：
#   curl -L https://raw.githubusercontent.com/piklen/manmankan/main/scripts/install.sh > /tmp/install.sh
#   less /tmp/install.sh
#   bash /tmp/install.sh
#
# 设计原则：真小白可读 · 全程中文 · idempotent · 失败给 fallback · 不留半成品

set -euo pipefail

# ── 颜色与输出 helper ────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
DIM='\033[2m'
NC='\033[0m'

say()  { printf "%b\n" "$1"; }
ok()   { say "${GREEN}✅ $1${NC}"; }
warn() { say "${YELLOW}⚠️  $1${NC}"; }
fail() { say "${RED}❌ $1${NC}" >&2; }
info() { say "${BLUE}→ $1${NC}"; }
hint() { say "${DIM}   $1${NC}"; }
step() { say ""; say "${BLUE}━━━ $1 ━━━${NC}"; }

# ── Banner ───────────────────────────────────────────────────────
say ""
say "🐙 慢慢看 (manmankan) 一键安装脚本"
say "   A 股自选股位置感工具 · 100% 本地 · 完全免费开源"
say ""
say "📋 即将做这 4 件事："
say "   1. 检查你的系统 (mac / Linux)"
say "   2. 检查 / 安装 uv (Python 工具管理器)"
say "   3. 安装 manmankan"
say "   4. 验证安装成功"
say ""
hint "全程约 1-3 分钟 · 失败可以重跑 · Ctrl-C 可随时中断"
say ""

# 交互式调用才给「按回车继续」确认 · piped 模式直接跑
if [ -t 0 ]; then
    read -r -p "↩️  按回车继续 · 或 Ctrl-C 取消..." _ || true
fi

# ── 1/4 系统检查 ─────────────────────────────────────────────────
step "1/4 系统检查"
OS=$(uname -s)
case "$OS" in
    Darwin)
        ok "检测到 macOS"
        ;;
    Linux)
        ok "检测到 Linux"
        ;;
    *)
        fail "暂不支持 $OS · 本脚本只支持 macOS / Linux"
        warn "Windows 用户请用 install.ps1 (PowerShell)"
        hint "见 README: https://github.com/piklen/manmankan#新手专区"
        exit 1
        ;;
esac

# bash 版本基本检查（mac 默认 3.2 即可）
BASH_MAJOR="${BASH_VERSINFO[0]:-3}"
if [ "$BASH_MAJOR" -lt 3 ]; then
    fail "需要 bash 3.2+ · 当前 bash 版本太老 ($BASH_VERSION)"
    hint "mac 用户:  brew install bash · 然后重跑本脚本"
    exit 1
fi

# ── 2/4 uv 检查 / 安装 ───────────────────────────────────────────
step "2/4 检查 uv (Python 工具管理器)"

if command -v uv >/dev/null 2>&1; then
    UV_VERSION=$(uv --version 2>/dev/null || echo "未知版本")
    ok "uv 已安装: $UV_VERSION"
else
    info "uv 未安装 · 即将从 astral.sh 下载安装"
    say ""
    hint "📋 安装 URL: https://astral.sh/uv/install.sh"
    hint "💡 不放心? 可以 Ctrl-C 退出 · 然后:"
    hint "      curl -L https://astral.sh/uv/install.sh > /tmp/uv-install.sh"
    hint "      less /tmp/uv-install.sh    # 自己看完再装"
    hint "      bash /tmp/uv-install.sh"
    say ""
    info "继续 · 下载安装中..."

    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        ok "uv 安装完成"
        # 把 uv 的常见 install 路径加进当前 shell PATH · 给后续步骤用
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    else
        fail "uv 安装失败"
        warn "备用方案 (任选一个):"
        hint "  brew install uv          # mac · 推荐"
        hint "  pipx install manmankan   # 跳过 uv · 直接装 manmankan"
        hint "详细文档 https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
fi

# 再次检查 uv 现在能调到
if ! command -v uv >/dev/null 2>&1; then
    fail "uv 装完了但当前终端找不到 (PATH 没更新)"
    warn "解决办法:"
    hint "  1. 关掉这个终端窗口"
    hint "  2. 重新打开一个新终端"
    hint "  3. 重跑本安装脚本"
    exit 1
fi

# ── 3/4 安装 manmankan ───────────────────────────────────────────
step "3/4 安装 manmankan"

if uv tool list 2>/dev/null | grep -q "^manmankan "; then
    info "manmankan 已装过 · 升级到最新版"
    if uv tool install --upgrade manmankan; then
        ok "manmankan 升级完成"
    else
        fail "升级失败"
        warn "可以试 --reinstall (彻底重装):"
        hint "  uv tool install --reinstall manmankan"
        exit 1
    fi
else
    info "首次安装 manmankan"
    hint "大约 30-60 秒 · 在下载 pandas / akshare 等依赖"
    if uv tool install manmankan; then
        ok "manmankan 安装完成"
    else
        fail "安装失败"
        warn "备用方案:"
        hint "  pipx install manmankan       # 用 pipx 试试"
        hint "  uv tool install --reinstall manmankan"
        hint "或来 https://github.com/piklen/manmankan/issues 提问"
        exit 1
    fi
fi

# ── 4/4 验证 ──────────────────────────────────────────────────────
step "4/4 验证安装"

NEEDS_RESHELL=0
if ! command -v kan >/dev/null 2>&1; then
    warn "kan 命令暂时调不到 · 这是正常的 · PATH 还没刷新"
    NEEDS_RESHELL=1
else
    if KAN_VER=$(kan --version 2>&1); then
        ok "kan 命令可用: $KAN_VER"
    else
        warn "kan 命令好像装上了但跑不动: $KAN_VER"
        NEEDS_RESHELL=1
    fi
fi

# ── 完成 ──────────────────────────────────────────────────────────
say ""
say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "🎉 安装完成!"
say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
say ""

if [ "$NEEDS_RESHELL" -eq 1 ]; then
    warn "⚠️  重要: 关掉这个终端 · 重新打开一个新的"
    hint "(只有重开后 kan 命令才能用 · 这是 PATH 加载的限制)"
    say ""
fi

say "📖 下一步 · 复制粘贴这两行试试:"
say ""
say "   kan add 600519 茅台 601318     ${DIM}# 加你的自选股${NC}"
say "   kan scan                        ${DIM}# 看一屏位置 + 共振${NC}"
say ""
say "📚 看完整命令:  kan --help"
say "📖 README:    https://github.com/piklen/manmankan"
say "❓ 装坏了:    https://github.com/piklen/manmankan/issues"
say ""
hint "🔒 manmankan 100% 本地运行 · 没账号 · 没推送 · 没广告"
hint "   你的自选股存 ~/.local/share/kan/ · 完全是你的"
say ""

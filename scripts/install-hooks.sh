#!/usr/bin/env bash
#
# 一键装 git hooks(manmankan 子仓)
#
# Usage:
#   bash scripts/install-hooks.sh
#
# 装完后:
#   - commit 时自动跑 pre-commit + commit-msg hook
#   - push 时自动跑 pre-push hook
#   - 命中禁忌词 / 在 main 直接操作 → 阻断
#
# 卸载:
#   git config --unset core.hooksPath

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "═══ install-hooks.sh(manmankan)═══"
echo ""

# 1. 验证目录存在
if [ ! -d ".githooks" ]; then
  echo "❌ .githooks/ 目录不存在"
  exit 1
fi

if [ ! -f "scripts/check-privacy-leaks.sh" ]; then
  echo "❌ scripts/check-privacy-leaks.sh 不存在"
  exit 1
fi

# 2. 设置 git config core.hooksPath
git config core.hooksPath .githooks
echo "✅ git config core.hooksPath .githooks"

# 3. 让所有 hook 可执行
chmod +x .githooks/*
HOOK_COUNT=$(ls .githooks/ | wc -l | tr -d ' ')
echo "✅ chmod +x .githooks/* (${HOOK_COUNT} 个 hook)"

# 4. 让 check-privacy-leaks.sh 可执行
chmod +x scripts/check-privacy-leaks.sh
echo "✅ chmod +x scripts/check-privacy-leaks.sh"

# 5. 验证 hooksPath 生效
CONFIGURED=$(git config --get core.hooksPath)
if [ "$CONFIGURED" != ".githooks" ]; then
  echo "❌ git config 验证失败: 实际 '$CONFIGURED'(期望 '.githooks')"
  exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "🔒 enforcement 已激活"
echo ""
echo "   commit-msg hook:扫 commit message 禁词 + 内部代号"
echo "   pre-commit hook:branch 守门(防 main 直 commit)+ 隐私自检 + ruff"
echo "   pre-push hook:拦 main / master push"
echo ""
echo "测试一下:"
echo "   bash scripts/check-privacy-leaks.sh"
echo ""
echo "卸载:"
echo "   git config --unset core.hooksPath"
echo "═══════════════════════════════════════════════════════════"

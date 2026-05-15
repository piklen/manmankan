#!/usr/bin/env bash
#
# manmankan 公开输出隐私泄漏检查
#
# 用法:
#   bash scripts/check-privacy-leaks.sh
#
# 退出码:
#   0 = clean (无禁用词命中 + 版本号一致)
#   1 = 发现禁用词命中或版本号撕裂 (打印命中位置)
#
# 详细规范见 CONTRIBUTING.md「公开输出语言规范」

set -uo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

# 禁用词表
# grep 用 -F (固定字符串) 避免正则误伤
DENY_TERMS=(
  # AI 工具自身署名
  "Claude"
  "Codex"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "Cursor 编辑器"
  "Co-authored-by:"
  "🤖 Generated"
  "claude.com/claude-code"
  # AI 协作过程语境
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***拍板"
  "和***REMOVED***讨论"
  "***REMOVED***决定"
  # 维护者私人称谓
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  # 维护者其他工作区 / 项目代号
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  # 维护者个人 / 账户
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  # 跨项目语境
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  # v0.0.4.4: 内部 mental model / OKR 节奏代号（安全审计 Finding S-6）
  # 防社工攻击者用同款话术构造钓鱼 PR / issue
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
  "***REMOVED***"
)

# 排除路径 (build artifacts + 私有目录)
EXCLUDES=(
  "--exclude-dir=.git"
  "--exclude-dir=.venv"
  "--exclude-dir=venv"
  "--exclude-dir=node_modules"
  "--exclude-dir=dist"
  "--exclude-dir=build"
  "--exclude-dir=.pytest_cache"
  "--exclude-dir=.ruff_cache"
  "--exclude-dir=.mypy_cache"
  "--exclude-dir=__pycache__"
  "--exclude-dir=htmlcov"
  "--exclude=*.parquet"
  "--exclude=*.pyc"
  "--exclude=uv.lock"
  "--exclude=poetry.lock"
  "--exclude=*.egg-info"
)

# 自身排除 (规范文件引用禁令字面值是合法用途 · 否则规范无法描述禁令)
SELF_EXCLUDES=(
  "scripts/check-privacy-leaks.sh"
  "CONTRIBUTING.md"
)

echo "🔍 manmankan 公开档案隐私泄漏自检 ..."
echo ""

LEAKS=0
HITS_FOUND=""

for term in "${DENY_TERMS[@]}"; do
  # 用 grep -F 固定字符串匹配避免正则误伤
  matches=$(grep -rnF "$term" "${EXCLUDES[@]}" . 2>/dev/null || true)

  # 过滤自身
  for self in "${SELF_EXCLUDES[@]}"; do
    matches=$(echo "$matches" | grep -v "^./${self}:" || true)
  done

  if [ -n "$matches" ]; then
    echo "❌ 命中禁用词「${term}」:"
    echo "$matches" | sed 's/^/   /'
    echo ""
    LEAKS=$((LEAKS + 1))
    HITS_FOUND="yes"
  fi
done

if [ -n "$HITS_FOUND" ]; then
  echo "═══════════════════════════════════════════════════════════"
  echo "❌ 共 ${LEAKS} 类禁用词命中 · 修复后再 commit / push"
  echo "   规范详见 CONTRIBUTING.md「公开输出语言规范」"
  echo "═══════════════════════════════════════════════════════════"
  exit 1
fi

# ===========================================================
# 版本号一致性检查 (堵文档与发版号撕裂的盲区)
# 允许位置: CHANGELOG.md / docs/reviews/ (历史回顾允许多版本号) ·
#           CODE_OF_CONDUCT.md (引用 Contributor Covenant 外部标准版本号)
# 其他文件出现 v0.[1-9].x 或 v[1-9].x 字样视为撕裂
# ===========================================================
echo ""
echo "🔍 版本号一致性检查 ..."

VERSION_PATTERN='v0\.[123456789]|v[1-9]\.[0-9]'
VERSION_LEAKS=$(grep -rEn "$VERSION_PATTERN" \
  "${EXCLUDES[@]}" \
  --exclude=check-privacy-leaks.sh \
  . 2>/dev/null \
  | grep -v '^\./CHANGELOG\.md:' \
  | grep -v '^\./docs/reviews/' \
  | grep -v '^\./CODE_OF_CONDUCT\.md:' \
  || true)

if [ -n "$VERSION_LEAKS" ]; then
  echo "❌ 发现非当前版本号引用 (允许位置: CHANGELOG.md · docs/reviews/ · CODE_OF_CONDUCT.md):"
  echo "$VERSION_LEAKS" | sed 's/^/   /'
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "❌ 版本号撕裂 · 修复后再 commit / push"
  echo "═══════════════════════════════════════════════════════════"
  exit 1
fi

echo "✅ 版本号一致"
echo ""
echo "✅ 自检全绿"
exit 0

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

# ─── 模式 1: --commit-msg <file> · 单独扫一个 commit message 文件 ───
# 给 .githooks/commit-msg 调用 · 拦下 commit 阶段的内部代号 / 隐私词
if [ "${1:-}" = "--commit-msg" ]; then
  COMMIT_MSG_FILE="${2:-}"
  if [ -z "$COMMIT_MSG_FILE" ] || [ ! -f "$COMMIT_MSG_FILE" ]; then
    echo "❌ check-privacy-leaks.sh --commit-msg: 收到无效 message 文件" >&2
    exit 1
  fi
  COMMIT_MSG="$(cat "$COMMIT_MSG_FILE")"
  # 跳过空 commit msg / merge commit / squash 模板
  if [ -z "$(echo "$COMMIT_MSG" | grep -v '^#' | tr -d '[:space:]')" ]; then
    exit 0
  fi
  # 简化扫描:对每个禁词跑 grep -F
  # 用 array 累积命中行 + 跳过 nounset 局部问题
  COMMIT_MSG_DENY=(
    "Claude" "Codex" "Co-authored-by:" "🤖 Generated" "claude.com/claude-code"
    "鼠鼠" "鼠哥" "所长" "章鱼哥" "韭菜实验室"
    "youzi" "biemai" "stock-mbti" "zhiyan-stock"
    "8w 韭菜" "¥8w" "北极星" "小红书" "雪球" "一鱼两吃"
    "silent 期" "round 2" "round 3" "候选版" ".dev-thinking/"
    "Spec §" "T6 熔断" "T16 " "card-" "F11"
  )
  COMMIT_HITS=()
  for t in "${COMMIT_MSG_DENY[@]}"; do
    if printf '%s' "$COMMIT_MSG" | grep -qF -- "$t"; then
      COMMIT_HITS+=("  命中字面值: $t")
    fi
  done
  # 任务卡代号模式扫描(grep -E · 精确捕获)
  COMMIT_MSG_PATTERNS=(
    '\(U-[0-9]+\)' '\(UX-[0-9]+\)' '\(CR-[0-9]+\)'
    '\(PM-[0-9]+\)' '\(架-[0-9]+\)' '\(安-[0-9]+\)' '\(合-[0-9]+\)'
  )
  for p in "${COMMIT_MSG_PATTERNS[@]}"; do
    if printf '%s' "$COMMIT_MSG" | grep -qE -- "$p"; then
      COMMIT_HITS+=("  命中模式: $p")
    fi
  done
  if [ "${#COMMIT_HITS[@]}" -gt 0 ]; then
    echo "❌ commit message 命中 ${#COMMIT_HITS[@]} 处禁词 / 内部代号:"
    printf '%s\n' "${COMMIT_HITS[@]}"
    echo ""
    echo "💡 改 commit message 后重新 commit · 紧急跳过: git commit --no-verify"
    exit 1
  fi
  exit 0
fi

# ─── 模式 2: 默认 · 扫 git tracked 工作树 + 版本号一致性 ───

# 禁用词表
# grep 用 -F (固定字符串) 避免正则误伤
DENY_TERMS=(
  # AI 工具自身署名
  "Claude"
  "Codex"
  "Plan agent"
  "Plan subagent"
  "Explore agent"
  "Cursor 编辑器"
  "Co-authored-by:"
  "🤖 Generated"
  "claude.com/claude-code"
  # AI 协作过程语境
  "audit 漏判"
  "audit-must-user-test"
  "user-test 漏判"
  "user-test"
  "LOCKED 准则"
  "LOCKED 工作流"
  "合伙人 mode"
  "subagent 产出"
  "用户拍板"
  "维护者拍板"
  "鼠鼠拍板"
  "和鼠鼠讨论"
  "鼠鼠决定"
  # 维护者私人称谓
  "鼠鼠"
  "鼠哥"
  "所长"
  "章鱼哥"
  "五好青年"
  "韭鼠"
  "韭菜实验室"
  # 维护者其他工作区 / 项目代号
  "youzi"
  "biemai"
  "stock-mbti"
  "zhiyan-stock"
  # 维护者个人 / 账户
  "8w 韭菜"
  "¥8w"
  "北极星"
  # 跨项目语境
  "小红书"
  "雪球"
  "一鱼两吃"
  "监管整改"
  # v0.0.4.4: 内部 mental model / OKR 节奏代号（安全审计 Finding S-6）
  # 防社工攻击者用同款话术构造钓鱼 PR / issue
  "silent 期"
  "round 2"
  "round 3"
  "round 4"
  "round 5"
  "候选版"
  ".dev-thinking/"
  "/tmp/adata-spike"
  "私密路线规划目录"
  # v0.0.5.0: 内部 spec / 任务卡代号(neutral-expression 公开仓硬规则)
  "F11"
  "T6 熔断"
  "T16 "
  "Spec §"
  "card-"
)

# 扫描范围委托给 git: ls-files --cached --others --exclude-standard
# 自动 respect .gitignore + .git/info/exclude + global gitignore
# (旧 EXCLUDES 数组已删 · 不再手动维护两套排除规则 · 防 .coverage 等 ignored 文件误报)
#
# 注: 用函数包装而非变量缓存 —— bash $(...) command substitution 会 strip NUL
# bytes (POSIX shell 限制 · 不可 work around)。函数 + pipe 避开此坑 · 同时
# git ls-files 本地极快 (几 ms · 多次调用无性能问题)。
scan_files_z() {
  git ls-files -z --cached --others --exclude-standard
}

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
  # grep -F 固定字符串避免正则误伤 · -H 强制显示文件名前缀
  matches=$(scan_files_z | xargs -0 grep -nHF "$term" 2>/dev/null || true)

  # 过滤自身 (git ls-files 输出不带 ./ 前缀)
  for self in "${SELF_EXCLUDES[@]}"; do
    matches=$(echo "$matches" | grep -v "^${self}:" || true)
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

PROJECT_VERSION=$(python - <<'PY'
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text())
print(data["project"]["version"])
PY
)

RUNTIME_VERSION=$(python - <<'PY'
from pathlib import Path

for line in Path("kan/__init__.py").read_text().splitlines():
    if line.startswith("__version__"):
        print(line.split("=", 1)[1].strip().strip('"'))
        break
PY
)

CHANGELOG_VERSION=$(python - <<'PY'
import re
from pathlib import Path

match = re.search(r"^## \[(\d+\.\d+\.\d+(?:\.\d+)?)\]", Path("CHANGELOG.md").read_text(), re.M)
print(match.group(1) if match else "")
PY
)

if [ "$PROJECT_VERSION" != "$RUNTIME_VERSION" ] || [ "$PROJECT_VERSION" != "$CHANGELOG_VERSION" ]; then
  echo "❌ 发布版本号不一致:"
  echo "   pyproject.toml: ${PROJECT_VERSION:-<missing>}"
  echo "   kan/__init__.py: ${RUNTIME_VERSION:-<missing>}"
  echo "   CHANGELOG.md 顶部: ${CHANGELOG_VERSION:-<missing>}"
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "❌ 版本号撕裂 · 修复后再 commit / push"
  echo "═══════════════════════════════════════════════════════════"
  exit 1
fi

CHANGELOG_LINK_ERRORS=$(python - <<'PY'
import re
from pathlib import Path

text = Path("CHANGELOG.md").read_text()
versions = re.findall(r"^## \[(\d+\.\d+\.\d+(?:\.\d+)?)\]", text, re.M)
errors = []

if versions:
    current = versions[0]
    current_tag = f"v{current}"
    unreleased_expected = (
        f"[Unreleased]: https://github.com/piklen/manmankan/compare/"
        f"{current_tag}...HEAD"
    )
    if unreleased_expected not in text:
        errors.append(f"missing or stale Unreleased compare link: {unreleased_expected}")

    if len(versions) > 1:
        previous = versions[1]
        current_expected = (
            f"[{current}]: https://github.com/piklen/manmankan/compare/"
            f"v{previous}...v{current}"
        )
        if current_expected not in text:
            errors.append(f"missing current release compare link: {current_expected}")

for version in versions:
    if f"[{version}]: " not in text:
        errors.append(f"missing changelog reference for [{version}]")

print("\n".join(errors))
PY
)

if [ -n "$CHANGELOG_LINK_ERRORS" ]; then
  echo "❌ CHANGELOG.md 版本链接不完整:"
  echo "$CHANGELOG_LINK_ERRORS" | sed 's/^/   /'
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "❌ CHANGELOG 链接撕裂 · 修复后再 commit / push"
  echo "═══════════════════════════════════════════════════════════"
  exit 1
fi

VERSION_PATTERN='v0\.[123456789]|v[1-9]\.[0-9]'
VERSION_LEAKS=$(scan_files_z | xargs -0 grep -nEH "$VERSION_PATTERN" 2>/dev/null \
  | grep -v '^scripts/check-privacy-leaks\.sh:' \
  | grep -v '^CHANGELOG\.md:' \
  | grep -v '^docs/reviews/' \
  | grep -v '^CODE_OF_CONDUCT\.md:' \
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

#!/usr/bin/env bash
#
# manmankan 公开输出隐私泄漏检查
#
# 用法:
#   bash scripts/check-privacy-leaks.sh                  # 扫 git tracked 工作树 + 版本号一致性
#   bash scripts/check-privacy-leaks.sh --commit-msg <file>   # commit-msg hook 用 · 扫单个 message 文件
#
# 退出码:
#   0 = clean (无禁用词命中 + 版本号一致)
#   1 = 发现禁用词命中或版本号撕裂 (打印命中位置)
#
# ─── 禁用词从哪来 ───────────────────────────────────────────────
# 本脚本是公开档案 · 不能把私密词清单写进来 (否则脚本本身就是泄漏面)。
#   · 公开词 (通用 AI 署名)        → 内联在本脚本 (PUBLIC_DENY_TERMS) · CI 也能拦
#   · 私密词 / 内部代号 / 正则模式  → .ai/private/privacy-deny.txt (gitignored · 维护者自维护)
# 私密清单缺失 (CI / 新 clone) → 自动降级只扫公开词 · 仍能拦 AI 署名。
#
# 详细规范见 CONTRIBUTING.md「公开输出语言规范」

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
cd "$REPO_ROOT"

# ─── 公开禁用词 · 通用 AI 工具署名 (留在 tracked 脚本里是合法的 · 不暴露维护者隐私) ───
# grep 用 -F (固定字符串) 避免正则误伤
PUBLIC_DENY_TERMS=(
  "Claude"
  "Codex"
  "Cursor 编辑器"
  "Co-authored-by:"
  "🤖 Generated"
  "claude.com/claude-code"
)

# ─── 私密禁用词 + 模式 · 从 gitignored 文件动态读 ───
# 文件格式: 一行一项 · `#` 开头 / 空行跳过 · `re:` 前缀 = 正则模式 (grep -E) · 其余 = 固定串 (grep -F)
# 维护者自己维护 · 子仓没此文件就降级 (CI / fresh clone 正常)
PRIVATE_DENY_FILE="${REPO_ROOT}/.ai/private/privacy-deny.txt"
PRIVATE_TERMS=()
PRIVATE_PATTERNS=()
if [ -f "$PRIVATE_DENY_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"          # 去掉 CRLF 尾
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
      re:*) PRIVATE_PATTERNS+=("${line#re:}") ;;
      *)    PRIVATE_TERMS+=("$line") ;;
    esac
  done < "$PRIVATE_DENY_FILE"
fi

PRIVATE_POINTER=".ai/private/privacy-deny.txt"

# ════════════════════════════════════════════════════════════════
# 模式 1: --commit-msg <file> · 单独扫一个 commit message 文件
# 给 .githooks/commit-msg 调用 · 拦下 commit 阶段的内部代号 / 隐私词
# ════════════════════════════════════════════════════════════════
if [ "${1:-}" = "--commit-msg" ]; then
  COMMIT_MSG_FILE="${2:-}"
  if [ -z "$COMMIT_MSG_FILE" ] || [ ! -f "$COMMIT_MSG_FILE" ]; then
    echo "❌ check-privacy-leaks.sh --commit-msg: 收到无效 message 文件" >&2
    exit 1
  fi
  COMMIT_MSG="$(cat "$COMMIT_MSG_FILE")"
  # 跳过空 commit msg / merge commit / squash 模板 (只剩 # 注释行)
  if [ -z "$(echo "$COMMIT_MSG" | grep -v '^#' | tr -d '[:space:]')" ]; then
    exit 0
  fi

  COMMIT_HITS=()
  # 公开词 (命中可打印字面值 · 本就公开)
  for t in "${PUBLIC_DENY_TERMS[@]}"; do
    if printf '%s' "$COMMIT_MSG" | grep -qF -- "$t"; then
      COMMIT_HITS+=("  命中公开禁词: $t")
    fi
  done
  # 私密词 (命中不回显字面值 · 防 log 二次泄漏)
  if [ "${#PRIVATE_TERMS[@]}" -gt 0 ]; then
    for t in "${PRIVATE_TERMS[@]}"; do
      if printf '%s' "$COMMIT_MSG" | grep -qF -- "$t"; then
        COMMIT_HITS+=("  命中私密禁词 (具体见 ${PRIVATE_POINTER})")
      fi
    done
  fi
  # 私密正则模式 (命中不回显)
  if [ "${#PRIVATE_PATTERNS[@]}" -gt 0 ]; then
    for p in "${PRIVATE_PATTERNS[@]}"; do
      if printf '%s' "$COMMIT_MSG" | grep -qE -- "$p"; then
        COMMIT_HITS+=("  命中私密模式 (具体见 ${PRIVATE_POINTER})")
      fi
    done
  fi

  if [ "${#COMMIT_HITS[@]}" -gt 0 ]; then
    echo "❌ commit message 命中 ${#COMMIT_HITS[@]} 处禁词 / 内部代号:"
    printf '%s\n' "${COMMIT_HITS[@]}"
    echo ""
    echo "💡 改 commit message 后重新 commit · 紧急跳过: git commit --no-verify"
    exit 1
  fi
  exit 0
fi

# ════════════════════════════════════════════════════════════════
# 模式 2: 默认 · 扫 git tracked 工作树 + 版本号一致性
# ════════════════════════════════════════════════════════════════

# 扫描范围委托给 git: ls-files --cached --others --exclude-standard
# 自动 respect .gitignore + .git/info/exclude + global gitignore
# (私密词文件 .ai/private/ 本身 gitignored · 不会被扫到 · 也不会进 git)
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
  ".ai/private/"
)

# 过滤 SELF_EXCLUDES (git ls-files 输出不带 ./ 前缀)
strip_self_excludes() {
  local matches="$1"
  local self
  for self in "${SELF_EXCLUDES[@]}"; do
    matches="$(echo "$matches" | grep -v "^${self}" || true)"
  done
  printf '%s' "$matches"
}

echo "🔍 manmankan 公开档案隐私泄漏自检 ..."
if [ ! -f "$PRIVATE_DENY_FILE" ]; then
  echo "   ⚠️ 私密词清单 ${PRIVATE_POINTER} 不存在 → 仅扫公开词 (CI / 新 clone 正常)"
fi
echo "   词清单: 公开 ${#PUBLIC_DENY_TERMS[@]} · 私密 ${#PRIVATE_TERMS[@]} · 私密模式 ${#PRIVATE_PATTERNS[@]}"
echo ""

LEAKS=0
HITS_FOUND=""

# ─── 公开词 (命中回显完整行 · 本就公开) ───
for term in "${PUBLIC_DENY_TERMS[@]}"; do
  matches=$(scan_files_z | xargs -0 grep -nHF "$term" 2>/dev/null || true)
  matches=$(strip_self_excludes "$matches")
  if [ -n "$matches" ]; then
    echo "❌ 命中公开禁用词「${term}」:"
    echo "$matches" | sed 's/^/   /'
    echo ""
    LEAKS=$((LEAKS + 1))
    HITS_FOUND="yes"
  fi
done

# ─── 私密词 (命中只回显 路径:行号 · 不回显内容 / 不回显词 · 防二次泄漏) ───
if [ "${#PRIVATE_TERMS[@]}" -gt 0 ]; then
  for term in "${PRIVATE_TERMS[@]}"; do
    matches=$(scan_files_z | xargs -0 grep -nHF "$term" 2>/dev/null || true)
    matches=$(strip_self_excludes "$matches")
    if [ -n "$matches" ]; then
      locs=$(echo "$matches" | cut -d: -f1,2)
      echo "❌ 命中私密禁用词 (具体词见 ${PRIVATE_POINTER}):"
      echo "$locs" | sed 's/^/   /'
      echo ""
      LEAKS=$((LEAKS + 1))
      HITS_FOUND="yes"
    fi
  done
fi

# ─── 私密正则模式 (同样只回显 路径:行号) ───
if [ "${#PRIVATE_PATTERNS[@]}" -gt 0 ]; then
  for pat in "${PRIVATE_PATTERNS[@]}"; do
    matches=$(scan_files_z | xargs -0 grep -nEH "$pat" 2>/dev/null || true)
    matches=$(strip_self_excludes "$matches")
    if [ -n "$matches" ]; then
      locs=$(echo "$matches" | cut -d: -f1,2)
      echo "❌ 命中私密内部代号模式 (具体见 ${PRIVATE_POINTER}):"
      echo "$locs" | sed 's/^/   /'
      echo ""
      LEAKS=$((LEAKS + 1))
      HITS_FOUND="yes"
    fi
  done
fi

if [ -n "$HITS_FOUND" ]; then
  echo "═══════════════════════════════════════════════════════════"
  echo "❌ 共 ${LEAKS} 类禁用词命中 · 修复后再 commit / push"
  echo "   规范详见 CONTRIBUTING.md「公开输出语言规范」"
  echo "   私密词清单: ${PRIVATE_POINTER} (gitignored)"
  echo "═══════════════════════════════════════════════════════════"
  exit 1
fi

# ════════════════════════════════════════════════════════════════
# 版本号一致性检查 (堵文档与发版号撕裂的盲区)
# 允许位置:
#   - CHANGELOG.md / docs/reviews/ (历史回顾允许多版本号)
#   - CODE_OF_CONDUCT.md (引用 Contributor Covenant 外部标准版本号)
#   - scripts/check-version-bump.sh (本身是版本守门脚本 · docstring 含反例)
#   - tests/test_check_version_bump.py (测试 fixture 含 fake 版本号合法)
# 其他文件出现 v0.[1-9].x 或 v[1-9].x 字样视为撕裂
# ════════════════════════════════════════════════════════════════
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
  | grep -v '^scripts/check-version-bump\.sh:' \
  | grep -v '^tests/test_check_version_bump\.py:' \
  | grep -v '^CHANGELOG\.md:' \
  | grep -v '^docs/reviews/' \
  | grep -v '^CODE_OF_CONDUCT\.md:' \
  || true)

if [ -n "$VERSION_LEAKS" ]; then
  echo "❌ 发现非当前版本号引用 (允许位置: CHANGELOG.md · docs/reviews/ · CODE_OF_CONDUCT.md · scripts/check-version-bump.sh · tests/test_check_version_bump.py):"
  echo "$VERSION_LEAKS" | sed 's/^/   /'
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "❌ 版本号撕裂 · 修复后再 commit / push"
  echo "═══════════════════════════════════════════════════════════"
  exit 1
fi

USER_VERSION_PATTERN='v?0\.0\.[0-9]+(\.[0-9]+)?|softwareVersion|当前 v'
USER_VERSION_SURFACES=(
  "README.md"
  "docs/README.md"
  "docs/cli-errors.md"
  "docs/compliance.md"
  "docs/roadmap.md"
  "site/index.html"
  "kan/cli/help.py"
)
USER_VERSION_LEAKS=""
for f in "${USER_VERSION_SURFACES[@]}"; do
  [ -f "$f" ] || continue
  hits=$(grep -nEH "$USER_VERSION_PATTERN" "$f" 2>/dev/null || true)
  if [ -n "$hits" ]; then
    USER_VERSION_LEAKS="${USER_VERSION_LEAKS}${hits}"$'\n'
  fi
done

if [ -n "$USER_VERSION_LEAKS" ]; then
  echo "❌ 用户面出现硬编码发布版本号:"
  echo "$USER_VERSION_LEAKS" | sed '/^$/d; s/^/   /'
  echo ""
  echo "   允许位置: pyproject.toml · kan/__init__.py · CHANGELOG.md · docs/reviews/ · docs/find.md schema 示例 · kan update 输出"
  echo "   用户面 README / site / kan help 应使用中性表达,不要写当前具体版本号。"
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "❌ 用户面版本号泄漏 · 修复后再 commit / push"
  echo "═══════════════════════════════════════════════════════════"
  exit 1
fi

echo "✅ 版本号一致"
echo ""
echo "✅ 自检全绿"
exit 0

#!/usr/bin/env bash
#
# check-version-bump.sh · commit message 版本号机械守门
#
# 规则 (manmankan 项目 PEP 440 4-段格式 A.B.C.D):
# - baseline = pyproject.toml 当前 version (例 0.0.5.1)
# - 前 3 段 A.B.C 是稳定段 (epoch.major.minor)
# - 第 4 段 D 是 patch · 任意值可累加
# - commit msg 提的任意 vA.B.C(.D)? 前 3 段必须 = baseline 前 3 段
# - 第 3 段 C 变 (跨 minor · 例 0.0.5 → 0.0.6) → block
# - 第 2 段 B 变 (跨 major · 例 0.0.x → 0.1.x) → block
# - 第 1 段 A 变 (跨 epoch · 例 0.x.x → 1.x.x) → block
#
# Why:
# - 项目本身节奏 = patch 累加 · 详见 docs/roadmap.md「版本节奏」
# - AI 工具严禁主动 bump · 版本号决策属项目所有者明示
# - 历史上 v0.0.5.7 → v0.0.6 一晚跨越 minor (PR #33) · 触发本守门
#
# 用法 (commit-msg hook 调用):
#   bash scripts/check-version-bump.sh "$COMMIT_MSG_FILE"
#
# 跳过 (紧急 · 不推荐 · 留 audit trail):
#   git commit --no-verify
#
# 退出码:
#   0  通过 (无版本号 / 全在 baseline 同稳定段)
#   1  发现跨 minor / major / epoch 版本号 · block
#   2  脚本参数错误 / pyproject.toml 缺失

set -uo pipefail

COMMIT_MSG_FILE="${1:-}"
if [ -z "$COMMIT_MSG_FILE" ] || [ ! -f "$COMMIT_MSG_FILE" ]; then
  echo "❌ check-version-bump: 收到无效 message 文件" >&2
  exit 2
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo '')"
if [ -z "$REPO_ROOT" ]; then
  echo "⚠️ check-version-bump: 不在 git repo · 跳过" >&2
  exit 0
fi

PYPROJECT="$REPO_ROOT/pyproject.toml"
if [ ! -f "$PYPROJECT" ]; then
  echo "⚠️ check-version-bump: 无 pyproject.toml · 跳过" >&2
  exit 0
fi

BASELINE_VERSION=$(grep -E '^version[[:space:]]*=' "$PYPROJECT" | head -1 \
  | sed -E 's/^version[[:space:]]*=[[:space:]]*"([^"]+)"/\1/')
if [ -z "$BASELINE_VERSION" ]; then
  echo "⚠️ check-version-bump: pyproject.toml 无 version 字段 · 跳过" >&2
  exit 0
fi

# 解析 baseline 前 3 段 (稳定段) + patch 段
# 例 0.0.5.1 → A=0 B=0 C=5 D=1
# 例 0.0.5   → A=0 B=0 C=5 D=0 (隐式)
BASELINE_A=$(echo "$BASELINE_VERSION" | cut -d. -f1)
BASELINE_B=$(echo "$BASELINE_VERSION" | cut -d. -f2)
BASELINE_C=$(echo "$BASELINE_VERSION" | cut -d. -f3)
BASELINE_D=$(echo "$BASELINE_VERSION" | cut -d. -f4)
BASELINE_D="${BASELINE_D:-0}"
BASELINE_STABLE="${BASELINE_A}.${BASELINE_B}.${BASELINE_C}"

# 提 commit msg 中所有 v?X.Y.Z(.W)? 形 · 去掉注释行
COMMIT_MSG=$(grep -v "^#" "$COMMIT_MSG_FILE" | tr -d '\r')
FOUND_VERSIONS=$(echo "$COMMIT_MSG" | grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?' | sort -u || true)

if [ -z "$FOUND_VERSIONS" ]; then
  exit 0
fi

VIOLATIONS=()
for v in $FOUND_VERSIONS; do
  ver="${v#v}"
  v_A=$(echo "$ver" | cut -d. -f1)
  v_B=$(echo "$ver" | cut -d. -f2)
  v_C=$(echo "$ver" | cut -d. -f3)
  if [ "$v_A" != "$BASELINE_A" ]; then
    VIOLATIONS+=("$v (epoch 跨越 · ${v_A} ≠ ${BASELINE_A})")
  elif [ "$v_B" != "$BASELINE_B" ]; then
    VIOLATIONS+=("$v (major 跨越 · ${v_A}.${v_B} ≠ ${BASELINE_A}.${BASELINE_B})")
  elif [ "$v_C" != "$BASELINE_C" ]; then
    VIOLATIONS+=("$v (minor 跨越 · ${v_A}.${v_B}.${v_C} ≠ ${BASELINE_STABLE})")
  fi
done

if [ ${#VIOLATIONS[@]} -eq 0 ]; then
  exit 0
fi

NEXT_PATCH=$((BASELINE_D + 1))

echo "" >&2
echo "═══ version-bump 守门 ═══" >&2
echo "❌ commit message 含跨 minor/major/epoch 版本号:" >&2
for v in "${VIOLATIONS[@]}"; do
  echo "    - $v" >&2
done
echo "" >&2
echo "   pyproject.toml baseline: $BASELINE_VERSION" >&2
echo "   允许范围: ${BASELINE_STABLE}.* (patch 累加 · 第 4 段任意)" >&2
echo "   候选下一 patch:       ${BASELINE_STABLE}.${NEXT_PATCH}" >&2
echo "" >&2
echo "   规则: AI 工具严禁主动 bump 版本号" >&2
echo "         跨 minor / major / epoch 由项目所有者明示同意" >&2
echo "         详见 docs/roadmap.md「版本节奏」" >&2
echo "   紧急跳过 (不推荐 · 留 audit trail): git commit --no-verify" >&2
echo "" >&2
exit 1

"""破坏性操作二次确认 helper · ***REMOVED*** 引入 · 给 add/remove/clear --theme(或 --industry) 用。

设计:
- show_summary_and_confirm(action, targets, current_size, skip=False)
  - skip=True(--yes) 跳过交互直接 True
  - 渲染影响 summary(action 名 + 目标数 + 当前/操作后大小)+ 交互 y/N
  - n / 回车 / Ctrl-C → False
  - y/Y → True

跟 ***REMOVED***010 backup 协议精神一致 · 不可逆操作 + summary + 确认。
"""
from __future__ import annotations

ACTION_VERB = {
    "add": "添加",
    "remove": "移除",
    "clear": "清除",
}


def show_summary_and_confirm(
    action: str,
    targets: list[tuple[str, str]],
    current_watchlist_size: int,
    skip: bool = False,
) -> bool:
    """渲染破坏性操作影响 summary + 二次确认。

    Args:
        action: "add" | "remove" | "clear"
        targets: 影响的 (代码, 名称) 列表
        current_watchlist_size: 当前自选股数量
        skip: True 跳过交互(--yes)

    Returns:
        True 继续 · False 取消。
    """
    if skip:
        return True

    n = len(targets)
    verb = ACTION_VERB.get(action, action)
    if action == "add":
        resulting = current_watchlist_size + n  # 上层应预先过滤已在自选的
        summary = (
            f"⚠️  将 {verb} {n} 只股票到自选(当前 {current_watchlist_size} 只 · 操作后 ≤ {resulting} 只)"
        )
    elif action in ("remove", "clear"):
        resulting = max(0, current_watchlist_size - n)
        summary = (
            f"⚠️  将 {verb} {n} 只股票(当前 {current_watchlist_size} 只 · 操作后 ≥ {resulting} 只)"
        )
    else:
        summary = f"⚠️  将 {verb} {n} 只股票"

    print(summary)
    # 列前 5 只预览(避免 100 只刷屏)
    preview_n = min(5, n)
    for code, name in targets[:preview_n]:
        print(f"   {code}  {name}")
    if n > preview_n:
        print(f"   ... 还有 {n - preview_n} 只")
    print()
    try:
        ans = input("继续? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False
    return ans in ("y", "yes")

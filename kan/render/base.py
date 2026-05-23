"""表格渲染 · 终端宽度自适应 + 百分比格式化"""

from __future__ import annotations

from rich.text import Text

DISCLAIMER = (
    "\n⚠️  创新低 ≠ 见底 · 创新高 ≠ 顶 "
    "· 历史价格不预示未来 · 仅供参考，不构成投资建议"
)


def responsive_periods(console_width: int) -> list[int]:
    """根据终端宽度选择要展示的周期子集 · 始终保证共振列可见。

    短密长疏策略：短线波段需要 5+10 日的密集信号 · 长期靠共振数补。
    实测列宽：股票(~22) + 现价(11) + 共振(7) ≈ 40 固定开销 · 每周期列 ≈ 9
    """
    from kan.core.scanner import PERIODS

    if console_width >= 130:
        return list(PERIODS)
    elif console_width >= 100:
        return [3, 5, 10, 30, 60, 180]
    elif console_width >= 90:
        return [5, 10, 30, 60, 180]
    elif console_width >= 80:
        return [5, 10, 30, 180]
    elif console_width >= 70:
        return [5, 30, 180]
    else:
        return [30, 180]


def max_trend_dates(console_width: int) -> int:
    """trend --latest 模式下最多展示的日期列数。"""
    base = 46
    per_date = 10
    return max(1, (console_width - base) // per_date)


def format_pct(pr, *, high_mode: bool = False) -> Text:
    """格式化位置百分比单元格 · [x%] 带颜色方括号表示触及极值。

    high_mode=True (kan scan --high) → 只对 at_high 加 [%] 高亮信号 ·
    at_low 走普通色, 防止深度回调股(全 0%)被误标 "触高信号"。
    """
    if pr.insufficient:
        return Text("-", style="dim")
    if high_mode:
        if pr.at_high:
            return Text(f"[{pr.position_pct:.0f}%]", style="bold yellow")
        if pr.position_pct <= 20:
            return Text(f"{pr.position_pct:.0f}%", style="green")
        if pr.position_pct >= 80:
            return Text(f"{pr.position_pct:.0f}%", style="red")
        return Text(f"{pr.position_pct:.0f}%")
    if pr.at_low:
        return Text(f"[{pr.position_pct:.0f}%]", style="bold green")
    if pr.at_high:
        return Text(f"[{pr.position_pct:.0f}%]", style="bold red")
    if pr.position_pct <= 20:
        return Text(f"{pr.position_pct:.0f}%", style="green")
    if pr.position_pct >= 80:
        return Text(f"{pr.position_pct:.0f}%", style="red")
    return Text(f"{pr.position_pct:.0f}%")

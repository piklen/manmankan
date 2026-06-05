"""表格渲染 · 终端宽度自适应 + 百分比格式化"""

from __future__ import annotations

from rich.text import Text

DISCLAIMER = (
    "\n⚠️  创新低 ≠ 见底 · 创新高 ≠ 顶 "
    "· 历史价格不预示未来 · 仅供参考，不构成投资建议"
)

# kan find 选股器专属免责 · compliance §5 强制文案 (背景 · 衍生不可删)。
# 单一 SOT:CLI Rich 渲染 (find_cmds.FIND_DISCLAIMER) 与 JSON/md 输出
# (export.find_payload / find_markdown) 都引用此纯文本 · 避免文案漂移。
FIND_DISCLAIMER_TEXT = (
    "候选 ≠ 买入信号 · 工具仅返回符合您设置规则的股票数据 · "
    "不构成任何形式的推荐或建议 · 用户自行评估"
)


def responsive_periods(console_width: int, periods: list[int] | None = None) -> list[int]:
    """根据终端宽度选择要展示的周期子集 · 始终保证共振列可见。

    短密长疏策略：短线波段需要 5+10 日的密集信号 · 长期靠共振数补。
    实测列宽：股票(~22) + 现价(11) + 共振(7) ≈ 40 固定开销 · 每周期列 ≈ 9
    """
    if periods is None:
        from kan.core.scanner import PERIODS

        period_list = list(PERIODS)
    else:
        period_list = sorted(dict.fromkeys(periods))

    def pick(preferred: list[int], *, fallback_count: int) -> list[int]:
        chosen = [p for p in preferred if p in period_list]
        if chosen:
            return chosen
        if len(period_list) <= fallback_count:
            return period_list
        if fallback_count <= 1:
            return [period_list[-1]]
        return sorted({period_list[0], period_list[len(period_list) // 2], period_list[-1]})

    if console_width >= 130:
        return period_list
    elif console_width >= 100:
        return pick([3, 5, 10, 30, 60, 180, 360], fallback_count=6)
    elif console_width >= 90:
        return pick([5, 10, 30, 60, 180, 360], fallback_count=5)
    elif console_width >= 80:
        return pick([5, 10, 30, 180, 360], fallback_count=4)
    elif console_width >= 70:
        return pick([5, 30, 180, 360], fallback_count=3)
    else:
        return pick([30, 180, 360], fallback_count=2)


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

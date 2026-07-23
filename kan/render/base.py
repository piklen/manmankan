"""表格渲染 · 终端宽度自适应 + 百分比格式化"""

from __future__ import annotations

from rich.text import Text

DISCLAIMER = (
    "\n⚠️  创新低 ≠ 见底 · 创新高 ≠ 顶 "
    "· 历史价格不预示未来 · 仅供参考，不构成投资建议"
)

# kan find 选股器专属免责 · compliance §5 强制文案 (项目内强制输出)。
# 单一 SOT:CLI Rich 渲染 (find_cmds.FIND_DISCLAIMER) 与 JSON/md 输出
# (export.find_payload / find_markdown) 都引用此纯文本 · 避免文案漂移。
FIND_DISCLAIMER_TEXT = (
    "候选 ≠ 买入信号 · 工具仅返回符合您设置规则的股票数据 · "
    "不构成任何形式的推荐或建议 · 用户自行评估"
)

HOLD_DISCLAIMER_TEXT = "持仓的客观坐标 + 盈亏事实 · 不构成买卖建议"


def trim_title_to_width(
    base: str, suffixes: list[str], max_width: int | None,
) -> str:
    """表格标题按终端宽度从尾舍弃后缀 · scan / trend / extreme 共用。

    suffixes 按价值从高到低排列 · 超宽时从末尾(价值最低)开始整段舍弃,
    基础标题始终保留。max_width=None(md export 等)时返回完整标题。
    背景:rich Table 会被长 title 撑宽或折行,窄终端裁右边框 / 折行难看。
    """
    full = base + "".join(suffixes)
    if max_width is None:
        return full
    from rich.cells import cell_len

    for keep in range(len(suffixes), -1, -1):
        candidate = base + "".join(suffixes[:keep])
        if cell_len(candidate) <= max_width:
            return candidate
    return base


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


def format_pct(pr, *, high_mode: bool = False, show_bar: bool = False) -> Text:
    """格式化位置百分比单元格 · [x%] 带颜色方括号表示触及极值。

    high_mode=True (kan scan --high) → 只对 at_high 加 [%] 高亮信号 ·
    at_low 走普通色, 防止深度回调股(全 0%)被误标 "触高信号"。

    show_bar=True → 在百分比后追加 Unicode 迷你位置条（▁▂▃▄▅▆▇█）。
    """
    if pr.insufficient:
        return Text("-", style="dim")
    pct = pr.position_pct
    bar = _mini_bar(pct) if show_bar else ""
    if high_mode:
        if pr.at_high:
            return Text(f"[{pct:.0f}%]{bar}", style="bold yellow")
        if pct <= 20:
            return Text(f"{pct:.0f}%{bar}", style="green")
        if pct >= 80:
            return Text(f"{pct:.0f}%{bar}", style="red")
        return Text(f"{pct:.0f}%{bar}")
    if pr.at_low:
        return Text(f"[{pct:.0f}%]{bar}", style="bold green")
    if pr.at_high:
        return Text(f"[{pct:.0f}%]{bar}", style="bold red")
    if pct <= 20:
        return Text(f"{pct:.0f}%{bar}", style="green")
    if pct >= 80:
        return Text(f"{pct:.0f}%{bar}", style="red")
    return Text(f"{pct:.0f}%{bar}")


_BAR_CHARS = "▁▂▃▄▅▆▇█"


def _mini_bar(pct: float) -> str:
    """将 0-100 百分比映射为单个 Unicode block 字符。"""
    idx = min(int(pct / 100 * len(_BAR_CHARS)), len(_BAR_CHARS) - 1)
    return _BAR_CHARS[idx]

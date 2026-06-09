"""compare 终端表格渲染。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from kan.infra.formatting import format_date_compact
from kan.render.base import format_pct

if TYPE_CHECKING:
    from kan.core.models import StockScanResult


# ── compare ───────────────────────────────────────────────────────────


def compare_table(
    results: list[StockScanResult],
    *,
    periods: list[int],
) -> Table:
    """kan compare 转置表 · 指标为行 · 个股为列(最多 8 只)。

    title 硬编码 "慢慢看 · 多股对比" · 不随 cutoff/freshness 变化 · 与原行为一致。

    Args:
        results: 2-8 只 StockScanResult。
        periods: 用户指定的周期列表(已校验过在 PERIODS 内)。
    """
    table = Table(
        title="慢慢看 · 多股对比", show_lines=False, pad_edge=False, padding=(0, 1),
    )
    table.add_column("指标", style="cyan", no_wrap=True)
    for r in results:
        table.add_column(f"{r.name.replace(' ', '')} {r.symbol}", justify="right")

    table.add_row("现价", *[f"{r.current_price:.2f}" for r in results])
    for p in periods:
        cells: list[str | Text] = []
        for r in results:
            pr = next((x for x in r.periods if x.period == p), None)
            cells.append(Text("-", style="dim") if pr is None else format_pct(pr))
        table.add_row(f"{p}日位置", *cells)
    table.add_row("低点共振", *[f"×{r.low_resonance}" for r in results])
    table.add_row("高点共振", *[f"×{r.high_resonance}" for r in results])
    table.add_row("ST", *["是" if r.is_st else "—" for r in results])
    table.add_row(
        "涨跌停",
        *["涨停" if r.limit_up else ("跌停" if r.limit_down else "—") for r in results],
    )
    table.add_row("数据截止", *[format_date_compact(r.scan_date) for r in results])

    return table

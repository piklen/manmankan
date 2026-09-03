"""`kan range` 的终端表格。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

if TYPE_CHECKING:
    from rich.console import Console

    from kan.domain.stock_range import (
        DownsideThresholdStudy,
        StockRangeStudy,
        StockRangeWindow,
        UpsideThresholdStudy,
    )


def _pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%" if signed else f"{value:.1f}%"


def _points(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}点"


def _ratio(_count: int, ratio: float | None, total: int) -> str:
    if ratio is None or total <= 0:
        return "—"
    return f"{ratio:.0f}%"


def _level_label(
    basis: str,
    level_pct: float | None,
    actual_coverage_pct: float | None,
) -> str:
    if basis == "custom":
        return "自定"
    target = f"{level_pct:g}%档" if level_pct is not None else "—"
    actual = (
        f"实{actual_coverage_pct:.0f}%"
        if actual_coverage_pct is not None else "实—"
    )
    return f"{target}\n{actual}"


def _short_level_label(basis: str, level_pct: float | None) -> str:
    if basis == "custom":
        return "自定"
    return f"{level_pct:g}%" if level_pct is not None else "—"


def _reference_price(reference_close: float, threshold_pct: float) -> str:
    price = max(0.0, reference_close * (1 + threshold_pct / 100))
    return f"{threshold_pct:+.2f}%\n{price:.2f}元"


def downside_table(
    window: StockRangeWindow,
    *,
    reference_close: float,
) -> Table:
    """展示下行幅度线以及触及后的收盘位置。"""

    table = Table(
        title="下行幅度线",
        pad_edge=False,
        show_lines=False,
        caption_justify="left",
    )
    table.add_column("档位/实际", no_wrap=True)
    table.add_column("下跌线/价格", justify="right", no_wrap=True)
    table.add_column("触及", justify="right", no_wrap=True)
    table.add_column("收回线", justify="right", no_wrap=True)
    table.add_column("收正", justify="right", no_wrap=True)
    table.add_column("收盘中位", justify="right", no_wrap=True)

    rows: list[DownsideThresholdStudy] = list(window.downside)
    if window.custom_downside is not None:
        rows.append(window.custom_downside)
    for row in rows:
        total = row.trigger_count
        table.add_row(
            _level_label(row.basis, row.level_pct, row.actual_coverage_pct),
            _reference_price(reference_close, row.threshold_pct),
            f"{row.trigger_count}/{window.sample_count}",
            _ratio(row.close_above_count, row.close_above_ratio_pct, total),
            _ratio(row.close_positive_count, row.close_positive_ratio_pct, total),
            _pct(row.close_median_pct, signed=True),
        )
    gap_parts = [
        f"{_short_level_label(row.basis, row.level_pct)} "
        f"{row.gap_trigger_count}/{row.trigger_count}"
        for row in rows
        if row.gap_trigger_count > 0
    ]
    if gap_parts:
        table.caption = "跳空直接越过: " + " · ".join(gap_parts)
    return table


def upside_table(
    window: StockRangeWindow,
    *,
    reference_close: float,
) -> Table:
    """展示上行幅度线以及触及后的收盘位置。"""

    table = Table(
        title="上行幅度线",
        pad_edge=False,
        show_lines=False,
        caption_justify="left",
    )
    table.add_column("档位/实际", no_wrap=True)
    table.add_column("上涨线/价格", justify="right", no_wrap=True)
    table.add_column("触及", justify="right", no_wrap=True)
    table.add_column("收盘线下", justify="right", no_wrap=True)
    table.add_column("收盘线上", justify="right", no_wrap=True)
    table.add_column("回吐中位", justify="right", no_wrap=True)

    rows: list[UpsideThresholdStudy] = list(window.upside)
    if window.custom_upside is not None:
        rows.append(window.custom_upside)
    for row in rows:
        total = row.trigger_count
        table.add_row(
            _level_label(row.basis, row.level_pct, row.actual_coverage_pct),
            _reference_price(reference_close, row.threshold_pct),
            f"{row.trigger_count}/{window.sample_count}",
            _ratio(row.close_below_count, row.close_below_ratio_pct, total),
            _ratio(
                row.close_at_or_above_count,
                row.close_at_or_above_ratio_pct,
                total,
            ),
            _points(row.pullback_median_pct),
        )
    gap_parts = [
        f"{_short_level_label(row.basis, row.level_pct)} "
        f"{row.gap_trigger_count}/{row.trigger_count}"
        for row in rows
        if row.gap_trigger_count > 0
    ]
    if gap_parts:
        table.caption = "跳空直接越过: " + " · ".join(gap_parts)
    return table


def render_stock_range(console: Console, study: StockRangeStudy) -> None:
    """渲染完整的单股历史日内范围复核结果。"""

    from kan.render.base import DISCLAIMER

    name = study.name.replace(" ", "")
    console.print(f"\n[bold]慢慢看 · {name} {study.symbol} · 日内上下行范围[/bold]")
    console.print(
        f"  数据截止 {study.data_cutoff} 收盘 · 前收基准 · 前复权 · "
        f"参考收盘 {study.reference_close:.2f} 元"
    )
    console.print(
        f"  原始 {study.coverage.raw_rows} 根 · "
        f"有效 {study.coverage.valid_observations} 个日内样本 · 来源 {study.source}"
    )

    for window in study.windows:
        console.print(
            f"\n[bold]近 {window.period} 个完整交易日[/bold] · "
            f"有效 {window.sample_count}/{window.period} · "
            f"{window.start_date or '—'} 至 {window.end_date or '—'}"
        )
        console.print(downside_table(window, reference_close=study.reference_close))
        console.print(upside_table(window, reference_close=study.reference_close))

    console.print(
        "\n[dim]档位 = 线性插值分位估计；实际 = 样本中未越过该线的比例；"
        "收回线、收正、收盘线上/线下均以本行触及次数为分母；"
        "下行未收回即收盘仍在线下。[/dim]"
    )
    for warning in study.warnings:
        console.print(f"[yellow]⚠️  {warning}[/yellow]")
    console.print(DISCLAIMER, style="dim")


__all__ = ["downside_table", "render_stock_range", "upside_table"]

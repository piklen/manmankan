"""`kan range` 的终端表格。"""

from __future__ import annotations

from collections import Counter
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


def _threshold_pct(value: float) -> str:
    """按统计实际采用的 4 位公开阈值展示，避免终端回传时丢精度。"""

    if value == 0:
        return "0%"
    magnitude = f"{abs(value):.4f}".rstrip("0").rstrip(".")
    sign = "+" if value > 0 else "-"
    return f"{sign}{magnitude}%"


def _reference_price(threshold_pct: float, reference_price: float) -> str:
    return f"{_threshold_pct(threshold_pct)}\n{reference_price:.2f}元"


def downside_table(
    window: StockRangeWindow,
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
            _reference_price(row.threshold_pct, row.reference_price),
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
            _reference_price(row.threshold_pct, row.reference_price),
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
        console.print(downside_table(window))
        console.print(upside_table(window))

    console.print(
        "\n[dim]档位 = 线性插值分位估计；实际 = 样本中未越过该线的比例；"
        "收回线、收正、收盘线上/线下均以本行触及次数为分母；"
        "下行未收回即收盘仍在线下。[/dim]"
    )
    for warning in study.warnings:
        console.print(f"[yellow]⚠️  {warning}[/yellow]")
    console.print(DISCLAIMER, style="dim")


def _level_row(rows, level: float):
    return next(
        (
            row
            for row in rows
            if row.level_pct is not None and abs(row.level_pct - level) < 1e-9
        ),
        None,
    )


def _compact_threshold(row, *, sample_count: int) -> str:
    if row is None:
        return "—"
    coverage = (
        "实—"
        if row.actual_coverage_pct is None
        else f"实{row.actual_coverage_pct:.0f}%"
    )
    return (
        f"{_threshold_pct(row.threshold_pct)}\n{row.reference_price:.2f}元\n"
        f"{coverage}\n触{row.trigger_count}/{sample_count}"
    )


def _batch_levels(studies: list[StockRangeStudy]) -> list[float]:
    if not studies:
        return [90.0, 95.0]
    requested = list(studies[0].request.levels)
    selected = [level for level in (90.0, 95.0) if level in requested]
    for level in reversed(requested):
        if level not in selected:
            selected.append(level)
        if len(selected) == 2:
            break
    return sorted(selected)


def _batch_table(studies: list[StockRangeStudy]) -> Table:
    levels = _batch_levels(studies)
    table = Table(
        title="多股日内上下行范围 · 紧凑视图",
        pad_edge=False,
        padding=(0, 0),
        show_lines=True,
    )
    table.add_column("股票/截止", no_wrap=True)
    table.add_column("期/样", justify="right", no_wrap=True)
    table.add_column("收盘", justify="right", no_wrap=True)
    for level in levels:
        table.add_column(f"下{level:g}", justify="right", no_wrap=True)
    for level in levels:
        table.add_column(f"上{level:g}", justify="right", no_wrap=True)

    for study in studies:
        stock_label = (
            f"{study.name.replace(' ', '')}\n{study.symbol}\n{study.data_cutoff}"
        )
        for window_index, window in enumerate(study.windows):
            cells = [
                stock_label if window_index == 0 else "",
                f"{window.period}日\n{window.sample_count}/{window.period}",
                f"{study.reference_close:.2f}",
            ]
            cells.extend(
                _compact_threshold(
                    _level_row(window.downside, level),
                    sample_count=window.sample_count,
                )
                for level in levels
            )
            cells.extend(
                _compact_threshold(
                    _level_row(window.upside, level),
                    sample_count=window.sample_count,
                )
                for level in levels
            )
            table.add_row(*cells)
    return table


def _custom_batch_table(studies: list[StockRangeStudy]) -> Table | None:
    if not any(
        window.custom_downside is not None or window.custom_upside is not None
        for study in studies
        for window in study.windows
    ):
        return None
    table = Table(title="用户指定幅度复核", pad_edge=False, show_lines=True)
    table.add_column("股票", no_wrap=True)
    table.add_column("窗口", justify="right", no_wrap=True)
    table.add_column("下行幅度 / 参考价", justify="right", no_wrap=True)
    table.add_column("上行幅度 / 参考价", justify="right", no_wrap=True)
    for study in studies:
        for window in study.windows:
            table.add_row(
                f"{study.name.replace(' ', '')} {study.symbol}",
                f"{window.period} 日 · {window.sample_count}/{window.period}",
                _compact_threshold(
                    window.custom_downside,
                    sample_count=window.sample_count,
                ),
                _compact_threshold(
                    window.custom_upside,
                    sample_count=window.sample_count,
                ),
            )
    return table


def render_stock_range_batch(
    console: Console,
    studies: list[StockRangeStudy],
    *,
    failures: list[tuple[str, str]],
) -> None:
    """把多只股票压成横向证据表；保持输入顺序，不做排名。"""

    from kan.render.base import DISCLAIMER

    console.print(
        f"\n[bold]慢慢看 · 多股日内上下行范围[/bold] · "
        f"成功 {len(studies)} · 失败 {len(failures)}",
    )
    if studies:
        console.print(_batch_table(studies))
        custom_table = _custom_batch_table(studies)
        if custom_table is not None:
            console.print(custom_table)
        console.print(
            "[dim]下/上表示下行/上行分位；单元格依次为幅度、当前参考价、"
            "实际覆盖率、触及次数/窗口样本。[/dim]",
        )
        console.print(
            "[dim]幅度保留分类实际使用的最多 4 位小数；参考价保留 2 位。"
            "批量表最多展示两个较高分位档，JSON 保留全部档位。[/dim]",
        )

    warning_counts: Counter[str] = Counter()
    warning_order: list[str] = []
    for study in studies:
        for warning in dict.fromkeys(study.warnings):
            warning_counts[warning] += 1
            if warning not in warning_order:
                warning_order.append(warning)
    common_warnings = {
        warning
        for warning, count in warning_counts.items()
        if len(studies) > 1 and count == len(studies)
    }
    for warning in warning_order:
        if warning in common_warnings:
            console.print(f"[yellow]⚠️  共同提示：{warning}[/yellow]")
    for study in studies:
        for warning in dict.fromkeys(study.warnings):
            if warning not in common_warnings:
                console.print(
                    f"[yellow]⚠️  {study.name.replace(' ', '')} "
                    f"{study.symbol}：{warning}[/yellow]",
                )
    for symbol, message in failures:
        console.print(f"[red]❌ {symbol}：{message}[/red]")
    console.print(DISCLAIMER, style="dim")


__all__ = [
    "downside_table",
    "render_stock_range",
    "render_stock_range_batch",
    "upside_table",
]

"""`kan range` 的人读视图：先回答用户的幅度，再复核历史证据。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import TYPE_CHECKING

from rich.table import Table

from kan.domain.stock_range import (
    DownsideThresholdStudy,
    StockRangeStudy,
    StockRangeWindow,
    UpsideThresholdStudy,
)

if TYPE_CHECKING:
    from rich.console import Console


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}".rstrip("0").rstrip(".") + "%"


def _ratio(count: int, ratio: float | None, total: int, *, inline: bool = False) -> str:
    """次数不能被百分比掩盖；没有触及不等于收回率为零。"""

    if ratio is None or total <= 0:
        return "无样本"
    if inline:
        return f"{count}/{total} 次（{_pct(ratio)}）"
    return f"{count}/{total}次\n{_pct(ratio)}"


def _threshold_pct(value: float) -> str:
    """保留分类采用的公开精度，复制幅度回查时不改变证据。"""

    if value == 0:
        return "0%"
    magnitude = f"{abs(value):.4f}".rstrip("0").rstrip(".")
    sign = "+" if value > 0 else "-"
    return f"{sign}{magnitude}%"


def _evidence_rows(
    windows: list[StockRangeWindow], *, upside: bool,
) -> Iterator[tuple[StockRangeWindow, DownsideThresholdStudy | UpsideThresholdStudy]]:
    # 同一档位的多个周期相邻，避免读者在两屏之间凭记忆对照。
    levels = sorted({
        row.level_pct
        for window in windows
        for row in (window.upside if upside else window.downside)
        if row.level_pct is not None
    })
    for level in levels:
        for window in windows:
            for row in (window.upside if upside else window.downside):
                if row.level_pct == level:
                    yield window, row


def _outcomes(
    row: DownsideThresholdStudy | UpsideThresholdStudy, *, inline: bool = False,
) -> tuple[str, str]:
    if isinstance(row, UpsideThresholdStudy):
        return (
            _ratio(row.close_below_count, row.close_below_ratio_pct, row.trigger_count, inline=inline),
            _ratio(row.close_at_or_above_count, row.close_at_or_above_ratio_pct, row.trigger_count, inline=inline),
        )
    return (
        _ratio(row.close_above_count, row.close_above_ratio_pct, row.trigger_count, inline=inline),
        _ratio(row.close_positive_count, row.close_positive_ratio_pct, row.trigger_count, inline=inline),
    )


def _outcome_table(windows: list[StockRangeWindow], *, upside: bool) -> Table:
    table = Table(
        title="涨到后，收盘守住了吗？" if upside else "跌到后，收盘收回了吗？",
        pad_edge=False,
        padding=(0, 1),
        show_lines=False,
        caption_justify="left",
    )
    table.add_column("历史档位", no_wrap=True)
    table.add_column("窗口", justify="right", no_wrap=True)
    table.add_column("涨幅/折算价" if upside else "跌幅/折算价", justify="right", no_wrap=True)
    table.add_column("到过/样本", justify="right", no_wrap=True)
    table.add_column("未守住/到过" if upside else "收回/到过", justify="right", no_wrap=True)
    table.add_column("守住/到过" if upside else "收涨/到过", justify="right", no_wrap=True)
    gaps: list[str] = []
    for window, row in _evidence_rows(windows, upside=upside):
        left, right = _outcomes(row)
        table.add_row(
            f"{row.level_pct:g}%档\n未越{_pct(row.actual_coverage_pct)}",
            f"{window.period}日",
            f"{_threshold_pct(row.threshold_pct)}\n{row.reference_price:.2f}元",
            f"{row.trigger_count}/{window.sample_count}天\n{_pct(row.trigger_ratio_pct)}",
            left,
            right,
        )
        if row.gap_trigger_count:
            gaps.append(
                f"{row.level_pct:g}%档 {window.period}日 {row.gap_trigger_count}/{row.trigger_count}次",
            )
    if gaps:
        table.caption = "到过的样本中，开盘已到或越过：" + "；".join(gaps)
    return table


def downside_table(windows: list[StockRangeWindow]) -> Table:
    """展示下行各档的跨周期证据。"""

    return _outcome_table(windows, upside=False)


def upside_table(windows: list[StockRangeWindow]) -> Table:
    """展示上行各档的跨周期证据。"""

    return _outcome_table(windows, upside=True)


def _custom_summary(console: Console, study: StockRangeStudy) -> None:
    if study.request.down_pct is None and study.request.up_pct is None:
        return
    console.print("\n[bold]你输入的幅度 · 先看历史上发生过什么[/bold]")
    for upside in (False, True):
        heading_printed = False
        for window in study.windows:
            row = window.custom_upside if upside else window.custom_downside
            if row is None:
                continue
            if not heading_printed:
                direction = "上涨" if upside else "下跌"
                console.print(
                    f"[bold]{direction} {_threshold_pct(row.threshold_pct)}[/bold]"
                    f" · 按本次参考收盘折算 {row.reference_price:.2f} 元",
                )
                heading_printed = True
            prefix = f"  近 {window.period} 日：{row.trigger_count}/{window.sample_count} 天到过"
            if row.trigger_count == 0:
                console.print(f"{prefix}；无触及样本，无法统计之后的收盘结果。")
                continue
            left, right = _outcomes(row, inline=True)
            outcomes = (
                f"收盘未守住 {left}；守住 {right}"
                if upside else f"收盘收回 {left}；收盘上涨 {right}"
            )
            console.print(f"{prefix}；{outcomes}。")
            if row.gap_trigger_count:
                console.print(f"    其中 {row.gap_trigger_count}/{row.trigger_count} 次在开盘就已到或越过该幅度。")


def _reading_guide(console: Console) -> None:
    console.print("[dim]读法：先看幅度与折算价，再看有几天到过，最后看这些天的收盘结果。[/dim]")
    console.print(
        "[yellow]95%档是历史幅度分位，不是未来有95%的把握；"
        "1/1次也只是一例，0次到过不代表以后到不了。[/yellow]",
    )
    console.print(
        "[dim]收回 = 收盘高于下跌线；收涨 = 收盘高于前收（两者有重叠）。"
        "守住 = 收盘≥上涨线；未守住 = 收盘<上涨线。[/dim]",
    )


def _stock_header(console: Console, study: StockRangeStudy) -> None:
    console.print(
        f"\n[bold]{study.name.replace(' ', '')} {study.symbol}[/bold]"
        f" · 数据截止 {study.data_cutoff} · 来源 {study.source}",
        highlight=False,
    )
    console.print(
        f"参考收盘 {study.reference_close:.2f} 元（{study.data_cutoff}）；"
        "折算价 = 此收盘 × (1 + 日涨跌幅)。",
    )
    for window in study.windows:
        console.print(
            f"近 {window.period} 个完整交易日 · 有效 {window.sample_count}/{window.period} · "
            f"{window.start_date or '—'} 至 {window.end_date or '—'}",
        )


def _stock_tables(console: Console, study: StockRangeStudy, *, guide: bool = False) -> None:
    _custom_summary(console, study)
    console.print("\n[bold]历史幅度对照 · 同档位的各周期相邻[/bold]")
    if guide:
        _reading_guide(console)
    console.print(downside_table(study.windows))
    console.print(upside_table(study.windows))


def _price_guide(console: Console) -> None:
    console.print(
        "[dim]日涨跌幅相对前收，不是持仓盈亏；前复权完整日K，不能还原盘中先后或水下时长。"
        "折算价不是实时价或成交保证，跨日需重算；短窗口包含在长窗口内，并非两组独立样本。[/dim]",
    )


def _footer(console: Console, studies: list[StockRangeStudy]) -> None:
    from kan.render.base import DISCLAIMER

    _price_guide(console)
    console.print(
        "\n[dim]档位由线性插值计算；未越 = 样本中没有越过该幅度的天数比例，"
        "不等于没到过（刚好等于线时，两项均计入）。"
        "幅度最多4位小数、折算价2位；收盘中位、最高到收盘回落等明细见 --format json。[/dim]",
    )
    if studies:
        console.print(
            "\n核对自己的幅度：在原命令后加 --down 3 --up 7，保留原股票池与周期。",
            markup=False,
        )
        console.print("[dim]3/7仅演示参数写法：分别表示下跌3% / 上涨7%，请换成你要核对的数值。[/dim]")
    console.print(DISCLAIMER, style="dim")


def _warnings(console: Console, studies: list[StockRangeStudy]) -> None:
    # 公共短样本提示只说一次，但必须在读者看到表格前出现。
    counts = Counter(warning for study in studies for warning in dict.fromkeys(study.warnings))
    common = {
        warning for warning, count in counts.items()
        if len(studies) > 1 and count == len(studies)
    }
    for warning in counts:
        if warning in common:
            console.print(f"⚠️  共同提示：{warning}", style="yellow", markup=False)
    for study in studies:
        for warning in dict.fromkeys(study.warnings):
            if warning not in common:
                label = f"{study.name.replace(' ', '')} {study.symbol}：" if len(studies) > 1 else ""
                console.print(f"⚠️  {label}{warning}", style="yellow", markup=False)


def render_stock_range(console: Console, study: StockRangeStudy) -> None:
    """单股先呈现用户明确给出的幅度，再按方向对照各周期。"""

    console.print("\n[bold]慢慢看 · 日涨跌幅历史复核[/bold]")
    _stock_header(console, study)
    console.print("[dim]以下都是历史次数，不是未来概率；日涨跌幅相对前收，不是持仓盈亏。[/dim]")
    _warnings(console, [study])
    _stock_tables(console, study, guide=True)
    _footer(console, [study])


def render_stock_range_batch(
    console: Console,
    studies: list[StockRangeStudy],
    *,
    failures: list[tuple[str, str]],
) -> None:
    """每股保留全部档位及收盘证据；顺序由用户输入决定。"""

    console.print(
        f"\n[bold]慢慢看 · 多股日涨跌幅历史复核[/bold] · "
        f"成功 {len(studies)} · 失败 {len(failures)}",
    )
    if studies:
        _reading_guide(console)
        console.print("[dim]日涨跌幅相对前收，不是持仓盈亏。[/dim]")
        _warnings(console, studies)
    for index, study in enumerate(studies, start=1):
        console.rule(f"{index}/{len(studies)} · {study.symbol}")
        _stock_header(console, study)
        _stock_tables(console, study)
    for symbol, message in failures:
        console.print(f"❌ {symbol}：{message}", style="red", markup=False)
    _footer(console, studies)


__all__ = [
    "downside_table",
    "render_stock_range",
    "render_stock_range_batch",
    "upside_table",
]

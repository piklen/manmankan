"""scan 终端表格渲染。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from kan.infra.formatting import format_date_compact, format_fetched_at_compact
from kan.render.base import format_pct
from kan.render.terminal_common import _board_reference_label

if TYPE_CHECKING:
    from kan.core.models import StockScanResult
    from kan.core.pipeline import DataCtx


# ── scan ──────────────────────────────────────────────────────────────


def scan_title(
    ctx: DataCtx,
    *,
    high_mode: bool,
    signal_only: bool = False,
) -> str:
    """构造 scan 命令标题 · 给 terminal table.title + md export 共用 · 单 SOT。"""
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta

    meta = ctx.meta
    data_cutoff = ctx.freshness.data_cutoff
    fetched_at = ctx.freshness.fetched_at

    if isinstance(meta, BoardMeta):
        return (
            f"慢慢看 · {meta.board.name} 行业位置扫描"
            f" · {'高点' if high_mode else '低点'}模式"
        )
    if isinstance(meta, HotMeta):
        return (
            f"慢慢看 · {meta.list_name} 位置扫描"
            f" · {'高点' if high_mode else '低点'}模式"
        )
    if isinstance(meta, ThemeMeta):
        return (
            f"慢慢看 · {meta.theme.name} 题材位置扫描"
            f" · {'高点' if high_mode else '低点'}模式"
        )
    source_name = getattr(ctx, "source_name", "") or "自选股"
    title = (
        f"慢慢看 · {source_name}位置扫描 · "
        f"{'高点' if high_mode else '低点'}模式"
    )
    if signal_only:
        title += " · 仅信号"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    return title


def scan_table(
    ctx: DataCtx,
    results: list[StockScanResult],
    *,
    display_periods: list[int],
    high_mode: bool,
    signal_only: bool = False,
    board_index_result: StockScanResult | None = None,
    show_context: bool = False,
) -> Table:
    """kan scan 10-周期全景表 · 支持板块指数 row + 热榜名次 + 自选 ⭐ 高亮。

    title 由 ctx.meta(BoardMeta/HotMeta/ThemeMeta/None)+ ctx.freshness 决定 ·
    自选模式带 cutoff/fetched_at 后缀 · 行业/热榜/题材模式标题完全替换不带后缀
    (与 原状一致 · 不改)。

    Args:
        ctx: 数据流水线产出快照 · 提供 meta + freshness。
        results: 已经过 exclude_st / --signal 过滤的展示行。
        display_periods: responsive_periods(console.width) 选出的周期子集。
        high_mode: True=高点模式 / False=低点模式 · 影响标题 + format_pct 色 + 共振取值。
        signal_only: True 时标题追加 " · 仅信号"(仅自选模式生效 · 板块模式忽略)。
        board_index_result: 板块指数 / 题材指数 K 线 scan 结果 · 不为 None 时作为
            第一行 + section 分隔(与 results 区分)。caller 提前算好(scan_stock 是
            重导入 · render 层不应自己调度)。
    """
    from kan.core.models import HotMeta

    meta = ctx.meta
    title = scan_title(ctx, high_mode=high_mode, signal_only=signal_only)
    is_hot = isinstance(meta, HotMeta)
    highlight = meta.highlight if meta else set()
    rank_map = meta.rank_map if is_hot else {}

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    if show_context:
        table.add_column("PE", justify="right", min_width=6)
        table.add_column("5日主力(万)", justify="right", min_width=10)
        table.add_column("10日线", justify="right", min_width=8)
        table.add_column("20日线", justify="right", min_width=8)
        table.add_column("20日低", justify="right", min_width=8)
        table.add_column("除权除息", justify="right", min_width=10)
    for p in display_periods:
        table.add_column(f"{p}日", justify="right", min_width=6)
    table.add_column("共振", justify="center")

    if board_index_result is not None:
        brow: list[str | Text] = [
            _board_reference_label(board_index_result.name, meta),
        ]
        brow.append(f"{board_index_result.current_price:.2f}")
        if show_context:
            brow.extend(["-", "-", "-", "-", "-", "-"])
        for p in display_periods:
            pr = next(
                (x for x in board_index_result.periods if x.period == p), None,
            )
            brow.append(
                Text("-", style="dim") if pr is None
                else format_pct(pr, high_mode=high_mode),
            )
        brow.append("")
        table.add_row(*brow)
        table.add_section()

    for r in results:
        row: list[str | Text] = []
        if is_hot:
            rank = rank_map.get(r.symbol)
            row.append(str(rank) if rank is not None else "-")
        name_short = r.name.replace(" ", "")
        tag = ""
        if r.limit_up:
            tag = " 涨停"
        elif r.limit_down:
            tag = " 跌停"
        star = "⭐ " if (r.symbol in highlight or getattr(r, "in_watchlist", False)) else ""
        hold = "💰 " if getattr(r, "in_holding", False) else ""
        row.append(f"{hold}{star}{name_short} {r.symbol}{tag}")
        row.append(f"{r.current_price:.2f}")
        if show_context:
            row.extend([
                _fmt_scan_number(getattr(r, "pe_ttm", None), digits=1),
                _fmt_money_wan(getattr(r, "moneyflow_5d_net_amount", None)),
                _fmt_scan_number(getattr(r, "ma_10", None)),
                _fmt_scan_number(getattr(r, "ma_20", None)),
                _fmt_scan_number(getattr(r, "recent_low_20", None)),
                _fmt_corporate_action(getattr(r, "corporate_action", None)),
            ])

        for p in display_periods:
            pr = next((x for x in r.periods if x.period == p), None)
            if pr is None:
                row.append(Text("-", style="dim"))
            else:
                row.append(format_pct(pr, high_mode=high_mode))

        resonance = r.high_resonance if high_mode else r.low_resonance
        if resonance >= 3:
            row.append(Text(f"×{resonance}", style="bold yellow"))
        elif resonance > 0:
            row.append(Text(f"×{resonance}", style="yellow"))
        else:
            row.append("")

        table.add_row(*row)

    return table


def _fmt_scan_number(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _fmt_money_wan(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}"


def _fmt_corporate_action(action) -> str:
    if action is None:
        return "-"
    text = action.ex_date.strftime("%m-%d")
    if action.reference_price is not None:
        text += f"@{action.reference_price:.2f}"
    return text

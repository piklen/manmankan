"""low/high 终端表格渲染。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from kan.infra.formatting import format_date_compact, format_fetched_at_compact
from kan.render.terminal_common import _board_reference_label

if TYPE_CHECKING:
    from datetime import date

    from kan.core.models import BoardMeta, HotMeta, PeriodResult, StockScanResult, ThemeMeta


# ── low / high ────────────────────────────────────────────────────────


def extreme_table(
    period: int,
    hits: list[tuple[StockScanResult, PeriodResult]],
    mode: str,
    *,
    is_hot: bool = False,
    rank_map: dict[str, int] | None = None,
    highlight: set[str] | None = None,
    data_cutoff: date | None = None,
    fetched_at: str | None = None,
    board_index_result: StockScanResult | None = None,
    board_meta: BoardMeta | HotMeta | ThemeMeta | None = None,
) -> Table:
    """kan low / high 单周期表 · 多周期时由 caller 循环逐张调用。

    title 含周期 + 触及数 + 累积 cutoff/fetched_at(caller 在跨周期循环里累积 ·
    与原行为一致 · 数据本身不变只是表头不同)。

    Args:
        period: 当前周期天数(2-360)。
        hits: filter_extreme 产出的 [(StockScanResult, PeriodResult), ...]。
        mode: "low" 或 "high" · 决定标签 + 位置百分比文字色。
        is_hot: True 时加 "榜" 名次列。
        rank_map: 热榜代码 → 名次。is_hot=False 时可 None。
        highlight: 自选股代码集合 · 用于 ⭐ 前缀。
        data_cutoff: 截至本周期累积的最大 cutoff · 影响 title。
        fetched_at: 截至本周期累积的最晚 cache_age · 影响 title。
        board_index_result: 板块 / 题材指数 K 线 scan 结果 · 不为 None 时
            作为首行 + add_section 与 hits 视觉分隔。caller 提前 scan_stock
            产出(传 periods=用户周期 list)· render 层不调度。
        board_meta: 用于选名称前缀(BoardMeta → 🏛️ 板块指数 · ThemeMeta →
            🎯 题材指数)· 当 board_index_result 非 None 时必须配套传入。
    """
    label = "低点" if mode == "low" else "高点"
    signal_style = "bold green" if mode == "low" else "bold yellow"
    rank_map = rank_map or {}
    highlight = highlight or set()

    title = f"慢慢看 · {period} 日{label} · {len(hits)} 只触及"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    table.add_column(f"{period}日最低", justify="right", style="dim", min_width=8)
    table.add_column(f"{period}日最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    if board_index_result is not None:
        # 找出当前 period 对应的 PeriodResult · caller 调 scan_stock 时
        # periods 应当含 period · 但 board K 线行数 < period 时会 insufficient。
        board_pr = next(
            (p for p in board_index_result.periods if p.period == period), None,
        )
        bref: list[str | Text] = []
        if is_hot:  # 兜底 · 当前 hot 无 index_kline · 此分支理论上走不到
            bref.append("-")
        bref.append(_board_reference_label(board_index_result.name, board_meta))
        bref.append(f"{board_index_result.current_price:.2f}")
        if board_pr is None or board_pr.insufficient:
            bref.append("-")
            bref.append("-")
            bref.append(Text("-", style="dim"))
        else:
            bref.append(f"{board_pr.n_low:.2f}")
            bref.append(f"{board_pr.n_high:.2f}")
            # reference 行用普通色不带 [%] · 与 hits 的 [pct%] bold 信号区分
            bref.append(f"{board_pr.position_pct:.1f}%")
        table.add_row(*bref)
        table.add_section()

    for result, pr in hits:
        name_short = result.name.replace(" ", "")
        star = "⭐ " if result.symbol in highlight else ""
        row: list[str | Text] = []
        if is_hot:
            rank = rank_map.get(result.symbol)
            row.append(str(rank) if rank is not None else "-")
        row.append(f"{star}{name_short} {result.symbol}")
        row.append(f"{result.current_price:.2f}")
        row.append(f"{pr.n_low:.2f}")
        row.append(f"{pr.n_high:.2f}")
        row.append(Text(f"[{pr.position_pct:.1f}%]", style=signal_style))
        table.add_row(*row)

    return table

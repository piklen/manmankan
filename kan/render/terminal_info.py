"""info 终端表格渲染。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from kan.render.base import format_pct

if TYPE_CHECKING:
    from kan.core.models import BoardMeta, BoardPositionContext, StockScanResult, ThemeMeta


# ── info(单股全周期 / 行业档案 / 题材档案 共用)─────────────────────────


def info_table(
    result: StockScanResult,
    *,
    is_industry: bool = False,
    board_meta: BoardMeta | ThemeMeta | None = None,
) -> Table:
    """4 列全周期位置表 · 周期 / 最低 / 最高 / 位置。

    info(单股) · _info_industry(行业档案) · _info_theme(题材档案)三处共用。
    有一个易错点:单股 info 的 insufficient 位置单元格用 Text("-", style="dim") ·
    industry/theme 档案用普通字符串 "-"。字符级一致约束下两条路径不能合并。

    Args:
        result: scan_stock 产出的 StockScanResult(单股 / 板块指数 / 题材指数)。
        is_industry: True → insufficient 位置单元格用 "-"(industry / theme)。
                     False → insufficient 位置单元格用 Text("-", style="dim")(info)。
        board_meta: 预留 · 当前不参与渲染(future-extension hook)。
    """
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("最低", justify="right", style="dim", min_width=8)
    table.add_column("最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    for pr in result.periods:
        if pr.insufficient:
            if is_industry:
                table.add_row(f"{pr.period}日", "-", "-", "-")
            else:
                table.add_row(
                    f"{pr.period}日", "-", "-", Text("-", style="dim"),
                )
        else:
            table.add_row(
                f"{pr.period}日",
                f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}",
                format_pct(pr),
            )

    return table


def board_position_table(context: BoardPositionContext) -> Table:
    """kan info 所属板块位置对照表 · 低到高排名是客观排序口径。"""
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("本股位置", justify="right")
    table.add_column("板块均值", justify="right")
    table.add_column("低到高排名", justify="right")

    for row in context.periods:
        table.add_row(
            f"{row.period}日",
            f"{row.position_pct:.1f}%",
            f"{row.board_avg_pct:.1f}%",
            f"{row.rank_low_to_high}/{row.sample}",
        )
    return table

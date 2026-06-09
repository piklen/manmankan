"""history 终端表格渲染。"""
from __future__ import annotations

from rich.table import Table
from rich.text import Text

from kan.infra.formatting import format_date_compact
from kan.render.base import format_pct

# ── 历史位置回溯(`kan history`)───────────────────────────────────────


class _HistCell:
    """把快照里的裸 dict 适配成 format_pct 吃的 duck-typed 对象(insufficient=False)。"""

    __slots__ = ("at_high", "at_low", "insufficient", "position_pct")

    def __init__(self, cell: dict):
        self.insufficient = False
        self.at_low = bool(cell.get("at_low"))
        self.at_high = bool(cell.get("at_high"))
        self.position_pct = cell.get("pct", 0.0)


def history_table(
    symbol: str,
    name: str,
    entries: list,
    *,
    period: int,
) -> Table:
    """单只股票位置回溯 · 行=快照日(新→旧)· 列=日期/N日位置/共振/标记。

    纯离线渲染:entries 来自 scanner.load_symbol_history(只读 snapshots/)。
    位置单元格复用 render.base.format_pct(跟 scan 同配色)· 某日缺该周期 → dim 「-」。
    """
    from kan.core.scanner import history_mark

    name_short = name.replace(" ", "")
    title = f"慢慢看 · {name_short} {symbol} · {period}日位置回溯"

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("日期", justify="left", style="white", no_wrap=True)
    table.add_column(f"{period}日位置", justify="right", min_width=7)
    table.add_column("共振", justify="center")
    table.add_column("标记", justify="left")

    for e in entries:
        cell = e.periods.get(period)
        if cell is None:
            pct_text: Text = Text("-", style="dim")
        else:
            pct_text = format_pct(_HistCell(cell))

        res, direction = history_mark(e.periods)
        if res == 0:
            res_text = Text("—", style="dim")
            mark_text = Text("—", style="dim")
        else:
            res_text = Text(f"×{res}", style="bold yellow" if res >= 3 else "")
            arrow = "⬇" if direction == "low" else "⬆"
            color = "green" if direction == "low" else "red"
            if res >= 3:
                word = "多周期低位" if direction == "low" else "多周期高位"
                mark_text = Text(f"{arrow} {word}", style=color)
            else:
                mark_text = Text(arrow, style=color)

        table.add_row(format_date_compact(e.snapshot_date), pct_text, res_text, mark_text)

    return table

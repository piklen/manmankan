"""hold 终端表格渲染。"""
from __future__ import annotations

from rich.table import Table
from rich.text import Text

from kan.infra.formatting import format_date_compact

# ── hold ──────────────────────────────────────────────────────────────

def _fmt_hold_num(value: float | int | None, *, digits: int = 2, mask: bool = False) -> str:
    if mask:
        return "***"
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    return f"{value:,.{digits}f}"


def _fmt_hold_pct(value: float | None, *, mask: bool = False) -> str:
    if mask:
        return "***"
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _pnl_text(value: float | None, *, pct: bool = False, mask: bool = False) -> Text:
    if mask:
        return Text("***", style="dim")
    if value is None:
        return Text("-", style="dim")
    text = f"{value:+.2f}%" if pct else f"{value:+,.2f}"
    if value > 0:
        return Text(text, style="red")
    if value < 0:
        return Text(text, style="green")
    return Text(text)


def hold_table(summary, *, mask: bool = False) -> Table:
    """持仓总览表 · A 股红涨绿跌。"""
    title = "慢慢看 · 持仓总览"
    if summary.data_cutoff:
        title += f" · 数据截止 {format_date_compact(summary.data_cutoff)}"
    title += f" · 现价口径 {summary.price_mode}"
    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", min_width=8)
    table.add_column("成本", justify="right", min_width=8)
    table.add_column("今日盈亏%", justify="right", min_width=10)
    table.add_column("累计盈亏%", justify="right", min_width=10)
    table.add_column("累计盈亏额", justify="right", min_width=11)
    table.add_column("市值", justify="right", min_width=10)
    table.add_column("仓位%", justify="right", min_width=8)
    for period in (30, 60, 180):
        table.add_column(f"{period}日", justify="right", min_width=6)

    for row in summary.results:
        name = row.name.replace(" ", "")
        status = " 停牌" if row.price_status == "suspended" else ""
        table.add_row(
            f"💰 {name} {row.symbol}{status}",
            _fmt_hold_num(row.price),
            _fmt_hold_num(row.cost, digits=4, mask=mask),
            _pnl_text(row.daily_pnl_pct, pct=True, mask=mask),
            _pnl_text(row.total_pnl_pct, pct=True, mask=mask),
            _pnl_text(row.total_pnl, mask=mask),
            _fmt_hold_num(row.market_value, mask=mask),
            _fmt_hold_pct(row.weight_pct, mask=mask),
            _fmt_hold_num(row.positions.get(30), digits=1),
            _fmt_hold_num(row.positions.get(60), digits=1),
            _fmt_hold_num(row.positions.get(180), digits=1),
        )
    return table


def render_hold_footer(summary, console, *, mask: bool = False) -> None:
    account = summary.account
    console.print(
        "\n[bold]账户[/bold] · "
        f"总市值 {_fmt_hold_num(account.total_market_value, mask=mask)} · "
        f"现金 {_fmt_hold_num(account.cash, mask=mask)} · "
        f"总资产 {_fmt_hold_num(account.total_assets, mask=mask)} · "
        f"总仓位 {_fmt_hold_pct(account.total_position_pct, mask=mask)} · "
        f"今日总盈亏 {_pnl_text(account.daily_pnl, mask=mask)} · "
        f"累计总盈亏 {_pnl_text(account.total_pnl, mask=mask)}"
    )
    h = summary.health
    console.print(
        "[bold]体检[/bold] · "
        f"高位 {h.high_count} 只 · 低位 {h.low_count} 只 · "
        f"中间 {h.middle_count} 只 · 浮盈 {h.profit_count} 只 · "
        f"浮亏 {h.loss_count} 只 · 持平/缺口 {h.flat_count} 只"
    )
    for note in summary.notes:
        console.print(f"[dim]{note}[/dim]")
    from kan.render.base import HOLD_DISCLAIMER_TEXT

    console.print(f"[bold dim]{HOLD_DISCLAIMER_TEXT}[/bold dim]")

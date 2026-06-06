"""`kan hold` 真实持仓命令组。"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err, confirm_destructive
from kan.storage import export

hold_app = typer.Typer(
    name="hold",
    help="真实持仓 · 客观位置 + 盈亏事实",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(hold_app, name="hold")


def _exit_hold_error(message: str, *, exit_code: int = 1) -> None:
    _print_err(f"❌ {message}")
    raise typer.Exit(exit_code)


def _read_import_source(source: str) -> str:
    if source == "-":
        import sys

        return sys.stdin.read()
    path = Path(source)
    if not path.exists() or not path.is_file():
        raise ValueError(f"导入文件不存在或不是普通文件: {source}")
    return path.read_text(encoding="utf-8")


def _format_wan(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 10000:
        return f"{value / 10000:.1f}万"
    return f"{value:.2f}"


def _cached_market_value(symbol: str, shares: int) -> float | None:
    try:
        from kan.core.positions import price_from_kline
        from kan.data.fetcher import get_cached

        quote = price_from_kline(symbol, get_cached(symbol))
    except Exception:
        return None
    if quote.price is None:
        return None
    return round(quote.price * shares, 2)


def _echo_position_confirm(prefix: str, position) -> None:
    market_value = _cached_market_value(position.symbol, position.shares)
    typer.echo(
        f"{prefix}:{position.name} {position.symbol} · "
        f"成本 {position.cost:g} × {position.shares} 股 · "
        f"市值 {_format_wan(market_value)}"
    )


def _build_summary(*, no_refresh: bool, check_corporate_actions: bool = True):
    from kan.core.positions import PriceSnapshot, evaluate_positions, price_from_kline
    from kan.core.scanner import scan_stock
    from kan.core.trading_calendar import PHASE_INTRADAY, latest_trade_date, market_phase
    from kan.data.fetcher import get_cached
    from kan.storage.positions import load_positions

    book = load_positions()
    pairs = [(p.symbol, p.name) for p in book.positions]
    if pairs and not no_refresh:
        from kan.cli.helpers import _auto_fetch_stale

        _auto_fetch_stale(pairs, days=180)

    cached = {symbol: get_cached(symbol) for symbol, _name in pairs}
    prices = {symbol: price_from_kline(symbol, df) for symbol, df in cached.items()}
    scans = {}
    for symbol, name in pairs:
        df = cached.get(symbol)
        if df is None or getattr(df, "empty", True):
            continue
        scans[symbol] = scan_stock(df, symbol, name, periods=[30, 60, 180])

    phase = market_phase()
    price_mode = "close"
    if phase == PHASE_INTRADAY and pairs and not no_refresh:
        from kan.data.realtime import fetch_realtime_quotes

        quotes = fetch_realtime_quotes([symbol for symbol, _name in pairs])
        if quotes:
            price_mode = "realtime"
        for symbol, quote in quotes.items():
            fallback = prices.get(symbol)
            prices[symbol] = PriceSnapshot(
                symbol=symbol,
                price=quote.price,
                prev_close=quote.prev_close or (fallback.prev_close if fallback else None),
                source=quote.source,
                data_cutoff=fallback.data_cutoff if fallback else None,
                trade_time=quote.trade_time,
                status=quote.status,
            )

    return evaluate_positions(
        book,
        prices=prices,
        scans=scans,
        price_mode=price_mode,
        as_of=latest_trade_date(),
        check_corporate_actions=check_corporate_actions,
    )


def _render_overview(
    *,
    fmt: export.OutputFormat,
    no_refresh: bool,
    mask: bool,
) -> None:
    from rich.console import Console

    summary = _build_summary(no_refresh=no_refresh)
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.hold_payload(summary, mask=mask)))
        return
    if fmt is export.OutputFormat.md:
        typer.echo(export.hold_markdown(summary, mask=mask))
        return

    from kan.render import terminal
    from kan.render.base import HOLD_DISCLAIMER_TEXT

    console = Console()
    if not summary.results:
        console.print("持仓为空 · 例: kan hold add 600519 --cost 1680 --shares 100")
        console.print(f"[bold dim]{HOLD_DISCLAIMER_TEXT}[/bold dim]")
        return
    console.print(terminal.hold_table(summary, mask=mask))
    terminal.render_hold_footer(summary, console, mask=mask)


@hold_app.callback()
def hold_root(
    ctx: typer.Context,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式:terminal(默认)/ md / json"),
    ] = export.OutputFormat.terminal,
    no_refresh: Annotated[
        bool,
        typer.Option("--no-refresh", help="只用本地缓存，不刷新 K 线或实时价"),
    ] = False,
    mask: Annotated[
        bool,
        typer.Option("--mask", help="金额脱敏，适合截图/演示"),
    ] = False,
) -> None:
    """持仓总览。"""
    if ctx.invoked_subcommand is None:
        _render_overview(fmt=fmt, no_refresh=no_refresh, mask=mask)
        raise typer.Exit()


@hold_app.command("add")
def add_cmd(
    items: Annotated[
        list[str] | None,
        typer.Argument(help="代码或紧凑格式 code:cost:shares，可一次多只"),
    ] = None,
    cost: Annotated[float | None, typer.Option("--cost", help="持仓成本/成交成本")] = None,
    shares: Annotated[int | None, typer.Option("--shares", help="股数（正整数）")] = None,
    add_to_existing: Annotated[
        bool,
        typer.Option("--add", help="追加到已有持仓并自动计算新均价"),
    ] = False,
    name: Annotated[str | None, typer.Option("--name", help="名称覆盖（可选）")] = None,
) -> None:
    """录入持仓。"""
    from kan.storage import positions

    if not items:
        _exit_hold_error("请提供代码或 code:cost:shares · 例: kan hold add 600519 --cost 1680 --shares 100", exit_code=2)
    try:
        if cost is not None or shares is not None:
            if len(items) != 1 or cost is None or shares is None:
                raise ValueError("结构化录入需要 1 个代码，并同时提供 --cost 与 --shares")
            pos = positions.add_position(
                items[0],
                cost=cost,
                shares=shares,
                name=name,
                merge=add_to_existing,
            )
            _echo_position_confirm("已录入", pos)
            return
        rows = [positions.parse_compact_token(item) for item in items]
        imported = positions.add_positions(rows)
    except ValueError as e:
        _exit_hold_error(str(e), exit_code=2)
    if imported.count == 1:
        _echo_position_confirm("已录入", imported.positions[0])
    else:
        total_market = sum(
            _cached_market_value(p.symbol, p.shares) or 0.0
            for p in imported.positions
        )
        typer.echo(
            f"录入 {imported.count} 只 · 总成本 {_format_wan(imported.total_cost)} · "
            f"总市值 {_format_wan(total_market)}"
        )


@hold_app.command("reduce")
def reduce_cmd(
    code: Annotated[str, typer.Argument(help="股票代码")],
    shares: Annotated[int, typer.Option("--shares", help="减少股数")],
) -> None:
    """减少持股数；减到 0 自动清仓。"""
    from kan.storage.positions import reduce_position

    try:
        pos, removed = reduce_position(code, shares=shares)
    except ValueError as e:
        _exit_hold_error(str(e), exit_code=2)
    if removed:
        typer.echo(f"已清仓:{pos.name} {pos.symbol}")
    else:
        _echo_position_confirm("已更新", pos)


@hold_app.command("remove")
def remove_cmd(code: Annotated[str, typer.Argument(help="股票代码")]) -> None:
    """删除单只持仓。"""
    from kan.storage.positions import remove_position

    try:
        pos = remove_position(code)
    except ValueError as e:
        _exit_hold_error(str(e), exit_code=2)
    typer.echo(f"已清仓:{pos.name} {pos.symbol}")


@hold_app.command("clear")
def clear_cmd(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过二次确认")] = False,
) -> None:
    """清空全部持仓。"""
    from kan.storage.positions import clear_positions, load_positions

    count = len(load_positions().positions)
    if count and not confirm_destructive(f"将清空 {count} 只持仓 · 不可恢复", yes=yes):
        typer.echo("已取消")
        return
    removed = clear_positions()
    typer.echo(f"已清空持仓 · {removed} 只")


@hold_app.command("update")
def update_cmd(
    code: Annotated[str, typer.Argument(help="股票代码")],
    cost: Annotated[float | None, typer.Option("--cost", help="覆盖成本")] = None,
    shares: Annotated[int | None, typer.Option("--shares", help="覆盖股数")] = None,
    name: Annotated[str | None, typer.Option("--name", help="覆盖名称")] = None,
) -> None:
    """纠错覆盖。"""
    from kan.storage.positions import update_position

    try:
        pos = update_position(code, cost=cost, shares=shares, name=name)
    except ValueError as e:
        _exit_hold_error(str(e), exit_code=2)
    _echo_position_confirm("已录入", pos)


@hold_app.command("cash")
def cash_cmd(amount: Annotated[float, typer.Argument(help="现金金额")]) -> None:
    """更新现金。"""
    from kan.storage.positions import set_cash

    try:
        book = set_cash(amount)
    except ValueError as e:
        _exit_hold_error(str(e), exit_code=2)
    typer.echo(f"已更新现金:{_format_wan(book.cash)}")


@hold_app.command("import")
def import_cmd(source: Annotated[str, typer.Argument(help="CSV 文件路径；- 表示 stdin")]) -> None:
    """批量导入持仓。"""
    from kan.storage.positions import import_positions_text

    try:
        text = _read_import_source(source)
        summary = import_positions_text(text)
    except ValueError as e:
        _exit_hold_error(str(e), exit_code=2)
    total_market = sum(
        _cached_market_value(p.symbol, p.shares) or 0.0
        for p in summary.positions
    )
    typer.echo(
        f"录入 {summary.count} 只 · 总成本 {_format_wan(summary.total_cost)} · "
        f"总市值 {_format_wan(total_market)}"
    )


@hold_app.command("scan")
def scan_cmd(
    high: Annotated[bool, typer.Option("--high", help="高点模式（默认低点模式）")] = False,
    signal: Annotated[bool, typer.Option("--signal", "-S", "-s", help="仅显示有共振信号的股票")] = False,
    exclude_st: Annotated[bool, typer.Option("--exclude-st", help="排除 ST/*ST 股票")] = False,
    periods: Annotated[
        str | None,
        typer.Option("--periods", help="计算/展示周期（2-360，逗号或空格分隔）"),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="终端只展示短/中/长关键周期"),
    ] = False,
    wide: Annotated[
        bool,
        typer.Option("--wide", help="终端展示全部计算周期"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """只扫描持仓池。"""
    from kan.cli.scan_cmds import scan

    scan(
        symbols=None,
        high=high,
        signal=signal,
        diff=False,
        exclude_st=exclude_st,
        codes=None,
        industry=None,
        hot=None,
        theme=None,
        only_watchlist=False,
        only_holdings=True,
        group=None,
        periods=periods,
        compact=compact,
        wide=wide,
        fmt=fmt,
    )

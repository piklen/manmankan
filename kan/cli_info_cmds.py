"""info · 单股 / 行业 / 题材 详情（全周期位置 + 涨跌信息）。"""
from typing import Annotated

import typer

from kan import export
from kan.app import app
from kan.cli_helpers import (
    _print_err,
    _safe_error_msg,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)


def _info_industry(industry: str, fmt: export.OutputFormat) -> None:
    """kan info --industry · 簡版板块档案。"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan import render_terminal
        from kan._pipeline import resolve_targets_or_exit
        from kan.render import DISCLAIMER
        from kan.scanner import scan_stock

    console = Console()
    _targets, meta = resolve_targets_or_exit(
        industry, only_watchlist=False, watchlist_pairs=[],
    )

    assert meta is not None
    board_result = scan_stock(meta.index_kline, meta.board.code, meta.board.name)

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.scan_payload(
                [board_result], mode="low", data_cutoff=board_result.scan_date,
                fetched_at=None, stale=False,
            )))
        else:
            typer.echo(export.scan_markdown(
                [board_result], periods=[p.period for p in board_result.periods],
                mode="low", title=f"慢慢看 · {meta.board.name} 板块档案",
            ))
        return

    lvl_name = {1: "申万一级", 2: "申万二级", 3: "申万三级"}[meta.board.level]
    console.print(
        f"\n[bold]🏛️ {meta.board.name} · {lvl_name} · {meta.board.code}[/bold]"
    )
    console.print(f"  成分股 {len(meta.constituents)} 只 · 板块指数多周期位置:")
    console.print()

    table = render_terminal.info_table(
        board_result, is_industry=True, board_meta=meta,
    )
    console.print(table)
    console.print(DISCLAIMER, style="dim")


def _info_theme(theme_query: str, fmt: export.OutputFormat) -> None:
    """kan info --theme · 题材档案 · 类似 _info_industry。"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan import render_terminal
        from kan._pipeline import resolve_targets_or_exit
        from kan.render_theme import render_theme_disclaimer
        from kan.scanner import scan_stock

    console = Console()
    _targets, meta = resolve_targets_or_exit(
        industry=None, only_watchlist=False, watchlist_pairs=[],
        theme=theme_query,
    )

    assert meta is not None
    if meta.index_kline.empty:
        _print_err("❌ 题材指数 K 线暂不可用 · 无法生成档案")
        raise typer.Exit(1)
    theme_result = scan_stock(meta.index_kline, meta.theme.code, meta.theme.name)

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.scan_payload(
                [theme_result], mode="low", data_cutoff=theme_result.scan_date,
                fetched_at=None, stale=False,
            )))
        else:
            typer.echo(export.scan_markdown(
                [theme_result], periods=[p.period for p in theme_result.periods],
                mode="low", title=f"慢慢看 · {meta.theme.name} 题材档案",
            ))
        return

    console.print(
        f"\n[bold]🎯 {meta.theme.name} · 同花顺概念 · {meta.theme.code}[/bold]"
    )
    console.print(f"  成分股 {len(meta.constituents)} 只 · 题材指数多周期位置:")
    console.print()

    table = render_terminal.info_table(
        theme_result, is_industry=True, board_meta=meta,
    )
    console.print(table)
    render_theme_disclaimer()


@app.command()
def info(
    symbol: Annotated[
        str | None,
        typer.Argument(help="股票代码（如 600519）", show_default=False),
    ] = None,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="查看某申万行业的板块档案"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="查看某题材的板块档案"),
    ] = None,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """单只股票详情（全周期位置 + 涨跌信息）"""
    if sum(1 for x in (industry, theme) if x is not None) > 1:
        _print_err("❌ --industry 与 --theme 不能同时使用")
        raise typer.Exit(2)
    if industry is not None:
        if symbol is not None:
            _print_err("❌ --industry 与股票代码不能同时使用")
            raise typer.Exit(2)
        _info_industry(industry, fmt)
        return
    if theme is not None:
        if symbol is not None:
            _print_err("❌ --theme 与股票代码不能同时使用")
            raise typer.Exit(2)
        _info_theme(theme, fmt)
        return
    # 跟 kan add 同款散户中文 · 兑现承诺到 info 命令
    if not symbol:
        typer.echo(
            "请告诉我看哪只股票 · 例: kan info 600519 (代码或名称都行)",
            err=True,
        )
        raise typer.Exit(2)

    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan import render_terminal
        from kan.fetcher import cache_age, data_cutoff_date, fetch_kline, get_cached, is_fresh
        from kan.render import DISCLAIMER
        from kan.scanner import calc_trend, calc_volume_state, scan_stock
        from kan.watchlist import _lookup_name, _normalize_symbol

    console = Console()

    try:
        symbol = _normalize_symbol(symbol)
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(1) from e

    try:
        name = _lookup_name(symbol)
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(1) from e

    if not is_fresh(symbol):
        try:
            with status_console.status(
                f"[yellow]⏳ 拉取数据... {name.replace(' ', '')} ({symbol})[/yellow]",
                spinner="dots",
            ):
                fetch_kline(symbol, force=True)
        except Exception as e:
            from rich.console import Console as _ErrConsole
            _ErrConsole(stderr=True).print(f"❌ 拉取失败：{_safe_error_msg(e)}")
            raise typer.Exit(1) from e

    df = get_cached(symbol)
    if df is None:
        _print_err("无数据")
        raise typer.Exit(1)

    result = scan_stock(df, symbol, name)
    trend_result = calc_trend(df, symbol, name)
    volume_state = calc_volume_state(df)
    name_short = name.replace(" ", "")

    # v0.0.4.5: 数据截止 / 拉取时间分离展示
    cutoff = data_cutoff_date(symbol)
    fetched_at = cache_age(symbol) or ""
    title = f"慢慢看 · {name_short} {symbol}"
    if cutoff:
        title += f" · 数据截止 {format_date_compact(cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"

    if fmt is not export.OutputFormat.terminal:
        from kan.trading_calendar import latest_trade_date
        is_stale = cutoff is None or cutoff < latest_trade_date()
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.info_payload(
                result, trend_result, volume=volume_state, data_cutoff=cutoff,
                fetched_at=fetched_at or None, stale=is_stale,
            )))
        else:
            typer.echo(export.info_markdown(
                result, trend_result, volume=volume_state, title=title,
            ))
        return

    # 基本信息
    tag = ""
    if result.is_st:
        tag = " [bold red]ST[/bold red]"
    if result.limit_up:
        tag += " [bold red]涨停[/bold red]"
    elif result.limit_down:
        tag += " [bold green]跌停[/bold green]"

    console.print(f"\n[bold]{title}[/bold]{tag}")
    # v0.0.4.4: 累计涨跌加 ▲/▼ 符号 + 红涨绿跌颜色 · 与 trend 命令详情列对齐
    # 修复 v0.0.4.3 用户报告："跌1天 · 累计 0.85%" 让人困惑（正数+负方向语义冲突）
    if trend_result.streak > 0:
        cum_str = f"[red]▲{abs(trend_result.streak_pct):.2f}%[/red]"
    elif trend_result.streak < 0:
        cum_str = f"[green]▼{abs(trend_result.streak_pct):.2f}%[/green]"
    else:
        cum_str = f"{abs(trend_result.streak_pct):.2f}%"
    console.print(f"  现价 {result.current_price:.2f} · {trend_result.direction} · 累计 {cum_str}")
    console.print()

    # 全周期位置表
    table = render_terminal.info_table(result, is_industry=False)
    console.print(table)
    console.print(f"\n  低点共振 ×{result.low_resonance} · 高点共振 ×{result.high_resonance}")
    if volume_state is not None:
        console.print(
            f"  成交量 · 今日是近 {volume_state.window} 日均量的 "
            f"{volume_state.ratio} 倍 · {volume_state.label}"
        )

    # kan info 加 stale/intraday 警告 · 与 scan/trend 一致
    # 单只详情诱导决策性比 scan 更强 · 缺警告是 dead-end 风险
    from kan.trading_calendar import PHASE_INTRADAY, latest_trade_date, market_phase
    expected_cutoff = latest_trade_date()
    is_stale = cutoff is None or cutoff < expected_cutoff
    phase = market_phase()
    if is_stale:
        cutoff_str = format_date_compact(cutoff) if cutoff else "无缓存"
        expected_str = format_date_compact(expected_cutoff)
        days_behind = (expected_cutoff - cutoff).days if cutoff else "?"
        console.print(
            f"\n  [bold yellow]⚠️ 当前缓存到 {cutoff_str} 收盘 · "
            f"最近交易日是 {expected_str} · 数据滞后 {days_behind} 天\n"
            "   运行 `kan fetch --force` 拉取最新数据[/bold yellow]"
        )
    elif phase == PHASE_INTRADAY:
        console.print(
            "\n  [bold yellow]⚠️ 当前盘中 · 涨跌停标签反映当前时刻 · 非收盘 final\n"
            "   (盘中价格仍在变动 · 涨停/跌停状态可能与收盘不同)\n"
            "   建议盘后 15:30 后看 final 数据[/bold yellow]"
        )

    console.print(DISCLAIMER, style="dim")

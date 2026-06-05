"""info · 单股 / 行业 / 题材 详情（全周期位置 + 涨跌信息）。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _print_err,
    _safe_error_msg,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)
from kan.storage import export

_MIN_BOARD_CONTEXT_SAMPLE = 3


def _build_board_position_context(result):
    """所属申万行业内的位置均值/排名 · 仅用本地 K 线缓存,失败时静默降级。"""
    try:
        from kan.core.models import BoardPositionContext, BoardPositionPeriod
        from kan.core.scanner import scan_stock
        from kan.data import boards
        from kan.data.fetcher import get_cached
        from kan.data.industry_map import fetch_sw_l1_map
        from kan.infra.log import debug_log

        target_periods = [p.period for p in result.periods if not p.insufficient]
        if not target_periods:
            return None

        industry = fetch_sw_l1_map().get(result.symbol)
        if not industry:
            return None

        board = boards.search_industry(industry)
        constituents = boards.get_industry_constituents(board)
        positions: dict[int, list[float]] = {p: [] for p in target_periods}
        seen_codes: set[str] = set()
        cached_codes: set[str] = set()

        for code, name in constituents:
            if code == result.symbol:
                peer = result
            else:
                df = get_cached(code)
                if df is None or df.empty:
                    continue
                try:
                    peer = scan_stock(df, code, name, periods=target_periods)
                except Exception as e:
                    debug_log(__name__, f"info board peer scan failed · {code}", e)
                    continue
            seen_codes.add(code)
            has_position = False
            for pr in peer.periods:
                if pr.insufficient or pr.period not in positions:
                    continue
                positions[pr.period].append(float(pr.position_pct))
                has_position = True
            if has_position:
                cached_codes.add(code)

        if result.symbol not in seen_codes:
            for pr in result.periods:
                if pr.insufficient or pr.period not in positions:
                    continue
                positions[pr.period].append(float(pr.position_pct))
                cached_codes.add(result.symbol)

        periods = []
        for pr in result.periods:
            if pr.insufficient:
                continue
            vals = positions.get(pr.period, [])
            if len(vals) < _MIN_BOARD_CONTEXT_SAMPLE:
                continue
            rank = 1 + sum(v < pr.position_pct for v in vals)
            periods.append(BoardPositionPeriod(
                period=pr.period,
                position_pct=round(float(pr.position_pct), 1),
                board_avg_pct=round(sum(vals) / len(vals), 1),
                rank_low_to_high=rank,
                sample=len(vals),
            ))

        if not periods:
            return None
        return BoardPositionContext(
            industry=industry,
            board_code=getattr(board, "code", None),
            board_level=getattr(board, "level", None),
            constituent_count=len(constituents),
            cached_sample=len(cached_codes),
            periods=periods,
        )
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, f"info board context failed · {result.symbol}", e)
        return None


def _info_industry(industry: str, fmt: export.OutputFormat) -> None:
    """kan info --industry · 簡版板块档案。"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.pipeline import resolve_stock_set_or_exit
        from kan.core.scanner import scan_stock
        from kan.core.stock_set import from_flags
        from kan.render import terminal
        from kan.render.base import DISCLAIMER

    console = Console()
    # OOP 路径
    _targets, meta = resolve_stock_set_or_exit(from_flags(industry=industry))

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

    table = terminal.info_table(
        board_result, is_industry=True, board_meta=meta,
    )
    console.print(table)
    console.print(DISCLAIMER, style="dim")


def _info_theme(theme_query: str, fmt: export.OutputFormat) -> None:
    """kan info --theme · 题材档案 · 类似 _info_industry。"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.pipeline import resolve_stock_set_or_exit
        from kan.core.scanner import scan_stock
        from kan.core.stock_set import from_flags
        from kan.render import terminal
        from kan.render.theme import render_theme_disclaimer

    console = Console()
    # OOP 路径
    _targets, meta = resolve_stock_set_or_exit(from_flags(theme=theme_query))

    assert meta is not None
    if meta.index_kline.empty:
        _print_err(
            "❌ 题材指数 K 线暂不可用 · 无法生成档案\n"
            f"   替代:`kan scan --theme={theme_query}` 看成分股(不依赖指数)\n"
            "   或 `kan info --industry <行业名>` 看相近行业档案"
        )
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

    table = terminal.info_table(
        theme_result, is_industry=True, board_meta=meta,
    )
    console.print(table)
    render_theme_disclaimer()


@app.command()
def info(
    symbol: Annotated[
        str | None,
        typer.Argument(help="股票代码或名称（如 600519 / 茅台）", show_default=False),
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
    """单只股票详情（全周期位置 + 所属行业位置对照 + 涨跌信息）。

    成交量 5 档对称 label(对比 5 日均量):
      明显放大 ≥2.0x · 温和放大 1.5-2.0x · 量能平稳 0.67-1.5x
      温和萎缩 0.5-0.67x · 明显萎缩 <0.5x
    """
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
        from kan.core.scanner import calc_trend, calc_volume_state, scan_stock
        from kan.data.fetcher import cache_age, data_cutoff_date, fetch_kline, get_cached, is_fresh
        from kan.render import terminal
        from kan.render.base import DISCLAIMER
        from kan.storage.watchlist import resolve_symbol_or_name

    console = Console()

    try:
        symbol, name = resolve_symbol_or_name(symbol)
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
    moneyflow = None
    sentiment = None
    valuation = None
    try:
        from kan.core.enrich import enrich_results

        enriched = enrich_results([result], need_moneyflow=True, need_sentiment=True)[0]
        moneyflow = enriched.moneyflow
        sentiment = enriched.sentiment
        valuation = enriched.valuation
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, f"info enrich failed · {symbol}", e)
    name_short = name.replace(" ", "")

    # 背景: 数据截止 / 拉取时间分离展示
    cutoff = data_cutoff_date(symbol)
    fetched_at = cache_age(symbol) or ""
    title = f"慢慢看 · {name_short} {symbol}"
    if cutoff:
        title += f" · 数据截止 {format_date_compact(cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    board_context = _build_board_position_context(result)

    if fmt is not export.OutputFormat.terminal:
        from kan.core.trading_calendar import latest_trade_date
        is_stale = cutoff is None or cutoff < latest_trade_date()
        if fmt is export.OutputFormat.json:
            # AI JSON 层:enrich 截面市场指标 · 全市场截面层:估值位置对照 (历史分位+行业中位)
            # 无 token → 均 None · 优雅降级 (info 仍出位置/涨跌/量能)
            from kan.core.valuation_context import build_valuation_context
            valuation_context = build_valuation_context(symbol)
            typer.echo(export.to_json(export.info_payload(
                result, trend_result, volume=volume_state, data_cutoff=cutoff,
                fetched_at=fetched_at or None, stale=is_stale,
                valuation=valuation, valuation_context=valuation_context,
                moneyflow=moneyflow, sentiment=sentiment, board_context=board_context,
            )))
        else:
            typer.echo(export.info_markdown(
                result, trend_result, volume=volume_state, title=title,
                moneyflow=moneyflow, sentiment=sentiment, board_context=board_context,
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
    # 背景: 累计涨跌加 ▲/▼ 符号 + 红涨绿跌颜色 · 与 trend 命令详情列对齐
    # 修复 早期用户报告："跌1天 · 累计 0.85%" 让人困惑（正数+负方向语义冲突）
    if trend_result.streak > 0:
        cum_str = f"[red]▲{abs(trend_result.streak_pct):.2f}%[/red]"
    elif trend_result.streak < 0:
        cum_str = f"[green]▼{abs(trend_result.streak_pct):.2f}%[/green]"
    else:
        cum_str = f"{abs(trend_result.streak_pct):.2f}%"
    console.print(f"  现价 {result.current_price:.2f} · {trend_result.direction} · 累计 {cum_str}")
    console.print()

    # 全周期位置表
    table = terminal.info_table(result, is_industry=False)
    console.print(table)
    if board_context is not None:
        console.print()
        console.print(
            f"  板块对比 · 申万一级 {board_context.industry} · "
            f"本地样本 {board_context.cached_sample}/{board_context.constituent_count}"
        )
        console.print(terminal.board_position_table(board_context))
    console.print(f"\n  低点共振 ×{result.low_resonance} · 高点共振 ×{result.high_resonance}")
    if volume_state is not None:
        console.print(
            f"  成交量 · 今日是近 {volume_state.window} 日均量的 "
            f"{volume_state.ratio} 倍 · {volume_state.label}"
        )
    if moneyflow is not None and (
        moneyflow.net_amount is not None
        or moneyflow.buy_elg_amount is not None
        or moneyflow.buy_lg_amount is not None
        or moneyflow.net_amount_5d is not None
    ):
        def _fmt(value: float | None, digits: int = 0) -> str:
            return "-" if value is None else f"{value:.{digits}f}"

        console.print(
            "  资金流 · "
            f"今日主力 {_fmt(moneyflow.net_amount)} 万元 · "
            f"超大单 {_fmt(moneyflow.buy_elg_amount)} 万元 · "
            f"大单 {_fmt(moneyflow.buy_lg_amount)} 万元 · "
            f"连续净流入 {moneyflow.inflow_days if moneyflow.inflow_days is not None else '-'} 天 · "
            f"5日合计 {_fmt(moneyflow.net_amount_5d)} 万元"
        )
    if sentiment is not None and (
        sentiment.first_time is not None
        or sentiment.last_time is not None
        or sentiment.open_times is not None
        or sentiment.fd_amount is not None
    ):
        def _fmt_detail(value: float | None, digits: int = 0) -> str:
            return "-" if value is None else f"{value:.{digits}f}"

        console.print(
            "  涨跌停详情 · "
            f"首次封板 {sentiment.first_time or '-'} · "
            f"最后封板 {sentiment.last_time or '-'} · "
            f"开板次数 {_fmt_detail(sentiment.open_times)} · "
            f"封单金额 {_fmt_detail(sentiment.fd_amount)}"
        )

    # kan info 加 stale/intraday 警告 · 与 scan/trend 一致
    # 单只详情诱导决策性比 scan 更强 · 缺警告是 dead-end 风险
    from kan.core.trading_calendar import PHASE_INTRADAY, latest_trade_date, market_phase
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

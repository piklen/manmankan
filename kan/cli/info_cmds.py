"""info · 单股 / 行业 / 题材 详情（全周期位置 + 涨跌信息）。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _print_err,
    _safe_error_msg,
    format_date_compact,
    format_fetched_at_compact,
)
from kan.storage import export


def _info_industry(industry: str, fmt: export.OutputFormat) -> None:
    """kan info --industry · 簡版板块档案。"""
    from rich.console import Console

    from kan.core.pipeline import resolve_stock_set_or_exit
    from kan.core.scanner import scan_stock
    from kan.core.stock_set import from_flags
    from kan.render import terminal
    from kan.render.base import DISCLAIMER

    console = Console()
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

    from kan.core.pipeline import resolve_stock_set_or_exit
    from kan.core.scanner import scan_stock
    from kan.core.stock_set import from_flags
    from kan.render import terminal
    from kan.render.theme import render_theme_disclaimer

    console = Console()
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

    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter
    from kan.render import terminal
    from kan.render.base import DISCLAIMER
    from kan.service.info_service import (
        InfoDataUnavailableError,
        InfoFetchError,
        InfoRequest,
        get_stock_info,
    )

    console = Console()
    reporter = operation_reporter()

    def _render() -> None:
        pass

    try:
        with operation("股票详情", reporter=reporter) as lifecycle:
            lifecycle.phase("拉取数据")
            try:
                info_result = get_stock_info(InfoRequest(
                    symbol_or_name=symbol,
                    include_valuation_context=fmt is export.OutputFormat.json,
                    fetch_status=None,
                ))
            except ValueError as e:
                if fmt is export.OutputFormat.json:
                    typer.echo(export.to_json(export.error_payload(
                        "info",
                        code="not_found",
                        message=str(e),
                        hint="例: kan info 600519",
                    )))
                else:
                    _print_err(f"❌ {e}")
                raise typer.Exit(1) from e
            except InfoFetchError as e:
                if fmt is export.OutputFormat.json:
                    typer.echo(export.to_json(export.error_payload(
                        "info",
                        code="fetch_error",
                        message=f"拉取失败：{_safe_error_msg(e.cause)}",
                        hint="例: kan fetch --force",
                    )))
                else:
                    Console(stderr=True).print(
                        f"❌ 拉取失败：{_safe_error_msg(e.cause)}"
                    )
                raise typer.Exit(1) from e
            except InfoDataUnavailableError as e:
                if fmt is export.OutputFormat.json:
                    typer.echo(export.to_json(export.error_payload(
                        "info",
                        code="data_unavailable",
                        message="无数据",
                        hint="例: kan fetch --force",
                    )))
                else:
                    _print_err("无数据")
                raise typer.Exit(1) from e

            lifecycle.phase("准备输出")
            symbol = info_result.symbol
            name = info_result.name
            result = info_result.result
            trend_result = info_result.trend
            volume_state = info_result.volume
            moneyflow = info_result.moneyflow
            sentiment = info_result.sentiment
            valuation = info_result.valuation
            board_context = info_result.board_context
            name_short = name.replace(" ", "")

            cutoff = info_result.data_cutoff
            fetched_at = info_result.fetched_at or ""
            title = f"慢慢看 · {name_short} {symbol}"
            if cutoff:
                title += f" · 数据截止 {format_date_compact(cutoff)} 收盘"
            if fetched_at:
                title += f" · {format_fetched_at_compact(fetched_at)} 拉取"

            if fmt is not export.OutputFormat.terminal:
                if fmt is export.OutputFormat.json:
                    json_str = export.to_json(export.info_payload(
                        result, trend_result, volume=volume_state,
                        data_cutoff=cutoff, fetched_at=info_result.fetched_at,
                        stale=info_result.stale, valuation=valuation,
                        valuation_context=info_result.valuation_context,
                        moneyflow=moneyflow, sentiment=sentiment,
                        board_context=board_context,
                    ))
                    def _render_json() -> None:
                        typer.echo(json_str)
                    _render = _render_json
                elif fmt is export.OutputFormat.csv:
                    csv_str = export.info_csv(
                        result, trend_result, volume=volume_state,
                        moneyflow=moneyflow,
                    )
                    def _render_csv() -> None:
                        typer.echo(csv_str)
                    _render = _render_csv
                else:
                    md_str = export.info_markdown(
                        result, trend_result, volume=volume_state, title=title,
                        moneyflow=moneyflow, sentiment=sentiment,
                        board_context=board_context,
                    )
                    def _render_md() -> None:
                        typer.echo(md_str)
                    _render = _render_md
            else:
                # terminal 渲染 —— 在 lifecycle 内准备，context 外输出
                tag = ""
                if result.is_st:
                    tag = " [bold red]ST[/bold red]"
                if result.limit_up:
                    tag += " [bold red]涨停[/bold red]"
                elif result.limit_down:
                    tag += " [bold green]跌停[/bold green]"

                if trend_result.streak > 0:
                    cum_str = f"[red]▲{abs(trend_result.streak_pct):.2f}%[/red]"
                elif trend_result.streak < 0:
                    cum_str = f"[green]▼{abs(trend_result.streak_pct):.2f}%[/green]"
                else:
                    cum_str = f"{abs(trend_result.streak_pct):.2f}%"

                lot = f"{result.lot_cost:,.0f}" if result.lot_cost is not None else "-"
                cash_pct = (
                    f"{result.cash_usage_pct:.1f}%"
                    if result.cash_usage_pct is not None else "-"
                )
                perm = result.permission_note or result.market_board or "-"

                table = terminal.info_table(result, is_industry=False)
                board_table = (
                    terminal.board_position_table(board_context)
                    if board_context is not None else None
                )

                from kan.core.trading_calendar import (
                    PHASE_INTRADAY,
                    latest_trade_date,
                    market_phase,
                )
                expected_cutoff = latest_trade_date()
                is_stale = cutoff is None or cutoff < expected_cutoff
                phase = market_phase()

                def _render_terminal() -> None:
                    console.print(f"\n[bold]{title}[/bold]{tag}")
                    console.print(
                        f"  现价 {result.current_price:.2f} · "
                        f"{trend_result.direction} · 累计 {cum_str}"
                    )
                    console.print(
                        f"  1手 {lot} 元 · 占现金 {cash_pct} · 权限 {perm}"
                    )
                    console.print()

                    console.print(table)
                    if board_context is not None:
                        console.print()
                        console.print(
                            f"  板块对比 · 申万一级 {board_context.industry} · "
                            f"本地样本 {board_context.cached_sample}/"
                            f"{board_context.constituent_count}"
                        )
                        console.print(board_table)
                    console.print(
                        f"\n  低点共振 ×{result.low_resonance} · "
                        f"高点共振 ×{result.high_resonance}"
                    )
                    if volume_state is not None:
                        suffix = (
                            f" · {volume_state.state}"
                            if volume_state.state else ""
                        )
                        console.print(
                            f"  成交量 · 今日是近 {volume_state.window} 日均量的 "
                            f"{volume_state.ratio} 倍 · "
                            f"{volume_state.label}{suffix}"
                        )
                    if moneyflow is not None and (
                        moneyflow.net_amount is not None
                        or moneyflow.buy_elg_amount is not None
                        or moneyflow.buy_lg_amount is not None
                        or moneyflow.net_amount_5d is not None
                    ):
                        def _fmt_mf(value: float | None, digits: int = 0) -> str:
                            return "-" if value is None else f"{value:.{digits}f}"
                        console.print(
                            "  资金流 · "
                            f"今日主力 {_fmt_mf(moneyflow.net_amount)} 万元 · "
                            f"超大单 {_fmt_mf(moneyflow.buy_elg_amount)} 万元 · "
                            f"大单 {_fmt_mf(moneyflow.buy_lg_amount)} 万元 · "
                            f"连续净流入 "
                            f"{moneyflow.inflow_days if moneyflow.inflow_days is not None else '-'} 天 · "
                            f"5日合计 {_fmt_mf(moneyflow.net_amount_5d)} 万元"
                        )
                    if sentiment is not None and (
                        sentiment.first_time is not None
                        or sentiment.last_time is not None
                        or sentiment.open_times is not None
                        or sentiment.fd_amount is not None
                    ):
                        def _fmt_sdetail(value: float | None, digits: int = 0) -> str:
                            return "-" if value is None else f"{value:.{digits}f}"
                        console.print(
                            "  涨跌停详情 · "
                            f"首次封板 {sentiment.first_time or '-'} · "
                            f"最后封板 {sentiment.last_time or '-'} · "
                            f"开板次数 {_fmt_sdetail(sentiment.open_times)} · "
                            f"封单金额 {_fmt_sdetail(sentiment.fd_amount)}"
                        )
                    if is_stale:
                        cutoff_str = (
                            format_date_compact(cutoff) if cutoff else "无缓存"
                        )
                        expected_str = format_date_compact(expected_cutoff)
                        days_behind = (
                            (expected_cutoff - cutoff).days if cutoff else "?"
                        )
                        console.print(
                            f"\n  [bold yellow]⚠️ 当前缓存到 {cutoff_str} 收盘 · "
                            f"最近交易日是 {expected_str} · "
                            f"数据滞后 {days_behind} 天\n"
                            "   运行 `kan fetch --force` 拉取最新数据[/bold yellow]"
                        )
                    elif phase == PHASE_INTRADAY:
                        console.print(
                            "\n  [bold yellow]⚠️ 当前盘中 · 涨跌停标签反映当前时刻"
                            " · 非收盘 final\n"
                            "   (盘中价格仍在变动 · 涨停/跌停状态可能与收盘不同)\n"
                            "   建议盘后 15:30 后看 final 数据[/bold yellow]"
                        )
                    console.print(DISCLAIMER, style="dim")

                _render = _render_terminal

    except typer.Exit:
        raise

    _render()

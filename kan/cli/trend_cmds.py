"""连续涨跌看板命令：trend。

单独一个文件因为命令逻辑独立（不跟 scan/low/high 共享代码 · 用单独的 trend_batch
算法 + 自己的日期列头逻辑），且日后可能加入更多 trend 衍生命令（如 trend backtest 等）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
)
from kan.data.hot import HotList
from kan.storage import export

if TYPE_CHECKING:
    from kan.core.pipeline import DataCtx
    from kan.infra.lifecycle import OperationLifecycle


def _finish_trend(
    ctx: DataCtx,
    *,
    all_stocks: bool,
    down: int | None,
    up: int | None,
    candle: bool,
    fmt: export.OutputFormat,
    latest: int | None,
    lifecycle: OperationLifecycle | None = None,
) -> Callable[[], None]:
    """完成过滤与输出构造，返回 lifecycle 关闭后执行的渲染函数。"""
    from rich.console import Console

    from kan.core.models import HotMeta, ThemeMeta
    from kan.core.pipeline import render_freshness_warning
    from kan.render import terminal
    from kan.render.base import DISCLAIMER, max_trend_dates

    console = Console()
    results = ctx.results
    board_meta = ctx.meta
    if not ctx.targets and all_stocks:
        _print_err("❌ 全市场股票池为空\n   例: kan config set tushare-token <YOUR_TOKEN>；或稍后重试")
        raise typer.Exit(1)
    if not results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    if lifecycle is not None:
        lifecycle.phase("过滤连续涨跌结果", result_count=len(results))
    filter_label = ""
    if down is not None:
        results = [result for result in results if result.streak <= -down]
        filter_label = f" · 连跌≥{down}天"
    elif up is not None:
        results = [result for result in results if result.streak >= up]
        filter_label = f" · 连涨≥{up}天"

    if not results and fmt is export.OutputFormat.terminal and (down is not None or up is not None):
        threshold = down if down is not None else up
        direction = "跌" if down is not None else "涨"
        message = f"没有连续{direction} ≥{threshold} 天的股票"
        return lambda: console.print(message)

    if lifecycle is not None:
        lifecycle.phase("构造趋势输出", result_count=len(results), format=fmt.value)
    title = terminal.trend_title(ctx, candle=candle, filter_label=filter_label)
    data_cutoff = ctx.freshness.data_cutoff
    fetched_at = ctx.freshness.fetched_at
    is_stale = ctx.freshness.is_stale

    if fmt is export.OutputFormat.json:
        payload = export.to_json(export.trend_payload(
            results,
            candle=candle,
            data_cutoff=data_cutoff,
            fetched_at=fetched_at,
            stale=is_stale,
        ))
        return lambda: typer.echo(payload)
    if fmt is export.OutputFormat.csv:
        csv_output = export.trend_csv(results, latest=latest)
        return lambda: typer.echo(csv_output)
    if fmt is export.OutputFormat.md:
        markdown = export.trend_markdown(results, title=title, latest=latest)
        return lambda: typer.echo(markdown)

    actual_latest = min(latest, max_trend_dates(console.width)) if latest and results else None
    table = terminal.trend_table(
        ctx,
        results,
        latest=actual_latest,
        candle=candle,
        filter_label=filter_label,
    )
    def render_terminal() -> None:
        console.print(table)
        if latest and actual_latest is not None and actual_latest < latest:
            console.print(
                f"\n  [dim]窄屏模式 · 显示近 {actual_latest}/{latest} 天"
                " · 加宽终端可见全部[/dim]"
            )
        render_freshness_warning(
            ctx.freshness,
            console,
            refresh_hint=("kan trend --all --force" if all_stocks else "kan fetch --force"),
        )
        console.print()
        if candle:
            console.print("[dim]  阳线阴线口径：收盘 > 开盘 = ▲ · 收盘 < 开盘 = ▼ · 平盘不断连续[/dim]")
        else:
            console.print("[dim]  收盘价口径：今日收盘 > 昨日收盘 = ▲ · 今日收盘 < 昨日收盘 = ▼ · 平盘不断连续[/dim]")
        if isinstance(board_meta, HotMeta):
            console.print(
                "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单\n"
                "  💡 涨停 / 大幅上涨个股天然在区间高位 · [100%] 是数学结果 不是 「过热信号」[/dim]"
            )
        if isinstance(board_meta, ThemeMeta):
            from kan.render.theme import render_theme_disclaimer

            render_theme_disclaimer()
        else:
            console.print(DISCLAIMER, style="dim")

    return render_terminal


@app.command()
def trend(
    extra_args: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="[...]",
            show_default=False,
            help="(内部:防 trend 600519 dead-end · 引导到 kan info · 不该传)",
        ),
    ] = None,
    latest: Annotated[int | None, typer.Option("--latest", "-l", help="展示近 N 天走势详情（1-180）", min=1, max=180)] = None,
    down: Annotated[int | None, typer.Option("--down", help="只看连跌≥N天（不带 N 默认 3）")] = None,
    up: Annotated[int | None, typer.Option("--up", help="只看连涨≥N天（不带 N 默认 3）")] = None,
    candle: Annotated[bool, typer.Option("--candle", "-c", help="阳线阴线口径（默认收盘价口径）")] = False,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="扫指定申万行业全部成分股 · 自选股 ⭐ 高亮"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="扫东财热榜 · rank=人气榜 / surge=飙升榜 · 自选股 ⭐ 高亮"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="扫指定题材全成分股 · 自选 ⭐ 高亮"),
    ] = None,
    all_stocks: Annotated[
        bool,
        typer.Option("--all", help="扫描 A 股全市场连续涨跌（约 5500 只；首次会补每日截面缓存）"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="强制重拉每日截面缓存（仅与 --all 配合）"),
    ] = False,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜/题材(需配合 --industry / --hot / --theme)"),
    ] = False,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="选自选股分组 (默认 default 组)"),
    ] = None,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """连续涨跌看板 (--group 切换分组)"""
    # 处理 trend <ticker> 误用 · 散户最直觉的"看茅台趋势 kan trend 600519"会进 extra_args
    # 引导到 `kan info <ticker>` · 接口未来计划改为收 ticker
    if extra_args:
        first = extra_args[0]
        if first.lower() == "all" or first == "全市场":
            _print_err("💡 全市场趋势用 `kan trend --all` · 可叠加 --down / --up / --latest")
            raise typer.Exit(2)
        # 判断:6 位数字 → 像股票代码 · isalpha 含非 ASCII(中文) / ASCII(英文)→ 像股票名
        # 用 .isdigit / .isalpha / .isascii 避开 unicode 字符范围正则
        looks_like_code = first.isdigit() and len(first) == 6
        looks_like_name = first.isalpha()  # 中文 / 英文都返 True
        if looks_like_code or looks_like_name:
            _print_err(
                f"💡 看单只趋势用 `kan info {first}` · "
                f"`kan trend` 是看全板涨跌(无 ticker 参数 · 用 --down / --up / --latest)"
            )
        else:
            _print_err(f"❌ 不识别的参数: {first}")
        raise typer.Exit(2)

    from kan.infra.progress import feedback_console, operation_reporter

    status_console = feedback_console()
    from kan.core.scanner import trend_batch

    pool_count = sum(1 for x in (industry, hot, theme) if x is not None) + int(all_stocks)
    if pool_count > 1:
        _print_err("❌ --industry / --hot / --theme / --all 互斥 · 同时只能用一个")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None or all_stocks
    if all_stocks and only_watchlist:
        _print_err(
            "❌ --all 与 --only-watchlist 不能同时使用\n"
            "   例: kan trend --all"
        )
        raise typer.Exit(2)
    if all_stocks and group is not None:
        _print_err(
            "❌ --all 已指定全市场池，不再叠加 --group\n"
            "   例: kan trend --all；或 kan trend --group <组名>"
        )
        raise typer.Exit(2)
    if force and not all_stocks:
        _print_err("❌ --force 目前仅用于 `kan trend --all --force`")
        raise typer.Exit(2)
    watchlist_pairs = (
        [] if all_stocks else (
            _load_watchlist_pairs(group) if source_mode else _get_watchlist_pairs(group)
        )
    )
    if only_watchlist and not source_mode:
        _print_err(
            "❌ --only-watchlist 需配合 --industry / --hot / --theme 使用\n"
            "   例: kan trend --industry 半导体 --only-watchlist"
        )
        raise typer.Exit(1)
    # fail-fast:参数校验前置 · 不让 invalid args 触发网络 fetch
    if down is not None and up is not None:
        _print_err("❌ --down 和 --up 不能同时使用")
        raise typer.Exit(1)
    for name, val in [("--down", down), ("--up", up)]:
        if val is not None and not (2 <= val <= 30):
            _print_err(f"❌ {name} 的值必须在 2-30 之间（当前：{val}）")
            raise typer.Exit(1)

    # OOP 路径
    from kan.core.pipeline import DataCtx, resolve_stock_set_or_exit, run_data_pipeline
    from kan.core.stock_set import from_flags
    stock_set = from_flags(
        industry=industry, hot=hot, theme=theme,
        watchlist_pairs=watchlist_pairs,
        only_watchlist=only_watchlist,
        watchlist_group=group,
        all_stocks=all_stocks,
        all_stocks_force=force,
    )

    if all_stocks:
        from kan.core.scanner_trend import TREND_STREAK_CAP, trend_batch_cross_section
        from kan.data.kline_snapshot import daily_panel_freshness, fetch_recent_daily_bars
        from kan.data.tushare import TushareDataContractError
        from kan.infra.lifecycle import operation

        reporter = operation_reporter(console=status_console)
        with operation("全市场连续涨跌", reporter=reporter) as lifecycle:
            lifecycle.phase("解析全市场股票池")
            targets, board_meta = resolve_stock_set_or_exit(stock_set)
            if not targets:
                _print_err(
                    "❌ 全市场股票池为空\n"
                    "   例: kan config set tushare-token <YOUR_TOKEN>；或稍后重试"
                )
                raise typer.Exit(1)

            symbols = [symbol for symbol, _name in targets]
            days = TREND_STREAK_CAP + 1
            lifecycle.phase("获取全市场日线截面", target_count=len(symbols), days=days)

            def _legacy_daily_progress(
                done: int,
                total: int,
                trade_day: object,
                row_count: int,
            ) -> None:
                del done, total, trade_day, row_count

            try:
                panel = fetch_recent_daily_bars(
                    days,
                    symbols=symbols,
                    force=force,
                    lifecycle=lifecycle,
                    on_progress=_legacy_daily_progress,
                )
            except TushareDataContractError as e:
                lifecycle.fail(
                    "全市场数据契约校验失败",
                    api_name=e.api_name,
                )
                _print_err(
                    f"❌ 全市场数据不完整：{e}\n"
                    "   manmankan 已按 Tushare 官方请求语义停止处理，且未写入错误缓存\n"
                    "   请检查当前配置的数据源是否完整兼容对应 Tushare 接口"
                )
                raise typer.Exit(1) from None
            lifecycle.phase("计算全市场连续涨跌", target_count=len(symbols))
            results = trend_batch_cross_section(
                targets,
                candle=candle,
                panel=panel,
                lifecycle=lifecycle,
            )
            lifecycle.phase("计算日线截面新鲜度")
            freshness = daily_panel_freshness(
                panel,
                symbols=symbols,
                required_rows=days,
            )
            ctx = DataCtx(
                targets=targets,
                meta=board_meta,
                results=results,
                freshness=freshness,
                source_name=getattr(stock_set, "name", ""),
            )
            render_output = _finish_trend(
                ctx,
                all_stocks=True,
                down=down,
                up=up,
                candle=candle,
                fmt=fmt,
                latest=latest,
                lifecycle=lifecycle,
            )
        render_output()
        return

    # 非 --all:走逐股 K 线管线(自选股/行业/热榜/题材 · 通常 < 数百只 · 逐股 fetch 可接受)
    ctx = run_data_pipeline(stock_set, compute=trend_batch, candle=candle)

    render_output = _finish_trend(
        ctx,
        all_stocks=False,
        down=down,
        up=up,
        candle=candle,
        fmt=fmt,
        latest=latest,
    )
    render_output()

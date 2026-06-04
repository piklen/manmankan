"""连续涨跌看板命令：trend。

单独一个文件因为命令逻辑独立（不跟 scan/low/high 共享代码 · 用单独的 trend_batch
算法 + 自己的日期列头逻辑），且日后可能加入更多 trend 衍生命令（如 trend backtest 等）。
"""
from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _auto_fetch_stale,  # noqa: F401 · 保留兼容测试 monkeypatch · 实际调用由 pipeline.run_data_pipeline 内部完成
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _with_heavy_imports_spinner,
)
from kan.data.hot import HotList
from kan.storage import export


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
    # 引导到 `kan info <ticker>` · 接口升级到收 ticker 是 历史背景计划
    if extra_args:
        first = extra_args[0]
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

    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.pipeline import render_freshness_warning
        from kan.core.scanner import trend_batch
        from kan.render import terminal
        from kan.render.base import DISCLAIMER, max_trend_dates

    console = Console()
    if sum(1 for x in (industry, hot, theme) if x is not None) > 1:
        _print_err("❌ --industry / --hot / --theme 三者互斥 · 同时只能用一个")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None
    watchlist_pairs = (
        _load_watchlist_pairs(group) if source_mode else _get_watchlist_pairs(group)
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry / --hot / --theme 使用")
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
    from kan.core.models import ThemeMeta
    from kan.core.pipeline import run_data_pipeline
    from kan.core.stock_set import from_flags
    stock_set = from_flags(
        industry=industry, hot=hot, theme=theme,
        watchlist_pairs=watchlist_pairs,
        only_watchlist=only_watchlist,
        watchlist_group=group,
    )
    ctx = run_data_pipeline(stock_set, compute=trend_batch, candle=candle)
    results = ctx.results
    board_meta = ctx.meta
    data_cutoff = ctx.freshness.data_cutoff
    fetched_at = ctx.freshness.fetched_at
    is_stale = ctx.freshness.is_stale  # JSON/MD payload 仍引用
    freshness = ctx.freshness  # 给 render_freshness_warning 用

    if not results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    # 筛选连续涨/跌
    filter_label = ""
    if down is not None:
        results = [r for r in results if r.streak <= -down]
        filter_label = f" · 连跌≥{down}天"
        if not results and fmt is export.OutputFormat.terminal:
            console.print(f"没有连续跌 ≥{down} 天的股票")
            return
    elif up is not None:
        results = [r for r in results if r.streak >= up]
        filter_label = f" · 连涨≥{up}天"
        if not results and fmt is export.OutputFormat.terminal:
            console.print(f"没有连续涨 ≥{up} 天的股票")
            return

    title = terminal.trend_title(
        ctx, candle=candle, filter_label=filter_label,
    )

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.trend_payload(
                results, candle=candle, data_cutoff=data_cutoff,
                fetched_at=fetched_at, stale=is_stale,
            )))
        else:
            typer.echo(export.trend_markdown(results, title=title, latest=latest))
        return

    from kan.core.models import HotMeta
    is_hot = isinstance(board_meta, HotMeta)

    actual_latest: int | None = None
    if latest and results:
        actual_latest = min(latest, max_trend_dates(console.width))

    table = terminal.trend_table(
        ctx, results,
        latest=actual_latest, candle=candle, filter_label=filter_label,
    )
    console.print(table)

    if latest and actual_latest is not None and actual_latest < latest:
        console.print(
            f"\n  [dim]窄屏模式 · 显示近 {actual_latest}/{latest} 天"
            " · 加宽终端可见全部[/dim]"
        )

    render_freshness_warning(freshness, console)

    console.print()
    if candle:
        console.print("[dim]  阳线阴线口径：收盘 > 开盘 = ▲ · 收盘 < 开盘 = ▼ · 平盘不断连续[/dim]")
    else:
        console.print("[dim]  收盘价口径：今日收盘 > 昨日收盘 = ▲ · 今日收盘 < 昨日收盘 = ▼ · 平盘不断连续[/dim]")
    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单\n  💡 涨停 / 大幅上涨个股天然在区间高位 · [100%] 是数学结果 不是 「过热信号」[/dim]"
        )
    if isinstance(board_meta, ThemeMeta):
        from kan.render.theme import render_theme_disclaimer
        render_theme_disclaimer()
    else:
        console.print(DISCLAIMER, style="dim")

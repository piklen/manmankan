"""scan · 自选股多周期位置扫描（10 周期全景 · --diff / --signal / --exclude-st）。

本版后此文件只装 scan 命令本身;fetch / low / high / info / compare 各自拆到
cli_fetch_cmds / cli_extreme_cmds / cli_info_cmds / cli_compare_cmds。
"""
from __future__ import annotations

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
def scan(
    high: Annotated[bool, typer.Option("--high", help="高点模式（默认低点模式）")] = False,
    signal: Annotated[bool, typer.Option("--signal", "-S", "-s", help="仅显示有共振信号的股票")] = False,
    diff: Annotated[bool, typer.Option("--diff", "-d", help="增量模式：显示与上次扫描的变化")] = False,
    exclude_st: Annotated[bool, typer.Option("--exclude-st", help="排除 ST/*ST 股票")] = False,
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
        typer.Option("--theme", help="扫指定题材全成分股 · 自选 ⭐ 高亮 · 题材 ≠ 行业,一股归多个"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜/题材(需配合 --industry / --hot / --theme)"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """扫描自选股多周期位置（10 周期全景模式）"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.pipeline import render_freshness_warning
        from kan.core.scanner import (
            PERIODS,
            compute_diff,
            load_snapshot,
            save_snapshot,
            scan_batch,
        )
        from kan.render import terminal
        from kan.render.base import DISCLAIMER, responsive_periods

    console = Console()
    if sum(1 for x in (industry, hot, theme) if x is not None) > 1:
        _print_err("❌ --industry / --hot / --theme 三者互斥 · 同时只能用一个")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None
    watchlist_pairs = (
        _load_watchlist_pairs() if source_mode else _get_watchlist_pairs()
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry / --hot / --theme 使用")
        raise typer.Exit(1)
    # v0.0.5.3 OOP 路径:CLI 构造 StockSet 再喂 pipeline · meta/highlight/filter 全部由 Set 承担
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.core.pipeline import run_data_pipeline
    from kan.core.stock_set import from_flags
    mode = "high" if high else "low"
    stock_set = from_flags(
        industry=industry, hot=hot, theme=theme,
        watchlist_pairs=watchlist_pairs,
        only_watchlist=only_watchlist,
    )
    ctx = run_data_pipeline(stock_set, compute=scan_batch, mode=mode)
    all_results = ctx.results
    board_meta = ctx.meta
    data_cutoff = ctx.freshness.data_cutoff
    fetched_at = ctx.freshness.fetched_at
    is_stale = ctx.freshness.is_stale  # JSON/MD payload + --diff 分支仍引用
    freshness = ctx.freshness  # 给 render_freshness_warning 用

    prev_snapshot = load_snapshot() if (diff and board_meta is None) else None

    board_index_result = None
    if isinstance(board_meta, BoardMeta):
        from kan.core.scanner import scan_stock
        board_index_result = scan_stock(
            board_meta.index_kline, board_meta.board.code, board_meta.board.name,
        )
    elif isinstance(board_meta, ThemeMeta) and not board_meta.index_kline.empty:
        from kan.core.scanner import scan_stock
        board_index_result = scan_stock(
            board_meta.index_kline, board_meta.theme.code, board_meta.theme.name,
        )

    if not all_results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    results = all_results
    if exclude_st:
        results = [r for r in results if not r.is_st]

    if signal:
        if mode == "high":
            results = [r for r in results if r.high_resonance > 0]
        else:
            results = [r for r in results if r.low_resonance > 0]
        if not results and fmt is export.OutputFormat.terminal:
            console.print("没有股票触及极值区 · 无共振信号")
            if board_meta is None:
                save_snapshot(all_results)
            return

    title = terminal.scan_title(ctx, high_mode=high, signal_only=signal)

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.scan_payload(
            results, mode=mode, data_cutoff=data_cutoff,
            fetched_at=fetched_at, stale=is_stale,
        )))
        if board_meta is None:
            save_snapshot(all_results)
        return
    if fmt is export.OutputFormat.md:
        typer.echo(export.scan_markdown(
            results, periods=list(PERIODS), mode=mode, title=title,
        ))
        if board_meta is None:
            save_snapshot(all_results)
        return

    display_periods = responsive_periods(console.width)
    is_compact = len(display_periods) < len(PERIODS)

    is_hot = isinstance(board_meta, HotMeta)
    table = terminal.scan_table(
        ctx, results,
        display_periods=display_periods,
        high_mode=high,
        signal_only=signal,
        board_index_result=board_index_result,
    )
    # U-7: 头部 1 行 disclaimer 呼应(自选 100+ 只表格 · 防底部 disclaimer 滚屏顶掉)
    console.print("[dim]💡 慢慢看是观察工具 · 不预测涨跌 · 详见底部免责[/dim]")
    console.print(table)

    if is_compact:
        shown = "/".join(str(p) for p in display_periods)
        n = len(display_periods)
        console.print(
            f"\n  [dim]窄屏模式 · 显示 {n}/10 周期"
            f"（{shown}日）· 加宽终端可见全部[/dim]"
        )

    render_freshness_warning(freshness, console)

    # 增量对比 · 仅自选模式 (board_meta is None) · industry/hot 模式不做 diff/snapshot
    if board_meta is None and diff and prev_snapshot:
        changes = compute_diff(all_results, prev_snapshot)
        if changes:
            console.print()
            console.print("[bold]与上次扫描的变化：[/bold]")
            for sym, name, _, desc in changes:
                name_short = name.replace(" ", "")
                console.print(f"  {name_short} {sym} · {desc}")
        else:
            if not is_stale:
                console.print("\n  [dim]与上次扫描无变化（同日数据，次日再对比可见变化）[/dim]")
            else:
                console.print("\n  与上次扫描无变化")
    elif diff and not prev_snapshot:
        console.print("\n  [dim]首次扫描，无历史对比（下次 --diff 将显示变化）[/dim]")

    # 保存快照供下次 diff 用 · 仅自选模式
    if board_meta is None:
        save_snapshot(all_results)

    console.print()
    if high:
        console.print("[dim]  \\[x%] = 触及高点(≥95%) · 100%=区间最高 · 越高=越接近 N 日最高价[/dim]")
    else:
        console.print("[dim]  \\[x%] = 触及低点(≤5%) · 0%=区间最低 · 越低=越接近 N 日最低价[/dim]")
    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单\n  💡 涨停 / 强势股天然在区间高位 · [100%] 是数学结果 不是 「过热信号」[/dim]"
        )
    if isinstance(board_meta, ThemeMeta):
        from kan.render.theme import render_theme_disclaimer
        render_theme_disclaimer()
    else:
        console.print(DISCLAIMER, style="dim")

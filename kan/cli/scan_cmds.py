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
    _resolve_code_pairs,
    _with_heavy_imports_spinner,
)
from kan.data.hot import HotList
from kan.storage import export


@app.command()
def scan(
    symbols: Annotated[
        list[str] | None,
        typer.Argument(help="可选代码列表（逗号/空格分隔）· 例: kan scan 600519,000858"),
    ] = None,
    high: Annotated[bool, typer.Option("--high", help="高点模式（默认低点模式）")] = False,
    signal: Annotated[bool, typer.Option("--signal", "-S", "-s", help="仅显示有共振信号的股票")] = False,
    diff: Annotated[bool, typer.Option("--diff", "-d", help="增量模式：显示与上次扫描的变化")] = False,
    exclude_st: Annotated[bool, typer.Option("--exclude-st", help="排除 ST/*ST 股票")] = False,
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="只扫描指定代码池（逗号/空格/换行分隔；- 从 stdin 读）"),
    ] = None,
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
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="选自选股分组 (默认 default 组 · 跑 kan group list 查看)"),
    ] = None,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """扫描自选股多周期位置（10 周期全景模式 · --group 切换分组）"""
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
    positional_codes = " ".join(symbols or []) or None
    if codes is not None and positional_codes is not None:
        _print_err("❌ 位置参数代码 与 --codes 不能同时使用")
        raise typer.Exit(2)
    raw_codes = codes if codes is not None else positional_codes
    code_pairs = _resolve_code_pairs(raw_codes, command="kan scan") if raw_codes else None
    if sum(1 for x in (industry, hot, theme, code_pairs) if x is not None) > 1:
        _print_err("❌ --industry / --hot / --theme / --codes 四者互斥 · 同时只能用一个")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None or code_pairs is not None
    watchlist_pairs = (
        [] if code_pairs is not None else (
            _load_watchlist_pairs(group) if source_mode else _get_watchlist_pairs(group)
        )
    )
    if only_watchlist and not source_mode:
        _print_err(
            "❌ --only-watchlist 需配合 --industry / --hot / --theme 使用\n"
            "   例: kan scan --industry 半导体 --only-watchlist"
        )
        raise typer.Exit(1)
    if code_pairs is not None and only_watchlist:
        _print_err(
            "❌ --codes 与 --only-watchlist 不能同时使用\n"
            "   例: kan scan --codes 600519,000858"
        )
        raise typer.Exit(2)
    if code_pairs is not None and group is not None:
        _print_err("❌ --codes 已显式指定代码池 · 不再叠加 --group")
        raise typer.Exit(2)
    if code_pairs is not None and diff:
        _print_err("❌ --diff 仅支持自选股扫描 · 自定义代码池不写入扫描快照")
        raise typer.Exit(2)
    # OOP 路径:CLI 构造 StockSet 再喂 pipeline · meta/highlight/filter 全部由 Set 承担
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.core.pipeline import run_data_pipeline
    from kan.core.stock_set import CodeListSet, from_flags
    mode = "high" if high else "low"
    stock_set = (
        CodeListSet(code_pairs)
        if code_pairs is not None else
        from_flags(
            industry=industry, hot=hot, theme=theme,
            watchlist_pairs=watchlist_pairs,
            only_watchlist=only_watchlist,
            watchlist_group=group,
        )
    )
    ctx = run_data_pipeline(
        stock_set,
        compute=scan_batch,
        mode=mode,
        show_progress=fmt is export.OutputFormat.terminal,
    )
    board_meta = ctx.meta
    data_cutoff = ctx.freshness.data_cutoff
    fetched_at = ctx.freshness.fetched_at
    is_stale = ctx.freshness.is_stale  # JSON/MD payload + --diff 分支仍引用
    freshness = ctx.freshness  # 给 render_freshness_warning 用

    is_code_mode = code_pairs is not None
    prev_snapshot = load_snapshot() if (diff and board_meta is None and not is_code_mode) else None

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

    if not ctx.results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    from kan.core.enrich import enrich_scan_rows

    all_results = enrich_scan_rows(ctx.results, data_cutoff=data_cutoff)

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
            if board_meta is None and not is_code_mode:
                save_snapshot(all_results)
            return

    title = terminal.scan_title(ctx, high_mode=high, signal_only=signal)

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.scan_payload(
            results, mode=mode, data_cutoff=data_cutoff,
            fetched_at=fetched_at, stale=is_stale,
        )))
        if board_meta is None and not is_code_mode:
            save_snapshot(all_results)
        return
    if fmt is export.OutputFormat.md:
        typer.echo(export.scan_markdown(
            results, periods=list(PERIODS), mode=mode, title=title,
            show_context=True,
        ))
        if board_meta is None and not is_code_mode:
            save_snapshot(all_results)
        return

    display_periods = responsive_periods(console.width - 56)
    is_compact = len(display_periods) < len(PERIODS)

    is_hot = isinstance(board_meta, HotMeta)
    table = terminal.scan_table(
        ctx, results,
        display_periods=display_periods,
        high_mode=high,
        signal_only=signal,
        board_index_result=board_index_result,
        show_context=True,
    )
    # 头部 1 行 disclaimer 呼应(自选 100+ 只表格 · 防底部 disclaimer 滚屏顶掉)
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
    if board_meta is None and not is_code_mode and diff and prev_snapshot:
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
    if board_meta is None and not is_code_mode:
        save_snapshot(all_results)

    console.print()
    if high:
        console.print("[dim]  \\[x%] = 触及高点(≥95%) · 100%=区间最高 · 越高=越接近 N 日最高价[/dim]")
    else:
        console.print("[dim]  \\[x%] = 触及极值 · \\[0%] 触低(≤5%) · \\[100%] 触高(≥95%) · 越低越接近 N 日最低[/dim]")
    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单\n  💡 涨停 / 大幅上涨个股天然在区间高位 · [100%] 是数学结果 不是 「过热信号」[/dim]"
        )
    if isinstance(board_meta, ThemeMeta):
        from kan.render.theme import render_theme_disclaimer
        render_theme_disclaimer()
    else:
        console.print(DISCLAIMER, style="dim")

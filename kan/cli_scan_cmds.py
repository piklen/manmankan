"""位置扫描 / 数据拉取相关命令：fetch / scan / low / high / info。

共同特征：触及 K 线数据 · 大多走 _auto_fetch_stale 自动补缺 · 输出 rich.Table 表格。
"""
from typing import Annotated

import typer

from kan import export
from kan.app import app
from kan.cli_helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _safe_error_msg,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)
from kan.hot import HotList


@app.command()
def fetch(
    symbols: Annotated[list[str] | None, typer.Argument(help="股票代码（留空则拉取全部自选）")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="强制刷新（忽略缓存）")] = False,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="预拉某申万行业全部成分股 + 板块指数"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="预拉东财热榜全部股票 · rank=人气榜 / surge=飙升榜"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="预拉某题材全部成分股 K 线"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅拉自选 ∩ 行业/热榜/题材"),
    ] = False,
) -> None:
    """拉取股票历史 K 线数据"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.fetcher import fetch_kline, is_fresh

    if sum(1 for x in (industry, hot, theme) if x is not None) > 1:
        typer.echo("--industry / --hot / --theme 三者互斥 · 同时只能用一个", err=True)
        raise typer.Exit(2)
    if industry is not None or hot is not None or theme is not None:
        if symbols:
            typer.echo("--industry / --hot / --theme 与股票代码不能同时使用", err=True)
            raise typer.Exit(2)
        from kan._pipeline import resolve_targets_or_exit
        wl_pairs = []
        if only_watchlist:
            from kan.watchlist import load_watchlist
            wl_pairs = [(s.symbol, s.name) for s in load_watchlist().stocks]
        targets, _meta = resolve_targets_or_exit(
            industry, only_watchlist, wl_pairs, hot=hot, theme=theme,
        )
        symbols = [s for s, _ in targets]

    if not symbols:
        from kan.watchlist import load_watchlist
        wl = load_watchlist()
        if not wl.stocks:
            typer.echo("自选列表为空 · 请先 `kan add <代码>` 添加", err=True)
            raise typer.Exit(1)
        symbols = [s.symbol for s in wl.stocks]

    success = 0
    for sym in symbols:
        if not force and is_fresh(sym):
            typer.echo(f"  {sym} 已是最新（今日已拉取）")
            success += 1
            continue
        try:
            with status_console.status(
                f"[yellow]⏳ 拉取数据... {sym}[/yellow]",
                spinner="dots",
            ):
                df = fetch_kline(sym, force=force)
            typer.echo(f"  ✅ {sym} 拉取成功（{len(df)} 条 K 线）")
            success += 1
        except Exception as e:
            typer.echo(f"  ❌ {sym} 拉取失败：{_safe_error_msg(e)}", err=True)


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
        from rich.table import Table
        from rich.text import Text

        from kan._pipeline import freshness_of, render_freshness_warning
        from kan.render import DISCLAIMER, format_pct, responsive_periods
        from kan.scanner import (
            PERIODS,
            compute_diff,
            load_snapshot,
            save_snapshot,
            scan_batch,
        )

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
    from kan._pipeline import resolve_targets_or_exit
    from kan._scan_targets import BoardMeta, HotMeta, ThemeMeta
    targets, board_meta = resolve_targets_or_exit(
        industry, only_watchlist, watchlist_pairs, hot=hot, theme=theme,
    )
    _auto_fetch_stale(targets)
    mode = "high" if high else "low"

    prev_snapshot = load_snapshot() if (diff and board_meta is None) else None

    # P1-8: 单次 scan_batch · 后续 filter / diff / snapshot 都用 all_results · 避免重复调用
    all_results = scan_batch(targets, mode=mode)

    board_index_result = None
    if isinstance(board_meta, BoardMeta):
        from kan.scanner import scan_stock
        board_index_result = scan_stock(
            board_meta.index_kline, board_meta.board.code, board_meta.board.name,
        )
    elif isinstance(board_meta, ThemeMeta) and not board_meta.index_kline.empty:
        from kan.scanner import scan_stock
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

    freshness = freshness_of(r.symbol for r in results)
    data_cutoff = freshness.data_cutoff
    fetched_at = freshness.fetched_at
    is_stale = freshness.is_stale  # JSON/MD payload + --diff branch 仍引用

    title = f"慢慢看 · 自选股位置扫描 · {'高点' if high else '低点'}模式"
    if signal:
        title += " · 仅信号"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    if isinstance(board_meta, BoardMeta):
        title = (
            f"慢慢看 · {board_meta.board.name} 行业位置扫描"
            f" · {'高点' if high else '低点'}模式"
        )
    elif isinstance(board_meta, HotMeta):
        title = (
            f"慢慢看 · {board_meta.list_name} 位置扫描"
            f" · {'高点' if high else '低点'}模式"
        )
    elif isinstance(board_meta, ThemeMeta):
        title = (
            f"慢慢看 · {board_meta.theme.name} 题材位置扫描"
            f" · {'高点' if high else '低点'}模式"
        )

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
    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    for p in display_periods:
        table.add_column(f"{p}日", justify="right", min_width=6)
    table.add_column("共振", justify="center")

    highlight = board_meta.highlight if board_meta else set()
    if board_index_result is not None:
        brow: list[str | Text] = [f"🏛️ {board_index_result.name} 板块指数"]
        brow.append(f"{board_index_result.current_price:.2f}")
        for p in display_periods:
            pr = next(
                (x for x in board_index_result.periods if x.period == p), None
            )
            brow.append(Text("-", style="dim") if pr is None
                        else format_pct(pr, high_mode=high))
        brow.append("")
        table.add_row(*brow)
        table.add_section()

    for r in results:
        row: list[str | Text] = []
        if is_hot:
            rank = board_meta.rank_map.get(r.symbol)
            row.append(str(rank) if rank is not None else "-")
        name_short = r.name.replace(" ", "")
        tag = ""
        if r.limit_up:
            tag = " 涨停"
        elif r.limit_down:
            tag = " 跌停"
        star = "⭐ " if r.symbol in highlight else ""
        row.append(f"{star}{name_short} {r.symbol}{tag}")
        row.append(f"{r.current_price:.2f}")

        for p in display_periods:
            pr = next((x for x in r.periods if x.period == p), None)
            if pr is None:
                row.append(Text("-", style="dim"))
            else:
                row.append(format_pct(pr, high_mode=high))

        resonance = r.high_resonance if high else r.low_resonance
        if resonance >= 3:
            row.append(Text(f"×{resonance}", style="bold yellow"))
        elif resonance > 0:
            row.append(Text(f"×{resonance}", style="yellow"))
        else:
            row.append("")

        table.add_row(*row)

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
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单[/dim]"
        )
    if isinstance(board_meta, ThemeMeta):
        from kan.render_theme import render_theme_disclaimer
        render_theme_disclaimer()
    else:
        console.print(DISCLAIMER, style="dim")


def _filter_extreme_cmd(
    periods: list[int], mode: str, fmt: export.OutputFormat,
    industry: str | None = None, only_watchlist: bool = False,
    hot: HotList | None = None,
    theme: str | None = None,
) -> None:
    """low/high 共享实现"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import cache_age, data_cutoff_date
        from kan.render import DISCLAIMER
        from kan.scanner import filter_extreme

    console = Console()
    for p in periods:
        if p < 2 or p > 360:
            _print_err(f"❌ 周期 {p} 无效（范围 2-360）")
            raise typer.Exit(1)

    label = "低点" if mode == "low" else "高点"
    signal_style = "bold green" if mode == "low" else "bold yellow"

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
    from kan._pipeline import resolve_targets_or_exit
    from kan._scan_targets import BoardMeta, HotMeta, ThemeMeta
    targets, board_meta = resolve_targets_or_exit(
        industry, only_watchlist, watchlist_pairs, hot=hot, theme=theme,
    )
    highlight = board_meta.highlight if board_meta else set()
    is_hot = isinstance(board_meta, HotMeta)
    rank_map = board_meta.rank_map if is_hot else {}
    _auto_fetch_stale(targets)
    results_by_period = filter_extreme(targets, periods, mode=mode)

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(
                export.extreme_payload(results_by_period, mode=mode)
            ))
        else:
            typer.echo(export.extreme_markdown(results_by_period, mode=mode))
        return

    if not results_by_period:
        if isinstance(board_meta, BoardMeta):
            where = f"{board_meta.board.name} 行业成分股"
        elif isinstance(board_meta, HotMeta):
            where = board_meta.list_name
        elif isinstance(board_meta, ThemeMeta):
            where = f"{board_meta.theme.name} 题材成分股"
        else:
            where = "自选股"
        console.print(f"{where}中没有触及 {'/'.join(map(str, periods))} 日{label}的股票")
        return

    # v0.0.4.5: 数据截止 / 拉取时间分离展示（与 scan 一致）
    data_cutoff = None
    fetched_at = None

    for n, hits in results_by_period.items():
        for r, _ in hits:
            d = data_cutoff_date(r.symbol)
            if d is not None and (data_cutoff is None or d > data_cutoff):
                data_cutoff = d
            t = cache_age(r.symbol)
            if t and (fetched_at is None or t > fetched_at):
                fetched_at = t

        title = f"慢慢看 · {n} 日{label} · {len(hits)} 只触及"
        if data_cutoff:
            title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
        if fetched_at:
            title += f" · {format_fetched_at_compact(fetched_at)} 拉取"

        table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
        if is_hot:
            table.add_column("榜", justify="right", style="cyan", min_width=3)
        table.add_column("股票", style="white", no_wrap=True)
        table.add_column("现价", justify="right", style="white", min_width=8)
        table.add_column(f"{n}日最低", justify="right", style="dim", min_width=8)
        table.add_column(f"{n}日最高", justify="right", style="dim", min_width=8)
        table.add_column("位置", justify="right", min_width=8)

        for result, pr in hits:
            name_short = result.name.replace(" ", "")
            star = "⭐ " if result.symbol in highlight else ""
            row: list[str | Text] = []
            if is_hot:
                rank = rank_map.get(result.symbol)
                row.append(str(rank) if rank is not None else "-")
            row.append(f"{star}{name_short} {result.symbol}")
            row.append(f"{result.current_price:.2f}")
            row.append(f"{pr.n_low:.2f}")
            row.append(f"{pr.n_high:.2f}")
            row.append(Text(f"[{pr.position_pct:.1f}%]", style=signal_style))
            table.add_row(*row)

        console.print(table)
        console.print()

    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单[/dim]"
        )
    if isinstance(board_meta, ThemeMeta):
        from kan.render_theme import render_theme_disclaimer
        render_theme_disclaimer()
    else:
        console.print(DISCLAIMER, style="dim")


@app.command()
def low(
    periods: Annotated[list[int], typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120）")],
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
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
) -> None:
    """筛选 N 日低点的自选股（支持多周期）"""
    _filter_extreme_cmd(
        periods, mode="low", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot, theme=theme,
    )


@app.command()
def high(
    periods: Annotated[list[int], typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120）")],
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
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
) -> None:
    """筛选 N 日高点的自选股（支持多周期）"""
    _filter_extreme_cmd(
        periods, mode="high", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot, theme=theme,
    )


def _info_industry(industry: str, fmt: export.OutputFormat) -> None:
    """kan info --industry · 簡版板块档案。"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table

        from kan._pipeline import resolve_targets_or_exit
        from kan.render import DISCLAIMER, format_pct
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

    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("最低", justify="right", style="dim", min_width=8)
    table.add_column("最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)
    for pr in board_result.periods:
        if pr.insufficient:
            table.add_row(f"{pr.period}日", "-", "-", "-")
        else:
            table.add_row(
                f"{pr.period}日", f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}", format_pct(pr),
            )
    console.print(table)
    console.print(DISCLAIMER, style="dim")


def _info_theme(theme_query: str, fmt: export.OutputFormat) -> None:
    """kan info --theme · 题材档案 · 类似 _info_industry。"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table

        from kan._pipeline import resolve_targets_or_exit
        from kan.render import format_pct
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

    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("最低", justify="right", style="dim", min_width=8)
    table.add_column("最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)
    for pr in theme_result.periods:
        if pr.insufficient:
            table.add_row(f"{pr.period}日", "-", "-", "-")
        else:
            table.add_row(
                f"{pr.period}日", f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}", format_pct(pr),
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
    # U-1 (v0.0.4.8 P0-6): 跟 kan add 同款散户中文 · 兑现 U-2 承诺到 info 命令
    if not symbol:
        typer.echo(
            "请告诉我看哪只股票 · 例: kan info 600519 (代码或名称都行)",
            err=True,
        )
        raise typer.Exit(2)

    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import cache_age, data_cutoff_date, fetch_kline, get_cached, is_fresh
        from kan.render import DISCLAIMER, format_pct
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
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("最低", justify="right", style="dim", min_width=8)
    table.add_column("最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    for pr in result.periods:
        if pr.insufficient:
            table.add_row(f"{pr.period}日", "-", "-", Text("-", style="dim"))
            continue

        table.add_row(
            f"{pr.period}日",
            f"{pr.n_low:.2f}",
            f"{pr.n_high:.2f}",
            format_pct(pr),
        )

    console.print(table)
    console.print(f"\n  低点共振 ×{result.low_resonance} · 高点共振 ×{result.high_resonance}")
    if volume_state is not None:
        console.print(
            f"  成交量 · 今日是近 {volume_state.window} 日均量的 "
            f"{volume_state.ratio} 倍 · {volume_state.label}"
        )

    # UX-1 (v0.0.4.7 P0): kan info 加 stale/intraday 警告 · 与 scan/trend 一致
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


MAX_COMPARE_SYMBOLS = 8


@app.command()
def compare(
    symbols: Annotated[list[str], typer.Argument(help="股票代码或名称（2-8 只）")],
    periods: Annotated[
        str,
        typer.Option("--periods", "-p", help="周期（默认 30 · 逗号分隔多个：7,30,90）"),
    ] = "30",
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """横向对比多只股票的多周期位置（转置表 · 指标为行 · 个股为列）"""
    if len(symbols) < 2:
        _print_err("❌ kan compare 至少需要 2 只股票 · 例: kan compare 600519 000858")
        raise typer.Exit(2)
    if len(symbols) > MAX_COMPARE_SYMBOLS:
        _print_err(
            f"❌ 最多对比 {MAX_COMPARE_SYMBOLS} 只 · 当前 {len(symbols)} 只 · "
            "表格太宽看不清"
        )
        raise typer.Exit(2)

    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import fetch_kline, get_cached, is_fresh
        from kan.render import DISCLAIMER, format_pct
        from kan.scanner import PERIODS, scan_stock
        from kan.watchlist import _lookup_name, _normalize_symbol

    console = Console()

    try:
        period_list = [int(p.strip()) for p in periods.split(",") if p.strip()]
    except ValueError:
        _print_err(f"❌ --periods 格式错误：{periods!r} · 应为逗号分隔整数")
        raise typer.Exit(2) from None
    invalid = [p for p in period_list if p not in PERIODS]
    if invalid or not period_list:
        _print_err(
            f"❌ 周期不支持：{invalid or periods!r} · 可选 {'/'.join(map(str, PERIODS))}"
        )
        raise typer.Exit(2)

    results = []
    for raw in symbols:
        try:
            sym = _normalize_symbol(raw)
            name = _lookup_name(sym)
        except ValueError as e:
            _print_err(f"❌ {raw}：{e}")
            raise typer.Exit(1) from e
        if not is_fresh(sym):
            try:
                with status_console.status(
                    f"[yellow]⏳ 拉取数据... {name.replace(' ', '')} ({sym})[/yellow]",
                    spinner="dots",
                ):
                    fetch_kline(sym, force=True)
            except Exception as e:
                _print_err(f"❌ {sym} 拉取失败：{_safe_error_msg(e)}")
                raise typer.Exit(1) from e
        df = get_cached(sym)
        if df is None:
            _print_err(f"❌ {sym} 无数据")
            raise typer.Exit(1)
        results.append(scan_stock(df, sym, name))

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.compare_payload(results, periods=period_list)))
        return
    if fmt is export.OutputFormat.md:
        typer.echo(export.compare_markdown(results, periods=period_list))
        return

    table = Table(
        title="慢慢看 · 多股对比", show_lines=False, pad_edge=False, padding=(0, 1),
    )
    table.add_column("指标", style="cyan", no_wrap=True)
    for r in results:
        table.add_column(f"{r.name.replace(' ', '')} {r.symbol}", justify="right")

    table.add_row("现价", *[f"{r.current_price:.2f}" for r in results])
    for p in period_list:
        cells: list[str | Text] = []
        for r in results:
            pr = next((x for x in r.periods if x.period == p), None)
            cells.append(Text("-", style="dim") if pr is None else format_pct(pr))
        table.add_row(f"{p}日位置", *cells)
    table.add_row("低点共振", *[f"×{r.low_resonance}" for r in results])
    table.add_row("高点共振", *[f"×{r.high_resonance}" for r in results])
    table.add_row("ST", *["是" if r.is_st else "—" for r in results])
    table.add_row(
        "涨跌停",
        *["涨停" if r.limit_up else ("跌停" if r.limit_down else "—") for r in results],
    )
    table.add_row("数据截止", *[format_date_compact(r.scan_date) for r in results])

    console.print(table)
    console.print(DISCLAIMER, style="dim")

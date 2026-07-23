"""low / high · N 日极值（低点/高点）筛选 · 多周期支持。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
)
from kan.data.hot import HotList
from kan.storage import export


def _filter_extreme_cmd(
    periods: list[int], mode: str, fmt: export.OutputFormat,
    industry: str | None = None, only_watchlist: bool = False,
    hot: HotList | None = None,
    theme: str | None = None,
    all_stocks: bool = False,
    group: str | None = None,
) -> None:
    """low/high 共享实现 (--group 切换自选分组)"""
    from rich.console import Console

    from kan.core.scanner import filter_extreme, scan_stock
    from kan.data.fetcher import cache_age, data_cutoff_date
    from kan.render import terminal
    from kan.render.base import DISCLAIMER

    console = Console()
    for p in periods:
        if p < 2 or p > 360:
            _print_err(f"❌ 周期 {p} 无效（范围 2-360）")
            raise typer.Exit(1)

    label = "低点" if mode == "low" else "高点"

    pool_count = sum(1 for x in (industry, hot, theme) if x is not None) + int(all_stocks)
    if pool_count > 1:
        _print_err("❌ --industry / --hot / --theme / --all 互斥 · 同时只能用一个")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None or all_stocks
    if all_stocks and only_watchlist:
        _print_err(
            "❌ --all 与 --only-watchlist 不能同时使用\n"
            "   例: kan low 30 --all"
        )
        raise typer.Exit(2)
    if all_stocks and group is not None:
        _print_err(
            "❌ --all 已指定全市场池，不再叠加 --group\n"
            "   例: kan low 30 --all；或 kan low 30 --group <组名>"
        )
        raise typer.Exit(2)
    watchlist_pairs = (
        [] if all_stocks else (
            _load_watchlist_pairs(group) if source_mode else _get_watchlist_pairs(group)
        )
    )
    if only_watchlist and not source_mode:
        _print_err(
            "❌ --only-watchlist 需配合 --industry / --hot / --theme 使用\n"
            "   例: kan low 30 --industry 半导体 --only-watchlist"
        )
        raise typer.Exit(1)
    # OOP 路径:from_flags → resolve_stock_set_or_exit · 取代 resolve_targets_or_exit
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.core.pipeline import resolve_stock_set_or_exit
    from kan.core.stock_set import from_flags
    stock_set = from_flags(
        industry=industry, hot=hot, theme=theme,
        watchlist_pairs=watchlist_pairs,
        only_watchlist=only_watchlist,
        watchlist_group=group,
        all_stocks=all_stocks,
    )
    targets, board_meta = resolve_stock_set_or_exit(stock_set)
    if not targets and all_stocks:
        _print_err(
            "❌ 全市场股票池为空\n"
            "   例: kan config set tushare-token <YOUR_TOKEN>；或稍后重试"
        )
        raise typer.Exit(1)
    highlight = board_meta.highlight if board_meta else set()
    is_hot = isinstance(board_meta, HotMeta)
    rank_map = board_meta.rank_map if is_hot else {}
    _auto_fetch_stale(targets, days=max(periods) if periods else None)

    # 板块 / 题材指数 reference · 跟 scan --industry / --theme 视觉对齐(backlog)
    board_index_result = None
    if isinstance(board_meta, BoardMeta):
        board_index_result = scan_stock(
            board_meta.index_kline,
            board_meta.board.code, board_meta.board.name, periods=periods,
        )
    elif isinstance(board_meta, ThemeMeta) and not board_meta.index_kline.empty:
        board_index_result = scan_stock(
            board_meta.index_kline,
            board_meta.theme.code, board_meta.theme.name, periods=periods,
        )

    results_by_period = filter_extreme(targets, periods, mode=mode)

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(
                export.extreme_payload(
                    results_by_period, mode=mode,
                    board_index_result=board_index_result, board_meta=board_meta,
                )
            ))
        elif fmt is export.OutputFormat.csv:
            typer.echo(export.extreme_csv(
                results_by_period, mode=mode,
                board_index_result=board_index_result, board_meta=board_meta,
                periods=periods,
            ))
        else:
            typer.echo(export.extreme_markdown(
                results_by_period, mode=mode,
                board_index_result=board_index_result, board_meta=board_meta,
                periods=periods,
            ))
        return

    # 数据截止 / 拉取时间分离展示 · 板块 K 线 cutoff 也聚合(reference 行需要)
    data_cutoff = None
    fetched_at = None
    if board_index_result is not None and isinstance(
        board_meta, (BoardMeta, ThemeMeta),
    ):
        import pandas as pd

        kline = board_meta.index_kline
        if not kline.empty and "date" in kline.columns:
            raw = kline["date"].iloc[-1]
            board_date = raw if hasattr(raw, "isoformat") else pd.Timestamp(raw).date()
            if data_cutoff is None or board_date > data_cutoff:
                data_cutoff = board_date

    # 空 hits 时:有 reference 就画 reference + 文案 + disclaimer(industry/theme) ·
    # 自选股 / hot 保持原行为(纯文案 return · 板块当前位置 reference 仅对 board/theme 有意义)
    if not results_by_period:
        if isinstance(board_meta, BoardMeta):
            where = f"{board_meta.board.name} 行业成分股"
        elif isinstance(board_meta, HotMeta):
            where = board_meta.list_name
        elif isinstance(board_meta, ThemeMeta):
            where = f"{board_meta.theme.name} 题材成分股"
        elif all_stocks:
            where = "A股全市场"
        else:
            where = "自选股"
        if board_index_result is not None:
            for p in periods:
                ref_table = terminal.extreme_table(
                    p, [], mode,
                    is_hot=is_hot, rank_map=rank_map, highlight=highlight,
                    data_cutoff=data_cutoff, fetched_at=fetched_at,
                    board_index_result=board_index_result,
                    board_meta=board_meta,
                )
                console.print(ref_table)
                console.print()
            console.print(
                f"{where}中没有触及 {'/'.join(map(str, periods))} 日{label}的股票"
            )
            if isinstance(board_meta, ThemeMeta):
                from kan.render.theme import render_theme_disclaimer
                render_theme_disclaimer()
            else:
                console.print(DISCLAIMER, style="dim")
        else:
            console.print(
                f"{where}中没有触及 {'/'.join(map(str, periods))} 日{label}的股票"
            )
        return

    for n, hits in results_by_period.items():
        for r, _ in hits:
            d = data_cutoff_date(r.symbol)
            if d is not None and (data_cutoff is None or d > data_cutoff):
                data_cutoff = d
            t = cache_age(r.symbol)
            if t and (fetched_at is None or t > fetched_at):
                fetched_at = t

        table = terminal.extreme_table(
            n, hits, mode,
            is_hot=is_hot, rank_map=rank_map, highlight=highlight,
            data_cutoff=data_cutoff, fetched_at=fetched_at,
            board_index_result=board_index_result,
            board_meta=board_meta,
        )
        console.print(table)
        console.print()

    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单\n  💡 涨停 / 大幅上涨个股天然在区间高位 · [100%] 是数学结果 不是 「过热信号」[/dim]"
        )
    if isinstance(board_meta, ThemeMeta):
        from kan.render.theme import render_theme_disclaimer
        render_theme_disclaimer()
    else:
        console.print(DISCLAIMER, style="dim")


_DEFAULT_PERIODS = [30, 60, 120]  # 无参时默认 · 覆盖中短中长 3 段


@app.command()
def low(
    periods: Annotated[
        list[int] | None,
        typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120 · 无参默认 30 60 120）"),
    ] = None,
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
    all_stocks: Annotated[
        bool,
        typer.Option("--all", help="扫描 A 股全市场池（约 5500 只；首次会补 K 线缓存）"),
    ] = False,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜/题材(需配合 --industry / --hot / --theme)"),
    ] = False,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="选自选股分组 (默认 default 组)"),
    ] = None,
) -> None:
    """筛选 N 日低点的自选股 · find --pos 低位快捷入口(默认 30/60/120 三段)."""
    _filter_extreme_cmd(
        periods or _DEFAULT_PERIODS, mode="low", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot, theme=theme,
        all_stocks=all_stocks, group=group,
    )


@app.command()
def high(
    periods: Annotated[
        list[int] | None,
        typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120 · 无参默认 30 60 120）"),
    ] = None,
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
    all_stocks: Annotated[
        bool,
        typer.Option("--all", help="扫描 A 股全市场池（约 5500 只；首次会补 K 线缓存）"),
    ] = False,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜/题材(需配合 --industry / --hot / --theme)"),
    ] = False,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="选自选股分组 (默认 default 组)"),
    ] = None,
) -> None:
    """筛选 N 日高点的自选股 · find --pos 高位快捷入口(默认 30/60/120 三段)."""
    _filter_extreme_cmd(
        periods or _DEFAULT_PERIODS, mode="high", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot, theme=theme,
        all_stocks=all_stocks, group=group,
    )

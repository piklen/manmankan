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
    _with_heavy_imports_spinner,
)
from kan.data.hot import HotList
from kan.storage import export


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
        from kan.core.scanner import filter_extreme
        from kan.data.fetcher import cache_age, data_cutoff_date
        from kan.render import terminal
        from kan.render.base import DISCLAIMER

    console = Console()
    for p in periods:
        if p < 2 or p > 360:
            _print_err(f"❌ 周期 {p} 无效（范围 2-360）")
            raise typer.Exit(1)

    label = "低点" if mode == "low" else "高点"

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
    # v0.0.5.3 OOP 路径:from_flags → resolve_stock_set_or_exit · 取代 resolve_targets_or_exit
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.core.pipeline import resolve_stock_set_or_exit
    from kan.core.stock_set import from_flags
    stock_set = from_flags(
        industry=industry, hot=hot, theme=theme,
        watchlist_pairs=watchlist_pairs,
        only_watchlist=only_watchlist,
    )
    targets, board_meta = resolve_stock_set_or_exit(stock_set)
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

        table = terminal.extreme_table(
            n, hits, mode,
            is_hot=is_hot, rank_map=rank_map, highlight=highlight,
            data_cutoff=data_cutoff, fetched_at=fetched_at,
        )
        console.print(table)
        console.print()

    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单\n  💡 涨停 / 强势股天然在区间高位 · [100%] 是数学结果 不是 「过热信号」[/dim]"
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
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜/题材(需配合 --industry / --hot / --theme)"),
    ] = False,
) -> None:
    """筛选 N 日低点的自选股（支持多周期 · 无参默认 30/60/120 三段）"""
    _filter_extreme_cmd(
        periods or _DEFAULT_PERIODS, mode="low", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot, theme=theme,
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
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜/题材(需配合 --industry / --hot / --theme)"),
    ] = False,
) -> None:
    """筛选 N 日高点的自选股（支持多周期 · 无参默认 30/60/120 三段）"""
    _filter_extreme_cmd(
        periods or _DEFAULT_PERIODS, mode="high", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot, theme=theme,
    )

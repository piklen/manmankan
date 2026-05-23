"""fetch · 拉取股票历史 K 线数据 (含 --industry / --hot / --theme 批量预拉)。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _safe_error_msg, _with_heavy_imports_spinner
from kan.data.hot import HotList


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
        from kan.data.fetcher import fetch_kline, is_fresh

    if sum(1 for x in (industry, hot, theme) if x is not None) > 1:
        typer.echo("--industry / --hot / --theme 三者互斥 · 同时只能用一个", err=True)
        raise typer.Exit(2)
    if industry is not None or hot is not None or theme is not None:
        if symbols:
            typer.echo("--industry / --hot / --theme 与股票代码不能同时使用", err=True)
            raise typer.Exit(2)
        from kan.core.pipeline import resolve_targets_or_exit
        wl_pairs = []
        if only_watchlist:
            from kan.storage.watchlist import load_watchlist
            wl_pairs = [(s.symbol, s.name) for s in load_watchlist().stocks]
        targets, _meta = resolve_targets_or_exit(
            industry, only_watchlist, wl_pairs, hot=hot, theme=theme,
        )
        symbols = [s for s, _ in targets]

    if not symbols:
        from kan.storage.watchlist import load_watchlist
        wl = load_watchlist()
        if not wl.stocks:
            typer.echo("自选列表为空 · 先加几只:`kan add 600519 茅台 000858` (代码或名称都行)", err=True)
            raise typer.Exit(1)
        symbols = [s.symbol for s in wl.stocks]

    success = 0
    failed = 0
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
            failed += 1

    if failed:
        typer.echo(f"拉取完成：✅ 成功 {success} · ❌ 失败 {failed}", err=True)
        raise typer.Exit(1)

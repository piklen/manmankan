"""fetch · 拉取股票历史 K 线数据 (含 --industry / --hot / --theme 批量预拉)。"""
from __future__ import annotations

from time import perf_counter
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
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="选自选股分组 (默认 default 组)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="逐只输出拉取状态"),
    ] = False,
) -> None:
    """拉取股票历史 K 线数据 (--group 切换分组)"""
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
        # OOP 路径:from_flags → resolve_stock_set_or_exit
        from kan.core.pipeline import resolve_stock_set_or_exit
        from kan.core.stock_set import from_flags
        wl_pairs = []
        if only_watchlist:
            from kan.storage.watchlist import GroupNotFoundError, load_watchlist
            try:
                wl_pairs = [(s.symbol, s.name) for s in load_watchlist(group).stocks]
            except GroupNotFoundError as e:
                typer.echo(f"❌ {e}", err=True)
                raise typer.Exit(2) from None
        stock_set = from_flags(
            industry=industry, hot=hot, theme=theme,
            watchlist_pairs=wl_pairs,
            only_watchlist=only_watchlist,
            watchlist_group=group,
        )
        symbols = stock_set.codes()
        resolve_stock_set_or_exit(stock_set)  # 触发 .pairs() lazy fetch + 转 typer.Exit · 上一行 .codes() 已触发了 fetch · 这里走 cache 不再 IO

    if not symbols:
        from kan.storage.watchlist import GroupNotFoundError, load_watchlist
        try:
            wl = load_watchlist(group)
        except GroupNotFoundError as e:
            typer.echo(f"❌ {e}", err=True)
            raise typer.Exit(2) from None
        if not wl.stocks:
            label = "自选" if not group else f"「{group}」组"
            suffix = "" if not group else f" --group {group}"
            typer.echo(
                f"{label}列表为空 · 先加几只:`kan add 600519 茅台 000858{suffix}` (代码或名称都行)",
                err=True,
            )
            raise typer.Exit(1)
        symbols = [s.symbol for s in wl.stocks]

    started = perf_counter()
    success = 0
    fresh = 0
    updated = 0
    failed = 0
    errors: list[tuple[str, str]] = []
    for sym in symbols:
        if not force and is_fresh(sym):
            if verbose:
                typer.echo(f"  {sym} 已是最新（今日已拉取）")
            fresh += 1
            success += 1
            continue
        try:
            with status_console.status(
                f"[yellow]⏳ 拉取数据... {sym}[/yellow]",
                spinner="dots",
            ):
                df = fetch_kline(sym, force=force)
            if verbose:
                typer.echo(f"  ✅ {sym} 拉取成功（{len(df)} 条 K 线）")
            updated += 1
            success += 1
        except Exception as e:
            msg = _safe_error_msg(e)
            if verbose:
                typer.echo(f"  ❌ {sym} 拉取失败：{msg}", err=True)
            errors.append((sym, msg))
            failed += 1

    elapsed = perf_counter() - started
    if failed:
        typer.echo(
            f"❌ 拉取失败 {failed} 只 · 成功 {success} 只 · 耗时 {elapsed:.1f}s",
            err=True,
        )
        if not verbose:
            for sym, msg in errors[:3]:
                typer.echo(f"  {sym}: {msg}", err=True)
        raise typer.Exit(1)
    if updated == 0:
        typer.echo(f"✅ 已最新 · {fresh} 只无需更新 · 耗时 {elapsed:.1f}s")
    else:
        suffix = f" · 已最新 {fresh} 只" if fresh else ""
        typer.echo(f"🔄 更新 {updated} 只{suffix} · 耗时 {elapsed:.1f}s")

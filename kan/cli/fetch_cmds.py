"""fetch · 拉取股票历史 K 线数据 (含 --industry / --hot / --theme 批量预拉)。"""
from __future__ import annotations

from contextlib import nullcontext
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
    all_stocks: Annotated[
        bool,
        typer.Option("--all", help="预拉 A 股全市场 K 线缓存（约 5500 只，耗时较久）"),
    ] = False,
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
    from kan.infra.progress import cli_status, determinate_progress, feedback_console

    status_console = feedback_console()
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.data.fetcher import fetch_kline, is_fresh

    pool_count = sum(1 for x in (industry, hot, theme) if x is not None) + int(all_stocks)
    if pool_count > 1:
        typer.echo("--industry / --hot / --theme / --all 互斥 · 同时只能用一个", err=True)
        raise typer.Exit(2)
    if all_stocks and symbols:
        typer.echo("--all 与股票代码不能同时使用", err=True)
        raise typer.Exit(2)
    if all_stocks and only_watchlist:
        typer.echo("--all 与 --only-watchlist 不能同时使用", err=True)
        raise typer.Exit(2)
    if all_stocks and group is not None:
        typer.echo("--all 已指定全市场池，不再叠加 --group", err=True)
        raise typer.Exit(2)
    if industry is not None or hot is not None or theme is not None or all_stocks:
        if symbols:
            typer.echo("--industry / --hot / --theme / --all 与股票代码不能同时使用", err=True)
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
            all_stocks=all_stocks,
        )
        symbols = stock_set.codes()
        resolve_stock_set_or_exit(stock_set)  # 触发 .pairs() lazy fetch + 转 typer.Exit · 上一行 .codes() 已触发了 fetch · 这里走 cache 不再 IO
        if not symbols and all_stocks:
            typer.echo(
                "全市场股票池为空 · 例: kan config set tushare-token <YOUR_TOKEN>；或稍后重试",
                err=True,
            )
            raise typer.Exit(1)

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
    show_batch_progress = len(symbols) > 1 and not verbose
    progress_cm = (
        determinate_progress(console=status_console)
        if show_batch_progress else nullcontext(None)
    )
    with progress_cm as progress:
        task_id = None
        if progress is not None:
            task_id = progress.add_task(
                f"⏳ 检查/拉取 K 线 · 0/{len(symbols)} 只",
                total=len(symbols),
            )
        for idx, sym in enumerate(symbols, start=1):
            if progress is not None and task_id is not None:
                progress.update(
                    task_id,
                    description=f"⏳ 检查/拉取 K 线 · {idx}/{len(symbols)} 只 · {sym}",
                )
            if not force and is_fresh(sym):
                if verbose:
                    typer.echo(f"  {sym} 已是最新（今日已拉取）")
                fresh += 1
                success += 1
                if progress is not None and task_id is not None:
                    progress.update(
                        task_id,
                        advance=1,
                        description=f"⏳ 检查/拉取 K 线 · ✅ 已最新 {sym}",
                    )
                continue
            try:
                if progress is None:
                    with cli_status(f"⏳ 拉取数据... {sym}", console=status_console):
                        df = fetch_kline(sym, force=force)
                else:
                    df = fetch_kline(sym, force=force)
                if verbose:
                    typer.echo(f"  ✅ {sym} 拉取成功（{len(df)} 条 K 线）")
                updated += 1
                success += 1
                if progress is not None and task_id is not None:
                    progress.update(
                        task_id,
                        advance=1,
                        description=f"⏳ 检查/拉取 K 线 · ✅ 更新 {sym}",
                    )
            except Exception as e:
                msg = _safe_error_msg(e)
                if verbose:
                    typer.echo(f"  ❌ {sym} 拉取失败：{msg}", err=True)
                errors.append((sym, msg))
                failed += 1
                if progress is not None and task_id is not None:
                    progress.update(
                        task_id,
                        advance=1,
                        description=f"⏳ 检查/拉取 K 线 · ❌ 失败 {sym}",
                    )

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

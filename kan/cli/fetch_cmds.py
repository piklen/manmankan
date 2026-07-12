"""fetch · 拉取股票历史 K 线数据 (含 --industry / --hot / --theme 批量预拉)。"""
from __future__ import annotations

from time import perf_counter
from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _safe_error_msg
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
    from kan.infra.progress import feedback_console, operation_reporter

    status_console = feedback_console()
    from kan.data.fetcher import fetch_batch, is_fresh

    pool_count = sum(1 for x in (industry, hot, theme) if x is not None) + int(all_stocks)
    has_explicit_pool = pool_count > 0
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
        pairs, _meta = resolve_stock_set_or_exit(stock_set)
        symbols = [code for code, _name in pairs]
        if not symbols and all_stocks:
            typer.echo(
                "全市场股票池为空 · 例: kan config set tushare-token <YOUR_TOKEN>；或稍后重试",
                err=True,
            )
            raise typer.Exit(1)

    if not symbols and not has_explicit_pool:
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

    symbols = list(dict.fromkeys(symbols or []))
    started = perf_counter()

    from kan.infra.lifecycle import operation

    reporter = operation_reporter(console=status_console)
    exit_code: int | None = None
    output_lines: list[tuple[str, bool]] = []
    with operation("拉取 K 线", reporter=reporter) as lifecycle:
        lifecycle.phase("检查本地缓存", total=len(symbols))
        fresh_symbols: list[str] = []
        if force:
            pending = list(symbols)
        else:
            fresh_symbols = [symbol for symbol in symbols if is_fresh(symbol)]
            fresh_set = set(fresh_symbols)
            pending = [symbol for symbol in symbols if symbol not in fresh_set]

        lifecycle.phase("批量拉取 K 线", pending=len(pending), fresh=len(fresh_symbols))
        results, batch_errors = fetch_batch(pending, force=force)

        error_by_symbol = {
            symbol: _safe_error_msg(ValueError(message))
            for symbol, message in batch_errors.items()
        }
        for symbol in pending:
            if symbol not in results and symbol not in error_by_symbol:
                error_by_symbol[symbol] = "批量拉取未返回结果"

        fresh_set = set(fresh_symbols)
        errors = [
            (symbol, error_by_symbol[symbol])
            for symbol in pending
            if symbol in error_by_symbol
        ]
        updated_symbols = [
            symbol
            for symbol in pending
            if symbol in results and symbol not in error_by_symbol
        ]
        fresh = len(fresh_symbols)
        updated = len(updated_symbols)
        failed = len(errors)
        success = fresh + updated

        if verbose:
            for symbol in symbols:
                if symbol in fresh_set:
                    output_lines.append((f"  {symbol} 已是最新（今日已拉取）", False))
                elif symbol in error_by_symbol:
                    output_lines.append(
                        (f"  ❌ {symbol} 拉取失败：{error_by_symbol[symbol]}", True)
                    )
                else:
                    output_lines.append(
                        (f"  ✅ {symbol} 拉取成功（{len(results[symbol])} 条 K 线）", False)
                    )

        lifecycle.progress(
            len(symbols),
            len(symbols),
            "K 线拉取完成",
            fresh=fresh,
            updated=updated,
            failed=failed,
        )
        elapsed = perf_counter() - started
        if failed:
            lifecycle.fail("部分股票拉取失败", failed=failed, success=success)
            output_lines.append(
                (f"❌ 拉取失败 {failed} 只 · 成功 {success} 只 · 耗时 {elapsed:.1f}s", True)
            )
            if not verbose:
                output_lines.extend(
                    (f"  {symbol}: {message}", True)
                    for symbol, message in errors[:3]
                )
            exit_code = 1
        elif updated == 0:
            output_lines.append(
                (f"✅ 已最新 · {fresh} 只无需更新 · 耗时 {elapsed:.1f}s", False)
            )
        else:
            suffix = f" · 已最新 {fresh} 只" if fresh else ""
            output_lines.append(
                (f"🔄 更新 {updated} 只{suffix} · 耗时 {elapsed:.1f}s", False)
            )

    for line, is_error in output_lines:
        typer.echo(line, err=is_error)
    if exit_code is not None:
        raise typer.Exit(exit_code)

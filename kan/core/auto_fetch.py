"""数据命令的自动补缓存 helper。"""
from __future__ import annotations

import contextlib

from kan.infra.errors import network_error_msg


def auto_fetch_stale(
    pairs: list[tuple[str, str]],
    *,
    days: int | None = None,
) -> None:
    """自动拉取缺失或过期（非今天）的自选股数据。"""
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    console = Console(stderr=True)
    n_total = len(pairs)

    with console.status(
        "[yellow]⏳ 加载数据模块...[/yellow]",
        spinner="dots",
    ) as status:
        from kan.data.fetcher import fetch_batch, is_fresh

        status.update(
            f"[yellow]⏳ 加载交易日历 · {n_total} 只自选股待检查...[/yellow]"
        )
        from kan.core.trading_calendar import latest_trade_date
        with contextlib.suppress(Exception):
            _ = latest_trade_date()

        status.update(
            f"[yellow]⏳ 检查缓存 · 0/{n_total} 只 · "
            f"首次稍慢 · 后续秒级[/yellow]"
        )
        stale: list[tuple[str, str]] = []
        update_every = max(1, n_total // 20)
        for i, (sym, name) in enumerate(pairs):
            fresh = is_fresh(sym) if days is None else is_fresh(sym, min_rows=days)
            if not fresh:
                stale.append((sym, name))
            if (i + 1) % update_every == 0 or i + 1 == n_total:
                status.update(
                    f"[yellow]⏳ 检查缓存 · {i + 1}/{n_total} 只 · "
                    f"已发现 {len(stale)} 只 stale[/yellow]"
                )
    if not stale:
        return

    n = len(stale)

    initial_workers: int | None = None
    if n >= 30:
        est_low = max(1, n // 60)
        est_high = max(2, n // 20)
        from kan.data.fetcher import resolve_batch_worker_bounds
        initial_workers, max_workers = resolve_batch_worker_bounds()
        worker_label = (
            f"动态并发 {initial_workers}"
            if initial_workers == max_workers
            else f"动态并发 {initial_workers}-{max_workers}"
        )
        console.print(
            f"[yellow]需更新 {n} 只股票数据 · {worker_label} · "
            f"预计 {est_low}-{est_high} 分钟[/yellow]"
        )
    elif n > 5:
        console.print(f"[yellow]更新 {n} 只股票数据...[/yellow]")

    name_map = dict(stale)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[dim]({task.completed}/{task.total})[/dim]"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("⏳ 拉取数据...", total=n)

        fails: list[str] = []
        current_workers = initial_workers

        def _on_done(symbol: str, ok: bool, _err_msg: str | None) -> None:
            full_name = name_map.get(symbol, symbol).replace(" ", "")
            name = full_name if len(full_name) <= 4 else full_name[:3] + "…"
            if not ok:
                fails.append(symbol)
            current_fail = len(fails)
            desc = (
                f"⏳ 补数据 {n} 只 · ✅ {name}" if ok
                else f"⏳ 补数据 {n} 只 · ❌ {name}"
            )
            if current_workers is not None:
                desc += f" · 并发 {current_workers}"
            if current_fail > 0:
                desc += f" · 失败 {current_fail}"
            progress.update(task_id, advance=1, description=desc)

        def _on_progress_state(state) -> None:
            nonlocal current_workers
            current_workers = state.concurrency

        try:
            fetch_kwargs = {"days": days} if days is not None else {}
            results, errors = fetch_batch(
                [s for s, _ in stale],
                **fetch_kwargs,
                force=True,
                on_progress=_on_done,
                on_progress_state=_on_progress_state,
            )
        except KeyboardInterrupt:
            progress.stop()
            console.print("\n  [yellow]已中断 · 已完成的数据已保存[/yellow]")
            import os as _os
            _os._exit(130)

    success_count = len(results)
    if errors:
        console.print(
            f"  [green]✅ 成功 {success_count}[/green] · "
            f"[red]❌ 失败 {len(errors)}[/red]"
        )
        for i, (sym, raw_err) in enumerate(errors.items()):
            if i >= 5:
                console.print(
                    f"  [dim]...及 {len(errors) - 5} 只失败 · "
                    f"`kan fetch` 重试[/dim]"
                )
                break
            name = name_map.get(sym, sym).replace(" ", "")
            console.print(
                f"  [red]· {name} ({sym}) · {network_error_msg(raw_err)}[/red]"
            )
    else:
        console.print(f"  [green]✅ {success_count} 只全部更新完成[/green]")
    console.print()

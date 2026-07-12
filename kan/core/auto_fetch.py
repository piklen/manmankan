"""数据命令的自动补缓存 helper。"""
from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from kan.infra.errors import network_error_msg

if TYPE_CHECKING:
    from kan.infra.lifecycle import OperationLifecycle


def auto_fetch_stale(
    pairs: list[tuple[str, str]],
    *,
    days: int | None = None,
    lifecycle: OperationLifecycle | None = None,
) -> None:
    """自动拉取缺失或过期缓存；反馈通过可选 lifecycle 上报。"""
    if lifecycle is not None:
        lifecycle.phase("加载数据模块", target_count=len(pairs))
    from kan.data.fetcher import fetch_batch, is_fresh

    n_total = len(pairs)
    if lifecycle is not None:
        lifecycle.phase("加载交易日历", target_count=n_total)
    from kan.core.trading_calendar import latest_trade_date
    with contextlib.suppress(Exception):
        _ = latest_trade_date()

    if lifecycle is not None:
        lifecycle.phase("检查缓存", target_count=n_total)
    stale: list[tuple[str, str]] = []
    update_every = max(1, n_total // 20)
    for i, (sym, name) in enumerate(pairs):
        fresh = is_fresh(sym) if days is None else is_fresh(sym, min_rows=days)
        if not fresh:
            stale.append((sym, name))
        if lifecycle is not None and (
            (i + 1) % update_every == 0 or i + 1 == n_total
        ):
            lifecycle.progress(
                i + 1,
                n_total,
                "检查缓存",
                stale_count=len(stale),
            )
    if not stale:
        return

    n = len(stale)
    initial_workers: int | None = None
    max_workers: int | None = None
    if n >= 30:
        from kan.data.fetcher import resolve_batch_worker_bounds

        initial_workers, max_workers = resolve_batch_worker_bounds()
    if lifecycle is not None:
        lifecycle.wait(
            "等待补齐缓存",
            stale_count=n,
            initial_workers=initial_workers,
            max_workers=max_workers,
        )

    completed = 0
    failures: list[str] = []
    current_workers = initial_workers

    def _on_done(symbol: str, ok: bool, _err_msg: str | None) -> None:
        nonlocal completed
        completed += 1
        if not ok:
            failures.append(symbol)
        if lifecycle is not None:
            lifecycle.progress(
                completed,
                n,
                "补齐缓存",
                symbol=symbol,
                failure_count=len(failures),
                concurrency=current_workers,
            )

    def _on_progress_state(state) -> None:
        nonlocal current_workers
        current_workers = state.concurrency

    fetch_kwargs = {"days": days} if days is not None else {}
    results, errors = fetch_batch(
        [symbol for symbol, _name in stale],
        **fetch_kwargs,
        force=True,
        on_progress=_on_done,
        on_progress_state=_on_progress_state,
    )
    if errors and lifecycle is not None:
        samples = [
            {
                "symbol": symbol,
                "error": network_error_msg(raw_error),
            }
            for symbol, raw_error in list(errors.items())[:5]
        ]
        lifecycle.degraded(
            "部分缓存补齐失败",
            success_count=len(results),
            failure_count=len(errors),
            samples=samples,
        )

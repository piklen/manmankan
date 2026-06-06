"""Shared scan use case.

The CLI owns Typer arguments, terminal rendering, snapshots, and diff output.
This module owns the scan data flow so future web/API surfaces can reuse the
same result object instead of copying CLI command logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kan.core.models import BoardMeta, HotMeta, StockScanResult, ThemeMeta
from kan.core.pipeline import DataCtx
from kan.core.stock_set import StockSet

ScanMode = Literal["low", "high"]


@dataclass(frozen=True)
class ScanRequest:
    """Input for one scan run."""

    stock_set: StockSet
    mode: ScanMode = "low"
    periods: list[int] | None = None
    signal_only: bool = False
    exclude_st: bool = False
    show_progress: bool = True


@dataclass(frozen=True)
class ScanServiceResult:
    """Render-neutral result for `kan scan`.

    `all_results` is the enriched unfiltered scan output, used by CLI snapshots
    and diff. `results` is the display/export subset after request filters.
    """

    ctx: DataCtx
    mode: ScanMode
    all_results: list[StockScanResult]
    results: list[StockScanResult]
    board_index_result: StockScanResult | None = None

    @property
    def meta(self) -> BoardMeta | HotMeta | ThemeMeta | None:
        return self.ctx.meta


def run_scan(request: ScanRequest) -> ScanServiceResult:
    """Run the scan data pipeline and return a render-neutral result."""
    from kan.core.enrich import enrich_scan_rows
    from kan.core.pipeline import run_data_pipeline
    from kan.core.scanner import scan_batch

    ctx = run_data_pipeline(
        request.stock_set,
        compute=scan_batch,
        mode=request.mode,
        periods=request.periods,
        fetch_days=max(request.periods) if request.periods else None,
        show_progress=request.show_progress,
        exit_on_resolve_error=False,
    )
    board_index_result = _scan_board_index(ctx.meta, periods=request.periods)
    all_results = enrich_scan_rows(ctx.results, data_cutoff=ctx.freshness.data_cutoff)
    _apply_membership_markers(all_results, request.stock_set)
    results = _filter_scan_results(
        all_results,
        mode=request.mode,
        signal_only=request.signal_only,
        exclude_st=request.exclude_st,
    )
    return ScanServiceResult(
        ctx=ctx,
        mode=request.mode,
        all_results=all_results,
        results=results,
        board_index_result=board_index_result,
    )


def _filter_scan_results(
    results: list[StockScanResult],
    *,
    mode: ScanMode,
    signal_only: bool,
    exclude_st: bool,
) -> list[StockScanResult]:
    filtered = [r for r in results if not r.is_st] if exclude_st else list(results)
    if not signal_only:
        return filtered
    if mode == "high":
        return [r for r in filtered if r.high_resonance > 0]
    return [r for r in filtered if r.low_resonance > 0]


def _scan_board_index(
    meta: BoardMeta | HotMeta | ThemeMeta | None,
    periods: list[int] | None = None,
) -> StockScanResult | None:
    """Scan industry/theme index K-line when available for contextual rows."""
    from kan.core.scanner import scan_stock

    if isinstance(meta, BoardMeta):
        return scan_stock(meta.index_kline, meta.board.code, meta.board.name, periods=periods)
    if isinstance(meta, ThemeMeta) and not meta.index_kline.empty:
        return scan_stock(meta.index_kline, meta.theme.code, meta.theme.name, periods=periods)
    return None


def _apply_membership_markers(results: list[StockScanResult], stock_set: StockSet) -> None:
    membership = getattr(stock_set, "membership", None)
    if not callable(membership):
        return
    for row in results:
        in_watchlist, in_holding = membership(row.symbol)
        row.in_watchlist = in_watchlist
        row.in_holding = in_holding

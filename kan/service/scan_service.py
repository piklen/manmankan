"""Shared scan use case.

The CLI owns Typer arguments, terminal rendering, snapshots, and diff output.
This module owns the scan data flow so future web/API surfaces can reuse the
same result object instead of copying CLI command logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

from kan.core.models import BoardMeta, HotMeta, StockScanResult, ThemeMeta
from kan.core.pipeline import DataCtx
from kan.core.stock_set import StockSet

ScanMode = Literal["low", "high"]
SCAN_ENRICH_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class ScanRequest:
    """Input for one scan run."""

    stock_set: StockSet
    mode: ScanMode = "low"
    periods: list[int] | None = None
    signal_only: bool = False
    exclude_st: bool = False
    exclude_star: bool = False
    exclude_bj: bool = False
    show_progress: bool = True
    include_external_context: bool = True
    enrich_timeout_seconds: float | None = SCAN_ENRICH_TIMEOUT_SECONDS


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
    all_results = (
        _enrich_scan_rows_best_effort(
            ctx.results,
            data_cutoff=ctx.freshness.data_cutoff,
            timeout_seconds=request.enrich_timeout_seconds,
        )
        if request.include_external_context
        else _apply_retail_facts_best_effort(ctx.results)
    )
    _apply_membership_markers(all_results, request.stock_set)
    results = _filter_scan_results(
        all_results,
        mode=request.mode,
        signal_only=request.signal_only,
        exclude_st=request.exclude_st,
        exclude_star=request.exclude_star,
        exclude_bj=request.exclude_bj,
    )
    return ScanServiceResult(
        ctx=ctx,
        mode=request.mode,
        all_results=all_results,
        results=results,
        board_index_result=board_index_result,
    )


def _enrich_scan_rows_best_effort(
    results: list[StockScanResult],
    *,
    data_cutoff: date | None,
    timeout_seconds: float | None,
) -> list[StockScanResult]:
    """Best-effort optional scan enrichment.

    位置扫描是主路径；PE/PB、资金、除权事件来自外部源，只能增益，不能拖死
    `kan scan`。这里用 daemon thread + queue，而不是 ThreadPoolExecutor：
    executor shutdown 会等待不可取消的网络调用，反而失去超时意义。
    """
    if not results:
        return []
    if timeout_seconds is None or timeout_seconds <= 0:
        from kan.core.enrich import enrich_scan_rows

        return enrich_scan_rows(results, data_cutoff=data_cutoff)

    import queue
    import threading

    out: queue.Queue[tuple[str, list[StockScanResult] | Exception]] = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            from kan.core.enrich import enrich_scan_rows

            out.put(("ok", enrich_scan_rows(results, data_cutoff=data_cutoff)))
        except Exception as e:
            out.put(("err", e))

    threading.Thread(
        target=_worker,
        name="kan-scan-enrich",
        daemon=True,
    ).start()

    try:
        kind, payload = out.get(timeout=timeout_seconds)
    except queue.Empty:
        from kan.infra.log import debug_log

        debug_log(
            __name__,
            "scan enrich timeout",
            TimeoutError(f">{timeout_seconds:.1f}s"),
        )
        return _apply_retail_facts_best_effort(results)

    if kind == "ok":
        return cast(list[StockScanResult], payload)

    from kan.infra.log import debug_log

    err = payload if isinstance(payload, BaseException) else RuntimeError(str(payload))
    debug_log(__name__, "scan enrich failed", err)
    return _apply_retail_facts_best_effort(results)


def _apply_retail_facts_best_effort(
    results: list[StockScanResult],
) -> list[StockScanResult]:
    """Attach local retail facts without touching external data sources."""
    if not results:
        return []
    try:
        from kan.storage.positions import load_positions

        cash = load_positions().cash
    except Exception:
        cash = None
    try:
        from kan.core.retail_facts import apply_retail_facts

        return [apply_retail_facts(r, cash=cash) for r in results]
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "scan retail facts failed", e)
        return list(results)


def _filter_scan_results(
    results: list[StockScanResult],
    *,
    mode: ScanMode,
    signal_only: bool,
    exclude_st: bool,
    exclude_star: bool,
    exclude_bj: bool,
) -> list[StockScanResult]:
    filtered = [r for r in results if not r.is_st] if exclude_st else list(results)
    if exclude_star or exclude_bj:
        from kan.core.retail_facts import market_board

        filtered = [
            r for r in filtered
            if not (exclude_star and market_board(r.symbol) == "科创板")
            and not (exclude_bj and market_board(r.symbol) == "北交所")
        ]
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

"""单股 info 用例服务。

本模块只产出领域对象和基础状态,不负责 Typer 参数、Rich 渲染或导出格式。
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from datetime import date

from kan.core.models import (
    BoardPositionContext,
    BoardPositionPeriod,
    MoneyflowMetrics,
    SentimentMetrics,
    StockScanResult,
    ValuationContext,
    ValuationMetrics,
    VolumeState,
)
from kan.core.scanner import TrendResult

_MIN_BOARD_CONTEXT_SAMPLE = 3

FetchStatus = Callable[[str, str], AbstractContextManager[object]]


class InfoDataUnavailableError(RuntimeError):
    """本地缓存没有可用于单股 info 的 K 线数据。"""


class InfoFetchError(RuntimeError):
    """自动补数据失败。"""

    def __init__(self, symbol: str, name: str, cause: Exception) -> None:
        self.symbol = symbol
        self.name = name
        self.cause = cause
        super().__init__(str(cause))


@dataclass(frozen=True)
class InfoRequest:
    """单股 info 输入。"""

    symbol_or_name: str
    allow_fetch: bool = True
    include_external_context: bool = True
    include_valuation_context: bool = False
    include_board_context: bool = True
    fetch_status: FetchStatus | None = None


@dataclass(frozen=True)
class InfoServiceResult:
    """单股 info 领域结果。"""

    symbol: str
    name: str
    result: StockScanResult
    trend: TrendResult
    volume: VolumeState | None
    data_cutoff: date | None
    fetched_at: str | None
    stale: bool
    valuation: ValuationMetrics | None = None
    valuation_context: ValuationContext | None = None
    moneyflow: MoneyflowMetrics | None = None
    sentiment: SentimentMetrics | None = None
    board_context: BoardPositionContext | None = None


def get_stock_info(request: InfoRequest) -> InfoServiceResult:
    """返回单股 info 数据。

    allow_fetch=False 时只读本地缓存,不触发网络补数据。
    """
    from kan.core.scanner import calc_trend, calc_volume_state, scan_stock
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.fetcher import cache_age, data_cutoff_date, fetch_kline, get_cached, is_fresh
    from kan.storage.watchlist import resolve_symbol_or_name

    symbol, name = resolve_symbol_or_name(request.symbol_or_name)

    if request.allow_fetch and not is_fresh(symbol):
        try:
            cm = (
                request.fetch_status(symbol, name)
                if request.fetch_status is not None
                else nullcontext()
            )
            with cm:
                fetch_kline(symbol, force=True)
        except Exception as e:
            raise InfoFetchError(symbol, name, e) from e

    df = get_cached(symbol)
    if df is None or df.empty:
        raise InfoDataUnavailableError(symbol)

    result = scan_stock(df, symbol, name)
    result = _apply_retail_facts(result)
    trend = calc_trend(df, symbol, name)
    volume = calc_volume_state(df)
    valuation, moneyflow, sentiment = _enrich_info_best_effort(
        result,
        enabled=request.include_external_context,
    )
    data_cutoff = data_cutoff_date(symbol)
    fetched_at = cache_age(symbol) or None
    stale = data_cutoff is None or data_cutoff < latest_trade_date()
    valuation_context = _valuation_context_best_effort(
        symbol,
        enabled=request.include_valuation_context,
    )
    board_context = (
        _build_board_position_context(result)
        if request.include_board_context else None
    )

    return InfoServiceResult(
        symbol=symbol,
        name=name,
        result=result,
        trend=trend,
        volume=volume,
        data_cutoff=data_cutoff,
        fetched_at=fetched_at,
        stale=stale,
        valuation=valuation,
        valuation_context=valuation_context,
        moneyflow=moneyflow,
        sentiment=sentiment,
        board_context=board_context,
    )


def _apply_retail_facts(result: StockScanResult) -> StockScanResult:
    try:
        from kan.storage.positions import load_positions

        cash = load_positions().cash
    except Exception:
        cash = None
    from kan.core.retail_facts import apply_retail_facts

    enriched = apply_retail_facts(result, cash=cash)
    try:
        from kan.core.stock_set import WatchlistHoldingsSet

        in_watchlist, in_holding = WatchlistHoldingsSet().membership(result.symbol)
    except Exception:
        in_watchlist, in_holding = False, False
    return enriched.model_copy(update={
        "in_watchlist": in_watchlist,
        "in_holding": in_holding,
    })


def _enrich_info_best_effort(
    result: StockScanResult,
    *,
    enabled: bool,
) -> tuple[ValuationMetrics | None, MoneyflowMetrics | None, SentimentMetrics | None]:
    if not enabled:
        return None, None, None
    try:
        from kan.core.enrich import enrich_results

        enriched = enrich_results([result], need_moneyflow=True, need_sentiment=True)[0]
        return enriched.valuation, enriched.moneyflow, enriched.sentiment
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, f"info enrich failed · {result.symbol}", e)
        return None, None, None


def enrich_info_results_best_effort(
    results: list[InfoServiceResult],
) -> list[InfoServiceResult]:
    """批量补齐对比页需要的估值与资金流，避免每只股票重复拉全市场截面。"""
    if not results:
        return []
    try:
        from kan.core.enrich import enrich_results

        enriched = enrich_results(
            [item.result for item in results],
            need_moneyflow=True,
        )
        return [
            replace(
                item,
                valuation=row.valuation,
                moneyflow=row.moneyflow,
            )
            for item, row in zip(results, enriched, strict=True)
        ]
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "batch info enrich failed", e)
        return results


def _valuation_context_best_effort(
    symbol: str,
    *,
    enabled: bool,
) -> ValuationContext | None:
    if not enabled:
        return None
    try:
        from kan.core.valuation_context import build_valuation_context

        return build_valuation_context(symbol)
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, f"info valuation context failed · {symbol}", e)
        return None


def _build_board_position_context(result: StockScanResult) -> BoardPositionContext | None:
    """所属申万行业内的位置均值/排名 · 仅用本地 K 线缓存,失败时静默降级。"""
    try:
        from kan.core.scanner import scan_stock
        from kan.data import boards
        from kan.data.fetcher import get_cached
        from kan.data.industry_map import fetch_sw_l1_map
        from kan.infra.log import debug_log

        target_periods = [p.period for p in result.periods if not p.insufficient]
        if not target_periods:
            return None

        industry = fetch_sw_l1_map().get(result.symbol)
        if not industry:
            return None

        board = boards.search_industry(industry)
        constituents = boards.get_industry_constituents(board)
        positions: dict[int, list[float]] = {p: [] for p in target_periods}
        seen_codes: set[str] = set()
        cached_codes: set[str] = set()

        for code, name in constituents:
            if code == result.symbol:
                peer = result
            else:
                df = get_cached(code)
                if df is None or df.empty:
                    continue
                try:
                    peer = scan_stock(df, code, name, periods=target_periods)
                except Exception as e:
                    debug_log(__name__, f"info board peer scan failed · {code}", e)
                    continue
            seen_codes.add(code)
            has_position = False
            for pr in peer.periods:
                if pr.insufficient or pr.period not in positions:
                    continue
                positions[pr.period].append(float(pr.position_pct))
                has_position = True
            if has_position:
                cached_codes.add(code)

        if result.symbol not in seen_codes:
            for pr in result.periods:
                if pr.insufficient or pr.period not in positions:
                    continue
                positions[pr.period].append(float(pr.position_pct))
                cached_codes.add(result.symbol)

        periods = []
        for pr in result.periods:
            if pr.insufficient:
                continue
            vals = positions.get(pr.period, [])
            if len(vals) < _MIN_BOARD_CONTEXT_SAMPLE:
                continue
            rank = 1 + sum(v < pr.position_pct for v in vals)
            periods.append(BoardPositionPeriod(
                period=pr.period,
                position_pct=round(float(pr.position_pct), 1),
                board_avg_pct=round(sum(vals) / len(vals), 1),
                rank_low_to_high=rank,
                sample=len(vals),
            ))

        if not periods:
            return None
        return BoardPositionContext(
            industry=industry,
            board_code=getattr(board, "code", None),
            board_level=getattr(board, "level", None),
            constituent_count=len(constituents),
            cached_sample=len(cached_codes),
            periods=periods,
        )
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, f"info board context failed · {result.symbol}", e)
        return None

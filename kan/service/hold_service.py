"""真实持仓 Web/CLI 共用用例服务。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kan.core.positions import PositionsSummary

RefreshStale = Callable[[list[tuple[str, str]], int | None], None]


@dataclass(frozen=True)
class HoldRequest:
    """持仓总览输入。"""

    no_refresh: bool = False
    check_corporate_actions: bool = True
    refresh_stale: RefreshStale | None = None
    realtime_fail_soft: bool = True


def build_hold_summary(request: HoldRequest | None = None) -> PositionsSummary:
    """构建持仓总览;失败由调用边界决定如何呈现。"""
    if request is None:
        request = HoldRequest()
    from kan.core.positions import PriceSnapshot, evaluate_positions, price_from_kline
    from kan.core.scanner import scan_stock
    from kan.core.trading_calendar import PHASE_INTRADAY, latest_trade_date, market_phase
    from kan.data.fetcher import get_cached
    from kan.storage.positions import load_positions

    book = load_positions()
    _resolve_placeholder_names(book)
    pairs = [(p.symbol, p.name) for p in book.positions]
    if pairs and not request.no_refresh:
        refresh = request.refresh_stale or _refresh_stale_silent
        refresh(pairs, 180)

    cached = {symbol: get_cached(symbol) for symbol, _name in pairs}
    prices = {symbol: price_from_kline(symbol, df) for symbol, df in cached.items()}
    scans = {}
    for symbol, name in pairs:
        df = cached.get(symbol)
        if df is None or getattr(df, "empty", True):
            continue
        scans[symbol] = scan_stock(df, symbol, name, periods=[30, 60, 180])

    phase = market_phase()
    price_mode = "close"
    if phase == PHASE_INTRADAY and pairs and not request.no_refresh:
        from kan.data.realtime import fetch_realtime_quotes

        if request.realtime_fail_soft:
            try:
                quotes = fetch_realtime_quotes([symbol for symbol, _name in pairs])
            except Exception:
                quotes = {}
        else:
            quotes = fetch_realtime_quotes([symbol for symbol, _name in pairs])
        if quotes:
            price_mode = "realtime"
        for symbol, quote in quotes.items():
            fallback = prices.get(symbol)
            prices[symbol] = PriceSnapshot(
                symbol=symbol,
                price=quote.price,
                prev_close=quote.prev_close or (fallback.prev_close if fallback else None),
                source=quote.source,
                data_cutoff=fallback.data_cutoff if fallback else None,
                trade_time=quote.trade_time,
                status=quote.status,
            )

    return evaluate_positions(
        book,
        prices=prices,
        scans=scans,
        price_mode=price_mode,
        as_of=latest_trade_date(),
        check_corporate_actions=request.check_corporate_actions,
    )


def _resolve_placeholder_names(book) -> None:
    """用本地名称缓存补 `name == symbol` 的占位名;只读 cache,不触发网络。"""
    placeholders = [p for p in book.positions if p.name == p.symbol]
    if not placeholders:
        return
    from kan.storage.watchlist_names import load_stock_names_cache

    names = load_stock_names_cache(allow_stale=True) or {}
    for position in placeholders:
        resolved = names.get(position.symbol)
        if resolved:
            position.name = resolved


def _refresh_stale_silent(pairs: list[tuple[str, str]], days: int | None) -> None:
    """Web 路径静默补缓存;失败交给后续缓存降级。"""
    from contextlib import suppress

    from kan.data.fetcher import fetch_batch, is_fresh

    stale = [
        symbol for symbol, _name in pairs
        if not _fresh_enough(symbol, days, is_fresh)
    ]
    if not stale:
        return
    with suppress(Exception):
        if days is None:
            fetch_batch(stale, force=True)
        else:
            fetch_batch(stale, days=days, force=True)


def _fresh_enough(symbol: str, days: int | None, is_fresh) -> bool:
    if days is None:
        return bool(is_fresh(symbol))
    return bool(is_fresh(symbol, min_rows=days))

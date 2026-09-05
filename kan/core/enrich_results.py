"""find/scan 结果多维指标挂载。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kan.core.enrich_index import (
    _index_chip,
    _index_moneyflow,
    _index_sentiment,
    _index_technical,
    _index_valuations,
    _resolve_fallback_date,
)
from kan.core.enrich_rows import (
    _row_to_fundamentals,
    _row_to_shareholder,
)

if TYPE_CHECKING:
    from kan.core.models import (
        ChipMetrics,
        EnrichedResult,
        FundamentalMetrics,
        MoneyflowMetrics,
        SentimentMetrics,
        ShareholderMetrics,
        StockScanResult,
        TechnicalMetrics,
    )
    from kan.infra.lifecycle import OperationLifecycle


def fetch_enrichments(
    symbols: list[str],
    *,
    dimensions: set[str],
    trade_date: str | None = None,
    force: bool = False,
    require_source_dates: bool = False,
    lifecycle: OperationLifecycle | None = None,
) -> dict[str, dict[str, Any]]:
    """按代码取独立指标，不要求先取得行情或构造扫描结果。"""
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.metrics import fetch_metrics

    if not symbols:
        return {}

    fallback_date = _resolve_fallback_date(trade_date, latest_trade_date)

    val_by_symbol = {}
    if "valuation" in dimensions:
        df = fetch_metrics(trade_date=trade_date, symbols=symbols, force=force)
        val_by_symbol = _index_valuations(_daily_rows(df, require_source_dates), fallback_date)

    fund_by_symbol: dict[str, FundamentalMetrics] = {}
    if "fundamentals" in dimensions:
        from kan.data.fundamentals import fetch_fundamentals

        fetched = fetch_fundamentals(symbols, force=force, lifecycle=lifecycle)
        for sym, row in fetched.items():
            fund_by_symbol[sym] = _row_to_fundamentals(row)

    mf_by_symbol: dict[str, MoneyflowMetrics] = {}
    if "moneyflow" in dimensions:
        from kan.data.moneyflow import fetch_moneyflow

        mf_df = fetch_moneyflow(trade_date=trade_date, symbols=symbols, force=force)
        mf_by_symbol = _index_moneyflow(_daily_rows(mf_df, require_source_dates), fallback_date)

    tech_by_symbol: dict[str, TechnicalMetrics] = {}
    if "technical" in dimensions:
        from kan.data.technical import fetch_technical

        tech_df = fetch_technical(trade_date=trade_date, symbols=symbols, force=force)
        tech_by_symbol = _index_technical(_daily_rows(tech_df, require_source_dates), fallback_date)

    senti_by_symbol: dict[str, SentimentMetrics] = {}
    if "sentiment" in dimensions:
        from kan.data.sentiment import fetch_sentiment

        senti_df = fetch_sentiment(trade_date=trade_date, symbols=symbols, force=force)
        senti_by_symbol = _index_sentiment(_daily_rows(senti_df, require_source_dates), fallback_date)

    chip_by_symbol: dict[str, ChipMetrics] = {}
    if "chip" in dimensions:
        from kan.data.chip import fetch_chip

        chip_df = fetch_chip(trade_date=trade_date, symbols=symbols, force=force)
        chip_by_symbol = _index_chip(_daily_rows(chip_df, require_source_dates), fallback_date)

    sh_by_symbol: dict[str, ShareholderMetrics] = {}
    if "shareholder" in dimensions:
        from kan.data.shareholder import fetch_shareholder

        fetched = fetch_shareholder(symbols, force=force, lifecycle=lifecycle)
        for sym, row in fetched.items():
            sh_by_symbol[sym] = _row_to_shareholder(row)

    by_dimension: dict[str, dict[str, Any]] = {
        "valuation": val_by_symbol, "fundamentals": fund_by_symbol,
        "moneyflow": mf_by_symbol, "technical": tech_by_symbol,
        "sentiment": senti_by_symbol, "chip": chip_by_symbol, "shareholder": sh_by_symbol,
    }
    return {symbol: {name: values.get(symbol) for name, values in by_dimension.items() if name in dimensions}
            for symbol in symbols}


def enrich_results(
    results: list[StockScanResult],
    *,
    trade_date: str | None = None,
    need_valuation: bool = True,
    require_source_dates: bool = False,
    need_fundamentals: bool = False,
    need_moneyflow: bool = False,
    need_technical: bool = False,
    need_sentiment: bool = False,
    need_chip: bool = False,
    need_shareholder: bool = False,
    lifecycle: OperationLifecycle | None = None,
) -> list[EnrichedResult]:
    """扫描/筛选共用的挂载入口，取数由独立指标函数负责。"""
    from kan.core.models import EnrichedResult

    dimensions = {name for name, requested in (
        ("valuation", need_valuation), ("fundamentals", need_fundamentals),
        ("moneyflow", need_moneyflow), ("technical", need_technical),
        ("sentiment", need_sentiment), ("chip", need_chip), ("shareholder", need_shareholder),
    ) if requested}
    metrics = fetch_enrichments(
        [result.symbol for result in results], dimensions=dimensions,
        trade_date=trade_date, require_source_dates=require_source_dates, lifecycle=lifecycle,
    )
    return [EnrichedResult.from_scan(result, **metrics[result.symbol]) for result in results]


def _daily_rows(frame, require_source_dates: bool):
    """严格研究入口拒绝无源日期的日频行，避免旧转换器补入查询日期。"""
    from datetime import date

    import pandas as pd

    if not require_source_dates or frame is None or frame.empty:
        return frame
    if "trade_date" not in frame:
        return frame.iloc[:0]
    known = frame["trade_date"].map(lambda value: isinstance(value, date) and not pd.isna(value))
    return frame.loc[known]


__all__ = ["enrich_results", "fetch_enrichments"]

"""find/scan 结果多维指标挂载。"""
from __future__ import annotations

from typing import TYPE_CHECKING

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


def enrich_results(
    results: list[StockScanResult],
    *,
    trade_date: str | None = None,
    need_fundamentals: bool = False,
    need_moneyflow: bool = False,
    need_technical: bool = False,
    need_sentiment: bool = False,
    need_chip: bool = False,
    need_shareholder: bool = False,
    lifecycle: OperationLifecycle | None = None,
) -> list[EnrichedResult]:
    """给 scan 结果按需挂多维指标 · 返回 EnrichedResult 列表 (原序)。

    valuation 总挂 (截面廉价 · 现有行为)· fundamentals (逐股 · 贵) / moneyflow /
    technical / sentiment / chip (截面 · 廉价) 仅在对应 need_* 为 True 时挂
    (caller 按 filter 需求传 · 见 find_cmds)。

    Args:
        results: scan_batch / find 命中的 StockScanResult 列表
        trade_date: YYYYMMDD 截面日 · None → 最近交易日 (fetch 内部解析)
        need_fundamentals: True 时逐股拉 fina_indicator (--roe filter · 全市场代价高)
        need_moneyflow: True 时拉 moneyflow_dc 截面 (--moneyflow filter · 截面廉价)
        need_technical: True 时拉 stk_factor_pro 截面 (--rsi/--macd-dif/--macd/--kdj-j · 技术/情绪/筹码维度)
        need_sentiment: True 时拉 limit_list_d 截面 (--streak · 稀疏事件型 · 技术/情绪/筹码维度)
        need_chip: True 时拉 cyq_perf 截面 (--winner · 技术/情绪/筹码维度)
        need_shareholder: True 时逐股拉 stk_holdernumber + top10_floatholders
            (--holders/--top10/--north filter · 逐股 · 全市场 --all 不支持 · 股东持股维度)

    Returns:
        list[EnrichedResult] · 与 results 等长同序 · 每只按需挂各维度 (无数据时 None)。
        空 results → 空列表 (不触网)。
    """
    from kan.core.models import EnrichedResult
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.metrics import fetch_metrics

    if not results:
        return []

    symbols = [r.symbol for r in results]
    fallback_date = _resolve_fallback_date(trade_date, latest_trade_date)

    df = fetch_metrics(trade_date=trade_date, symbols=symbols)
    val_by_symbol = _index_valuations(df, fallback_date)

    fund_by_symbol: dict[str, FundamentalMetrics] = {}
    if need_fundamentals:
        from kan.data.fundamentals import fetch_fundamentals

        fetched = (
            fetch_fundamentals(symbols)
            if lifecycle is None
            else fetch_fundamentals(symbols, lifecycle=lifecycle)
        )
        for sym, row in fetched.items():
            fund_by_symbol[sym] = _row_to_fundamentals(row)

    mf_by_symbol: dict[str, MoneyflowMetrics] = {}
    if need_moneyflow:
        from kan.data.moneyflow import fetch_moneyflow

        mf_df = fetch_moneyflow(trade_date=trade_date, symbols=symbols)
        mf_by_symbol = _index_moneyflow(mf_df, fallback_date)

    tech_by_symbol: dict[str, TechnicalMetrics] = {}
    if need_technical:
        from kan.data.technical import fetch_technical

        tech_df = fetch_technical(trade_date=trade_date, symbols=symbols)
        tech_by_symbol = _index_technical(tech_df, fallback_date)

    senti_by_symbol: dict[str, SentimentMetrics] = {}
    if need_sentiment:
        from kan.data.sentiment import fetch_sentiment

        senti_df = fetch_sentiment(trade_date=trade_date, symbols=symbols)
        senti_by_symbol = _index_sentiment(senti_df, fallback_date)

    chip_by_symbol: dict[str, ChipMetrics] = {}
    if need_chip:
        from kan.data.chip import fetch_chip

        chip_df = fetch_chip(trade_date=trade_date, symbols=symbols)
        chip_by_symbol = _index_chip(chip_df, fallback_date)

    sh_by_symbol: dict[str, ShareholderMetrics] = {}
    if need_shareholder:
        from kan.data.shareholder import fetch_shareholder

        fetched = (
            fetch_shareholder(symbols)
            if lifecycle is None
            else fetch_shareholder(symbols, lifecycle=lifecycle)
        )
        for sym, row in fetched.items():
            sh_by_symbol[sym] = _row_to_shareholder(row)

    return [
        EnrichedResult.from_scan(
            r,
            valuation=val_by_symbol.get(r.symbol),
            fundamentals=fund_by_symbol.get(r.symbol),
            moneyflow=mf_by_symbol.get(r.symbol),
            technical=tech_by_symbol.get(r.symbol),
            sentiment=senti_by_symbol.get(r.symbol),
            chip=chip_by_symbol.get(r.symbol),
            shareholder=sh_by_symbol.get(r.symbol),
        )
        for r in results
    ]


__all__ = ["enrich_results"]

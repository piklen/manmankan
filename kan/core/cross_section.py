"""全市场截面取数编排 (地基-3 · kan find --all 截面专用路径)。

与 K 线管线 (pipeline.run_data_pipeline + scan_batch) 正交:K 线管线逐股
auto-fetch 历史 K 线 (全市场 ~5500 只 = 灾难) · 本模块走截面 (按 trade_date
一次拉全市场 daily_basic · 一次 HTTP) · 只算"市场客观事实 + 行业内分位 + 行业
中位" · **不带** K 线位置/共振 · **不带**历史估值分位 (逐股 HTTP 太贵 ·
PRD §3.2 截面 vs K 线代价不对称)。

数据流 (全部复用现成):
  stock_set.pairs()                    → [(code, name)] 骨架 (name 来源)
  metrics.fetch_metrics()              → 全市场截面 DataFrame (一次 HTTP · parquet 缓存)
  industry_map.fetch_sw_l1_map()       → {symbol: 申万一级}
  valuation_context.compute_cross_section_contexts() → 批量行业内分位 + 中位 (O(N))
  enrich._row_to_valuation()           → 单行截面 → ValuationMetrics (NaN→None 一处逻辑)

合规 (compliance §6/§7 · PRD §6):本层 valuation 仍承载原始指标 (同 enrich) ·
估值裸值是否对外由输出层 (export._valuation_public_dict) 决定 · 数据层不过滤。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from kan.core.models import (
        ChipMetrics,
        MoneyflowMetrics,
        SentimentMetrics,
        TechnicalMetrics,
        ValuationContext,
        ValuationMetrics,
    )
    from kan.core.stock_set import StockSet


@dataclass(frozen=True)
class CrossSectionRow:
    """单只股票的截面取数结果 · code/name + 客观事实 valuation + 估值对照 context。

    整合-1 加 moneyflow (主力资金截面)· 整合-2 加 technical/sentiment/chip (技术/情绪/
    筹码截面 · 支持 --all --rsi/--macd-dif/--macd/--kdj-j/--streak/--winner filter)。
    """

    code: str
    name: str
    valuation: ValuationMetrics | None
    valuation_context: ValuationContext | None
    moneyflow: MoneyflowMetrics | None = None    # 整合-1 · 主力资金截面 (None=无数据/早期)
    technical: TechnicalMetrics | None = None    # 整合-2 · 技术面截面 (None=无数据)
    sentiment: SentimentMetrics | None = None    # 整合-2 · 情绪截面 (None=当日未涨跌停)
    chip: ChipMetrics | None = None              # 整合-2 · 筹码截面 (None=无数据)


@dataclass(frozen=True)
class CrossSectionCtx:
    """截面取数编排产出快照 · 命令层只读。

    rows:        逐股截面结果 (顺序跟随 stock_set.pairs())
    pool_size:   池内总股票数 (= len(pairs) · 筛前)
    data_cutoff: 截面数据交易日 (cross 的 max trade_date · None 若无数据)
    stale:       data_cutoff is None 或 < latest_trade_date (截面缓存滞后)
    """

    rows: list[CrossSectionRow]
    pool_size: int
    data_cutoff: date | None
    stale: bool


def _cross_data_cutoff(cross: pd.DataFrame) -> date | None:
    """截面 DataFrame 的最大 trade_date (已规范化为 date · NaT 剔除)。"""
    import pandas as pd

    if "trade_date" not in cross.columns:
        return None
    vals = [d for d in cross["trade_date"] if d is not None and not pd.isna(d)]
    return max(vals) if vals else None


def run_cross_section(
    stock_set: StockSet,
    *,
    trade_date: str | None = None,
) -> CrossSectionCtx:
    """全市场截面编排 · 不走 run_data_pipeline (K 线管线) · 截面一次拉全市场。

    Args:
        stock_set: 任意 StockSet (--all 传 AllStocksSet · name 来源 + 池范围)
        trade_date: YYYYMMDD 截面日 · None → 最近交易日 (fetch_metrics 内部解析)

    Returns:
        CrossSectionCtx · rows 顺序跟随 stock_set.pairs()。
        无 token / 空池 / 无截面 → rows 空 (caller 按空判断报错 · 优雅降级)。
    """
    from kan.core.enrich import (
        _resolve_fallback_date,
        _row_to_chip,
        _row_to_moneyflow,
        _row_to_sentiment,
        _row_to_technical,
        _row_to_valuation,
    )
    from kan.core.trading_calendar import latest_trade_date
    from kan.core.valuation_context import compute_cross_section_contexts
    from kan.data.chip import fetch_chip
    from kan.data.industry_map import fetch_sw_l1_map
    from kan.data.metrics import _DEFAULT_LOOKBACK_DAYS, fetch_metrics
    from kan.data.moneyflow import fetch_moneyflow
    from kan.data.sentiment import fetch_sentiment
    from kan.data.technical import fetch_technical

    pairs = stock_set.pairs()
    pool_size = len(pairs)
    if not pairs:
        return CrossSectionCtx(rows=[], pool_size=0, data_cutoff=None, stale=True)

    codes = [c for c, _ in pairs]
    cross = fetch_metrics(trade_date=trade_date, symbols=codes)
    if cross is None or cross.empty:
        # 无 token / 无截面 → 全空 (caller 报错引导配 token)
        return CrossSectionCtx(
            rows=[], pool_size=pool_size, data_cutoff=None, stale=True,
        )

    l1_map = fetch_sw_l1_map()
    contexts = compute_cross_section_contexts(
        cross, l1_map, lookback_days=_DEFAULT_LOOKBACK_DAYS,
    )
    fallback_date = _resolve_fallback_date(trade_date, latest_trade_date)
    by_symbol = {str(r.get("symbol", "")).strip(): r for _, r in cross.iterrows()}

    # 主力资金截面 (整合-1 · 同截面廉价一次 HTTP · 支持 --all --moneyflow · 早期/无数据降级)
    mf = fetch_moneyflow(trade_date=trade_date, symbols=codes)
    mf_by_symbol = (
        {str(r.get("symbol", "")).strip(): r for _, r in mf.iterrows()}
        if mf is not None and not mf.empty
        else {}
    )

    # 技术/情绪/筹码截面 (整合-2 · 同截面廉价 · 取数全维度 · 无条件挂 · 无数据/早期降级)
    tech = fetch_technical(trade_date=trade_date, symbols=codes)
    tech_by_symbol = (
        {str(r.get("symbol", "")).strip(): r for _, r in tech.iterrows()}
        if tech is not None and not tech.empty
        else {}
    )
    senti = fetch_sentiment(trade_date=trade_date, symbols=codes)
    senti_by_symbol = (
        {str(r.get("symbol", "")).strip(): r for _, r in senti.iterrows()}
        if senti is not None and not senti.empty
        else {}
    )
    chip = fetch_chip(trade_date=trade_date, symbols=codes)
    chip_by_symbol = (
        {str(r.get("symbol", "")).strip(): r for _, r in chip.iterrows()}
        if chip is not None and not chip.empty
        else {}
    )

    rows: list[CrossSectionRow] = []
    for code, name in pairs:
        row = by_symbol.get(code)
        valuation = _row_to_valuation(row, fallback_date) if row is not None else None
        mf_row = mf_by_symbol.get(code)
        moneyflow = _row_to_moneyflow(mf_row, fallback_date) if mf_row is not None else None
        tech_row = tech_by_symbol.get(code)
        technical = _row_to_technical(tech_row, fallback_date) if tech_row is not None else None
        senti_row = senti_by_symbol.get(code)
        sentiment = _row_to_sentiment(senti_row, fallback_date) if senti_row is not None else None
        chip_row = chip_by_symbol.get(code)
        chip_metrics = _row_to_chip(chip_row, fallback_date) if chip_row is not None else None
        rows.append(CrossSectionRow(
            code=code,
            name=name,
            valuation=valuation,
            valuation_context=contexts.get(code),
            moneyflow=moneyflow,
            technical=technical,
            sentiment=sentiment,
            chip=chip_metrics,
        ))

    data_cutoff = _cross_data_cutoff(cross)
    stale = data_cutoff is None or data_cutoff < latest_trade_date()
    return CrossSectionCtx(
        rows=rows, pool_size=pool_size, data_cutoff=data_cutoff, stale=stale,
    )


__all__ = ["CrossSectionCtx", "CrossSectionRow", "run_cross_section"]

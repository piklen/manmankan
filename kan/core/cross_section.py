"""全市场截面取数编排 (地基-3 · kan find --all 截面专用路径)。

与 K 线管线 (pipeline.run_data_pipeline + scan_batch) 正交:K 线管线逐股
auto-fetch 历史 K 线 (全市场 ~5500 只 = 灾难) · 本模块主路径走截面 (按 trade_date
一次拉全市场 daily_basic) · 只算"市场客观事实 + 行业内分位 + 行业中位"。
需要位置/共振/涨幅/连阳时,通过 `need_kline=True` 额外挂载每日批量 K 线快照,
仍避免逐股拉 K。历史估值分位暂不做 (逐股 HTTP 太贵 · PRD §3.2 截面 vs K 线代价不对称)。

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
        PeriodResult,
        SentimentMetrics,
        StockScanResult,
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
    scan: StockScanResult | None = None          # --all K 线裸值快照 (pos/gain/up_days)


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


def _max_date_from_series(values) -> date | None:
    """从 pandas Series / iterable 里取最大 date · 空或全 NaT 返回 None。"""
    import pandas as pd

    vals = [d for d in values if d is not None and not pd.isna(d)]
    return max(vals) if vals else None


def _snapshot_row_to_scan(row, name: str, periods: list[int]) -> StockScanResult | None:
    """kline_snapshot 一行 → StockScanResult · 复用现有 matcher/export context。"""
    import pandas as pd

    from kan.core.models import PeriodResult, StockScanResult

    symbol = str(row.get("symbol", "")).strip()
    trade_date = row.get("trade_date")
    close = row.get("close")
    if not symbol or trade_date is None or pd.isna(trade_date) or close is None or pd.isna(close):
        return None
    trade_date = pd.Timestamp(trade_date).date()
    period_results: list[PeriodResult] = []
    for p in periods:
        insufficient = bool(row.get(f"insufficient_{p}", True))
        pos = row.get(f"pos_{p}")
        low = row.get(f"low_{p}")
        high = row.get(f"high_{p}")
        gain = row.get(f"gain_{p}")
        if insufficient or pos is None or pd.isna(pos):
            period_results.append(PeriodResult(
                period=p,
                n_low=0.0,
                n_high=0.0,
                position_pct=0.0,
                at_low=False,
                at_high=False,
                insufficient=True,
                gain_pct=None if gain is None or pd.isna(gain) else float(gain),
            ))
            continue
        period_results.append(PeriodResult(
            period=p,
            n_low=0.0 if low is None or pd.isna(low) else round(float(low), 2),
            n_high=0.0 if high is None or pd.isna(high) else round(float(high), 2),
            position_pct=float(pos),
            at_low=float(pos) <= 5.0,
            at_high=float(pos) >= 95.0,
            gain_pct=None if gain is None or pd.isna(gain) else float(gain),
        ))
    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=round(float(close), 2),
        scan_date=trade_date,
        periods=period_results,
        low_resonance=int(row.get("low_resonance", 0) or 0),
        high_resonance=int(row.get("high_resonance", 0) or 0),
        is_st=("ST" in name or "*ST" in name),
        up_days=int(row.get("up_days", 0) or 0),
    )


def run_cross_section(
    stock_set: StockSet,
    *,
    trade_date: str | None = None,
    need_kline: bool = False,
    kline_periods: list[int] | None = None,
    included_dimensions: set[str] | None = None,
    need_valuation_context: bool = True,
) -> CrossSectionCtx:
    """全市场截面编排 · 不走 run_data_pipeline (K 线管线) · 截面一次拉全市场。

    Args:
        stock_set: 任意 StockSet (--all 传 AllStocksSet · name 来源 + 池范围)
        trade_date: YYYYMMDD 截面日 · None → 最近交易日 (fetch_metrics 内部解析)
        need_kline: True 时额外挂载每日 K 线预计算快照 (位置/涨幅/连阳/共振)
        kline_periods: 快照需要计算的周期 · None 时默认全周期 PERIODS
        included_dimensions: None 保持历史全维度取数;传 set 时只取对应截面维度。
            valuation 截面仍作为基础价格/截止日来源由本函数固定读取。
        need_valuation_context: True 时计算行业内分位/中位;fields/compact 可关闭。

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
    from kan.data.metrics import _DEFAULT_LOOKBACK_DAYS, fetch_metrics

    dims = (
        {"valuation", "moneyflow", "technical", "sentiment", "chip"}
        if included_dimensions is None
        else set(included_dimensions)
    )

    pairs = stock_set.pairs()
    pool_size = len(pairs)
    if not pairs:
        return CrossSectionCtx(rows=[], pool_size=0, data_cutoff=None, stale=True)

    codes = [c for c, _ in pairs]
    cross = fetch_metrics(trade_date=trade_date, symbols=codes)
    cross_empty = cross is None or cross.empty
    if cross_empty and not need_kline:
        # 无 token / 无截面 → 全空 (caller 报错引导配 token)
        return CrossSectionCtx(
            rows=[], pool_size=pool_size, data_cutoff=None, stale=True,
        )

    if need_valuation_context and not cross_empty:
        from kan.core.valuation_context import compute_cross_section_contexts
        from kan.data.industry_map import fetch_sw_l1_map

        l1_map = fetch_sw_l1_map()
        contexts = compute_cross_section_contexts(
            cross, l1_map, lookback_days=_DEFAULT_LOOKBACK_DAYS,
        )
    else:
        contexts = {}
    fallback_date = _resolve_fallback_date(trade_date, latest_trade_date)
    by_symbol = (
        {}
        if cross_empty
        else {str(r.get("symbol", "")).strip(): r for _, r in cross.iterrows()}
    )

    # 这些维度由 CLI 的 fields/compact/filter 反向驱动;未请求则不触发远端截面取数。
    if "moneyflow" in dims:
        from kan.data.moneyflow import fetch_moneyflow

        mf = fetch_moneyflow(trade_date=trade_date, symbols=codes)
        mf_by_symbol = (
            {str(r.get("symbol", "")).strip(): r for _, r in mf.iterrows()}
            if mf is not None and not mf.empty
            else {}
        )
    else:
        mf_by_symbol = {}

    if "technical" in dims:
        from kan.data.technical import fetch_technical

        tech = fetch_technical(trade_date=trade_date, symbols=codes)
        tech_by_symbol = (
            {str(r.get("symbol", "")).strip(): r for _, r in tech.iterrows()}
            if tech is not None and not tech.empty
            else {}
        )
    else:
        tech_by_symbol = {}

    if "sentiment" in dims:
        from kan.data.sentiment import fetch_sentiment

        senti = fetch_sentiment(trade_date=trade_date, symbols=codes)
        senti_by_symbol = (
            {str(r.get("symbol", "")).strip(): r for _, r in senti.iterrows()}
            if senti is not None and not senti.empty
            else {}
        )
    else:
        senti_by_symbol = {}

    if "chip" in dims:
        from kan.data.chip import fetch_chip

        chip = fetch_chip(trade_date=trade_date, symbols=codes)
        chip_by_symbol = (
            {str(r.get("symbol", "")).strip(): r for _, r in chip.iterrows()}
            if chip is not None and not chip.empty
            else {}
        )
    else:
        chip_by_symbol = {}
    from kan.core.scanner import PERIODS

    scan_periods = sorted(set(kline_periods or PERIODS))
    if need_kline:
        from kan.data.kline_snapshot import fetch_kline_snapshot

        snap = fetch_kline_snapshot(trade_date=trade_date, symbols=codes, periods=scan_periods)
        scan_by_symbol = (
            {
                str(r.get("symbol", "")).strip(): r
                for _, r in snap.iterrows()
            }
            if snap is not None and not snap.empty
            else {}
        )
    else:
        snap = None
        scan_by_symbol = {}

    if cross_empty and not scan_by_symbol:
        # 无 token / 无截面 / 无 K 线快照 → 全空 (caller 报错引导配 token)
        return CrossSectionCtx(
            rows=[], pool_size=pool_size, data_cutoff=None, stale=True,
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
        scan_row = scan_by_symbol.get(code)
        scan = (
            _snapshot_row_to_scan(scan_row, name, scan_periods)
            if scan_row is not None else None
        )
        rows.append(CrossSectionRow(
            code=code,
            name=name,
            valuation=valuation,
            valuation_context=contexts.get(code),
            moneyflow=moneyflow,
            technical=technical,
            sentiment=sentiment,
            chip=chip_metrics,
            scan=scan,
        ))

    cutoffs = []
    data_cutoff = None if cross_empty else _cross_data_cutoff(cross)
    if data_cutoff is not None:
        cutoffs.append(data_cutoff)
    if snap is not None and not snap.empty and "trade_date" in snap.columns:
        snap_cutoff = _max_date_from_series(snap["trade_date"])
        if snap_cutoff is not None:
            cutoffs.append(snap_cutoff)
    data_cutoff = max(cutoffs) if cutoffs else None
    stale = data_cutoff is None or data_cutoff < latest_trade_date()
    return CrossSectionCtx(
        rows=rows, pool_size=pool_size, data_cutoff=data_cutoff, stale=stale,
    )


__all__ = ["CrossSectionCtx", "CrossSectionRow", "run_cross_section"]

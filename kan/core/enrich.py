"""把 scan 结果按需 enrich 多维指标 (地基-2 AI 消费入口 + 整合-1 质量/资金)。

`StockScanResult` (K 线衍生位置 / 共振) + 按需挂载的截面/财务子对象 → `EnrichedResult`:
- valuation (daily_basic 截面 · 总挂 · 一次 HTTP 拉全市场切子集)
- moneyflow (moneyflow_dc 截面 · need_moneyflow · 同截面廉价)
- fundamentals (fina_indicator 逐股 · need_fundamentals · 逐股 HTTP 贵 · 严格按需)

设计要点:
- 成本分级:截面 (valuation/moneyflow) 一次拉全市场切子集 · 逐股 (fundamentals) N 次 HTTP ·
  fundamentals 仅 need_fundamentals=True (用户传 --roe) 才拉 · 避免无谓逐股
- 优雅降级:无 token / 失败 → 对应子对象 None · AI 消费契约仍成立 (结构 + disclaimer 在)
- 顺序保持:返回顺序与入参 results 一致 (find 命中排序不被打乱)

合规 (compliance §6/§7 · PRD §6 · 整合-1 拍板):本层只把原始指标值挂到对象上 · 不算
分位 / 不判断 · 估值/财务/资金裸值自整合-1 起对外输出 (输出过滤见 export · 不再删裸值)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from kan.core.models import (
        EnrichedResult,
        FundamentalMetrics,
        MoneyflowMetrics,
        StockScanResult,
        ValuationMetrics,
    )


def _opt_float(value: object) -> float | None:
    """截面单元格 → float | None · NaN / None / 不可解析一律 None。"""
    import pandas as pd

    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _row_to_valuation(row: pd.Series, fallback_date: date) -> ValuationMetrics:
    """单行截面 DataFrame → ValuationMetrics · NaN 数值置 None。

    trade_date 取行内规范化后的 date · NaT 时退回 fallback_date
    (ValuationMetrics.trade_date 必填 · 不能 None)。
    """
    import pandas as pd

    from kan.core.models import ValuationMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return ValuationMetrics(
        trade_date=td,
        close=_opt_float(row.get("close")),
        pe_ttm=_opt_float(row.get("pe_ttm")),
        pb=_opt_float(row.get("pb")),
        ps_ttm=_opt_float(row.get("ps_ttm")),
        dv_ttm=_opt_float(row.get("dv_ttm")),
        turnover_rate=_opt_float(row.get("turnover_rate")),
        volume_ratio=_opt_float(row.get("volume_ratio")),
        total_mv=_opt_float(row.get("total_mv")),
        circ_mv=_opt_float(row.get("circ_mv")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_fundamentals(row: pd.Series) -> FundamentalMetrics:
    """单股最新一期财务 Series → FundamentalMetrics (整合-1)。

    row 来自 fetch_fundamentals (已 normalize · end_date 是 date · 数值已清洗)。
    """
    import pandas as pd

    from kan.core.models import FundamentalMetrics

    end_date = row.get("end_date")
    if end_date is None or (not hasattr(end_date, "isoformat")) or pd.isna(end_date):
        end_date = None
    return FundamentalMetrics(
        end_date=end_date,
        roe=_opt_float(row.get("roe")),
        netprofit_yoy=_opt_float(row.get("netprofit_yoy")),
        or_yoy=_opt_float(row.get("or_yoy")),
        source="tushare_fina",
    )


def _row_to_moneyflow(row: pd.Series, fallback_date: date) -> MoneyflowMetrics:
    """单行主力资金截面 → MoneyflowMetrics · NaN 数值置 None (整合-1)。"""
    import pandas as pd

    from kan.core.models import MoneyflowMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return MoneyflowMetrics(
        trade_date=td,
        net_amount=_opt_float(row.get("net_amount")),
        buy_elg_amount=_opt_float(row.get("buy_elg_amount")),
        buy_lg_amount=_opt_float(row.get("buy_lg_amount")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def enrich_results(
    results: list[StockScanResult],
    *,
    trade_date: str | None = None,
    need_fundamentals: bool = False,
    need_moneyflow: bool = False,
) -> list[EnrichedResult]:
    """给 scan 结果按需挂多维指标 · 返回 EnrichedResult 列表 (原序)。

    valuation 总挂 (截面廉价 · 现有行为)· fundamentals (逐股 · 贵) / moneyflow
    (截面 · 廉价) 仅在对应 need_* 为 True 时挂 (caller 按 filter 需求传 · 见 find_cmds)。

    Args:
        results: scan_batch / find 命中的 StockScanResult 列表
        trade_date: YYYYMMDD 截面日 · None → 最近交易日 (fetch 内部解析)
        need_fundamentals: True 时逐股拉 fina_indicator (--roe filter · 全市场代价高)
        need_moneyflow: True 时拉 moneyflow_dc 截面 (--moneyflow filter · 截面廉价)

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

        for sym, row in fetch_fundamentals(symbols).items():
            fund_by_symbol[sym] = _row_to_fundamentals(row)

    mf_by_symbol: dict[str, MoneyflowMetrics] = {}
    if need_moneyflow:
        from kan.data.moneyflow import fetch_moneyflow

        mf_df = fetch_moneyflow(trade_date=trade_date, symbols=symbols)
        mf_by_symbol = _index_moneyflow(mf_df, fallback_date)

    return [
        EnrichedResult.from_scan(
            r,
            valuation=val_by_symbol.get(r.symbol),
            fundamentals=fund_by_symbol.get(r.symbol),
            moneyflow=mf_by_symbol.get(r.symbol),
        )
        for r in results
    ]


def _resolve_fallback_date(trade_date: str | None, latest_fn) -> date:
    """ValuationMetrics.trade_date 的兜底日期 (行内 trade_date 缺失时用)。"""
    if trade_date is None:
        return latest_fn()
    from datetime import datetime

    try:
        return datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError:
        return latest_fn()


def _index_valuations(df: pd.DataFrame, fallback_date: date) -> dict[str, ValuationMetrics]:
    """截面 DataFrame → {symbol: ValuationMetrics} · 空 df 返空 dict。"""
    if df is None or df.empty:
        return {}
    out: dict[str, ValuationMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_valuation(row, fallback_date)
    return out


def _index_moneyflow(df: pd.DataFrame, fallback_date: date) -> dict[str, MoneyflowMetrics]:
    """主力资金截面 DataFrame → {symbol: MoneyflowMetrics} · 空 df 返空 dict (整合-1)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, MoneyflowMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_moneyflow(row, fallback_date)
    return out


__all__ = ["enrich_results"]

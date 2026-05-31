"""把 scan 结果按需 enrich 截面市场指标 (地基-2 · AI 消费入口)。

`StockScanResult` (K 线衍生位置 / 共振) + `ValuationMetrics` (daily_basic 截面)
→ `EnrichedResult`。一次 `fetch_metrics` 拉全市场截面 (一次 HTTP · parquet 缓存) ·
按 symbols 切子集挂载 · 无 token / 无数据时 valuation=None (优雅降级)。

设计要点:
- 截面优势:`fetch_metrics` 按 trade_date 一次拉全市场 · 即便命中 50 只也只一次 HTTP ·
  缓存复用 (区别于 K 线逐只)
- 优雅降级:无 token / 全源失败 → fetch_metrics 返空 df → 所有 valuation=None ·
  AI 消费契约仍成立 (结构 + disclaimer 在 · 只是 valuation 维度缺失 · PRD §8 token 依赖)
- 顺序保持:返回顺序与入参 results 一致 (find 命中排序不被打乱)

合规 (compliance §6/§7 · PRD §6):本层只负责"把原始指标值挂到对象上" · 不算分位 /
不判断 · 估值裸值是否对外由输出层 (export._valuation_public_dict) 决定。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from kan.core.models import EnrichedResult, StockScanResult, ValuationMetrics


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


def enrich_results(
    results: list[StockScanResult],
    *,
    trade_date: str | None = None,
) -> list[EnrichedResult]:
    """给 scan 结果挂 valuation (截面市场指标) · 返回 EnrichedResult 列表 (原序)。

    Args:
        results: scan_batch / find 命中的 StockScanResult 列表
        trade_date: YYYYMMDD 截面日 · None → 最近交易日 (fetch_metrics 内部解析)

    Returns:
        list[EnrichedResult] · 与 results 等长同序 · 每只挂 valuation (无数据时 None)。
        空 results → 空列表 (不触网)。
    """
    from kan.core.models import EnrichedResult
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.metrics import fetch_metrics

    if not results:
        return []

    symbols = [r.symbol for r in results]
    df = fetch_metrics(trade_date=trade_date, symbols=symbols)

    fallback_date = _resolve_fallback_date(trade_date, latest_trade_date)
    by_symbol = _index_valuations(df, fallback_date)
    return [EnrichedResult.from_scan(r, by_symbol.get(r.symbol)) for r in results]


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


__all__ = ["enrich_results"]

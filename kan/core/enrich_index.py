"""enrich 截面 DataFrame 索引工具。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.enrich_rows import (
    _row_to_chip,
    _row_to_moneyflow,
    _row_to_sentiment,
    _row_to_technical,
    _row_to_valuation,
)

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from kan.core.models import (
        ChipMetrics,
        MoneyflowMetrics,
        SentimentMetrics,
        TechnicalMetrics,
        ValuationMetrics,
    )


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
    """主力资金截面 DataFrame → {symbol: MoneyflowMetrics} · 空 df 返空 dict (估值/质量/资金维度)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, MoneyflowMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_moneyflow(row, fallback_date)
    return out


def _index_technical(df: pd.DataFrame, fallback_date: date) -> dict[str, TechnicalMetrics]:
    """技术面截面 DataFrame → {symbol: TechnicalMetrics} · 空 df 返空 dict (技术/情绪/筹码维度)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, TechnicalMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_technical(row, fallback_date)
    return out


def _index_sentiment(df: pd.DataFrame, fallback_date: date) -> dict[str, SentimentMetrics]:
    """情绪截面 DataFrame → {symbol: SentimentMetrics} · 空 df 返空 dict (技术/情绪/筹码维度 · 稀疏)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, SentimentMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_sentiment(row, fallback_date)
    return out


def _index_chip(df: pd.DataFrame, fallback_date: date) -> dict[str, ChipMetrics]:
    """筹码截面 DataFrame → {symbol: ChipMetrics} · 空 df 返空 dict (技术/情绪/筹码维度)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, ChipMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_chip(row, fallback_date)
    return out


__all__ = [
    "_index_chip",
    "_index_moneyflow",
    "_index_sentiment",
    "_index_technical",
    "_index_valuations",
    "_resolve_fallback_date",
]

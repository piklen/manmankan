"""enrich 行级转换: DataFrame row -> metrics model。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from kan.core.models import (
        ChipMetrics,
        FundamentalMetrics,
        MoneyflowMetrics,
        SentimentMetrics,
        ShareholderMetrics,
        TechnicalMetrics,
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
    """单股最新一期财务 Series → FundamentalMetrics (估值/质量/资金维度)。

    row 来自 fetch_fundamentals (已 normalize · end_date 是 date · 数值已清洗)。
    """
    import pandas as pd

    from kan.core.models import FundamentalMetrics

    end_date = row.get("end_date")
    if end_date is None or (not hasattr(end_date, "isoformat")) or pd.isna(end_date):
        end_date = None
    ann_date = row.get("ann_date")
    if ann_date is None or (not hasattr(ann_date, "isoformat")) or pd.isna(ann_date):
        ann_date = None
    return FundamentalMetrics(
        end_date=end_date,
        ann_date=ann_date,
        fetched_at=row.get("fetched_at") if isinstance(row.get("fetched_at"), str) else None,
        roe=_opt_float(row.get("roe")),
        netprofit_yoy=_opt_float(row.get("netprofit_yoy")),
        or_yoy=_opt_float(row.get("or_yoy")),
        source="tushare_fina",
    )


def _row_to_moneyflow(row: pd.Series, fallback_date: date) -> MoneyflowMetrics:
    """单行主力资金截面 → MoneyflowMetrics · NaN 数值置 None (估值/质量/资金维度)。"""
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
        buy_md_amount=_opt_float(row.get("buy_md_amount")),
        buy_sm_amount=_opt_float(row.get("buy_sm_amount")),
        inflow_days=(
            int(v) if (v := _opt_float(row.get("inflow_days"))) is not None else None
        ),
        outflow_days=(
            int(v) if (v := _opt_float(row.get("outflow_days"))) is not None else None
        ),
        net_amount_5d=_opt_float(row.get("net_amount_5d")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_technical(row: pd.Series, fallback_date: date) -> TechnicalMetrics:
    """单行技术面截面 → TechnicalMetrics · NaN 数值置 None。"""
    import pandas as pd

    from kan.core.models import TechnicalMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return TechnicalMetrics(
        trade_date=td,
        close=_opt_float(row.get("close")),
        macd_dif=_opt_float(row.get("macd_dif")),
        macd_dea=_opt_float(row.get("macd_dea")),
        macd=_opt_float(row.get("macd")),
        atr=_opt_float(row.get("atr")),
        kdj_k=_opt_float(row.get("kdj_k")),
        kdj_d=_opt_float(row.get("kdj_d")),
        kdj_j=_opt_float(row.get("kdj_j")),
        rsi_6=_opt_float(row.get("rsi_6")),
        rsi_12=_opt_float(row.get("rsi_12")),
        rsi_24=_opt_float(row.get("rsi_24")),
        ma_5=_opt_float(row.get("ma_5")),
        ma_10=_opt_float(row.get("ma_10")),
        ma_20=_opt_float(row.get("ma_20")),
        ma_60=_opt_float(row.get("ma_60")),
        boll_upper=_opt_float(row.get("boll_upper")),
        boll_mid=_opt_float(row.get("boll_mid")),
        boll_lower=_opt_float(row.get("boll_lower")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_sentiment(row: pd.Series, fallback_date: date) -> SentimentMetrics:
    """单行情绪截面 → SentimentMetrics · 数值 NaN 置 None · limit/up_stat 保 str (技术/情绪/筹码维度)。"""
    import pandas as pd

    from kan.core.models import SentimentMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return SentimentMetrics(
        trade_date=td,
        limit_times=_opt_float(row.get("limit_times")),
        open_times=_opt_float(row.get("open_times")),
        first_time=row.get("first_time") if isinstance(row.get("first_time"), str) else None,
        last_time=row.get("last_time") if isinstance(row.get("last_time"), str) else None,
        fd_amount=_opt_float(row.get("fd_amount")),
        limit=row.get("limit") if isinstance(row.get("limit"), str) else None,
        up_stat=row.get("up_stat") if isinstance(row.get("up_stat"), str) else None,
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_chip(row: pd.Series, fallback_date: date) -> ChipMetrics:
    """单行筹码截面 → ChipMetrics · NaN 数值置 None (技术/情绪/筹码维度)。"""
    import pandas as pd

    from kan.core.models import ChipMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return ChipMetrics(
        trade_date=td,
        winner_rate=_opt_float(row.get("winner_rate")),
        cost_5pct=_opt_float(row.get("cost_5pct")),
        cost_50pct=_opt_float(row.get("cost_50pct")),
        cost_95pct=_opt_float(row.get("cost_95pct")),
        weight_avg=_opt_float(row.get("weight_avg")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_shareholder(row: pd.Series) -> ShareholderMetrics:
    """单股股东·持股结构衍生 Series → ShareholderMetrics (逐股 · 股东持股维度)。

    row 来自 fetch_shareholder (已 normalize · 日期是 date · 数值已清洗)。季度披露 ·
    各字段独立可空 (未披露 / 未进前十 → None · 优雅降级)。
    """
    import pandas as pd

    from kan.core.models import ShareholderMetrics

    h_end = row.get("holder_end_date")
    if h_end is None or (not hasattr(h_end, "isoformat")) or pd.isna(h_end):
        h_end = None
    t_end = row.get("top10_end_date")
    if t_end is None or (not hasattr(t_end, "isoformat")) or pd.isna(t_end):
        t_end = None
    return ShareholderMetrics(
        holder_end_date=h_end,
        holder_num=_opt_float(row.get("holder_num")),
        holder_chg_pct=_opt_float(row.get("holder_chg_pct")),
        top10_end_date=t_end,
        top10_float_ratio=_opt_float(row.get("top10_float_ratio")),
        north_hold_ratio=_opt_float(row.get("north_hold_ratio")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


__all__ = [
    "_opt_float",
    "_row_to_chip",
    "_row_to_fundamentals",
    "_row_to_moneyflow",
    "_row_to_sentiment",
    "_row_to_shareholder",
    "_row_to_technical",
    "_row_to_valuation",
]

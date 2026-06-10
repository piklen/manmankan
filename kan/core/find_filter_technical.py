"""技术、情绪和筹码维度 matcher。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.find_dsl import (
    AtrPctFilter,
    KdjJFilter,
    MacdDifFilter,
    MacdFilter,
    RsiFilter,
    StreakFilter,
    WinnerFilter,
    apply_op,
)
from kan.core.find_filter_models import TriggeredFilter

if TYPE_CHECKING:
    from kan.core.models import ChipMetrics, SentimentMetrics, TechnicalMetrics


def _match_rsi(
    filter: RsiFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """匹配 RSI(6 日) filter · rsi_6 缺失不命中。"""
    if technical is None or technical.rsi_6 is None:
        return None
    if apply_op(filter.op, technical.rsi_6, filter.value):
        return TriggeredFilter(
            filter_type="rsi",
            param=f"{filter.op}:{filter.value:g}",
            value=technical.rsi_6,
        )
    return None


def _match_macd_dif(
    filter: MacdDifFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """匹配 MACD DIF filter · macd_dif 缺失不命中。"""
    if technical is None or technical.macd_dif is None:
        return None
    if apply_op(filter.op, technical.macd_dif, filter.value):
        return TriggeredFilter(
            filter_type="macd_dif",
            param=f"{filter.op}:{filter.value:g}",
            value=technical.macd_dif,
        )
    return None


def _match_macd(
    filter: MacdFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """匹配 MACD 柱 filter · macd 缺失不命中。"""
    if technical is None or technical.macd is None:
        return None
    if apply_op(filter.op, technical.macd, filter.value):
        return TriggeredFilter(
            filter_type="macd",
            param=f"{filter.op}:{filter.value:g}",
            value=technical.macd,
        )
    return None


def _match_kdj_j(
    filter: KdjJFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """匹配 KDJ J filter · kdj_j 缺失不命中。"""
    if technical is None or technical.kdj_j is None:
        return None
    if apply_op(filter.op, technical.kdj_j, filter.value):
        return TriggeredFilter(
            filter_type="kdj_j",
            param=f"{filter.op}:{filter.value:g}",
            value=technical.kdj_j,
        )
    return None


def _match_atr_pct(
    filter: AtrPctFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """匹配 ATR 波动率百分比 filter · atr_pct 缺失不命中。"""
    if technical is None:
        return None
    atr_pct_val = technical.atr_pct()
    if atr_pct_val is None:
        return None
    if apply_op(filter.op, atr_pct_val, filter.value):
        return TriggeredFilter(
            filter_type="atr_pct",
            param=f"{filter.op}:{filter.value:g}",
            value=atr_pct_val,
        )
    return None


def _match_streak(
    filter: StreakFilter, sentiment: SentimentMetrics | None
) -> TriggeredFilter | None:
    """匹配连板天数 filter · sentiment 缺失不命中。"""
    if sentiment is None or sentiment.limit_times is None:
        return None
    if apply_op(filter.op, sentiment.limit_times, filter.value):
        return TriggeredFilter(
            filter_type="streak",
            param=f"{filter.op}:{filter.value:g}",
            value=sentiment.limit_times,
        )
    return None


def _match_winner(
    filter: WinnerFilter, chip: ChipMetrics | None
) -> TriggeredFilter | None:
    """匹配获利盘 filter · winner_rate 缺失不命中。"""
    if chip is None or chip.winner_rate is None:
        return None
    if apply_op(filter.op, chip.winner_rate, filter.value):
        return TriggeredFilter(
            filter_type="winner",
            param=f"{filter.op}:{filter.value:g}",
            value=chip.winner_rate,
        )
    return None

"""估值和基本面维度 matcher。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.find_dsl import (
    MarketCapFilter,
    PbFilter,
    PeFilter,
    RoeFilter,
    TurnoverFilter,
    VolumeRatioFilter,
    apply_op,
)
from kan.core.find_filter_models import TriggeredFilter

if TYPE_CHECKING:
    from kan.core.models import FundamentalMetrics, ValuationMetrics


def _match_pe(
    filter: PeFilter, valuation: ValuationMetrics | None
) -> TriggeredFilter | None:
    """匹配 PE filter · pe_ttm 缺失不命中。"""
    if valuation is None or valuation.pe_ttm is None:
        return None
    if apply_op(filter.op, valuation.pe_ttm, filter.value):
        return TriggeredFilter(
            filter_type="pe",
            param=f"{filter.op}:{filter.value:g}",
            value=valuation.pe_ttm,
        )
    return None


def _match_pb(
    filter: PbFilter, valuation: ValuationMetrics | None
) -> TriggeredFilter | None:
    """匹配 PB filter · pb 缺失不命中。"""
    if valuation is None or valuation.pb is None:
        return None
    if apply_op(filter.op, valuation.pb, filter.value):
        return TriggeredFilter(
            filter_type="pb",
            param=f"{filter.op}:{filter.value:g}",
            value=valuation.pb,
        )
    return None


def _match_turnover(
    filter: TurnoverFilter, valuation: ValuationMetrics | None
) -> TriggeredFilter | None:
    """匹配换手率 filter · turnover_rate 缺失不命中。"""
    if valuation is None or valuation.turnover_rate is None:
        return None
    if apply_op(filter.op, valuation.turnover_rate, filter.value):
        return TriggeredFilter(
            filter_type="turnover",
            param=f"{filter.op}:{filter.value:g}",
            value=valuation.turnover_rate,
        )
    return None


def _match_market_cap(
    filter: MarketCapFilter, valuation: ValuationMetrics | None
) -> TriggeredFilter | None:
    """匹配总市值 filter · total_mv 从万元换算为亿元后比较。"""
    if valuation is None or valuation.total_mv is None:
        return None
    cap_yi = valuation.total_mv / 1e4
    if apply_op(filter.op, cap_yi, filter.value):
        return TriggeredFilter(
            filter_type="market_cap",
            param=f"{filter.op}:{filter.value:g}",
            value=cap_yi,
        )
    return None


def _match_volume_ratio(
    filter: VolumeRatioFilter, valuation: ValuationMetrics | None
) -> TriggeredFilter | None:
    """匹配量比 filter · volume_ratio 缺失不命中。"""
    if valuation is None or valuation.volume_ratio is None:
        return None
    if apply_op(filter.op, valuation.volume_ratio, filter.value):
        return TriggeredFilter(
            filter_type="volume_ratio",
            param=f"{filter.op}:{filter.value:g}",
            value=valuation.volume_ratio,
        )
    return None


def _match_roe(
    filter: RoeFilter, fundamentals: FundamentalMetrics | None
) -> TriggeredFilter | None:
    """匹配 ROE filter · roe 缺失不命中。"""
    if fundamentals is None or fundamentals.roe is None:
        return None
    if apply_op(filter.op, fundamentals.roe, filter.value):
        return TriggeredFilter(
            filter_type="roe",
            param=f"{filter.op}:{filter.value:g}",
            value=fundamentals.roe,
        )
    return None

"""K 线结果维度 matcher。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.find_dsl import (
    GainFilter,
    MaBiasFilter,
    PosFilter,
    ResonanceFilter,
    UpDaysFilter,
    apply_op,
)
from kan.core.find_filter_models import TriggeredFilter

if TYPE_CHECKING:
    from kan.core.models import StockScanResult


def _match_pos(filter: PosFilter, result: StockScanResult) -> TriggeredFilter | None:
    """匹配位置 filter。"""
    for p in result.periods:
        if p.period == filter.period:
            if p.insufficient:
                return None
            if apply_op(filter.op, p.position_pct, filter.value):
                return TriggeredFilter(
                    filter_type="pos",
                    param=f"{filter.period}:{filter.op}:{filter.value:g}",
                    value=p.position_pct,
                )
            return None
    return None


def _match_resonance(
    filter: ResonanceFilter, result: StockScanResult
) -> TriggeredFilter | None:
    """匹配高/低位共振 filter。"""
    actual = result.low_resonance if filter.level == "low" else result.high_resonance
    if apply_op(filter.op, actual, filter.value):
        return TriggeredFilter(
            filter_type="resonance",
            param=f"{filter.level}:{filter.op}:{filter.value}",
            value=float(actual),
        )
    return None


def _match_gain(filter: GainFilter, result: StockScanResult) -> TriggeredFilter | None:
    """匹配近 N 日涨幅 filter · 周期不足不命中。"""
    for p in result.periods:
        if p.period == filter.period:
            if p.insufficient or p.gain_pct is None:
                return None
            if apply_op(filter.op, p.gain_pct, filter.value):
                return TriggeredFilter(
                    filter_type="gain",
                    param=f"{filter.period}:{filter.op}:{filter.value:g}",
                    value=p.gain_pct,
                )
            return None
    return None


def _match_up_days(
    filter: UpDaysFilter, result: StockScanResult
) -> TriggeredFilter | None:
    """匹配连阳天数 filter · 0 也参与比较。"""
    if apply_op(filter.op, result.up_days, filter.value):
        return TriggeredFilter(
            filter_type="up_days",
            param=f"{filter.op}:{filter.value:g}",
            value=float(result.up_days),
        )
    return None


def _match_ma_bias(
    filter: MaBiasFilter, result: StockScanResult
) -> TriggeredFilter | None:
    """匹配 K 线衍生 BIAS filter。"""
    bias = result.ma_biases.get(filter.period)
    if bias is None:
        return None
    if apply_op(filter.op, bias, filter.value):
        return TriggeredFilter(
            filter_type="ma_bias",
            param=f"{filter.period}:{filter.op}:{filter.value:g}",
            value=bias,
        )
    return None

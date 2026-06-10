"""股东持股维度 matcher。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.find_dsl import HoldersFilter, NorthFilter, Top10Filter, apply_op
from kan.core.find_filter_models import TriggeredFilter

if TYPE_CHECKING:
    from kan.core.models import ShareholderMetrics


def _match_holders(
    filter: HoldersFilter, shareholder: ShareholderMetrics | None
) -> TriggeredFilter | None:
    """匹配户数环比 filter · holder_chg_pct 缺失不命中。"""
    if shareholder is None or shareholder.holder_chg_pct is None:
        return None
    if apply_op(filter.op, shareholder.holder_chg_pct, filter.value):
        return TriggeredFilter(
            filter_type="holders",
            param=f"{filter.op}:{filter.value:g}",
            value=shareholder.holder_chg_pct,
        )
    return None


def _match_top10(
    filter: Top10Filter, shareholder: ShareholderMetrics | None
) -> TriggeredFilter | None:
    """匹配前十大流通集中度 filter · top10_float_ratio 缺失不命中。"""
    if shareholder is None or shareholder.top10_float_ratio is None:
        return None
    if apply_op(filter.op, shareholder.top10_float_ratio, filter.value):
        return TriggeredFilter(
            filter_type="top10",
            param=f"{filter.op}:{filter.value:g}",
            value=shareholder.top10_float_ratio,
        )
    return None


def _match_north(
    filter: NorthFilter, shareholder: ShareholderMetrics | None
) -> TriggeredFilter | None:
    """匹配北向持股代理口径 filter · north_hold_ratio 缺失不命中。"""
    if shareholder is None or shareholder.north_hold_ratio is None:
        return None
    if apply_op(filter.op, shareholder.north_hold_ratio, filter.value):
        return TriggeredFilter(
            filter_type="north",
            param=f"{filter.op}:{filter.value:g}",
            value=shareholder.north_hold_ratio,
        )
    return None

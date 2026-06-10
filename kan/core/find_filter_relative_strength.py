"""相对强度维度 matcher。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.find_dsl import RsBoardFilter, RsIndexFilter, apply_op
from kan.core.find_filter_models import TriggeredFilter

if TYPE_CHECKING:
    from kan.core.models import RelativeStrengthMetrics


def _match_rs_index(
    filter: RsIndexFilter, relative_strength: RelativeStrengthMetrics | None
) -> TriggeredFilter | None:
    """匹配相对大盘强度 filter · 缺少差值不命中。"""
    if relative_strength is None:
        return None
    diff = relative_strength.rs_index.get(filter.period)
    if diff is None:
        return None
    if apply_op(filter.op, diff, filter.value):
        return TriggeredFilter(
            filter_type="rs_index",
            param=f"{filter.period}:{filter.op}:{filter.value:g}",
            value=diff,
        )
    return None


def _match_rs_board(
    filter: RsBoardFilter, relative_strength: RelativeStrengthMetrics | None
) -> TriggeredFilter | None:
    """匹配相对所属申万一级行业强度 filter · 缺少差值不命中。"""
    if relative_strength is None:
        return None
    diff = relative_strength.rs_board.get(filter.period)
    if diff is None:
        return None
    if apply_op(filter.op, diff, filter.value):
        return TriggeredFilter(
            filter_type="rs_board",
            param=f"{filter.period}:{filter.op}:{filter.value:g}",
            value=diff,
        )
    return None

"""Filter functions for `kan find` · v0.0.6.4 MVP

Apply ConditionSet to list[StockScanResult] · return matching subset + audit trail.

设计原则:
- 复用 scan_batch 输出 (StockScanResult) · 不重做位置/共振算法
- 每个 filter 独立 · pure function · 可单独测试
- 返回 FindMatch (含 triggered filters list) · AI 友好 metadata
- AND 语义 · 多 filter 全部命中才入选

合规边界(manmankan/docs/compliance.md §7):
- 输出 "符合条件的股票" · 不评分 / 不推荐
- 排序按命中 filter 数倒序 · 不混合"综合得分"
- triggered 记录原始 DSL string + 实际命中值 · 供用户审计
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kan.core.find_dsl import ConditionSet, PosFilter, ResonanceFilter, apply_op

if TYPE_CHECKING:
    from kan.core.models import StockScanResult


@dataclass(frozen=True)
class TriggeredFilter:
    """One filter that matched · used in find result audit trail."""

    filter_type: str  # "pos" / "resonance"
    param: str        # original DSL string e.g. "180:lt:5"
    value: float      # actual measured value


@dataclass(frozen=True)
class FindMatch:
    """One stock that matched all filters · with audit trail.

    triggered: list of filters that matched
    (exclude_st is a quiet filter · not recorded in triggered · just drops)
    """

    result: StockScanResult
    triggered: tuple[TriggeredFilter, ...]


def _match_pos(filter: PosFilter, result: StockScanResult) -> TriggeredFilter | None:
    """Match position filter against scan result · returns triggered info or None."""
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
    return None  # period not in result.periods (shouldn't happen with PERIODS)


def _match_resonance(
    filter: ResonanceFilter, result: StockScanResult
) -> TriggeredFilter | None:
    """Match resonance filter (low or high) · returns triggered info or None."""
    actual = result.low_resonance if filter.level == "low" else result.high_resonance
    if apply_op(filter.op, actual, filter.value):
        return TriggeredFilter(
            filter_type="resonance",
            param=f"{filter.level}:{filter.op}:{filter.value}",
            value=float(actual),
        )
    return None


def apply_conditions(
    results: list[StockScanResult],
    conditions: ConditionSet,
) -> list[FindMatch]:
    """Apply ConditionSet to scan results · AND across all filters.

    For each stock:
    1. ST drop (early reject if exclude_st and is_st)
    2. ALL pos filters must match (AND)
    3. ALL resonance filters must match (AND)

    Args:
        results: scan_batch output (already sorted by resonance)
        conditions: parsed DSL conditions

    Returns:
        list[FindMatch] · sorted by len(triggered) desc · then low_resonance desc · then symbol
    """
    if conditions.is_empty():
        return [FindMatch(result=r, triggered=()) for r in results]

    matches: list[FindMatch] = []
    for r in results:
        if conditions.exclude_st and r.is_st:
            continue

        triggered: list[TriggeredFilter] = []
        all_match = True

        for pf in conditions.pos_filters:
            t = _match_pos(pf, r)
            if t is None:
                all_match = False
                break
            triggered.append(t)
        if not all_match:
            continue

        for rf in conditions.resonance_filters:
            t = _match_resonance(rf, r)
            if t is None:
                all_match = False
                break
            triggered.append(t)
        if not all_match:
            continue

        matches.append(FindMatch(result=r, triggered=tuple(triggered)))

    matches.sort(
        key=lambda m: (
            -len(m.triggered),
            -m.result.low_resonance,
            m.result.symbol,
        )
    )
    return matches


__all__ = ["FindMatch", "TriggeredFilter", "apply_conditions"]

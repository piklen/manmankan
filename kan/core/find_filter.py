"""Filter functions for `kan find` · v0.0.6.4 MVP + 整合-1 截面/财务 filter

Apply ConditionSet to scan / cross-section results · return matching subset + audit trail.

设计原则:
- 复用 scan_batch / enrich 输出 · 不重做位置/共振/截面算法
- 每个 _match_* 独立 · pure function · **吃子对象不吃整个 result** (整合-1) ·
  让 K 线池 (EnrichedResult) 与截面 (CrossSectionRow) 两路共享同一匹配逻辑
- 返回 FindMatch (含 triggered filters list) · AI 友好 metadata
- AND 语义 · 多 filter 全部命中才入选

整合-1 新增三类 filter:
- pe (估值 · 读 valuation.pe_ttm) / moneyflow (资金 · 读 moneyflow.net_amount):
  K 线池 + 截面 (--all) 两路都支持
- roe (质量 · 读 fundamentals.roe):逐股 · 仅 K 线池 / 小池 (全市场 --all 不支持)

合规边界(manmankan/docs/compliance.md §7):
- 输出 "符合条件的股票" · 不评分 / 不推荐
- 排序按命中 filter 数倒序 · 不混合"综合得分"
- triggered 记录原始 DSL string + 实际命中值 (含估值/财务裸值 · 整合-1 拍板放开) · 供用户审计
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kan.core.find_dsl import (
    MoneyflowFilter,
    PeFilter,
    PosFilter,
    ResonanceFilter,
    RoeFilter,
    apply_op,
)

if TYPE_CHECKING:
    from kan.core.cross_section import CrossSectionRow
    from kan.core.find_dsl import ConditionSet
    from kan.core.models import (
        EnrichedResult,
        FundamentalMetrics,
        MoneyflowMetrics,
        StockScanResult,
        ValuationMetrics,
    )


@dataclass(frozen=True)
class TriggeredFilter:
    """One filter that matched · used in find result audit trail."""

    filter_type: str  # "pos" / "resonance" / "pe" / "roe" / "moneyflow"
    param: str        # original DSL string e.g. "180:lt:5" / "lt:20"
    value: float      # actual measured value (含估值/财务裸值 · 整合-1 拍板放开)


@dataclass(frozen=True)
class FindMatch:
    """One stock that matched all filters · with audit trail.

    triggered: list of filters that matched
    (exclude_st is a quiet filter · not recorded in triggered · just drops)
    """

    result: StockScanResult
    triggered: tuple[TriggeredFilter, ...]


# ─── 单 filter 匹配器 (统一签名 (filter, target) → TriggeredFilter | None) ───

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


def _match_pe(
    filter: PeFilter, valuation: ValuationMetrics | None
) -> TriggeredFilter | None:
    """Match PE filter against valuation · valuation/pe_ttm 缺失 → 不命中 (整合-1)。"""
    if valuation is None or valuation.pe_ttm is None:
        return None
    if apply_op(filter.op, valuation.pe_ttm, filter.value):
        return TriggeredFilter(
            filter_type="pe",
            param=f"{filter.op}:{filter.value:g}",
            value=valuation.pe_ttm,
        )
    return None


def _match_roe(
    filter: RoeFilter, fundamentals: FundamentalMetrics | None
) -> TriggeredFilter | None:
    """Match ROE filter against fundamentals · fundamentals/roe 缺失 → 不命中 (整合-1)。"""
    if fundamentals is None or fundamentals.roe is None:
        return None
    if apply_op(filter.op, fundamentals.roe, filter.value):
        return TriggeredFilter(
            filter_type="roe",
            param=f"{filter.op}:{filter.value:g}",
            value=fundamentals.roe,
        )
    return None


def _match_moneyflow(
    filter: MoneyflowFilter, moneyflow: MoneyflowMetrics | None
) -> TriggeredFilter | None:
    """Match 主力净额 filter against moneyflow · net_amount 缺失 → 不命中 (整合-1)。"""
    if moneyflow is None or moneyflow.net_amount is None:
        return None
    if apply_op(filter.op, moneyflow.net_amount, filter.value):
        return TriggeredFilter(
            filter_type="moneyflow",
            param=f"{filter.op}:{filter.value:g}",
            value=moneyflow.net_amount,
        )
    return None


def _match_all(
    filters: tuple,
    target: object,
    matcher: Callable[..., TriggeredFilter | None],
) -> list[TriggeredFilter] | None:
    """一组同类 filter 全部匹配 target · 任一不命中返 None (AND short-circuit)。"""
    out: list[TriggeredFilter] = []
    for f in filters:
        t = matcher(f, target)
        if t is None:
            return None
        out.append(t)
    return out


def apply_conditions(
    results: list[EnrichedResult] | list[StockScanResult],
    conditions: ConditionSet,
) -> list[FindMatch]:
    """Apply ConditionSet to (enriched) scan results · AND across all filters.

    For each stock (AND · 任一组不全命中即淘汰):
    1. ST drop (early reject if exclude_st and is_st)
    2. pos / resonance filters (K 线衍生 · 读 result)
    3. pe / roe / moneyflow filters (整合-1 · 读 enrich 子对象 · 子对象缺失 → 不命中)

    子对象用 getattr 安全提取:传 StockScanResult (未 enrich) 时 valuation 等为 None ·
    但 caller (find_cmds) 保证有截面/财务 filter 时已 enrich (见 PRD 数据流)。

    Args:
        results: scan_batch / enrich_results 输出 (已按 resonance 排序)
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

        # 表驱动:每行 = (一组 filter, 匹配目标, 匹配器) · pos/resonance 吃 result ·
        # pe/roe/moneyflow 吃 enrich 子对象 (getattr 安全 · 未 enrich → None → 不命中)
        segments = [
            (conditions.pos_filters, r, _match_pos),
            (conditions.resonance_filters, r, _match_resonance),
            (conditions.pe_filters, getattr(r, "valuation", None), _match_pe),
            (conditions.roe_filters, getattr(r, "fundamentals", None), _match_roe),
            (conditions.moneyflow_filters, getattr(r, "moneyflow", None), _match_moneyflow),
        ]
        triggered: list[TriggeredFilter] = []
        all_match = True
        for filters, target, matcher in segments:
            seg = _match_all(filters, target, matcher)
            if seg is None:
                all_match = False
                break
            triggered.extend(seg)
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


def apply_cross_section_conditions(
    rows: list[CrossSectionRow],
    conditions: ConditionSet,
) -> list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]]:
    """截面行 (CrossSectionRow) 应用截面类 filter (pe + moneyflow · 整合-1 · --all 路径)。

    截面无 K 线衍生 (位置/共振) 也无 fundamentals (逐股太贵) · 只处理 pe/moneyflow ·
    复用 _match_pe / _match_moneyflow (传 row.valuation / row.moneyflow)。AND 语义 ·
    无 pe/moneyflow filter → 全量返回 (取数语义)。

    Returns:
        list[(CrossSectionRow, triggered)] · 按命中 filter 数倒序 · 然后 code 升序。
    """
    pe_filters = conditions.pe_filters
    mf_filters = conditions.moneyflow_filters
    if not pe_filters and not mf_filters:
        return [(r, ()) for r in rows]

    out: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]] = []
    for row in rows:
        segments = [
            (pe_filters, row.valuation, _match_pe),
            (mf_filters, row.moneyflow, _match_moneyflow),
        ]
        triggered: list[TriggeredFilter] = []
        all_match = True
        for filters, target, matcher in segments:
            seg = _match_all(filters, target, matcher)
            if seg is None:
                all_match = False
                break
            triggered.extend(seg)
        if all_match:
            out.append((row, tuple(triggered)))

    out.sort(key=lambda x: (-len(x[1]), x[0].code))
    return out


__all__ = [
    "FindMatch",
    "TriggeredFilter",
    "apply_conditions",
    "apply_cross_section_conditions",
]

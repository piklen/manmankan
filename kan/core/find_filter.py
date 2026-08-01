"""Filter functions for `kan find`.

Apply ConditionSet to scan / cross-section results · return matching subset + audit trail.

本模块保留 `kan.core.find_filter` 旧导入路径:
- `apply_conditions` / `apply_cross_section_conditions` 仍是生产入口
- `TriggeredFilter` / `FindMatch` / `MatchSegmentSpec` 仍从这里 re-export
- `_match_*` 仍挂在本模块，便于既有测试和外部脚本直接导入或 monkeypatch
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from kan.core.find_filter_kline import (
    _match_gain,
    _match_ma_bias,
    _match_pos,
    _match_resonance,
    _match_up_days,
)
from kan.core.find_filter_models import FindMatch, MatchSegmentSpec, TriggeredFilter
from kan.core.find_filter_moneyflow import (
    _match_moneyflow,
    _match_moneyflow_daily,
    _match_moneyflow_days,
)
from kan.core.find_filter_relative_strength import _match_rs_board, _match_rs_index
from kan.core.find_filter_shareholder import _match_holders, _match_north, _match_top10
from kan.core.find_filter_technical import (
    _match_atr_pct,
    _match_kdj_j,
    _match_macd,
    _match_macd_dif,
    _match_rsi,
    _match_streak,
    _match_winner,
)
from kan.core.find_filter_valuation import (
    _match_dv,
    _match_market_cap,
    _match_pb,
    _match_pe,
    _match_roe,
    _match_turnover,
    _match_volume_ratio,
)

if TYPE_CHECKING:
    from kan.core.cross_section import CrossSectionRow
    from kan.core.find_dsl import ConditionSet
    from kan.core.models import EnrichedResult, StockScanResult

_Matcher = Callable[..., TriggeredFilter | None]


FIND_MATCH_SEGMENTS: tuple[MatchSegmentSpec, ...] = (
    MatchSegmentSpec("pos", "pos_filters", "result", _match_pos),
    MatchSegmentSpec("resonance", "resonance_filters", "result", _match_resonance),
    MatchSegmentSpec("gain", "gain_filters", "result", _match_gain),
    MatchSegmentSpec("up_days", "up_days_filters", "result", _match_up_days),
    MatchSegmentSpec(
        "rs_index", "rs_index_filters", "relative_strength", _match_rs_index
    ),
    MatchSegmentSpec(
        "rs_board", "rs_board_filters", "relative_strength", _match_rs_board
    ),
    MatchSegmentSpec("pe", "pe_filters", "valuation", _match_pe),
    MatchSegmentSpec("pb", "pb_filters", "valuation", _match_pb),
    MatchSegmentSpec("dv", "dv_filters", "valuation", _match_dv),
    MatchSegmentSpec("turnover", "turnover_filters", "valuation", _match_turnover),
    MatchSegmentSpec("market_cap", "market_cap_filters", "valuation", _match_market_cap),
    MatchSegmentSpec(
        "volume_ratio", "volume_ratio_filters", "valuation", _match_volume_ratio
    ),
    MatchSegmentSpec(
        "roe",
        "roe_filters",
        "fundamentals",
        _match_roe,
        supports_cross_section=False,
    ),
    MatchSegmentSpec("moneyflow", "moneyflow_filters", "moneyflow", _match_moneyflow),
    MatchSegmentSpec(
        "moneyflow_daily",
        "moneyflow_daily_filters",
        "moneyflow",
        _match_moneyflow_daily,
    ),
    MatchSegmentSpec(
        "moneyflow_days",
        "moneyflow_days_filters",
        "moneyflow",
        _match_moneyflow_days,
    ),
    MatchSegmentSpec("rsi", "rsi_filters", "technical", _match_rsi),
    MatchSegmentSpec("macd_dif", "macd_dif_filters", "technical", _match_macd_dif),
    MatchSegmentSpec("macd", "macd_filters", "technical", _match_macd),
    MatchSegmentSpec("kdj_j", "kdj_j_filters", "technical", _match_kdj_j),
    MatchSegmentSpec("ma_bias", "ma_bias_filters", "result", _match_ma_bias),
    MatchSegmentSpec("atr_pct", "atr_pct_filters", "technical", _match_atr_pct),
    MatchSegmentSpec("streak", "streak_filters", "sentiment", _match_streak),
    MatchSegmentSpec("winner", "winner_filters", "chip", _match_winner),
    MatchSegmentSpec(
        "holders",
        "holders_filters",
        "shareholder",
        _match_holders,
        supports_cross_section=False,
    ),
    MatchSegmentSpec(
        "top10",
        "top10_filters",
        "shareholder",
        _match_top10,
        supports_cross_section=False,
    ),
    MatchSegmentSpec(
        "north",
        "north_filters",
        "shareholder",
        _match_north,
        supports_cross_section=False,
    ),
)


def _result_target(result: object, target_attr: str) -> object:
    if target_attr == "result":
        return result
    return getattr(result, target_attr, None)


def _cross_section_target(row: CrossSectionRow, target_attr: str) -> object:
    if target_attr == "result":
        return row.scan
    return getattr(row, target_attr, None)


def _resolve_segment_matcher(segment: MatchSegmentSpec) -> _Matcher:
    """从兼容入口动态解析 matcher，保留老路径 monkeypatch 语义。"""
    matcher = globals().get(segment.matcher.__name__, segment.matcher)
    return cast(_Matcher, matcher)


def _match_all(
    filters: tuple,
    target: object,
    matcher: _Matcher,
) -> list[TriggeredFilter] | None:
    """一组同类 filter 全部匹配 target · 任一不命中返 None。"""
    if not filters:
        return []
    if target is None:
        return None
    out: list[TriggeredFilter] = []
    for f in filters:
        t = matcher(f, target)
        if t is None:
            return None
        out.append(t)
    return out


def _match_any(
    filters: tuple,
    target: object,
    matcher: _Matcher,
) -> list[TriggeredFilter]:
    """一组同类 filter 任一匹配 target 即记录；缺数据视为该组无命中。"""
    if not filters or target is None:
        return []
    out: list[TriggeredFilter] = []
    for f in filters:
        t = matcher(f, target)
        if t is not None:
            out.append(t)
    return out


def apply_conditions(
    results: list[EnrichedResult] | list[StockScanResult],
    conditions: ConditionSet,
) -> list[FindMatch]:
    """Apply ConditionSet to (enriched) scan results · AND by default, optional OR.

    For each stock:
    1. ST drop (early reject if exclude_st and is_st)
    2. K 线衍生 filter 读 result
    3. 估值/资金/技术/情绪/筹码/股东持股 filter 读 enrich 子对象

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
        if conditions.match_any:
            for segment in FIND_MATCH_SEGMENTS:
                filters = getattr(conditions, segment.condition_attr)
                target = _result_target(r, segment.target_attr)
                matcher = _resolve_segment_matcher(segment)
                triggered.extend(_match_any(filters, target, matcher))
            if not triggered:
                continue
        else:
            all_match = True
            for segment in FIND_MATCH_SEGMENTS:
                filters = getattr(conditions, segment.condition_attr)
                target = _result_target(r, segment.target_attr)
                matcher = _resolve_segment_matcher(segment)
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
    """截面行 (CrossSectionRow) 应用 filter (`--all` 路径)。"""
    if conditions.is_empty():
        return [(r, ()) for r in rows]

    out: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]] = []
    for row in rows:
        if conditions.exclude_st and ("ST" in row.name or "*ST" in row.name):
            continue
        triggered: list[TriggeredFilter] = []
        if conditions.match_any:
            for segment in FIND_MATCH_SEGMENTS:
                if not segment.supports_cross_section:
                    continue
                filters = getattr(conditions, segment.condition_attr)
                target = _cross_section_target(row, segment.target_attr)
                matcher = _resolve_segment_matcher(segment)
                triggered.extend(_match_any(filters, target, matcher))
            if triggered:
                out.append((row, tuple(triggered)))
        else:
            all_match = True
            for segment in FIND_MATCH_SEGMENTS:
                if not segment.supports_cross_section:
                    continue
                filters = getattr(conditions, segment.condition_attr)
                target = _cross_section_target(row, segment.target_attr)
                matcher = _resolve_segment_matcher(segment)
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
    "FIND_MATCH_SEGMENTS",
    "FindMatch",
    "MatchSegmentSpec",
    "TriggeredFilter",
    "apply_conditions",
    "apply_cross_section_conditions",
]

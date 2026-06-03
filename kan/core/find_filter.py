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
    AtrPctFilter,
    GainFilter,
    HoldersFilter,
    KdjJFilter,
    MaBiasFilter,
    MacdDifFilter,
    MacdFilter,
    MoneyflowFilter,
    NorthFilter,
    PeFilter,
    PosFilter,
    ResonanceFilter,
    RoeFilter,
    RsiFilter,
    StreakFilter,
    Top10Filter,
    UpDaysFilter,
    WinnerFilter,
    apply_op,
)

if TYPE_CHECKING:
    from kan.core.cross_section import CrossSectionRow
    from kan.core.find_dsl import ConditionSet
    from kan.core.models import (
        ChipMetrics,
        EnrichedResult,
        FundamentalMetrics,
        MoneyflowMetrics,
        SentimentMetrics,
        ShareholderMetrics,
        StockScanResult,
        TechnicalMetrics,
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


@dataclass(frozen=True)
class MatchSegmentSpec:
    """One ConditionSet field and its target object/matcher binding."""

    filter_type: str
    condition_attr: str
    target_attr: str
    matcher: Callable[..., TriggeredFilter | None]
    supports_cross_section: bool = True


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


# ─── 整合-2 技术/情绪/筹码匹配器 (吃子对象 · 缺失 → None · 同整合-1 范式) ───

def _match_rsi(
    filter: RsiFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """Match RSI(6 日) filter against technical · rsi_6 缺失 → 不命中 (整合-2)。"""
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
    """Match MACD DIF filter against technical · macd_dif 缺失 → 不命中 (整合-2)。"""
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
    """Match MACD 柱 filter against technical · macd 缺失 → 不命中 (整合-2)。"""
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
    """Match KDJ J filter against technical · kdj_j 缺失 → 不命中 (整合-2)。"""
    if technical is None or technical.kdj_j is None:
        return None
    if apply_op(filter.op, technical.kdj_j, filter.value):
        return TriggeredFilter(
            filter_type="kdj_j",
            param=f"{filter.op}:{filter.value:g}",
            value=technical.kdj_j,
        )
    return None


def _match_streak(
    filter: StreakFilter, sentiment: SentimentMetrics | None
) -> TriggeredFilter | None:
    """Match 连板天数 filter against sentiment · limit_times 缺失 → 不命中 (整合-2)。

    sentiment 为 None = 该股当日未涨跌停 (稀疏事件型) → 不命中 (非连板股不入选)。
    """
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
    """Match 获利盘 filter against chip · winner_rate 缺失 → 不命中 (整合-2)。"""
    if chip is None or chip.winner_rate is None:
        return None
    if apply_op(filter.op, chip.winner_rate, filter.value):
        return TriggeredFilter(
            filter_type="winner",
            param=f"{filter.op}:{filter.value:g}",
            value=chip.winner_rate,
        )
    return None


# ─── 趋势/动量扩展匹配器 (ma_bias/atr_pct 吃 technical · gain/up_days 吃 result) ───

def _match_ma_bias(
    filter: MaBiasFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """Match 乖离率 filter against technical · ma_bias(period) 缺失 → 不命中。"""
    if technical is None:
        return None
    bias = technical.ma_bias(filter.period)
    if bias is None:
        return None
    if apply_op(filter.op, bias, filter.value):
        return TriggeredFilter(
            filter_type="ma_bias",
            param=f"{filter.period}:{filter.op}:{filter.value:g}",
            value=bias,
        )
    return None


def _match_atr_pct(
    filter: AtrPctFilter, technical: TechnicalMetrics | None
) -> TriggeredFilter | None:
    """Match ATR 波动率% filter against technical · atr_pct() 缺失 → 不命中。"""
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


def _match_gain(
    filter: GainFilter, result: StockScanResult
) -> TriggeredFilter | None:
    """Match 近 N 日涨幅 filter against scan result · period 不足/insufficient → 不命中。"""
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
    """Match 连阳天数 filter against scan result · up_days 客观计数 (0 也参与比较)。"""
    if apply_op(filter.op, result.up_days, filter.value):
        return TriggeredFilter(
            filter_type="up_days",
            param=f"{filter.op}:{filter.value:g}",
            value=float(result.up_days),
        )
    return None


# ─── 整合-3 股东·持股结构匹配器 (吃 shareholder 子对象 · 缺失/未进前十 → None) ───

def _match_holders(
    filter: HoldersFilter, shareholder: ShareholderMetrics | None
) -> TriggeredFilter | None:
    """Match 户数环比 filter against shareholder · holder_chg_pct 缺失 → 不命中 (整合-3)。"""
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
    """Match 前十大流通集中度 filter against shareholder · top10_float_ratio 缺失 → 不命中 (整合-3)。"""
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
    """Match 北向持股 filter against shareholder · north_hold_ratio 缺失/未进前十 → 不命中 (整合-3)。"""
    if shareholder is None or shareholder.north_hold_ratio is None:
        return None
    if apply_op(filter.op, shareholder.north_hold_ratio, filter.value):
        return TriggeredFilter(
            filter_type="north",
            param=f"{filter.op}:{filter.value:g}",
            value=shareholder.north_hold_ratio,
        )
    return None


FIND_MATCH_SEGMENTS: tuple[MatchSegmentSpec, ...] = (
    MatchSegmentSpec("pos", "pos_filters", "result", _match_pos),
    MatchSegmentSpec("resonance", "resonance_filters", "result", _match_resonance),
    MatchSegmentSpec("gain", "gain_filters", "result", _match_gain),
    MatchSegmentSpec("up_days", "up_days_filters", "result", _match_up_days),
    MatchSegmentSpec("pe", "pe_filters", "valuation", _match_pe),
    MatchSegmentSpec("roe", "roe_filters", "fundamentals", _match_roe, supports_cross_section=False),
    MatchSegmentSpec("moneyflow", "moneyflow_filters", "moneyflow", _match_moneyflow),
    MatchSegmentSpec("rsi", "rsi_filters", "technical", _match_rsi),
    MatchSegmentSpec("macd_dif", "macd_dif_filters", "technical", _match_macd_dif),
    MatchSegmentSpec("macd", "macd_filters", "technical", _match_macd),
    MatchSegmentSpec("kdj_j", "kdj_j_filters", "technical", _match_kdj_j),
    MatchSegmentSpec("ma_bias", "ma_bias_filters", "technical", _match_ma_bias),
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


def _match_all(
    filters: tuple,
    target: object,
    matcher: Callable[..., TriggeredFilter | None],
) -> list[TriggeredFilter] | None:
    """一组同类 filter 全部匹配 target · 任一不命中返 None (AND short-circuit)。"""
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


def apply_conditions(
    results: list[EnrichedResult] | list[StockScanResult],
    conditions: ConditionSet,
) -> list[FindMatch]:
    """Apply ConditionSet to (enriched) scan results · AND across all filters.

    For each stock (AND · 任一组不全命中即淘汰):
    1. ST drop (early reject if exclude_st and is_st)
    2. pos / resonance filters (K 线衍生 · 读 result)
    3. pe/roe/moneyflow/rsi/macd/kdj/streak/winner filters (整合-1/2 · 读 enrich 子对象 · 缺失 → 不命中)

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

        triggered: list[TriggeredFilter] = []
        all_match = True
        for segment in FIND_MATCH_SEGMENTS:
            filters = getattr(conditions, segment.condition_attr)
            target = _result_target(r, segment.target_attr)
            matcher = segment.matcher
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
    """截面行 (CrossSectionRow) 应用 filter (`--all` 路径)。

    `run_cross_section(..., need_kline=True)` 可挂载 row.scan,于是位置/共振/
    涨幅/连阳也能像 K 线池一样复用 _match_*。fundamentals / shareholder 仍是
    逐股维度,由 CLI 在 --all 下拦截。AND 语义 · 无 filter → 全量返回 (取数语义)。

    Returns:
        list[(CrossSectionRow, triggered)] · 按命中 filter 数倒序 · 然后 code 升序。
    """
    if conditions.is_empty():
        return [(r, ()) for r in rows]

    out: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]] = []
    for row in rows:
        if conditions.exclude_st and ("ST" in row.name or "*ST" in row.name):
            continue
        triggered: list[TriggeredFilter] = []
        all_match = True
        for segment in FIND_MATCH_SEGMENTS:
            if not segment.supports_cross_section:
                continue
            filters = getattr(conditions, segment.condition_attr)
            target = _cross_section_target(row, segment.target_attr)
            matcher = segment.matcher
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

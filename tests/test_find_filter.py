"""Tests for kan/core/find_filter.py · filter application (历史背景)."""

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from kan.core.find_dsl import ConditionSet
from kan.core.find_filter import (
    FindMatch,
    TriggeredFilter,
    apply_conditions,
)
from kan.core.models import MoneyflowMetrics, PeriodResult, StockScanResult

PERIODS = [3, 5, 7, 10, 15, 30, 60, 90, 120, 180]


def _mk_result(
    symbol: str = "600519",
    name: str = "贵州茅台",
    *,
    positions: dict[int, float] | None = None,
    low_resonance: int = 0,
    high_resonance: int = 0,
    is_st: bool = False,
    insufficient_periods: set[int] | None = None,
) -> StockScanResult:
    """Build a fake StockScanResult for testing."""
    if positions is None:
        positions = dict.fromkeys(PERIODS, 50.0)
    if insufficient_periods is None:
        insufficient_periods = set()

    period_results = []
    for p in PERIODS:
        pct = positions.get(p, 50.0)
        period_results.append(
            PeriodResult(
                period=p,
                n_low=0.0,
                n_high=100.0,
                position_pct=pct,
                at_low=pct <= 5,
                at_high=pct >= 95,
                insufficient=p in insufficient_periods,
            )
        )

    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=100.0,
        scan_date=date(2026, 5, 27),
        periods=period_results,
        low_resonance=low_resonance,
        high_resonance=high_resonance,
        is_st=is_st,
    )


class TestApplyConditions:
    def test_empty_conditions_returns_all(self):
        results = [_mk_result(), _mk_result(symbol="600036", name="招商银行")]
        matches = apply_conditions(results, ConditionSet.from_flags())
        assert len(matches) == 2
        assert all(isinstance(m, FindMatch) for m in matches)
        assert all(m.triggered == () for m in matches)

    def test_empty_results(self):
        cs = ConditionSet.from_flags(pos=["180:lt:5"])
        assert apply_conditions([], cs) == []

    def test_pos_filter_match(self):
        r = _mk_result(positions={180: 3.0})
        cs = ConditionSet.from_flags(pos=["180:lt:5"])
        matches = apply_conditions([r], cs)
        assert len(matches) == 1
        assert matches[0].triggered[0].filter_type == "pos"
        assert matches[0].triggered[0].value == 3.0

    def test_pos_filter_no_match(self):
        r = _mk_result(positions={180: 8.0})
        cs = ConditionSet.from_flags(pos=["180:lt:5"])
        assert apply_conditions([r], cs) == []

    def test_pos_filter_insufficient_period(self):
        r = _mk_result(positions={180: 3.0}, insufficient_periods={180})
        cs = ConditionSet.from_flags(pos=["180:lt:5"])
        # insufficient period · should not match (treated as no data)
        assert apply_conditions([r], cs) == []

    def test_low_resonance_filter_match(self):
        r = _mk_result(low_resonance=4)
        cs = ConditionSet.from_flags(resonance=["low:gte:3"])
        matches = apply_conditions([r], cs)
        assert len(matches) == 1
        assert matches[0].triggered[0].filter_type == "resonance"
        assert matches[0].triggered[0].value == 4.0

    def test_low_resonance_filter_no_match(self):
        r = _mk_result(low_resonance=2)
        cs = ConditionSet.from_flags(resonance=["low:gte:3"])
        assert apply_conditions([r], cs) == []

    def test_high_resonance_filter(self):
        r = _mk_result(high_resonance=5)
        cs = ConditionSet.from_flags(resonance=["high:gte:4"])
        matches = apply_conditions([r], cs)
        assert len(matches) == 1
        assert matches[0].triggered[0].param == "high:gte:4"

    def test_and_semantics_all_match(self):
        r = _mk_result(positions={180: 3.0}, low_resonance=4)
        cs = ConditionSet.from_flags(
            pos=["180:lt:5"], resonance=["low:gte:3"]
        )
        matches = apply_conditions([r], cs)
        assert len(matches) == 1
        assert len(matches[0].triggered) == 2

    def test_and_semantics_one_fails(self):
        r = _mk_result(positions={180: 3.0}, low_resonance=2)
        cs = ConditionSet.from_flags(
            pos=["180:lt:5"], resonance=["low:gte:3"]
        )
        # pos matches but resonance fails · AND fails
        assert apply_conditions([r], cs) == []

    def test_any_semantics_one_match_keeps_result(self):
        r = _mk_result(positions={180: 30.0}, low_resonance=4)
        cs = ConditionSet.from_flags(
            pos=["180:lt:5"], resonance=["low:gte:3"], match_any=True
        )
        matches = apply_conditions([r], cs)
        assert len(matches) == 1
        assert [t.filter_type for t in matches[0].triggered] == ["resonance"]

    def test_exclude_st_drops_st(self):
        r1 = _mk_result(symbol="600519", is_st=False)
        r2 = _mk_result(symbol="600000", name="*ST 浦发", is_st=True)
        cs = ConditionSet.from_flags(pos=["180:lte:100"], exclude_st=True)
        matches = apply_conditions([r1, r2], cs)
        assert len(matches) == 1
        assert matches[0].result.symbol == "600519"

    def test_exclude_st_does_not_record_in_triggered(self):
        r = _mk_result(positions={180: 3.0}, is_st=False)
        cs = ConditionSet.from_flags(pos=["180:lt:5"], exclude_st=True)
        matches = apply_conditions([r], cs)
        assert len(matches) == 1
        # exclude_st is a quiet filter · not in triggered list
        assert all(t.filter_type != "exclude_st" for t in matches[0].triggered)
        assert len(matches[0].triggered) == 1  # only pos triggered

    def test_sort_by_triggered_count_desc(self):
        # A: 2 filters match · B: 1 filter (resonance fails) · C: dropped
        a = _mk_result(symbol="A", positions={180: 3.0}, low_resonance=4)
        b = _mk_result(symbol="B", positions={180: 3.0}, low_resonance=2)
        cs = ConditionSet.from_flags(
            pos=["180:lt:5"], resonance=["low:gte:3"]
        )
        matches = apply_conditions([a, b], cs)
        # B fails AND so dropped · only A matches
        assert len(matches) == 1
        assert matches[0].result.symbol == "A"

    def test_multiple_pos_filters_all_match(self):
        r = _mk_result(positions={180: 3.0, 60: 8.0})
        cs = ConditionSet.from_flags(pos=["180:lt:5", "60:lt:10"])
        matches = apply_conditions([r], cs)
        assert len(matches) == 1
        assert len(matches[0].triggered) == 2

    def test_multiple_pos_filters_one_fails(self):
        r = _mk_result(positions={180: 3.0, 60: 12.0})  # 60 not < 10
        cs = ConditionSet.from_flags(pos=["180:lt:5", "60:lt:10"])
        assert apply_conditions([r], cs) == []

    def test_triggered_filter_param_format(self):
        r = _mk_result(positions={180: 3.0})
        cs = ConditionSet.from_flags(pos=["180:lt:5"])
        m = apply_conditions([r], cs)[0]
        # param uses :g format to drop trailing .0 if integer-valued
        assert m.triggered[0].param == "180:lt:5"

    def test_immutable_match(self):
        r = _mk_result()
        m = FindMatch(result=r, triggered=())
        with pytest.raises(FrozenInstanceError):
            m.triggered = (TriggeredFilter(filter_type="pos", param="x", value=1.0),)


class TestMoneyflowMatchers:
    """资金流 ScalarFilter matcher 单测."""

    def test_moneyflow_uses_5d_sum_when_available(self):
        from kan.core.find_dsl import MoneyflowFilter
        from kan.core.find_filter import _match_moneyflow

        mf = MoneyflowMetrics(net_amount=100.0, net_amount_5d=900.0)
        hit = _match_moneyflow(MoneyflowFilter(op="gt", value=500.0), mf)
        assert hit is not None
        assert hit.value == 900.0

    def test_moneyflow_daily_uses_today_net_amount(self):
        from kan.core.find_dsl import MoneyflowDailyFilter
        from kan.core.find_filter import _match_moneyflow_daily

        mf = MoneyflowMetrics(net_amount=120.0, net_amount_5d=-300.0)
        assert _match_moneyflow_daily(MoneyflowDailyFilter(op="gt", value=0.0), mf) is not None
        assert _match_moneyflow_daily(MoneyflowDailyFilter(op="lt", value=0.0), mf) is None

    def test_moneyflow_days_uses_inflow_days(self):
        from kan.core.find_dsl import MoneyflowDaysFilter
        from kan.core.find_filter import _match_moneyflow_days

        mf = MoneyflowMetrics(net_amount=10.0, inflow_days=4)
        hit = _match_moneyflow_days(MoneyflowDaysFilter(op="gte", value=3.0), mf)
        assert hit is not None
        assert hit.value == 4.0

    def test_moneyflow_missing_does_not_match(self):
        from kan.core.find_dsl import MoneyflowDailyFilter, MoneyflowDaysFilter
        from kan.core.find_filter import _match_moneyflow_daily, _match_moneyflow_days

        assert _match_moneyflow_daily(MoneyflowDailyFilter(op="gt", value=0.0), None) is None
        assert _match_moneyflow_days(MoneyflowDaysFilter(op="gt", value=0.0), None) is None


class TestValuationScalarMatchers:
    """估值维度 ScalarFilter matcher 单测 (--pb/--turnover/--market-cap/--volume-ratio)。"""

    @staticmethod
    def _val(**kw):
        from kan.core.models import ValuationMetrics
        return ValuationMetrics(trade_date=date(2026, 6, 3), **kw)

    def test_market_cap_converts_wan_to_yi(self):
        # total_mv 万元 → 亿元换算:1_500_000 万 = 150 亿
        from kan.core.find_dsl import MarketCapFilter
        from kan.core.find_filter import _match_market_cap
        v = self._val(total_mv=1_500_000.0)
        hit = _match_market_cap(MarketCapFilter(op="gt", value=100.0), v)
        assert hit is not None
        assert hit.value == 150.0  # 输出亿元
        assert _match_market_cap(MarketCapFilter(op="lt", value=100.0), v) is None

    def test_pb_match_and_missing(self):
        from kan.core.find_dsl import PbFilter
        from kan.core.find_filter import _match_pb
        v = self._val(pb=2.5)
        assert _match_pb(PbFilter(op="lt", value=3.0), v) is not None
        assert _match_pb(PbFilter(op="gt", value=3.0), v) is None
        # 缺数据(pb None)→ 不命中 · 优雅降级
        assert _match_pb(PbFilter(op="lt", value=3.0), self._val()) is None

    def test_turnover_and_volume_ratio(self):
        from kan.core.find_dsl import TurnoverFilter, VolumeRatioFilter
        from kan.core.find_filter import _match_turnover, _match_volume_ratio
        v = self._val(turnover_rate=6.0, volume_ratio=1.8)
        assert _match_turnover(TurnoverFilter(op="gt", value=5.0), v) is not None
        assert _match_volume_ratio(VolumeRatioFilter(op="gt", value=1.5), v) is not None
        # None valuation → 不命中(集成路径传未 enrich 结果时安全降级)
        assert _match_turnover(TurnoverFilter(op="gt", value=5.0), None) is None


class TestRelativeStrengthMatchers:
    """相对强度 matcher 单测 (--rs-index/--rs-board · 读 relative_strength 子对象 · 缺差值不命中)。"""

    @staticmethod
    def _rs(**kw):
        from kan.core.models import RelativeStrengthMetrics

        return RelativeStrengthMetrics(**kw)

    def test_rs_index_match_and_direction(self):
        from kan.core.find_dsl import RsIndexFilter
        from kan.core.find_filter import _match_rs_index

        rs = self._rs(rs_index={30: 5.3})  # 个股近 30 日跑赢大盘 5.3 个点
        hit = _match_rs_index(RsIndexFilter(period=30, op="gt", value=0.0), rs)
        assert hit is not None
        assert hit.value == 5.3
        assert hit.param == "30:gt:0"
        # 反方向(找跑输的)不命中
        assert _match_rs_index(RsIndexFilter(period=30, op="lt", value=0.0), rs) is None

    def test_rs_index_negative_diff(self):
        from kan.core.find_dsl import RsIndexFilter
        from kan.core.find_filter import _match_rs_index

        rs = self._rs(rs_index={20: -4.2})  # 跑输大盘 4.2 个点
        hit = _match_rs_index(RsIndexFilter(period=20, op="lt", value=0.0), rs)
        assert hit is not None
        assert hit.value == -4.2

    def test_rs_index_period_missing_does_not_match(self):
        # 请求周期不在 dict (周期不足 / 对照缺) → 不命中 · 绝不当 0
        from kan.core.find_dsl import RsIndexFilter
        from kan.core.find_filter import _match_rs_index

        rs = self._rs(rs_index={30: 5.0})
        assert _match_rs_index(RsIndexFilter(period=60, op="gt", value=0.0), rs) is None

    def test_rs_board_match(self):
        from kan.core.find_dsl import RsBoardFilter
        from kan.core.find_filter import _match_rs_board

        rs = self._rs(rs_board={30: 2.1}, industry="电子")
        hit = _match_rs_board(RsBoardFilter(period=30, op="gt", value=0.0), rs)
        assert hit is not None
        assert hit.value == 2.1
        assert hit.param == "30:gt:0"

    def test_rs_none_subobject_does_not_match(self):
        # relative_strength 子对象 None (未 attach) → 不命中 · 安全降级
        from kan.core.find_dsl import RsBoardFilter, RsIndexFilter
        from kan.core.find_filter import _match_rs_board, _match_rs_index

        assert _match_rs_index(RsIndexFilter(period=30, op="gt", value=0.0), None) is None
        assert _match_rs_board(RsBoardFilter(period=30, op="gt", value=0.0), None) is None

    def test_rs_index_and_board_independent(self):
        # 只有 index 差值 · board 空 → board filter 不命中 (两维度独立 · 四象限基础)
        from kan.core.find_dsl import RsBoardFilter
        from kan.core.find_filter import _match_rs_board

        rs = self._rs(rs_index={30: 5.0})
        assert _match_rs_board(RsBoardFilter(period=30, op="gt", value=0.0), rs) is None


class TestSortOffsetLimit:
    """find_service._sorted_offset_limit · 排序(None 末尾)+ offset/limit 分页。"""

    @staticmethod
    def _mk(pe):
        from kan.core.models import ValuationMetrics
        return type(
            "M",
            (),
            {"valuation": ValuationMetrics(trade_date=date(2026, 6, 3), pe_ttm=pe)},
        )()

    def test_sort_desc_none_last(self):
        from kan.service.find_service import _sorted_offset_limit
        items = [self._mk(10), self._mk(30), self._mk(20), self._mk(None)]
        out = _sorted_offset_limit(items, lambda x: x, ("pe", "desc"), 0, None)
        assert [x.valuation.pe_ttm for x in out] == [30, 20, 10, None]

    def test_offset_limit_pagination(self):
        from kan.service.find_service import _sorted_offset_limit
        items = [self._mk(10), self._mk(30), self._mk(20)]
        # asc → [10,20,30] · offset 1 limit 1 → [20]
        out = _sorted_offset_limit(items, lambda x: x, ("pe", "asc"), 1, 1)
        assert [x.valuation.pe_ttm for x in out] == [20]

    def test_no_sort_offset_only_keeps_order(self):
        from kan.service.find_service import _sorted_offset_limit
        items = [self._mk(10), self._mk(30), self._mk(20)]
        out = _sorted_offset_limit(items, lambda x: x, None, 1, None)
        assert [x.valuation.pe_ttm for x in out] == [30, 20]  # 不排序 · 仅跳过第 1 个

"""Tests for kan/core/find_filter.py · filter application (v0.0.6.4)."""

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from kan.core.find_dsl import ConditionSet
from kan.core.find_filter import (
    FindMatch,
    TriggeredFilter,
    apply_conditions,
)
from kan.core.models import PeriodResult, StockScanResult

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

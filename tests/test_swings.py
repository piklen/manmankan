"""波段按原始算例核对方向、确认时点与当前/历史共享口径。"""

import numpy as np
import pandas as pd
import pytest

from kan.core.swings import scan_swings
from kan.domain.market_study import StudyCondition, StudyQuery
from kan.service import market_study as study
from kan.service import trend_search as search


def history(prices):
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-05", periods=len(prices)),
        "open": prices, "close": prices,
        "high": np.array(prices) + 1, "low": np.array(prices) - 1,
        "volume": 1000., "_source": "synthetic",
    })


def test_confirmed_pivots_ignore_seed_and_never_claim_the_active_leg_complete():
    prices = np.array([10., 12., 11., 13., 12., 14., 13., 15.])
    result = scan_swings(prices, 5)
    assert result.structure == 1 and result.direction == 1 and result.count == 5
    assert [(p.index, p.kind, p.confirmed_index) for p in result.pivots] == [
        (1, "high", 2), (2, "low", 3), (3, "high", 4),
        (4, "low", 5), (5, "high", 6), (6, "low", 7),
    ]
    assert result.start_index == 6 and result.extreme_index == 7
    # 窗口首点和尾部极值均不是已确认转折，延长价格也不能改写确认记录。
    for end in range(2, len(prices) + 1):
        prefix = scan_swings(prices[:end], 5)
        assert prefix.pivots == [point for point in result.pivots if point.confirmed_index < end]
    assert scan_swings(np.array([15., 13., 14., 12., 13., 11.]), 5).structure == -1
    assert scan_swings(np.array([10., 12., 11., 13., 10.5, 14.]), 5).structure == 0
    assert scan_swings(prices, 10).structure is None
    monotonic = scan_swings(np.array([10., 11., 12., 13.]), 5)
    assert monotonic.structure is None and monotonic.count == 0 and monotonic.direction == 1
    assert scan_swings(np.array([10., 10., 10.]), 5).direction == 0
    assert scan_swings(np.array([10., 10., 10.]), 1e-11).direction == 0
    # 18.8 → 19.74 数学上恰好 +5%；复权尾差不能决定是否确认转折。
    boundary = np.array([20., 18.8, 19.74, 18.7, 20.])
    exact = scan_swings(boundary, 5)
    assert exact.pivots[0].index == 1 and exact.pivots[0].confirmed_index == 2
    for scale in (.013, 1, 100):
        perturbed = boundary * scale * np.array([1, 1 + 2e-15, 1 - 2e-15, 1, 1])
        assert [(p.index, p.kind, p.confirmed_index) for p in scan_swings(perturbed, 5).pivots] == [(p.index, p.kind, p.confirmed_index) for p in exact.pivots]
    below = boundary.copy()
    below[2] *= 1 - 1e-8
    assert all(p.confirmed_index != 2 for p in scan_swings(below, 5).pivots)
    equal_extrema = np.array([10., 12., 11., 12 * (1 + 2e-14), 11 * (1 - 2e-14), 13.])
    assert scan_swings(equal_extrema, 5).structure == 0


def test_candle_balance_slope_and_efficiency_are_distinct_scale_invariant_facts():
    raw = history([10, 12, 11, 13, 12, 14])
    raw["open"] = [10, 12.5, 11.5, 12.5, 11.5, 13.5]
    days = raw.date.dt.date.tolist()
    fields = [("bull_count", 5), ("bear_count", 5), ("candle_balance", 5), ("trend_slope", 5), ("trend_efficiency", 5)]
    values, _ = study.calculate_metrics(study.prepare_history(raw, days), fields)
    final = values.iloc[-1]
    assert (final["bull_count.5"], final["bear_count.5"], final["candle_balance.5"]) == (3, 2, 1)
    assert final["trend_efficiency.5"] == pytest.approx(4 / 8)
    expected_slope = np.expm1(np.polyfit(np.arange(6), np.log(raw.close), 1)[0]) * 100
    assert final["trend_slope.5"] == pytest.approx(expected_slope)
    scaled = raw.copy()
    scaled[["open", "close", "high", "low"]] *= .5
    scaled_values, _ = study.calculate_metrics(study.prepare_history(scaled, days), fields)
    pd.testing.assert_frame_equal(values, scaled_values)
    incomplete, _ = study.calculate_metrics(study.prepare_history(raw.drop(index=3), days), fields)
    assert incomplete.iloc[-1].drop("change_pct").isna().all()
    geometric = history([10 * 1.02 ** index for index in range(6)])
    slope, _ = study.calculate_metrics(study.prepare_history(geometric, days), fields)
    assert slope["trend_slope.5"].iloc[-1] == pytest.approx(2)
    assert slope["trend_efficiency.5"].iloc[-1] == pytest.approx(1)
    for price in (3., 123.45):
        flat = history([price] * 16)
        flat_metrics, _ = study.calculate_metrics(study.prepare_history(flat, flat.date.dt.date.tolist()), [("trend_slope", 15)])
        assert flat_metrics["trend_slope.15"].iloc[-1] == 0
    for daily_change in (-1e-10, 1e-10):
        tiny = history([123.45 * (1 + daily_change) ** index for index in range(16)])
        tiny_metrics, _ = study.calculate_metrics(study.prepare_history(tiny, tiny.date.dt.date.tolist()), [("trend_slope", 15)])
        assert tiny_metrics["trend_slope.15"].iloc[-1] == pytest.approx(daily_change * 100, rel=1e-4, abs=0)


def test_current_comparison_evidence_and_history_share_causal_swing_results(monkeypatch):
    raw = history([10, 12, 11, 13, 12, 14, 13, 15])
    days = raw.date.dt.date.tolist()
    conditions = [StudyCondition(field="swing_structure", operator="eq", value=1, window=6)]
    for service in (study, search):
        monkeypatch.setattr(service, "resolve_market_calendar", lambda as_of=None: (days, as_of or days[-1]))
        monkeypatch.setattr(service, "resolve_study_members", lambda universe, codes: [("000001", "合成公司")])
    monkeypatch.setattr(search, "_industries", lambda: {})
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda symbol: raw)
    request = search.TrendSearchQuery(universe="codes", codes=["000001"], conditions=conditions, compare_to=days[5], swing_reversal_pct=5)
    current = search.search_trends(request)
    historical = study.evaluate_study(StudyQuery(universe="codes", codes=["000001"], conditions=conditions, lookback_days=8, swing_reversal_pct=5), [("000001", "合成公司", raw)], days, days[-1])[0]
    assert current.rows[0].values["swing_structure.6"] == historical.current_matches[0].values["swing_structure.6"] == 1
    assert current.rows[0].values["swing_direction.6"] == 1
    assert current.rows[0].values["swing_count.6"] == 3
    assert list(historical.current_matches[0].values) == ["swing_structure.6"]
    assert current.query.conditions == conditions
    assert current.comparison.coverage.continued == 1
    prior = search.trend_search_evidence(request, "000001", at=days[5])
    evidence = prior.swings[0]
    assert evidence.structure == 1 and evidence.direction == 1
    assert all(point.confirmed_at <= days[5] and point.date < point.confirmed_at for point in evidence.pivots)
    assert evidence.current.start_confirmed and evidence.current.days == 1
    assert evidence.current.return_pct == pytest.approx((14 / 12 - 1) * 100)
    # 修改核对日之后的行情，已经存在的图证与历史指标不得变化。
    raw.loc[6:, ["open", "close", "high", "low"]] *= 10
    assert search.trend_search_evidence(request, "000001", at=days[5]) == prior
    shifted = request.model_copy(update={"swing_reversal_pct": 30})
    missing = search.search_trends(shifted)
    assert missing.coverage.missing == 1 and "尚不足两组" in missing.missing_rows[0].reason
    # 已确认结构描述历史高低点，当前穿越最近低点要另行提示，不能继续暗示结构完好。
    broken_raw = history([10, 12, 11, 13, 12, 14, 10])
    broken = study.swing_evidence(study.prepare_history(broken_raw, broken_raw.date.dt.date.tolist()), [StudyCondition(field="swing_structure", operator="eq", value=1, window=7)], 5)[0]
    assert broken.structure == 1 and broken.direction == -1 and broken.structure_broken is True
    with pytest.raises(ValueError, match="等于比较"):
        StudyCondition(field="swing_structure", operator="gte", value=1, window=6)

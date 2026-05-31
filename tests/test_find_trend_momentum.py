"""Tests for 趋势/动量扩展 filter · ma-bias / gain / atr-pct / up-days。

合规:全部客观裸值 filter · 阈值用户主导 · 不判断方向。覆盖:
- parse(含值域边界:--gain 拒 20 / --ma-bias 拒非 5/10/20/60)
- TechnicalMetrics.ma_bias()/atr_pct() 纯算 + 缺失降级
- matcher 命中/不命中/None 降级(ma_bias/atr_pct 吃 technical · gain/up_days 吃 result)
- ConditionSet 路由归属(K 线衍生 vs 截面)
- scanner.scan_stock 衍生(gain_pct / up_days)
- cross_section(--all)路径 ma_bias/atr_pct 支持
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from kan.core.cross_section import CrossSectionRow
from kan.core.find_dsl import (
    ALLOWED_MA,
    AtrPctFilter,
    ConditionSet,
    FilterParseError,
    GainFilter,
    MaBiasFilter,
    UpDaysFilter,
)
from kan.core.find_filter import apply_conditions, apply_cross_section_conditions
from kan.core.models import (
    EnrichedResult,
    PeriodResult,
    StockScanResult,
    TechnicalMetrics,
)
from kan.core.scanner import scan_stock

PERIODS = [3, 5, 7, 10, 15, 30, 60, 90, 120, 180]


def _mk_result(
    *,
    gains: dict[int, float] | None = None,
    up_days: int = 0,
    technical: TechnicalMetrics | None = None,
    symbol: str = "600519",
    name: str = "贵州茅台",
):
    """造 StockScanResult(无 technical)或 EnrichedResult(有 technical)。"""
    gains = gains or {}
    periods = [
        PeriodResult(
            period=p,
            n_low=0.0,
            n_high=100.0,
            position_pct=50.0,
            at_low=False,
            at_high=False,
            gain_pct=gains.get(p),
        )
        for p in PERIODS
    ]
    scan = StockScanResult(
        symbol=symbol,
        name=name,
        current_price=100.0,
        scan_date=date(2026, 5, 29),
        periods=periods,
        low_resonance=0,
        high_resonance=0,
        up_days=up_days,
    )
    if technical is not None:
        return EnrichedResult.from_scan(scan, technical=technical)
    return scan


def _make_df(opens, closes, highs=None, lows=None) -> pd.DataFrame:
    n = len(closes)
    base = date(2026, 1, 1)
    return pd.DataFrame(
        {
            "date": [base + timedelta(days=i) for i in range(n)],
            "open": opens,
            "high": highs or closes,
            "low": lows or closes,
            "close": closes,
            "volume": [10000] * n,
        }
    )


# ─────────────────────────── parse ───────────────────────────


class TestMaBiasFilterParse:
    def test_basic(self):
        f = MaBiasFilter.parse("20:gt:0")
        assert f.period == 20
        assert f.op == "gt"
        assert f.value == 0.0

    @pytest.mark.parametrize("period", ALLOWED_MA)
    def test_all_ma_periods(self, period):
        assert MaBiasFilter.parse(f"{period}:gt:0").period == period

    def test_reject_non_ma_period(self):
        # 7 在 ALLOWED_PERIODS 但不在 ALLOWED_MA(只有 5/10/20/60 有均线)
        with pytest.raises(FilterParseError, match="周期 7 不支持"):
            MaBiasFilter.parse("7:gt:0")

    def test_negative_value_ok(self):
        # 乖离率可负(收盘在均线下方)· 不卡范围
        assert MaBiasFilter.parse("20:lt:-5").value == -5.0

    def test_bad_format(self):
        with pytest.raises(FilterParseError, match="格式错误"):
            MaBiasFilter.parse("20:gt")

    def test_bad_op(self):
        with pytest.raises(FilterParseError, match="运算符"):
            MaBiasFilter.parse("20:xx:0")


class TestGainFilterParse:
    def test_basic(self):
        f = GainFilter.parse("30:gt:20")
        assert f.period == 30
        assert f.value == 20.0

    def test_reject_period_20(self):
        # 20 不在 ALLOWED_PERIODS(易踩坑:月窗口需用 15/30)
        with pytest.raises(FilterParseError, match="周期 20 不支持"):
            GainFilter.parse("20:gt:30")

    def test_large_gain_ok(self):
        # 涨幅可 >100% · 不卡范围
        assert GainFilter.parse("60:gt:150").value == 150.0


class TestAtrPctFilterParse:
    def test_basic(self):
        f = AtrPctFilter.parse("lt:5")
        assert f.op == "lt"
        assert f.value == 5.0

    def test_bad_format(self):
        with pytest.raises(FilterParseError, match="格式错误"):
            AtrPctFilter.parse("lt:5:x")


class TestUpDaysFilterParse:
    def test_basic(self):
        f = UpDaysFilter.parse("gte:3")
        assert f.op == "gte"
        assert f.value == 3.0


# ──────────────────── TechnicalMetrics 方法 ────────────────────


class TestTechnicalMethods:
    def test_ma_bias_positive(self):
        assert TechnicalMetrics(close=110.0, ma_20=100.0).ma_bias(20) == 10.0

    def test_ma_bias_negative(self):
        assert TechnicalMetrics(close=95.0, ma_20=100.0).ma_bias(20) == -5.0

    def test_ma_bias_missing_ma(self):
        assert TechnicalMetrics(close=110.0).ma_bias(20) is None

    def test_ma_bias_zero_ma(self):
        assert TechnicalMetrics(close=110.0, ma_20=0.0).ma_bias(20) is None

    def test_atr_pct(self):
        assert TechnicalMetrics(close=100.0, atr=5.0).atr_pct() == 5.0

    def test_atr_pct_missing(self):
        assert TechnicalMetrics(close=100.0).atr_pct() is None


# ──────────────────── ConditionSet 路由归属 ────────────────────


class TestConditionSetRouting:
    def test_gain_up_days_are_kline(self):
        assert ConditionSet.from_flags(gain=["30:gt:20"]).has_kline_filters() is True
        assert ConditionSet.from_flags(up_days=["gte:3"]).has_kline_filters() is True

    def test_ma_bias_atr_are_technical_not_kline(self):
        cs = ConditionSet.from_flags(ma_bias=["20:gt:0"])
        assert cs.needs_technical() is True
        assert cs.has_cross_section_filters() is True
        assert cs.has_kline_filters() is False
        assert ConditionSet.from_flags(atr_pct=["lt:5"]).needs_technical() is True

    def test_empty(self):
        assert ConditionSet.from_flags().is_empty() is True
        assert ConditionSet.from_flags(gain=["30:gt:20"]).is_empty() is False


# ─────────── matcher: gain / up_days(K 线衍生 · 吃 result）───────────


class TestGainUpDaysMatch:
    def test_gain_match(self):
        r = _mk_result(gains={30: 35.0})
        m = apply_conditions([r], ConditionSet.from_flags(gain=["30:gt:20"]))
        assert len(m) == 1
        assert m[0].triggered[0].filter_type == "gain"
        assert m[0].triggered[0].value == 35.0

    def test_gain_no_match(self):
        r = _mk_result(gains={30: 10.0})
        assert apply_conditions([r], ConditionSet.from_flags(gain=["30:gt:20"])) == []

    def test_gain_none_no_match(self):
        # gain_pct None(数据不足)→ 不命中
        r = _mk_result(gains={})
        assert apply_conditions([r], ConditionSet.from_flags(gain=["30:gt:20"])) == []

    def test_up_days_match(self):
        r = _mk_result(up_days=4)
        m = apply_conditions([r], ConditionSet.from_flags(up_days=["gte:3"]))
        assert len(m) == 1
        assert m[0].triggered[0].value == 4.0

    def test_up_days_no_match(self):
        r = _mk_result(up_days=1)
        assert apply_conditions([r], ConditionSet.from_flags(up_days=["gte:3"])) == []


# ─────────── matcher: ma_bias / atr_pct(技术 · 吃 technical）───────────


class TestMaBiasAtrMatch:
    def test_ma_bias_match(self):
        r = _mk_result(technical=TechnicalMetrics(close=110.0, ma_20=100.0))
        m = apply_conditions([r], ConditionSet.from_flags(ma_bias=["20:gt:0"]))
        assert len(m) == 1
        assert m[0].triggered[0].filter_type == "ma_bias"
        assert m[0].triggered[0].value == 10.0

    def test_ma_bias_below_no_match(self):
        r = _mk_result(technical=TechnicalMetrics(close=95.0, ma_20=100.0))
        assert apply_conditions([r], ConditionSet.from_flags(ma_bias=["20:gt:0"])) == []

    def test_ma_bias_no_technical_no_match(self):
        # StockScanResult 无 technical 属性 → getattr None → 不命中
        r = _mk_result(technical=None)
        assert apply_conditions([r], ConditionSet.from_flags(ma_bias=["20:gt:0"])) == []

    def test_atr_pct_match(self):
        r = _mk_result(technical=TechnicalMetrics(close=100.0, atr=3.0))
        m = apply_conditions([r], ConditionSet.from_flags(atr_pct=["lt:5"]))
        assert len(m) == 1
        assert m[0].triggered[0].value == 3.0


# ─────────── cross_section(--all 路径）ma_bias/atr_pct 支持 ───────────


class TestCrossSectionTrend:
    @staticmethod
    def _row(technical):
        return CrossSectionRow(
            code="600519",
            name="贵州茅台",
            valuation=None,
            valuation_context=None,
            technical=technical,
        )

    def test_ma_bias_cross_section(self):
        row = self._row(TechnicalMetrics(close=110.0, ma_20=100.0))
        out = apply_cross_section_conditions(
            [row], ConditionSet.from_flags(ma_bias=["20:gt:0"])
        )
        assert len(out) == 1
        assert out[0][1][0].filter_type == "ma_bias"

    def test_atr_pct_cross_section(self):
        row = self._row(TechnicalMetrics(close=100.0, atr=3.0))
        out = apply_cross_section_conditions(
            [row], ConditionSet.from_flags(atr_pct=["lt:5"])
        )
        assert len(out) == 1


# ──────────────── scanner.scan_stock 衍生（gain_pct / up_days）────────────────


class TestScannerDerived:
    def test_gain_pct(self):
        # 11 根 · 近 5 日:今收 150 vs 5 日前收 100(index -6)→ 50%
        closes = [100.0] * 6 + [110.0, 120.0, 130.0, 140.0, 150.0]
        r = scan_stock(_make_df(closes, closes), "000001", "测试")
        p5 = next(p for p in r.periods if p.period == 5)
        assert p5.gain_pct == 50.0

    def test_gain_pct_insufficient(self):
        # 2 根 · 不足 → 该 period insufficient · gain_pct None
        r = scan_stock(_make_df([100.0, 110.0], [100.0, 110.0]), "000001", "测试")
        p5 = next(p for p in r.periods if p.period == 5)
        assert p5.gain_pct is None

    def test_up_days_counts_trailing_bullish(self):
        # 末 3 根 close>open(阳线)· 第 7 根阴线 → 连阳 3
        opens = [10.0] * 7 + [9.0, 9.0, 9.0]
        closes = [9.0] * 7 + [10.0, 11.0, 12.0]
        r = scan_stock(_make_df(opens, closes), "000001", "测试")
        assert r.up_days == 3

    def test_up_days_zero_when_last_bearish(self):
        # 最后一根阴线(close<open)→ 连阳 0
        opens = [9.0, 9.0, 9.0, 10.0]
        closes = [10.0, 11.0, 12.0, 9.0]
        r = scan_stock(_make_df(opens, closes), "000001", "测试")
        assert r.up_days == 0

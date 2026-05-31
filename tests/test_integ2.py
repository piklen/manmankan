"""整合-2 · 技术/情绪/筹码 filter (DSL parse + match + apply) 纯函数单元测试。

覆盖 RsiFilter/MacdDifFilter/MacdFilter/KdjJFilter/StreakFilter/WinnerFilter parse +
apply_conditions (K线池) + apply_cross_section_conditions (--all 截面)。合规:裸值回显 +
None 降级 (数据缺失 / 未涨停视为不命中 · 不误入选)。仿 test_integ1.py。
"""
from __future__ import annotations

import datetime

import pytest

from kan.core.find_dsl import (
    ConditionSet,
    FilterParseError,
    KdjJFilter,
    MacdDifFilter,
    MacdFilter,
    RsiFilter,
    StreakFilter,
    WinnerFilter,
)
from kan.core.find_filter import apply_conditions, apply_cross_section_conditions
from kan.core.models import (
    ChipMetrics,
    EnrichedResult,
    PeriodResult,
    SentimentMetrics,
    StockScanResult,
    TechnicalMetrics,
)

# ── DSL parse ──────────────────────────────────────────────────────────

class TestNewFilterParse:
    def test_rsi_parse(self):
        f = RsiFilter.parse("lt:30")
        assert f.op == "lt" and f.value == 30.0

    def test_macd_dif_parse_negative(self):
        f = MacdDifFilter.parse("gt:-5")  # MACD 可负 · 不卡范围
        assert f.op == "gt" and f.value == -5.0

    def test_macd_bar_parse(self):
        f = MacdFilter.parse("gt:0")
        assert f.op == "gt" and f.value == 0.0

    def test_kdj_j_parse(self):
        f = KdjJFilter.parse("lt:20")
        assert f.op == "lt" and f.value == 20.0

    def test_streak_parse(self):
        f = StreakFilter.parse("gte:3")
        assert f.op == "gte" and f.value == 3.0

    def test_winner_parse(self):
        f = WinnerFilter.parse("gte:50")
        assert f.op == "gte" and f.value == 50.0

    @pytest.mark.parametrize("raw", ["lt", "lt:20:30", "20"])
    def test_bad_format(self, raw):
        with pytest.raises(FilterParseError, match="格式错误"):
            RsiFilter.parse(raw)

    def test_bad_op(self):
        with pytest.raises(FilterParseError, match="运算符"):
            StreakFilter.parse("xx:3")

    def test_bad_value(self):
        with pytest.raises(FilterParseError, match="非数字"):
            WinnerFilter.parse("gte:abc")

    def test_nan_rejected(self):
        with pytest.raises(FilterParseError, match="非有限数"):
            RsiFilter.parse("lt:nan")

    def test_from_flags_and_gates(self):
        cs = ConditionSet.from_flags(
            rsi=["lt:30"], macd=["gt:0"], streak=["gte:3"], winner=["gte:50"],
        )
        assert len(cs.rsi_filters) == 1
        assert cs.needs_technical() is True
        assert cs.needs_sentiment() is True
        assert cs.needs_chip() is True
        assert cs.has_cross_section_filters() is True
        assert cs.has_kline_filters() is False
        assert cs.is_empty() is False

    def test_macd_dif_separate_from_macd(self):
        """--macd-dif (DIF 线) 与 --macd (柱) 是独立 filter。"""
        cs = ConditionSet.from_flags(macd_dif=["gt:0"], macd=["lt:0"])
        assert len(cs.macd_dif_filters) == 1
        assert len(cs.macd_filters) == 1


# ── helpers ──────────────────────────────────────────────────────────────

def _scan(symbol="600519", is_st=False):
    return StockScanResult(
        symbol=symbol, name="测试", current_price=100.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[PeriodResult(period=180, n_low=50.0, n_high=200.0,
                              position_pct=30.0, at_low=False, at_high=False)],
        low_resonance=1, high_resonance=0, is_st=is_st,
    )


def _enriched(symbol="600519", rsi=None, macd=None, kdj_j=None, streak=None, winner=None):
    tech = (
        TechnicalMetrics(rsi_6=rsi, macd=macd, kdj_j=kdj_j)
        if any(v is not None for v in (rsi, macd, kdj_j)) else None
    )
    senti = SentimentMetrics(limit_times=streak) if streak is not None else None
    chip = ChipMetrics(winner_rate=winner) if winner is not None else None
    return EnrichedResult.from_scan(_scan(symbol), technical=tech, sentiment=senti, chip=chip)


# ── apply_conditions (K线池) ──────────────────────────────────────────────

class TestApplyConditionsNewFilters:
    def test_rsi_match_and_echo_raw(self):
        cs = ConditionSet.from_flags(rsi=["lt:30"])
        matches = apply_conditions([_enriched(rsi=25.0)], cs)
        assert len(matches) == 1
        t = matches[0].triggered[0]
        assert t.filter_type == "rsi" and t.value == 25.0  # 裸值回显

    def test_rsi_no_match(self):
        cs = ConditionSet.from_flags(rsi=["lt:20"])
        assert apply_conditions([_enriched(rsi=25.0)], cs) == []

    def test_macd_bar_sign(self):
        """MACD 柱 > 0 = 当前 DIF 在 DEA 上方 (非金叉)。"""
        cs = ConditionSet.from_flags(macd=["gt:0"])
        assert len(apply_conditions([_enriched(macd=0.5)], cs)) == 1
        assert apply_conditions([_enriched(macd=-0.5)], cs) == []

    def test_streak_gte(self):
        cs = ConditionSet.from_flags(streak=["gte:3"])
        assert len(apply_conditions([_enriched(streak=5.0)], cs)) == 1
        assert apply_conditions([_enriched(streak=2.0)], cs) == []

    def test_winner_gte(self):
        cs = ConditionSet.from_flags(winner=["gte:50"])
        assert len(apply_conditions([_enriched(winner=60.0)], cs)) == 1
        assert apply_conditions([_enriched(winner=40.0)], cs) == []

    def test_missing_subobject_not_match(self):
        """数据缺失 (technical/sentiment/chip None) → 不命中 (优雅降级 · 不误入选)。"""
        assert apply_conditions([_enriched(rsi=None)], ConditionSet.from_flags(rsi=["lt:30"])) == []
        assert apply_conditions([_enriched(streak=None)], ConditionSet.from_flags(streak=["gte:3"])) == []
        assert apply_conditions([_enriched(winner=None)], ConditionSet.from_flags(winner=["gte:50"])) == []

    def test_and_combo_rsi_streak_winner(self):
        cs = ConditionSet.from_flags(rsi=["lt:30"], streak=["gte:3"], winner=["gte:50"])
        hit = _enriched(rsi=25.0, streak=5.0, winner=60.0)
        miss = _enriched("000001", rsi=25.0, streak=1.0, winner=60.0)  # streak 不够
        matches = apply_conditions([hit, miss], cs)
        assert [m.result.symbol for m in matches] == ["600519"]
        assert len(matches[0].triggered) == 3  # rsi + streak + winner 都记

    def test_plain_scan_safe_with_new_filter(self):
        """传未 enrich 的 StockScanResult + rsi filter → getattr None → 不命中 (不炸)。"""
        assert apply_conditions([_scan()], ConditionSet.from_flags(rsi=["lt:30"])) == []


# ── apply_cross_section_conditions (--all 截面) ───────────────────────────

class TestApplyCrossSection:
    def _row(self, code="600519", rsi=None, streak=None, winner=None):
        from kan.core.cross_section import CrossSectionRow
        tech = TechnicalMetrics(rsi_6=rsi) if rsi is not None else None
        senti = SentimentMetrics(limit_times=streak) if streak is not None else None
        chip = ChipMetrics(winner_rate=winner) if winner is not None else None
        return CrossSectionRow(
            code=code, name="测试", valuation=None, valuation_context=None,
            technical=tech, sentiment=senti, chip=chip,
        )

    def test_no_filter_returns_all(self):
        rows = [self._row(rsi=25.0), self._row("000001", rsi=50.0)]
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags())
        assert len(out) == 2
        assert all(t == () for _, t in out)  # 取数语义 · 无 triggered

    def test_rsi_filter_and_echo(self):
        rows = [self._row("600519", rsi=25.0), self._row("000001", rsi=50.0)]
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags(rsi=["lt:30"]))
        assert [r.code for r, _ in out] == ["600519"]
        assert out[0][1][0].value == 25.0  # 裸值回显

    def test_streak_filter(self):
        rows = [self._row("600519", streak=5.0), self._row("000001", streak=1.0)]
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags(streak=["gte:3"]))
        assert [r.code for r, _ in out] == ["600519"]

    def test_combo_rsi_winner(self):
        rows = [
            self._row("600519", rsi=25.0, winner=60.0),   # 全中
            self._row("000001", rsi=25.0, winner=40.0),   # winner 不中
        ]
        cs = ConditionSet.from_flags(rsi=["lt:30"], winner=["gte:50"])
        out = apply_cross_section_conditions(rows, cs)
        assert [r.code for r, _ in out] == ["600519"]
        assert len(out[0][1]) == 2

    def test_missing_data_not_match(self):
        """截面缺数据 (sentiment None = 该股当日未涨停) → --streak 不命中。"""
        rows = [self._row("600519", streak=None)]  # 未涨停
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags(streak=["gte:3"]))
        assert out == []

"""整合-1 · 质量/资金 filter (DSL parse + match + apply) 纯函数单元测试。

覆盖 PeFilter / RoeFilter / MoneyflowFilter parse + apply_conditions (K线池) +
apply_cross_section_conditions (--all 截面)。合规:裸值回显 + None 降级
(数据缺失视为不命中 · 不误入选)。
"""
from __future__ import annotations

import datetime

import pytest

from kan.core.find_dsl import (
    ConditionSet,
    FilterParseError,
    MoneyflowFilter,
    PeFilter,
    RoeFilter,
)
from kan.core.find_filter import apply_conditions, apply_cross_section_conditions
from kan.core.models import (
    EnrichedResult,
    FundamentalMetrics,
    MoneyflowMetrics,
    PeriodResult,
    StockScanResult,
    ValuationMetrics,
)

# ── DSL parse ──────────────────────────────────────────────────────────

class TestNewFilterParse:
    def test_pe_parse(self):
        f = PeFilter.parse("lt:20")
        assert f.op == "lt" and f.value == 20.0

    def test_roe_parse_negative(self):
        f = RoeFilter.parse("gte:-5")  # ROE 可负 (亏损股)· 不卡范围
        assert f.op == "gte" and f.value == -5.0

    def test_moneyflow_parse_large(self):
        f = MoneyflowFilter.parse("gt:50000")  # 资金量级大 · 不卡范围
        assert f.op == "gt" and f.value == 50000.0

    @pytest.mark.parametrize("raw", ["lt", "lt:20:30", "20"])
    def test_bad_format(self, raw):
        with pytest.raises(FilterParseError, match="格式错误"):
            PeFilter.parse(raw)

    def test_bad_op(self):
        with pytest.raises(FilterParseError, match="运算符"):
            PeFilter.parse("xx:20")

    def test_bad_value(self):
        with pytest.raises(FilterParseError, match="非数字"):
            RoeFilter.parse("gte:abc")

    def test_nan_rejected(self):
        with pytest.raises(FilterParseError, match="非有限数"):
            MoneyflowFilter.parse("gt:nan")

    def test_from_flags_and_helpers(self):
        cs = ConditionSet.from_flags(pe=["lt:20"], roe=["gte:15"], moneyflow=["gt:0"])
        assert len(cs.pe_filters) == 1
        assert cs.has_cross_section_filters() is True
        assert cs.needs_fundamentals() is True
        assert cs.needs_moneyflow() is True
        assert cs.has_kline_filters() is False
        assert cs.is_empty() is False


# ── helpers ──────────────────────────────────────────────────────────────

def _scan(symbol="600519", is_st=False):
    return StockScanResult(
        symbol=symbol, name="测试", current_price=100.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[PeriodResult(period=180, n_low=50.0, n_high=200.0,
                              position_pct=30.0, at_low=False, at_high=False)],
        low_resonance=1, high_resonance=0, is_st=is_st,
    )


def _enriched(symbol="600519", pe=None, roe=None, net=None):
    val = (
        ValuationMetrics(trade_date=datetime.date(2026, 5, 29), pe_ttm=pe)
        if pe is not None else None
    )
    fund = FundamentalMetrics(roe=roe) if roe is not None else None
    mf = MoneyflowMetrics(net_amount=net) if net is not None else None
    return EnrichedResult.from_scan(_scan(symbol), val, fund, mf)


# ── apply_conditions (K线池) ──────────────────────────────────────────────

class TestApplyConditionsNewFilters:
    def test_pe_match_and_echo_raw(self):
        cs = ConditionSet.from_flags(pe=["lt:25"])
        matches = apply_conditions([_enriched(pe=20.0)], cs)
        assert len(matches) == 1
        t = matches[0].triggered[0]
        assert t.filter_type == "pe" and t.value == 20.0  # 裸值回显

    def test_pe_no_match(self):
        cs = ConditionSet.from_flags(pe=["lt:15"])
        assert apply_conditions([_enriched(pe=20.0)], cs) == []

    def test_roe_gte(self):
        cs = ConditionSet.from_flags(roe=["gte:15"])
        assert len(apply_conditions([_enriched(roe=18.0)], cs)) == 1
        assert apply_conditions([_enriched(roe=10.0)], cs) == []

    def test_moneyflow_inflow_vs_outflow(self):
        cs = ConditionSet.from_flags(moneyflow=["gt:0"])
        assert len(apply_conditions([_enriched(net=500.0)], cs)) == 1
        assert apply_conditions([_enriched(net=-500.0)], cs) == []

    def test_missing_subobject_not_match(self):
        """数据缺失 (子对象/字段 None) → 不命中 (优雅降级 · 不误入选)。"""
        assert apply_conditions([_enriched(pe=None)], ConditionSet.from_flags(pe=["lt:25"])) == []
        assert apply_conditions([_enriched(roe=None)], ConditionSet.from_flags(roe=["gte:15"])) == []

    def test_and_combo_pe_roe(self):
        cs = ConditionSet.from_flags(pe=["lt:25"], roe=["gte:15"])
        hit = _enriched(pe=20.0, roe=18.0)
        miss = _enriched("000001", pe=20.0, roe=10.0)  # roe 不够
        matches = apply_conditions([hit, miss], cs)
        assert [m.result.symbol for m in matches] == ["600519"]
        assert len(matches[0].triggered) == 2  # pe + roe 都记

    def test_plain_scan_safe_with_new_filter(self):
        """传未 enrich 的 StockScanResult + pe filter → getattr None → 不命中 (不炸)。"""
        assert apply_conditions([_scan()], ConditionSet.from_flags(pe=["lt:25"])) == []


# ── apply_cross_section_conditions (--all 截面) ───────────────────────────

class TestApplyCrossSection:
    def _row(self, code="600519", pe=None, net=None):
        from kan.core.cross_section import CrossSectionRow
        val = (
            ValuationMetrics(trade_date=datetime.date(2026, 5, 29), pe_ttm=pe)
            if pe is not None else None
        )
        mf = MoneyflowMetrics(net_amount=net) if net is not None else None
        return CrossSectionRow(
            code=code, name="测试", valuation=val, valuation_context=None, moneyflow=mf,
        )

    def test_no_filter_returns_all(self):
        rows = [self._row(pe=20.0), self._row("000001", pe=5.0)]
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags())
        assert len(out) == 2
        assert all(t == () for _, t in out)  # 取数语义 · 无 triggered

    def test_pe_filter_and_echo(self):
        rows = [self._row("600519", pe=20.0), self._row("000001", pe=40.0)]
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags(pe=["lt:30"]))
        assert [r.code for r, _ in out] == ["600519"]
        assert out[0][1][0].value == 20.0  # 裸值回显

    def test_moneyflow_filter(self):
        rows = [self._row("600519", net=1000.0), self._row("000001", net=-200.0)]
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags(moneyflow=["gt:0"]))
        assert [r.code for r, _ in out] == ["600519"]

    def test_pe_and_moneyflow_combo(self):
        rows = [
            self._row("600519", pe=20.0, net=1000.0),   # 全中
            self._row("000001", pe=20.0, net=-200.0),   # net 不中
        ]
        cs = ConditionSet.from_flags(pe=["lt:30"], moneyflow=["gt:0"])
        out = apply_cross_section_conditions(rows, cs)
        assert [r.code for r, _ in out] == ["600519"]
        assert len(out[0][1]) == 2

    def test_missing_data_not_match(self):
        """截面缺数据 (valuation/moneyflow None) → 不命中。"""
        rows = [self._row("600519", pe=None)]  # 无 valuation
        out = apply_cross_section_conditions(rows, ConditionSet.from_flags(pe=["lt:30"]))
        assert out == []

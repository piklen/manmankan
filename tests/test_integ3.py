"""整合-3 · 股东·持股结构 filter + 数据层衍生 纯函数单元测试。

覆盖 HoldersFilter/Top10Filter/NorthFilter parse + apply_conditions (K线池) +
shareholder 数据层衍生 (_derive_holders 去重环比 / _derive_top10 集中度+北向)。
合规:裸值回显 + None 降级 (无披露 / 未进前十视为不命中 · 不误入选) · 逐股 --all 不支持。
仿 test_integ2.py。无网络 (mock DataFrame · 不触 tushare)。
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from kan.core.find_dsl import (
    ConditionSet,
    FilterParseError,
    HoldersFilter,
    NorthFilter,
    Top10Filter,
)
from kan.core.find_filter import apply_conditions, apply_cross_section_conditions
from kan.core.models import (
    EnrichedResult,
    PeriodResult,
    ShareholderMetrics,
    StockScanResult,
)
from kan.data.shareholder import _derive_holders, _derive_top10

# ── DSL parse ──────────────────────────────────────────────────────────


class TestShareholderFilterParse:
    def test_holders_parse(self):
        f = HoldersFilter.parse("lt:0")
        assert f.op == "lt" and f.value == 0.0

    def test_holders_parse_negative(self):
        f = HoldersFilter.parse("lt:-5")  # 户数环比可负 (减少) · 不卡范围
        assert f.op == "lt" and f.value == -5.0

    def test_top10_parse(self):
        f = Top10Filter.parse("gte:50")
        assert f.op == "gte" and f.value == 50.0

    def test_north_parse(self):
        f = NorthFilter.parse("gte:3")
        assert f.op == "gte" and f.value == 3.0

    @pytest.mark.parametrize("raw", ["lt", "lt:20:30", "50"])
    def test_bad_format(self, raw):
        with pytest.raises(FilterParseError, match="格式错误"):
            Top10Filter.parse(raw)

    def test_bad_op(self):
        with pytest.raises(FilterParseError, match="运算符"):
            HoldersFilter.parse("xx:0")

    def test_bad_value(self):
        with pytest.raises(FilterParseError, match="非数字"):
            NorthFilter.parse("gte:abc")

    def test_nan_rejected(self):
        with pytest.raises(FilterParseError, match="非有限数"):
            Top10Filter.parse("gte:nan")

    def test_from_flags_and_gates(self):
        cs = ConditionSet.from_flags(
            holders=["lt:0"], top10=["gte:50"], north=["gte:3"],
        )
        assert len(cs.holders_filters) == 1
        assert len(cs.top10_filters) == 1
        assert len(cs.north_filters) == 1
        assert cs.needs_shareholder() is True
        # 逐股维度 · 不进截面 (同 fundamentals/roe · 全市场 --all 不支持)
        assert cs.has_cross_section_filters() is False
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


def _enriched(symbol="600519", holders=None, top10=None, north=None, has_sh=True):
    sh = None
    if has_sh and any(v is not None for v in (holders, top10, north)):
        sh = ShareholderMetrics(
            holder_chg_pct=holders, top10_float_ratio=top10, north_hold_ratio=north,
        )
    return EnrichedResult.from_scan(_scan(symbol), shareholder=sh)


# ── apply_conditions (K线池) ──────────────────────────────────────────────


class TestApplyConditionsShareholder:
    def test_holders_match_and_echo_raw(self):
        cs = ConditionSet.from_flags(holders=["lt:0"])
        matches = apply_conditions([_enriched(holders=-5.0)], cs)
        assert len(matches) == 1
        t = matches[0].triggered[0]
        assert t.filter_type == "holders" and t.value == -5.0  # 裸值回显

    def test_holders_no_match(self):
        cs = ConditionSet.from_flags(holders=["lt:0"])
        assert apply_conditions([_enriched(holders=3.0)], cs) == []  # 户数增加 · 不中

    def test_top10_gte(self):
        cs = ConditionSet.from_flags(top10=["gte:50"])
        assert len(apply_conditions([_enriched(top10=69.9)], cs)) == 1
        assert apply_conditions([_enriched(top10=40.0)], cs) == []

    def test_north_gte(self):
        cs = ConditionSet.from_flags(north=["gte:3"])
        assert len(apply_conditions([_enriched(north=4.4)], cs)) == 1
        assert apply_conditions([_enriched(north=1.0)], cs) == []

    def test_missing_shareholder_not_match(self):
        """shareholder None (未 enrich / 无披露) → 不命中 (优雅降级 · 不误入选)。"""
        assert apply_conditions(
            [_enriched(holders=None, has_sh=False)],
            ConditionSet.from_flags(holders=["lt:0"]),
        ) == []

    def test_missing_field_not_match(self):
        """字段 None (北向未进前十) → --north 不命中 (非数据故障 · 不误入选)。"""
        sh = ShareholderMetrics(top10_float_ratio=60.0, north_hold_ratio=None)
        er = EnrichedResult.from_scan(_scan(), shareholder=sh)
        assert apply_conditions([er], ConditionSet.from_flags(north=["gte:3"])) == []

    def test_and_combo(self):
        cs = ConditionSet.from_flags(
            holders=["lt:0"], top10=["gte:50"], north=["gte:3"],
        )
        hit = _enriched("600519", holders=-5.0, top10=69.9, north=4.4)
        miss = _enriched("000001", holders=-5.0, top10=40.0, north=4.4)  # top10 不够
        matches = apply_conditions([hit, miss], cs)
        assert [m.result.symbol for m in matches] == ["600519"]
        assert len(matches[0].triggered) == 3  # holders + top10 + north 都记

    def test_plain_scan_safe(self):
        """未 enrich 的 StockScanResult + holders filter → getattr None → 不命中 (不炸)。"""
        assert apply_conditions(
            [_scan()], ConditionSet.from_flags(holders=["lt:0"]),
        ) == []


# ── 逐股不进截面 (--all 路径契约守护) ──────────────────────────────────────


class TestShareholderNotInCrossSection:
    def test_cross_section_ignores_shareholder_filter(self):
        """股东 filter 是逐股维度 · has_cross_section_filters False → 截面视为无 filter (全量返回)。

        守护"逐股不进 --all"契约:即使传 shareholder filter · apply_cross_section 不筛行
        (CrossSectionRow 无 shareholder 字段 · --all 由 find_cmds 入口拦截 · 同 --roe)。
        """
        from kan.core.cross_section import CrossSectionRow

        rows = [
            CrossSectionRow(code="600519", name="测试", valuation=None,
                            valuation_context=None),
            CrossSectionRow(code="000001", name="测试2", valuation=None,
                            valuation_context=None),
        ]
        out = apply_cross_section_conditions(
            rows, ConditionSet.from_flags(top10=["gte:50"]),
        )
        assert len(out) == 2  # 全量返回 (股东 filter 不在截面生效)
        assert all(t == () for _, t in out)


# ── 数据层衍生 (_derive_holders / _derive_top10) ───────────────────────────


class TestDeriveHolders:
    def test_chg_pct_dedup_adjacent(self):
        """同 end_date 多 ann_date 去重 + 相邻两期算环比 (茅台真实数据形态)。"""
        raw = pd.DataFrame([
            {"ann_date": "20260417", "end_date": "20260331", "holder_num": 243159},
            {"ann_date": "20260425", "end_date": "20260331", "holder_num": 243159},  # 重复期
            {"ann_date": "20260417", "end_date": "20251231", "holder_num": 255892},
        ])
        end, num, chg = _derive_holders(raw)
        assert end == datetime.date(2026, 3, 31)
        assert num == 243159.0
        # (243159 - 255892) / 255892 * 100 ≈ -4.976 (不被重复期污染成 0)
        assert chg == pytest.approx(-4.976, abs=0.01)

    def test_single_period_no_chg(self):
        raw = pd.DataFrame([
            {"ann_date": "20260417", "end_date": "20260331", "holder_num": 100000},
        ])
        _end, num, chg = _derive_holders(raw)
        assert num == 100000.0
        assert chg is None  # 不足两期 → 环比 None

    def test_empty(self):
        assert _derive_holders(None) == (None, None, None)
        assert _derive_holders(pd.DataFrame()) == (None, None, None)


class TestDeriveTop10:
    def test_concentration_and_north(self):
        """最新期前十大求和 (集中度) + 筛"香港中央结算" (北向代理) · 旧期不计。"""
        raw = pd.DataFrame([
            {"end_date": "20251231", "holder_name": "贵州茅台集团", "hold_ratio": 54.0},
            {"end_date": "20251231", "holder_name": "香港中央结算有限公司", "hold_ratio": 4.4},
            {"end_date": "20251231", "holder_name": "证金公司", "hold_ratio": 0.64},
            {"end_date": "20250930", "holder_name": "旧期股东", "hold_ratio": 99.0},  # 非最新期
        ])
        end, ratio, north = _derive_top10(raw)
        assert end == datetime.date(2025, 12, 31)
        assert ratio == pytest.approx(54.0 + 4.4 + 0.64)  # 仅最新期求和
        assert north == pytest.approx(4.4)

    def test_north_not_in_top10(self):
        """香港中央结算未进前十 → north None (非故障) · 集中度仍算。"""
        raw = pd.DataFrame([
            {"end_date": "20251231", "holder_name": "大股东A", "hold_ratio": 60.0},
            {"end_date": "20251231", "holder_name": "基金B", "hold_ratio": 5.0},
        ])
        _end, ratio, north = _derive_top10(raw)
        assert ratio == pytest.approx(65.0)
        assert north is None

    def test_empty(self):
        assert _derive_top10(None) == (None, None, None)
        assert _derive_top10(pd.DataFrame()) == (None, None, None)

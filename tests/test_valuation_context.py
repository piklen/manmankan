"""kan/core/valuation_context.py · 估值分位 + 行业中位对照 (地基-3)。

纯函数逻辑 (pct_rank / _median / compute_valuation_context) 离线可测 ·
合规守护:对外只出分位 + 行业中位 · 绝不出个股估值裸值。
"""
from __future__ import annotations

import pandas as pd

from kan.core import valuation_context as vc
from kan.core.models import ValuationContext


class TestPctRank:
    def test_mid(self):
        assert vc.pct_rank(5, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 50.0

    def test_lowest(self):
        assert vc.pct_rank(1, [1, 2, 3, 4]) == 25.0

    def test_highest(self):
        assert vc.pct_rank(10, [1, 2, 3, 10]) == 100.0

    def test_none_value(self):
        assert vc.pct_rank(None, [1, 2, 3]) is None

    def test_empty_series(self):
        assert vc.pct_rank(5, []) is None

    def test_series_drops_none(self):
        assert vc.pct_rank(2, [1, None, 3]) == 50.0  # clean=[1,3] · 2≥1 → 1/2


class TestMedian:
    def test_odd(self):
        assert vc._median([3, 1, 2]) == 2.0

    def test_even(self):
        assert vc._median([1, 2, 3, 4]) == 2.5

    def test_empty(self):
        assert vc._median([]) is None

    def test_drops_none(self):
        assert vc._median([1, None, 3]) == 2.0


class TestComputeValuationContext:
    def _history(self, n=40, pe_base=20.0):
        return pd.DataFrame({
            "pe_ttm": [pe_base + i * 0.1 for i in range(n)],
            "pb": [6.0 + i * 0.01 for i in range(n)],
        })

    def _cross(self):
        return pd.DataFrame({
            "symbol": ["600519", "000858", "600600", "000001", "601318", "300999", "603288"],
            "pe_ttm": [20.0, 30.0, 25.0, 5.0, 8.0, 22.0, 28.0],
            "pb": [6.0, 5.0, 4.0, 0.6, 1.0, 5.0, 6.0],
        })

    def _map(self):
        return {
            "600519": "食品饮料", "000858": "食品饮料", "600600": "食品饮料",
            "300999": "食品饮料", "603288": "食品饮料",
            "000001": "银行", "601318": "非银金融",
        }

    def test_history_percentile_lowest(self):
        ctx = vc.compute_valuation_context(
            "600519", pe=20.0, pb=6.0, history_df=self._history(40),
            cross_section_df=self._cross(), l1_map=self._map(), lookback_days=730,
        )
        assert ctx.industry == "食品饮料"
        assert ctx.lookback_days == 730
        # pe=20.0 是历史序列 (20.0..23.9) 最低 → 历史分位 2.5 (1/40)
        assert ctx.pe_pct_rank == 2.5

    def test_industry_percentile_and_median(self):
        ctx = vc.compute_valuation_context(
            "600519", pe=20.0, pb=6.0, history_df=self._history(40),
            cross_section_df=self._cross(), l1_map=self._map(), lookback_days=730,
        )
        # 食品饮料同行 pe = [20,30,25,22,28] · 5 只 ≥ MIN_INDUSTRY
        assert ctx.industry_sample == 5
        assert ctx.pe_industry_median == 25.0
        assert ctx.pe_industry_pct == 20.0  # 20.0 高于行业 1/5 → 20 分位

    def test_insufficient_history_pct_none(self):
        ctx = vc.compute_valuation_context(
            "600519", pe=20.0, pb=6.0, history_df=self._history(10),
            cross_section_df=self._cross(), l1_map=self._map(), lookback_days=730,
        )
        assert ctx.pe_pct_rank is None  # 10 < MIN_HISTORY 30

    def test_unknown_industry_no_peers(self):
        ctx = vc.compute_valuation_context(
            "999999", pe=20.0, pb=6.0, history_df=self._history(40),
            cross_section_df=self._cross(), l1_map={}, lookback_days=730,
        )
        assert ctx.industry is None
        assert ctx.pe_industry_pct is None
        assert ctx.pe_industry_median is None

    def test_small_industry_below_min(self):
        small_map = {"600519": "食品饮料", "000858": "食品饮料"}  # 2 < MIN_INDUSTRY
        ctx = vc.compute_valuation_context(
            "600519", pe=20.0, pb=6.0, history_df=self._history(40),
            cross_section_df=self._cross(), l1_map=small_map, lookback_days=730,
        )
        assert ctx.industry_sample is None
        assert ctx.pe_industry_pct is None

    def test_none_pe_pct_none(self):
        ctx = vc.compute_valuation_context(
            "600519", pe=None, pb=6.0, history_df=self._history(40),
            cross_section_df=self._cross(), l1_map=self._map(), lookback_days=730,
        )
        assert ctx.pe_pct_rank is None
        assert ctx.pb_pct_rank is not None  # pb 仍算


class TestValuationContextCompliance:
    """ValuationContext 序列化:只分位 + 行业中位 · 无个股估值裸值。"""

    def test_model_dump_no_stock_raw_estimation(self):
        ctx = ValuationContext(
            industry="食品饮料", lookback_days=730, industry_sample=20,
            pe_pct_rank=2.5, pb_pct_rank=10.0,
            pe_industry_pct=20.0, pe_industry_median=25.0,
        )
        d = ctx.model_dump()
        # 个股估值裸值字段不存在 (只有分位 + 行业 aggregate 中位)
        assert "pe_ttm" not in d
        assert "pb" not in d
        assert "ps_ttm" not in d
        assert "dv_ttm" not in d
        # 分位 + 行业中位参照存在 (PRD 明确要"分位 + 行业中位对照")
        assert d["pe_pct_rank"] == 2.5
        assert d["pe_industry_median"] == 25.0
        assert d["industry"] == "食品饮料"


class TestBuildValuationContext:
    """编排层 build_valuation_context · mock 三个数据源 (无网络)。"""

    def _cross(self):
        return pd.DataFrame({
            "symbol": ["600519", "000858", "600600", "300999", "603288"],
            "pe_ttm": [20.0, 30.0, 25.0, 22.0, 28.0],
            "pb": [6.0, 5.0, 4.0, 5.0, 6.0],
        })

    def _hist(self):
        return pd.DataFrame({
            "pe_ttm": [20.0 + i * 0.1 for i in range(40)],
            "pb": [6.0 + i * 0.01 for i in range(40)],
        })

    def test_no_cross_section_returns_none(self, monkeypatch):
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: pd.DataFrame())
        assert vc.build_valuation_context("600519") is None  # 无 token → None

    def test_builds_from_mocked_sources(self, monkeypatch):
        m = dict.fromkeys(
            ["600519", "000858", "600600", "300999", "603288"], "食品饮料",
        )
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: self._cross())
        monkeypatch.setattr(
            "kan.data.metrics.fetch_valuation_history", lambda _s: self._hist(),
        )
        monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: dict(m))
        ctx = vc.build_valuation_context("600519")
        assert ctx is not None
        assert ctx.industry == "食品饮料"
        assert ctx.pe_industry_median == 25.0
        assert ctx.pe_pct_rank == 2.5  # 历史最低档

    def test_all_none_degrades_to_none(self, monkeypatch):
        # 截面有数据但无历史 + 无行业映射 → 全 None → 返 None (不出空壳)
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: self._cross())
        monkeypatch.setattr(
            "kan.data.metrics.fetch_valuation_history", lambda _s: pd.DataFrame(),
        )
        monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: {})
        assert vc.build_valuation_context("600519") is None


class TestInfoPayloadValuationContext:
    """export.info_payload 序列化 valuation_context · 守裸值不出。"""

    class _Trend:
        streak = 1
        streak_pct = 0.85
        direction = "↑反弹"

    def _scan(self):
        import datetime

        from kan.core.models import PeriodResult, StockScanResult
        return StockScanResult(
            symbol="600519", name="贵州茅台", current_price=1326.0,
            scan_date=datetime.date(2026, 5, 29),
            periods=[PeriodResult(
                period=60, n_low=1000.0, n_high=1400.0,
                position_pct=81.5, at_low=False, at_high=False,
            )],
            low_resonance=0, high_resonance=1,
        )

    def test_context_serialized_no_raw(self):
        import json

        from kan.storage import export
        ctx = ValuationContext(
            industry="食品饮料", lookback_days=730, industry_sample=20,
            pe_pct_rank=2.5, pe_industry_pct=20.0, pe_industry_median=25.0,
        )
        p = export.info_payload(
            self._scan(), self._Trend(), volume=None, data_cutoff=None,
            fetched_at=None, stale=True, valuation_context=ctx,
        )
        assert p["valuation_context"]["pe_pct_rank"] == 2.5
        assert p["valuation_context"]["industry"] == "食品饮料"
        # 估值裸值 key 不进 valuation_context
        s = json.dumps(p["valuation_context"], ensure_ascii=False)
        for raw in ("pe_ttm", "ps_ttm", "dv_ttm"):
            assert raw not in s

    def test_context_none_default(self):
        from kan.storage import export
        p = export.info_payload(
            self._scan(), self._Trend(), volume=None, data_cutoff=None,
            fetched_at=None, stale=True,
        )
        assert p["valuation_context"] is None  # 未传 → None (向后兼容)

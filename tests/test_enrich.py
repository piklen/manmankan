"""kan/core/enrich.py · enrich_results 截面指标挂载 (地基-2)。

mock fetch_metrics (enrich 内函数级 import · monkeypatch 模块属性生效) ·
传 trade_date 显式值避开 latest_trade_date (conftest 离线 akshare double)。
"""
from __future__ import annotations

import datetime

import pandas as pd

from kan.core import enrich
from kan.core.models import PeriodResult, StockScanResult


def _scan(symbol: str = "600519", name: str = "贵州茅台") -> StockScanResult:
    return StockScanResult(
        symbol=symbol, name=name, current_price=1326.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[PeriodResult(
            period=60, n_low=1000.0, n_high=1400.0,
            position_pct=81.5, at_low=False, at_high=False,
        )],
        low_resonance=0, high_resonance=1,
    )


class TestEnrichResults:
    def test_empty_results_no_fetch(self, monkeypatch):
        called = {"n": 0}

        def _fake(**_kw):
            called["n"] += 1
            return pd.DataFrame()
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", _fake)
        assert enrich.enrich_results([]) == []
        assert called["n"] == 0  # 空 results 不触网

    def test_attaches_valuation_raw_values(self, monkeypatch):
        df = pd.DataFrame([{
            "symbol": "600519", "trade_date": datetime.date(2026, 5, 29),
            "close": 1326.0, "pe_ttm": 20.04, "pb": 6.19, "ps_ttm": 9.6,
            "dv_ttm": 3.9, "turnover_rate": 0.61, "volume_ratio": 1.42,
            "total_mv": 1.0e8, "circ_mv": 1.0e8, "_source": "tushare_metrics",
        }])
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df)
        out = enrich.enrich_results([_scan()], trade_date="20260529")
        assert len(out) == 1
        assert out[0].symbol == "600519"
        # 数据层存原始值 (决策① · 裸值过滤在 export 层)
        assert out[0].valuation.pe_ttm == 20.04
        assert out[0].valuation.turnover_rate == 0.61
        assert out[0].valuation.source == "tushare_metrics"

    def test_missing_symbol_valuation_none(self, monkeypatch):
        df = pd.DataFrame([{
            "symbol": "000001", "trade_date": datetime.date(2026, 5, 29), "pe_ttm": 5.0,
        }])
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df)
        out = enrich.enrich_results([_scan("600519")], trade_date="20260529")
        assert out[0].valuation is None  # 截面无此股

    def test_empty_metrics_all_none(self, monkeypatch):
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: pd.DataFrame())
        out = enrich.enrich_results([_scan()], trade_date="20260529")
        assert out[0].valuation is None  # 无 token / 空 df → 优雅降级

    def test_nan_values_to_none(self, monkeypatch):
        df = pd.DataFrame([{
            "symbol": "600519", "trade_date": datetime.date(2026, 5, 29),
            "pe_ttm": float("nan"), "close": 1326.0,
        }])
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df)
        out = enrich.enrich_results([_scan()], trade_date="20260529")
        assert out[0].valuation.pe_ttm is None
        assert out[0].valuation.close == 1326.0

    def test_preserves_results_order(self, monkeypatch):
        df = pd.DataFrame([
            {"symbol": "000001", "trade_date": datetime.date(2026, 5, 29), "pe_ttm": 5.0},
            {"symbol": "600519", "trade_date": datetime.date(2026, 5, 29), "pe_ttm": 20.0},
        ])
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df)
        out = enrich.enrich_results(
            [_scan("600519"), _scan("000001", "平安银行")], trade_date="20260529",
        )
        # 输出顺序跟随 results · 不被 df 行顺序打乱
        assert [r.symbol for r in out] == ["600519", "000001"]

    def test_nat_trade_date_falls_back(self, monkeypatch):
        df = pd.DataFrame([{"symbol": "600519", "trade_date": pd.NaT, "pe_ttm": 20.0}])
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df)
        out = enrich.enrich_results([_scan()], trade_date="20260529")
        # ValuationMetrics.trade_date 必填 · NaT 退回 fetch 日
        assert out[0].valuation.trade_date == datetime.date(2026, 5, 29)

    def test_none_trade_date_uses_latest(self, monkeypatch):
        monkeypatch.setattr(
            "kan.core.trading_calendar.latest_trade_date",
            lambda: datetime.date(2026, 6, 1),
        )
        df = pd.DataFrame([{"symbol": "600519", "trade_date": pd.NaT, "pe_ttm": 20.0}])
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df)
        out = enrich.enrich_results([_scan()])  # trade_date=None → latest
        assert out[0].valuation.trade_date == datetime.date(2026, 6, 1)


class TestEnrichFundamentalsMoneyflow:
    """整合-1 · 按需挂 fundamentals (逐股) / moneyflow (截面)。"""

    _VAL_DF = pd.DataFrame([{
        "symbol": "600519", "trade_date": datetime.date(2026, 5, 29), "pe_ttm": 20.0,
    }])

    def test_need_false_skips_extra_fetch(self, monkeypatch):
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: self._VAL_DF)
        fund_calls = {"n": 0}
        mf_calls = {"n": 0}
        monkeypatch.setattr(
            "kan.data.fundamentals.fetch_fundamentals",
            lambda *a, **k: fund_calls.__setitem__("n", fund_calls["n"] + 1) or {},
        )
        monkeypatch.setattr(
            "kan.data.moneyflow.fetch_moneyflow",
            lambda **k: mf_calls.__setitem__("n", mf_calls["n"] + 1) or pd.DataFrame(),
        )
        out = enrich.enrich_results([_scan()], trade_date="20260529")
        assert out[0].fundamentals is None
        assert out[0].moneyflow is None
        assert fund_calls["n"] == 0  # need_fundamentals 默认 False · 逐股贵 · 不拉
        assert mf_calls["n"] == 0

    def test_need_fundamentals_attaches(self, monkeypatch):
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: self._VAL_DF)
        fund_row = pd.Series({
            "end_date": datetime.date(2025, 12, 31), "roe": 15.2,
            "netprofit_yoy": 8.5, "or_yoy": 12.1,
        })
        monkeypatch.setattr(
            "kan.data.fundamentals.fetch_fundamentals", lambda syms, **k: {"600519": fund_row},
        )
        out = enrich.enrich_results(
            [_scan()], trade_date="20260529", need_fundamentals=True,
        )
        assert out[0].fundamentals.roe == 15.2
        assert out[0].fundamentals.source == "tushare_fina"

    def test_need_moneyflow_attaches(self, monkeypatch):
        monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: self._VAL_DF)
        mf_df = pd.DataFrame([{
            "symbol": "600519", "trade_date": datetime.date(2026, 5, 29),
            "net_amount": 5000.0, "buy_elg_amount": 3000.0, "buy_lg_amount": 2000.0,
            "_source": "tushare_moneyflow",
        }])
        monkeypatch.setattr("kan.data.moneyflow.fetch_moneyflow", lambda **k: mf_df)
        out = enrich.enrich_results(
            [_scan()], trade_date="20260529", need_moneyflow=True,
        )
        assert out[0].moneyflow.net_amount == 5000.0
        assert out[0].moneyflow.source == "tushare_moneyflow"

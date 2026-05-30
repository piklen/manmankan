"""kan/data/metrics.py · fetch_valuation_history (估值历史时序 · 地基-3)。"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from kan.data import metrics


class TestFetchValuationHistory:
    @pytest.fixture
    def temp_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(metrics, "DATA_DIR", tmp_path)
        monkeypatch.setattr(metrics, "ensure_dirs", lambda: None)
        monkeypatch.setattr(
            "kan.core.trading_calendar.latest_trade_date",
            lambda: datetime.date(2026, 5, 29),
        )
        return tmp_path

    def test_no_token_empty_df(self, temp_env, monkeypatch):
        monkeypatch.setattr(
            "kan.data.tushare._fetch_tushare_metrics_history", lambda s, st: None,
        )
        df = metrics.fetch_valuation_history("600519")
        assert list(df.columns) == metrics._HISTORY_COLUMNS
        assert len(df) == 0

    def test_invalid_symbol_empty(self, temp_env):
        assert len(metrics.fetch_valuation_history("BK0001")) == 0

    def test_normalizes_and_caches(self, temp_env, monkeypatch):
        raw = pd.DataFrame({
            "trade_date": ["20260529", "20260528"],
            "pe_ttm": [20.0, 20.1], "pb": [6.0, 6.1],
        })
        monkeypatch.setattr(
            "kan.data.tushare._fetch_tushare_metrics_history",
            lambda s, st: raw.copy(),
        )
        df = metrics.fetch_valuation_history("600519")
        assert len(df) == 2
        assert df.iloc[0]["trade_date"] == datetime.date(2026, 5, 29)
        assert df.iloc[0]["pe_ttm"] == 20.0
        assert (temp_env / "metrics_hist_600519.parquet").exists()

    def test_cache_hit_skips_fetch(self, temp_env, monkeypatch):
        raw = pd.DataFrame({"trade_date": ["20260529"], "pe_ttm": [20.0]})
        calls = {"n": 0}

        def _f(s, st):
            calls["n"] += 1
            return raw.copy()
        monkeypatch.setattr("kan.data.tushare._fetch_tushare_metrics_history", _f)
        metrics.fetch_valuation_history("600519")
        metrics.fetch_valuation_history("600519")
        assert calls["n"] == 1  # 第二次走缓存

    def test_bad_numeric_coerced(self, temp_env, monkeypatch):
        raw = pd.DataFrame({"trade_date": ["20260529"], "pe_ttm": ["N/A"], "pb": [6.0]})
        monkeypatch.setattr(
            "kan.data.tushare._fetch_tushare_metrics_history", lambda s, st: raw.copy(),
        )
        df = metrics.fetch_valuation_history("600519")
        assert pd.isna(df.iloc[0]["pe_ttm"])
        assert df.iloc[0]["pb"] == 6.0

"""kan/data/metrics.py · 截面指标 normalize + cache + fetch_metrics 编排测试 (地基-1)。"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from kan.data import metrics


class TestNormalizeMetrics:
    def test_fills_missing_columns(self):
        df = pd.DataFrame({"symbol": ["600519"], "pe_ttm": [20.04]})
        out = metrics._normalize_metrics(df, source="tushare_metrics")
        assert list(out.columns) == metrics.METRICS_COLUMNS
        assert out.iloc[0]["_source"] == "tushare_metrics"
        assert out.iloc[0]["symbol"] == "600519"
        assert pd.isna(out.iloc[0]["pb"])  # 缺列补 NaN

    def test_requires_symbol(self):
        df = pd.DataFrame({"pe_ttm": [20.0]})
        with pytest.raises(ValueError, match="symbol"):
            metrics._normalize_metrics(df)

    def test_filters_non_6digit_symbol(self):
        df = pd.DataFrame({"symbol": ["600519", "BK0001", "abc", "000001"]})
        out = metrics._normalize_metrics(df)
        assert set(out["symbol"]) == {"600519", "000001"}

    def test_dedup_keeps_first(self):
        df = pd.DataFrame({"symbol": ["600519", "600519"], "pe_ttm": [20.0, 99.0]})
        out = metrics._normalize_metrics(df)
        assert len(out) == 1
        assert out.iloc[0]["pe_ttm"] == 20.0

    def test_bad_numeric_coerced_nan(self):
        df = pd.DataFrame({"symbol": ["600519"], "pe_ttm": ["N/A"]})
        out = metrics._normalize_metrics(df)
        assert pd.isna(out.iloc[0]["pe_ttm"])

    def test_trade_date_to_date(self):
        df = pd.DataFrame({"symbol": ["600519"], "trade_date": ["20260529"]})
        out = metrics._normalize_metrics(df)
        assert out.iloc[0]["trade_date"] == datetime.date(2026, 5, 29)


class TestValidateTradeDate:
    def test_valid(self):
        assert metrics._validate_trade_date("20260529") == "20260529"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="YYYYMMDD"):
            metrics._validate_trade_date("2026-05-29")
        with pytest.raises(ValueError, match="YYYYMMDD"):
            metrics._validate_trade_date("../etc")  # path traversal 防御


class TestFilterSymbols:
    def test_none_returns_all(self):
        df = pd.DataFrame({"symbol": ["600519", "000001"]})
        assert len(metrics._filter_symbols(df, None)) == 2

    def test_subset(self):
        df = pd.DataFrame({"symbol": ["600519", "000001", "300750"]})
        out = metrics._filter_symbols(df, ["600519", "300750"])
        assert set(out["symbol"]) == {"600519", "300750"}


class TestMetricsCacheFresh:
    def test_missing_file_not_fresh(self, tmp_path):
        assert metrics._metrics_cache_fresh(tmp_path / "nope.parquet", "20260529") is False

    def test_historical_date_always_fresh(self, tmp_path, monkeypatch):
        p = tmp_path / "metrics_20260101.parquet"
        p.write_bytes(b"x")
        monkeypatch.setattr(
            "kan.core.trading_calendar.latest_trade_date",
            lambda: datetime.date(2026, 6, 1),
        )
        # 20260101 < latest 20260601 · 历史交易日截面固定 · 永鲜
        assert metrics._metrics_cache_fresh(p, "20260101") is True


class TestFetchMetrics:
    @pytest.fixture
    def temp_env(self, tmp_path, monkeypatch):
        # DATA_DIR 指向 tmp · ensure_dirs no-op (tmp_path 已存在 · 不污染真实 ~/.local/share)
        monkeypatch.setattr(metrics, "DATA_DIR", tmp_path)
        monkeypatch.setattr(metrics, "ensure_dirs", lambda: None)
        return tmp_path

    def test_no_source_returns_empty_df(self, temp_env, monkeypatch):
        """chain 返回 None (无 token / 全失败) → 空 schema df · 不抛。"""
        class _NoneChain:
            def fetch(self, trade_date, symbols=None):
                return None
        monkeypatch.setattr(metrics, "default_metrics_chain", lambda: _NoneChain())
        df = metrics.fetch_metrics("20260529")
        assert list(df.columns) == metrics.METRICS_COLUMNS
        assert len(df) == 0

    def test_fetch_normalizes_and_caches(self, temp_env, monkeypatch):
        raw = pd.DataFrame({"symbol": ["600519", "000001"], "pe_ttm": [20.0, 5.0]})

        class _Chain:
            def fetch(self, trade_date, symbols=None):
                return raw.copy(), "tushare_metrics"
        monkeypatch.setattr(metrics, "default_metrics_chain", lambda: _Chain())
        df = metrics.fetch_metrics("20260529")
        assert len(df) == 2
        assert (temp_env / "metrics_20260529.parquet").exists()  # 落全市场缓存

    def test_cache_hit_skips_chain(self, temp_env, monkeypatch):
        raw = pd.DataFrame({"symbol": ["600519"], "pe_ttm": [20.0]})
        calls = {"n": 0}

        class _Chain:
            def fetch(self, trade_date, symbols=None):
                calls["n"] += 1
                return raw.copy(), "tushare_metrics"
        monkeypatch.setattr(metrics, "default_metrics_chain", lambda: _Chain())
        # 历史交易日 → 永鲜
        monkeypatch.setattr(
            "kan.core.trading_calendar.latest_trade_date",
            lambda: datetime.date(2026, 6, 1),
        )
        metrics.fetch_metrics("20260529")  # 拉 + 缓存
        metrics.fetch_metrics("20260529")  # 缓存命中 · 不再调 chain
        assert calls["n"] == 1

    def test_force_bypasses_cache(self, temp_env, monkeypatch):
        raw = pd.DataFrame({"symbol": ["600519"], "pe_ttm": [20.0]})
        calls = {"n": 0}

        class _Chain:
            def fetch(self, trade_date, symbols=None):
                calls["n"] += 1
                return raw.copy(), "tushare_metrics"
        monkeypatch.setattr(metrics, "default_metrics_chain", lambda: _Chain())
        monkeypatch.setattr(
            "kan.core.trading_calendar.latest_trade_date",
            lambda: datetime.date(2026, 6, 1),
        )
        metrics.fetch_metrics("20260529")
        metrics.fetch_metrics("20260529", force=True)  # force 跳缓存
        assert calls["n"] == 2

    def test_symbols_filter_on_fetch(self, temp_env, monkeypatch):
        raw = pd.DataFrame({
            "symbol": ["600519", "000001", "300750"], "pe_ttm": [20.0, 5.0, 50.0],
        })

        class _Chain:
            def fetch(self, trade_date, symbols=None):
                return raw.copy(), "tushare_metrics"
        monkeypatch.setattr(metrics, "default_metrics_chain", lambda: _Chain())
        df = metrics.fetch_metrics("20260529", symbols=["600519", "300750"])
        assert set(df["symbol"]) == {"600519", "300750"}

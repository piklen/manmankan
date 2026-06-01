"""kan/data/tushare.py · TushareMetricsSource (daily_basic 截面) 接入测试 (地基-1)。

对齐 test_tushare_pro.py 的 _FakeSession mock _get_session + temp_env fixture pattern。
"""
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from kan.data import tushare
from kan.storage import config


class TestStripTsSuffix:
    @pytest.mark.parametrize("ts_code,expected", [
        ("600519.SH", "600519"),
        ("000001.SZ", "000001"),
        ("830799.BJ", "830799"),
        ("600519", "600519"),  # 无后缀
    ])
    def test_strip(self, ts_code, expected):
        assert tushare._strip_ts_suffix(ts_code) == expected


class TestToMetricsDf:
    SAMPLE: ClassVar[dict] = {
        "fields": ["ts_code", "trade_date", "close", "pe_ttm", "pb"],
        "items": [
            ["600519.SH", "20260529", 1326.0, 20.04, 6.19],
            ["000001.SZ", "20260529", 12.0, 5.0, 0.6],
        ],
    }

    def test_maps_ts_code_to_symbol(self):
        df = tushare._to_metrics_df(self.SAMPLE)
        assert "symbol" in df.columns
        assert "ts_code" not in df.columns  # 原列已 drop
        assert set(df["symbol"]) == {"600519", "000001"}

    def test_empty_items_none(self):
        assert tushare._to_metrics_df({"fields": ["ts_code"], "items": []}) is None

    def test_missing_data_none(self):
        assert tushare._to_metrics_df(None) is None
        assert tushare._to_metrics_df({}) is None


class TestToDailyBarsDf:
    def test_maps_qfq_daily_bars(self):
        sample = {
            "fields": ["ts_code", "trade_date", "open_qfq", "high_qfq", "low_qfq", "close_qfq"],
            "items": [["600519.SH", "20260529", 10.0, 11.0, 9.0, 10.5]],
        }
        df = tushare._to_daily_bars_df(sample)
        assert list(df[["symbol", "date", "open", "high", "low", "close"]].iloc[0]) == [
            "600519", "20260529", 10.0, 11.0, 9.0, 10.5,
        ]


class TestFetchTushareMetrics:
    @pytest.fixture
    def temp_env(self, tmp_path, monkeypatch):
        from kan.infra import circuit_breaker
        from kan.storage import paths
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(paths, "CIRCUIT_PATH", tmp_path / "circuit.json")
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(circuit_breaker, "_default", None)
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def _fake_session(self, monkeypatch, sample):
        class _FakeSession:
            def post(self, url, json, timeout):
                m = MagicMock()
                m.status_code = 200
                m.json.return_value = sample
                return m
        monkeypatch.setattr(tushare, "_get_session", lambda: _FakeSession())

    def test_no_token_returns_none(self, temp_env):
        """未配 token → 直接 None · 不发请求。"""
        assert tushare._fetch_tushare_metrics("20260529") is None

    def test_with_token_returns_df(self, temp_env, monkeypatch):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})
        sample = {
            "code": 0,
            "data": {
                "fields": ["ts_code", "trade_date", "close", "pe_ttm", "pb", "dv_ttm"],
                "items": [["600519.SH", "20260529", 1326.0, 20.04, 6.19, 3.90]],
            },
        }
        self._fake_session(monkeypatch, sample)
        df = tushare._fetch_tushare_metrics("20260529")
        assert df is not None
        assert "symbol" in df.columns
        assert df.iloc[0]["symbol"] == "600519"  # ts_code 后缀已 strip
        assert df.iloc[0]["pe_ttm"] == 20.04

    def test_metrics_breaker_independent_from_kline(self, temp_env, monkeypatch):
        """tushare_metrics 熔断 key 独立于 K 线 tushare · K 线熔断不影响 metrics。"""
        from kan.infra import circuit_breaker
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})
        circuit_breaker.get_breaker().record("tushare", ok=False)  # 熔断 K 线
        sample = {
            "code": 0,
            "data": {"fields": ["ts_code", "pe_ttm"], "items": [["600519.SH", 20.0]]},
        }
        self._fake_session(monkeypatch, sample)
        # metrics 仍可拉 (不同熔断 key)
        assert tushare._fetch_tushare_metrics("20260529") is not None

    def test_metrics_breaker_skips_when_down(self, temp_env, monkeypatch):
        from kan.infra import circuit_breaker
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})
        circuit_breaker.get_breaker().record("tushare_metrics", ok=False)

        class _TrapSession:
            def post(self, *a, **kw):
                raise AssertionError("熔断器没拦住 · 不该发请求")
        monkeypatch.setattr(tushare, "_get_session", lambda: _TrapSession())
        assert tushare._fetch_tushare_metrics("20260529") is None

    def test_api_failure_records_breaker(self, temp_env, monkeypatch):
        from kan.infra import circuit_breaker
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        class _BoomSession:
            def post(self, *a, **kw):
                raise tushare.requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(tushare, "_get_session", lambda: _BoomSession())
        tushare._fetch_tushare_metrics("20260529")
        assert circuit_breaker.get_breaker().is_down("tushare_metrics")


class TestTushareMetricsSource:
    def test_name_priority(self):
        src = tushare.TushareMetricsSource()
        assert src.name == "tushare_metrics"  # 独立熔断 key
        assert src.priority == 10

    def test_is_available_false_without_token(self, tmp_path, monkeypatch):
        from kan.storage import paths
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        assert tushare.TushareMetricsSource().is_available() is False

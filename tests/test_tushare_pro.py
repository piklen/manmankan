"""kan/tushare_pro.py · TuShare Pro 数据源接入测试"""

from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from kan import config, tushare_pro


class TestNormalizeSymbolToTs:
    """6 位股票代码 → TuShare ts_code 格式（带交易所后缀）"""

    @pytest.mark.parametrize("symbol,expected", [
        ("600519", "600519.SH"),  # 上证主板
        ("601318", "601318.SH"),
        ("688981", "688981.SH"),  # 科创板
        ("000001", "000001.SZ"),  # 深证主板
        ("002594", "002594.SZ"),
        ("300750", "300750.SZ"),  # 创业板
        ("830799", "830799.BJ"),  # 北交所
        ("430047", "430047.BJ"),  # 新三板精选
        ("900901", "900901.SH"),  # 上证 B 股
    ])
    def test_normalizes_by_prefix(self, symbol, expected):
        assert tushare_pro._normalize_symbol_to_ts(symbol) == expected

    def test_unknown_prefix_defaults_to_sz(self):
        """未知前缀走深证防御性回退（实际 A 股不存在 5xxxxx，但 SDK 应不抛）"""
        assert tushare_pro._normalize_symbol_to_ts("500001") == "500001.SZ"

    def test_invalid_symbol_raises(self):
        with pytest.raises(ValueError, match="6 位"):
            tushare_pro._normalize_symbol_to_ts("abc")
        with pytest.raises(ValueError, match="6 位"):
            tushare_pro._normalize_symbol_to_ts("12345")


class TestResolveConfig:
    """env > config > default 优先级"""

    DEFAULT_ENDPOINT = "https://api.tushare.pro"

    @pytest.fixture
    def temp_config(self, tmp_path, monkeypatch):
        from kan import paths
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def test_no_config_no_env_returns_none_token_default_endpoint(self, temp_config):
        token, endpoint = tushare_pro._resolve_config()
        assert token is None
        assert endpoint == self.DEFAULT_ENDPOINT

    def test_config_only(self, temp_config):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_from_cfg"})
        token, endpoint = tushare_pro._resolve_config()
        assert token == "tk_from_cfg"
        assert endpoint == self.DEFAULT_ENDPOINT

    def test_env_overrides_config(self, temp_config, monkeypatch):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_from_cfg"})
        monkeypatch.setenv("TUSHARE_TOKEN", "tk_from_env")
        token, _ = tushare_pro._resolve_config()
        assert token == "tk_from_env"

    def test_endpoint_env_overrides(self, temp_config, monkeypatch):
        monkeypatch.setenv("TUSHARE_ENDPOINT", "https://mirror.example.com")
        _, endpoint = tushare_pro._resolve_config()
        assert endpoint == "https://mirror.example.com"

    def test_config_endpoint_used_when_no_env(self, temp_config):
        config.save({**config.DEFAULT_CONFIG, "tushare_endpoint": "https://my.mirror"})
        _, endpoint = tushare_pro._resolve_config()
        assert endpoint == "https://my.mirror"

    def test_blank_token_treated_as_unset(self, temp_config, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "   ")
        token, _ = tushare_pro._resolve_config()
        assert token is None

    def test_invalid_endpoint_falls_back_to_default(self, temp_config, monkeypatch):
        monkeypatch.setenv("TUSHARE_ENDPOINT", "not-a-url")
        _, endpoint = tushare_pro._resolve_config()
        assert endpoint == self.DEFAULT_ENDPOINT


class TestPostTushareApi:
    """POST JSON 协议 · 字段映射 · 错误码处理"""

    SAMPLE_RESPONSE: ClassVar[dict] = {
        "code": 0,
        "msg": "",
        "data": {
            "fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
            "items": [
                ["20260102", 1500.0, 1520.0, 1490.0, 1510.0, 100000.0, 150000000.0],
                ["20260103", 1510.0, 1530.0, 1500.0, 1525.0, 120000.0, 180000000.0],
            ],
        },
    }

    def test_post_sends_correct_payload(self, monkeypatch):
        captured = {}

        def fake_post(url, json, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = self.SAMPLE_RESPONSE
            return mock

        # ***REMOVED*** 后用 _get_session() · monkeypatch 改为 inject fake session
        class _FakeSession:
            def post(self, url, json, timeout):
                return fake_post(url, json, timeout)

        monkeypatch.setattr(tushare_pro, "_get_session", lambda: _FakeSession())

        result = tushare_pro._post_tushare_api(
            endpoint="http://api.tushare.pro",
            token="tk_test",
            api_name="daily",
            params={"ts_code": "600519.SH", "start_date": "20260101"},
            fields="trade_date,open,high,low,close,vol,amount",
        )

        assert captured["url"] == "http://api.tushare.pro"
        assert captured["json"]["api_name"] == "daily"
        assert captured["json"]["token"] == "tk_test"
        assert captured["json"]["params"]["ts_code"] == "600519.SH"
        assert captured["json"]["fields"] == "trade_date,open,high,low,close,vol,amount"
        assert captured["timeout"] == 30
        assert result == self.SAMPLE_RESPONSE["data"]

    def test_nonzero_code_returns_none(self, monkeypatch):
        def fake_post(url, json, timeout):
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = {"code": 40001, "msg": "token 无效", "data": None}
            return mock
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        assert tushare_pro._post_tushare_api(
            "http://api.tushare.pro", "bad", "daily", {}, "x") is None

    def test_http_5xx_returns_none(self, monkeypatch):
        def fake_post(url, json, timeout):
            mock = MagicMock()
            mock.status_code = 502
            mock.json.return_value = {}
            return mock
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        assert tushare_pro._post_tushare_api(
            "http://api.tushare.pro", "tk", "daily", {}, "x") is None

    def test_network_exception_returns_none(self, monkeypatch):
        def fake_post(*a, **kw):
            raise tushare_pro.requests.exceptions.ConnectionError("DNS fail")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        assert tushare_pro._post_tushare_api(
            "http://api.tushare.pro", "tk", "daily", {}, "x") is None

    def test_exception_message_does_not_leak_token(self, monkeypatch, caplog):
        """token 永不进 logs / exception 文本"""
        import logging
        def fake_post(*a, **kw):
            raise tushare_pro.requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        with caplog.at_level(logging.DEBUG):
            tushare_pro._post_tushare_api(
                "http://api.tushare.pro", "SECRET_TK", "daily", {}, "x")
        for rec in caplog.records:
            assert "SECRET_TK" not in rec.getMessage()


class TestToKlineDf:
    """TuShare 响应 → manmankan KLINE_REQUIRED schema 转换"""

    def test_maps_fields(self):
        data = {
            "fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
            "items": [
                ["20260102", 1500.0, 1520.0, 1490.0, 1510.0, 100000.0, 150000000.0],
            ],
        }
        df = tushare_pro._to_kline_df(data)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
        assert df.iloc[0]["close"] == 1510.0

    def test_empty_items_returns_none(self):
        data = {"fields": ["trade_date", "open"], "items": []}
        assert tushare_pro._to_kline_df(data) is None

    def test_missing_data_returns_none(self):
        assert tushare_pro._to_kline_df(None) is None
        assert tushare_pro._to_kline_df({}) is None


class TestFetchTushare:
    """_fetch_tushare 集成：resolver + circuit_breaker + client + DataFrame"""

    @pytest.fixture
    def temp_env(self, tmp_path, monkeypatch):
        from kan import circuit_breaker, paths
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(paths, "CIRCUIT_PATH", tmp_path / "circuit.json")
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(circuit_breaker, "_default", None)
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def test_no_token_returns_none(self, temp_env):
        """未配 token → 直接 None，不发请求"""
        assert tushare_pro._fetch_tushare("600519", "20260101") is None

    def test_with_token_returns_dataframe(self, temp_env, monkeypatch):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        sample = {
            "code": 0,
            "data": {
                "fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
                "items": [["20260102", 1500.0, 1520.0, 1490.0, 1510.0, 100000.0, 150000000.0]],
            },
        }

        def fake_post(url, json, timeout):
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = sample
            return mock

        # ***REMOVED*** 后用 _get_session() · monkeypatch 改为 inject fake session
        class _FakeSession:
            def post(self, url, json, timeout):
                return fake_post(url, json, timeout)

        monkeypatch.setattr(tushare_pro, "_get_session", lambda: _FakeSession())
        df = tushare_pro._fetch_tushare("600519", "20260101")
        assert df is not None
        assert "date" in df.columns
        assert "volume" in df.columns
        assert len(df) == 1

    def test_circuit_breaker_skips_when_down(self, temp_env, monkeypatch):
        from kan import circuit_breaker
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})
        cb = circuit_breaker.get_breaker()
        cb.record("tushare", ok=False)

        called = {"hit": False}
        def fake_post(*a, **kw):
            called["hit"] = True
            raise AssertionError("circuit breaker 没拦住")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)

        assert tushare_pro._fetch_tushare("600519", "20260101") is None
        assert not called["hit"]

    def test_api_failure_records_breaker(self, temp_env, monkeypatch):
        from kan import circuit_breaker
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        def fake_post(*a, **kw):
            raise tushare_pro.requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)

        tushare_pro._fetch_tushare("600519", "20260101")
        cb = circuit_breaker.get_breaker()
        assert cb.is_down("tushare")

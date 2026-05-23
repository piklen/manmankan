"""kan/tushare_pro.py · TuShare Pro 数据源接入测试"""

import pytest

from kan import tushare_pro


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


from kan import config


class TestResolveConfig:
    """env > config > default 优先级"""

    DEFAULT_ENDPOINT = "http://api.tushare.pro"

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

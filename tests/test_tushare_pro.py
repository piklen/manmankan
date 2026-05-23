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

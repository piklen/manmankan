"""涨跌停限制 + ST 检测测试"""

from datetime import date, timedelta

import pandas as pd

from kan.core.scanner import (
    ST_LIMIT_CHANGE_DATE,
    get_limit_threshold,
    scan_stock,
)


def test_main_board_threshold():
    assert get_limit_threshold("600519", "贵州茅台") == 10.0


def test_chinext_threshold():
    """创业板 30 开头 → 20%"""
    assert get_limit_threshold("300750", "宁德时代") == 20.0


def test_star_market_threshold():
    """科创板 68 开头 → 20%"""
    assert get_limit_threshold("688981", "中芯国际") == 20.0


def test_beijing_exchange_threshold():
    """北交所 8/4 开头 → 30%"""
    assert get_limit_threshold("830799", "测试股") == 30.0
    assert get_limit_threshold("430510", "测试股") == 30.0


def test_st_before_policy_change():
    """*ST 在 2026-07-06 前 5%"""
    before = ST_LIMIT_CHANGE_DATE - timedelta(days=1)
    assert get_limit_threshold("600519", "*ST 测试", as_of=before) == 5.0


def test_st_after_policy_change():
    """*ST 在 2026-07-06 起 10%"""
    after = ST_LIMIT_CHANGE_DATE
    assert get_limit_threshold("600519", "*ST 测试", as_of=after) == 10.0


def test_st_on_chinext_still_20():
    """创业板 ST 仍按 20%（板块优先）"""
    before = ST_LIMIT_CHANGE_DATE - timedelta(days=1)
    assert get_limit_threshold("300001", "*ST 创业", as_of=before) == 20.0


def _make_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    base = date(2026, 4, 1)
    return pd.DataFrame({
        "date": [base + timedelta(days=i) for i in range(n)],
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [10000] * n,
    })


def test_scan_stock_detects_limit_up():
    """主板涨幅 ≥ 9.9% 应标记为涨停"""
    df = _make_df([100.0] * 10 + [110.0])
    result = scan_stock(df, "600519", "贵州茅台")
    assert result.limit_up is True
    assert result.limit_down is False


def test_scan_stock_detects_limit_down():
    """主板跌幅 ≥ 9.9% 应标记为跌停"""
    df = _make_df([100.0] * 10 + [90.0])
    result = scan_stock(df, "600519", "贵州茅台")
    assert result.limit_down is True
    assert result.limit_up is False


def test_scan_stock_normal_change_not_flagged():
    df = _make_df([100.0] * 10 + [105.0])
    result = scan_stock(df, "600519", "贵州茅台")
    assert result.limit_up is False
    assert result.limit_down is False


def test_scan_stock_st_detection():
    df = _make_df([10.0] * 10)
    result = scan_stock(df, "000123", "*ST 测试")
    assert result.is_st is True


def test_scan_stock_non_st():
    df = _make_df([10.0] * 10)
    result = scan_stock(df, "600519", "贵州茅台")
    assert result.is_st is False

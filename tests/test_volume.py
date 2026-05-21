"""成交量异动测试 · calc_volume_state"""

import pandas as pd

from kan.scanner import VOLUME_WINDOW, calc_volume_state


def _df(volumes):
    """构造只含 volume 列的最小 df。"""
    return pd.DataFrame({"volume": volumes})


def test_volume_surge():
    """今日量 = 近 5 日均量的 3 倍 → 明显放大。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 300]))
    assert v is not None
    assert v.ratio == 3.0
    assert v.label == "明显放大"
    assert v.window == VOLUME_WINDOW


def test_volume_shrink():
    """今日量 = 近 5 日均量的 0.3 倍 → 明显萎缩。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 30]))
    assert v is not None
    assert v.ratio == 0.3
    assert v.label == "明显萎缩"


def test_volume_steady():
    """今日量 ≈ 近 5 日均量 → 量能平稳。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 110]))
    assert v is not None
    assert v.label == "量能平稳"


def test_volume_insufficient_history():
    """不足 VOLUME_WINDOW + 1 行 → None。"""
    assert calc_volume_state(_df([100, 100, 100])) is None


def test_volume_nan_today_returns_none():
    """今日 volume 缺失(腾讯源)→ None。"""
    assert calc_volume_state(_df([100, 100, 100, 100, 100, float("nan")])) is None


def test_volume_all_nan_returns_none():
    """整列 volume 缺失 → None。"""
    assert calc_volume_state(_df([float("nan")] * 6)) is None


def test_volume_missing_column_returns_none():
    """无 volume 列 → None。"""
    assert calc_volume_state(pd.DataFrame({"close": [1, 2, 3, 4, 5, 6]})) is None

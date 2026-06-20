"""成交量异动测试 · calc_volume_state · 5 档对称设计

档位边界(对数对称):
  [2.0, ∞)   明显放大
  [1.5, 2.0) 温和放大
  [0.67, 1.5)量能平稳   ← 0.67 = 1/1.5 几何中位对称
  [0.5, 0.67)温和萎缩
  [0, 0.5)   明显萎缩    ← 0.5 = 1/2.0 几何中位对称
"""

import pandas as pd

from kan.core.scanner import VOLUME_WINDOW, calc_volume_state


def _df(volumes, closes=None):
    """构造只含 volume 列的最小 df。"""
    data = {"volume": volumes}
    if closes is not None:
        data["close"] = closes
    return pd.DataFrame(data)


def test_volume_surge():
    """今日量 = 近 5 日均量的 3 倍 → 明显放大。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 300]))
    assert v is not None
    assert v.ratio == 3.0
    assert v.label == "明显放大"
    assert v.window == VOLUME_WINDOW


def test_volume_state_includes_price_direction_when_close_exists():
    """有 close 列时补充收盘方向与量价组合事实。"""
    v = calc_volume_state(
        _df(
            [100, 100, 100, 100, 100, 180],
            closes=[10, 10, 10, 10, 10, 11],
        )
    )
    assert v is not None
    assert v.price_direction == "收涨"
    assert v.state == "量增·收涨"


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


def test_volume_mild_surge_typical():
    """涨停日实例: 今日量 = 近 5 日均量的 1.73 倍 → 温和放大(不再误标量能平稳)。

    任务卡 5a 来源场景: kan info 002463 涨停日,旧 2 档把 1.73 倍归"量能平稳",
    违反"只如实描述"红线。本测试锚定 5 档落地。
    """
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 173]))
    assert v is not None
    assert v.ratio == 1.73
    assert v.label == "温和放大"


def test_volume_mild_surge_lower_boundary():
    """ratio 恰好 1.5 → 温和放大(下边界含)。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 150]))
    assert v is not None
    assert v.ratio == 1.5
    assert v.label == "温和放大"


def test_volume_steady_just_below_mild_surge():
    """ratio 1.49 → 量能平稳(温和放大区间不含)。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 149]))
    assert v is not None
    assert v.ratio == 1.49
    assert v.label == "量能平稳"


def test_volume_steady_lower_boundary():
    """ratio 恰好 0.67(= 1/1.5 几何对称) → 量能平稳(下边界含)。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 67]))
    assert v is not None
    assert v.ratio == 0.67
    assert v.label == "量能平稳"


def test_volume_mild_shrink_typical():
    """ratio = 0.6 → 温和萎缩(中间档落地)。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 60]))
    assert v is not None
    assert v.ratio == 0.6
    assert v.label == "温和萎缩"


def test_volume_mild_shrink_lower_boundary():
    """ratio 恰好 0.5(= 1/2.0 几何对称) → 温和萎缩(下边界含)。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 50]))
    assert v is not None
    assert v.ratio == 0.5
    assert v.label == "温和萎缩"


def test_volume_obvious_surge_upper_boundary():
    """ratio 恰好 2.0 → 明显放大(明显放大区间含 2.0)。"""
    v = calc_volume_state(_df([100, 100, 100, 100, 100, 200]))
    assert v is not None
    assert v.ratio == 2.0
    assert v.label == "明显放大"


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


def test_volume_zero_prior_average_returns_none():
    """近 VOLUME_WINDOW 日均量为 0 → None，避免除零。"""
    assert calc_volume_state(_df([0, 0, 0, 0, 0, 100])) is None

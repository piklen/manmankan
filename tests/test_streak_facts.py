"""所有连续段入口必须保留原值方向、复合变化和数据边界。"""

import numpy as np
import pandas as pd
import pytest

from kan.core.scanner_trend import calc_trend


def bars(closes, opens=None):
    return pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=len(closes)),
                         "open": closes if opens is None else opens, "close": closes})


def test_raw_direction_and_endpoint_return_do_not_depend_on_display_rounding():
    tiny = calc_trend(bars([10., 9., 9.0001]), "000001", "极小涨幅")
    assert tiny.streak == 1 and tiny.streak_exact
    result = calc_trend(bars([101., 100., 110., 121.]), "000001", "复合变化")
    assert result.streak == 2 and result.streak_pct == pytest.approx(21.)


def test_long_and_incomplete_runs_are_not_capped_or_claimed_exact():
    result = calc_trend(bars(np.arange(1., 65.)), "000001", "长连续段")
    assert result.streak == 63 and not result.streak_exact
    assert "至少63天" in result.direction
    gap = calc_trend(bars([10., 9., np.nan, 8., 9.]), "000001", "缺口")
    assert gap.streak == 1 and not gap.streak_exact
    candle = calc_trend(bars([11., 10.], [10., 9.]), "000001", "隔夜缺口", candle=True)
    assert candle.streak == 2 and candle.streak_pct == 0

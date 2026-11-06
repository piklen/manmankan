"""收益窗口的缺口、零变化和真实微小变化。"""

import numpy as np

from kan.core.returns import rolling_returns


def test_rolling_returns_preserve_dates_and_do_not_round_changes():
    close = np.array([10, 11, 12, np.nan, 14, 15, 15, 18])
    original = close.copy()
    valid = np.isfinite(close)
    np.testing.assert_allclose(
        rolling_returns(close, valid, 2),
        [np.nan, np.nan, 20, np.nan, np.nan, np.nan, (15 / 14 - 1) * 100, 20],
    )
    assert rolling_returns(close, valid, 1)[6] == 0
    assert np.isnan(rolling_returns(close[:2], valid[:2], 2)).all()
    tiny = np.array([100., 100. + 1e-8])
    assert rolling_returns(tiny, np.ones(2, dtype=bool), 1)[1] > 0
    np.testing.assert_equal(close, original)

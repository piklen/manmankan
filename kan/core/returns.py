"""已对齐市场交易日的区间变化；缺口保留，不压缩时间。"""

import numpy as np


def rolling_returns(close: np.ndarray, valid: np.ndarray, window: int) -> np.ndarray:
    """输入已校验；N 次变化需要连续 N+1 根有效日线。"""
    result = np.full(len(close), np.nan)
    if len(close) <= window:
        return result
    missing = np.concatenate(([0], np.cumsum(~valid)))
    complete = missing[window + 1:] == missing[:-window - 1]
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        changes = (close[window:] / close[:-window] - 1) * 100
    result[window:] = np.where(complete & np.isfinite(changes), changes, np.nan)
    return result

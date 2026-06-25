"""数值转换 + 坏数据检测 helper.

独立 module 理由:
- _normalize_kline (fetcher.py) 把 4 个数据源的字符串列统一转 numeric ·
  pd.to_numeric(errors="coerce") 会把无法解析的值静默变 NaN · 错误数据无声流入计算。
- 这里把"转换 + 检测被转坏的 cell 数"收成纯函数 · 0 上游依赖 · 不做 I/O 不打日志 ·
  由 caller 决定如何上报 · 方便单测。
- pandas 延迟 import (函数内) · 不破坏 fetcher 的冷启动优化 (顶层不 import pandas)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def to_numeric_checked(series: pd.Series) -> tuple[pd.Series, int]:
    """转 numeric (errors='coerce') · 返回 (转换后 series, 被转坏的 cell 数).

    "被转坏" = 转换前 notna、转换后 isna 的 cell · 即转换真正破坏掉的值。
    源数据本来就是 None / NaN / 空 的 cell 不计入 (那是正常缺口 · 不是错误)。

    Args:
        series: 待转换的列 (通常是数据源返回的字符串列).

    Returns:
        (converted, bad_count): converted 是 pd.to_numeric 结果;
        bad_count 是被转换破坏的 cell 数 (0 = 干净)。
    """
    import pandas as pd

    blank = series.astype("string").str.strip().eq("").fillna(False)
    converted = pd.to_numeric(series.mask(blank), errors="coerce")
    bad_count = int((converted.isna() & series.notna() & ~blank).sum())
    return converted, bad_count

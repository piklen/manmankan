"""成交量相对状态计算。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.models import VolumeState

if TYPE_CHECKING:
    import pandas as pd

VOLUME_WINDOW = 5


def calc_volume_state(df: pd.DataFrame) -> VolumeState | None:
    """今日成交量相对近 VOLUME_WINDOW 日均量的状态。

    比值天然单位无关:同一缓存来自单一数据源(fetch_kline 整体重写整个
    缓存文件),量纲在"今日量 / 均量"的比值里抵消,所以不受 baostock(股)
    / 东财(手) 等跨源 volume 单位差异影响。
    volume 缺失(腾讯源不返 volume / 旧缓存)或历史不足 → 返 None。
    """
    import pandas as pd

    if "volume" not in df.columns or len(df) < VOLUME_WINDOW + 1:
        return None
    today = df["volume"].iloc[-1]
    prior = df["volume"].iloc[-(VOLUME_WINDOW + 1):-1]
    if pd.isna(today):
        return None
    avg = prior.mean()
    if pd.isna(avg) or avg <= 0:
        return None
    ratio = round(float(today) / float(avg), 2)
    if ratio >= 2.0:
        label = "明显放大"
    elif ratio >= 1.5:
        label = "温和放大"
    elif ratio >= 0.67:
        label = "量能平稳"
    elif ratio >= 0.5:
        label = "温和萎缩"
    else:
        label = "明显萎缩"
    prev_close = None
    if len(df) >= 2 and "close" in df.columns:
        prev_close = df["close"].iloc[-2]
    close = df["close"].iloc[-1] if "close" in df.columns else None
    close_value = None if close is None or pd.isna(close) else float(close)
    prev_close_value = (
        None if prev_close is None or pd.isna(prev_close) else float(prev_close)
    )
    from kan.core.retail_facts import volume_price_state

    direction, state = volume_price_state(
        volume_ratio=ratio,
        close=close_value,
        prev_close=prev_close_value,
    )
    return VolumeState(
        ratio=ratio,
        label=label,
        window=VOLUME_WINDOW,
        price_direction=direction,
        state=state,
    )

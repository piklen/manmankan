"""连续涨跌计算。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


class TrendResult:
    def __init__(
        self,
        symbol: str,
        name: str,
        current_price: float,
        streak: int,
        streak_pct: float,
        daily_changes: list[tuple[str, float]],
        streak_exact: bool = True,
    ):
        self.symbol = symbol
        self.name = name
        self.current_price = current_price
        self.streak = streak  # 正=连涨 负=连跌
        self.streak_pct = streak_pct
        self.daily_changes = daily_changes  # [(date_str, change_pct), ...]
        self.streak_exact = streak_exact
        self.moneyflow_net: float | None = None

    @property
    def direction(self) -> str:
        bound = "" if self.streak_exact else "至少"
        if self.streak > 0:
            return f"涨{bound}{self.streak}天"
        elif self.streak < 0:
            return f"跌{bound}{abs(self.streak)}天"
        return "平" if self.streak_exact else "无法判定"


def calc_trend(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    candle: bool = False,
) -> TrendResult:
    """计算连续涨跌。

    candle=False: 收盘价口径（close vs 前日 close）
    candle=True:  阳线阴线口径（close vs 当日 open）
    """
    import numpy as np

    from kan.core.streaks import streak_counts

    if df.empty:
        raise ValueError("没有可计算的行情")
    close = df["close"]
    base = df["open"] if candle else close.shift(1)
    known = np.isfinite(close) & np.isfinite(base) & close.gt(0) & base.gt(0)
    changes = ((close / base - 1) * 100).where(known)
    if not np.isfinite(close.iloc[-1]) or close.iloc[-1] <= 0:
        raise ValueError("截止日收盘价缺失")
    current_price = float(close.iloc[-1])
    direction = 1 if changes.iloc[-1] > 0 else -1 if changes.iloc[-1] < 0 else 0
    counts, exact = streak_counts(changes.gt(0) if direction > 0 else changes.lt(0), known)
    days = int(counts.iloc[-1]) if direction else 0
    start = len(df) - days
    # 连续判定使用原值，区间变化按起止价格计算；展示精度不改变事实。
    streak_pct = (current_price / float(base.iloc[start]) - 1) * 100 if days else 0.0
    daily = [(str(df["date"].iloc[i]), round(float(changes.iloc[i]), 2))
             for i in range(len(df) - 1, max(-1, len(df) - 31), -1) if known.iloc[i]]
    return TrendResult(
        symbol=symbol,
        name=name,
        current_price=current_price,
        streak=direction * days,
        streak_pct=round(streak_pct, 2),
        daily_changes=daily,
        streak_exact=bool(exact.iloc[-1]),
    )

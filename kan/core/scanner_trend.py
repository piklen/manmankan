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
    ):
        self.symbol = symbol
        self.name = name
        self.current_price = current_price
        self.streak = streak  # 正=连涨 负=连跌
        self.streak_pct = streak_pct
        self.daily_changes = daily_changes  # [(date_str, change_pct), ...]
        self.moneyflow_net: float | None = None

    @property
    def direction(self) -> str:
        if self.streak > 0:
            return f"涨{self.streak}天"
        elif self.streak < 0:
            return f"跌{abs(self.streak)}天"
        return "平"


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
    if len(df) < 2:
        return TrendResult(symbol, name, float(df["close"].iloc[-1]), 0, 0.0, [])

    current_price = float(df["close"].iloc[-1])
    daily: list[tuple[str, float]] = []

    for i in range(1, min(len(df), 31)):
        idx = len(df) - i
        row = df.iloc[idx]
        d = str(row["date"])

        if candle:
            change = (float(row["close"]) - float(row["open"])) / float(row["open"]) * 100
        else:
            prev_close = float(df.iloc[idx - 1]["close"])
            change = (float(row["close"]) - prev_close) / prev_close * 100

        daily.append((d, round(change, 2)))

    # 计算连续天数（平盘穿透不断连续）
    streak = 0
    streak_pct = 0.0
    if daily:
        # 找到第一个非平盘的方向
        first_dir = 0
        for _, chg in daily:
            if chg > 0:
                first_dir = 1
                break
            elif chg < 0:
                first_dir = -1
                break

        if first_dir != 0:
            for _, chg in daily:
                if chg == 0.0:
                    # 平盘穿透：计入天数但不计入累计涨跌幅
                    streak += first_dir
                elif (first_dir > 0 and chg > 0) or (first_dir < 0 and chg < 0):
                    streak += first_dir
                    streak_pct += chg
                else:
                    break

    return TrendResult(
        symbol=symbol,
        name=name,
        current_price=current_price,
        streak=streak,
        streak_pct=round(streak_pct, 2),
        daily_changes=daily,
    )

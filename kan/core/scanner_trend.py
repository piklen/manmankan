"""连续涨跌计算。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.infra.log import debug_log

if TYPE_CHECKING:
    import pandas as pd


# streak 算法 cap · 与 calc_trend 的 min(len(df), 31) 对齐
TREND_STREAK_CAP = 30


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


def trend_batch_cross_section(
    watchlist: list[tuple[str, str]],
    *,
    candle: bool = False,
    panel: pd.DataFrame | None = None,
) -> list[TrendResult]:
    """截面版 trend_batch · 用全市场 daily panel 算 streak · trend --all 专用。

    与 `trend_batch` 的逐股 get_cached 路径等价输出,但数据源是 `fetch_recent_daily_bars`
    拉的近 31 天全市场截面(31 次 HTTP · vs 逐股 4137 次 HTTP)。

    - panel: 调用方预先拉的 (symbol,date,open,close,...) DataFrame · None 时本函数返回空
    - 输出只保留 watchlist 目标池内股票,避免上游日截面混入目标池外代码
    - 连续天数上限沿用 calc_trend 的 30 天 cap,保持与逐股路径同契约
    """
    if panel is None or panel.empty:
        return []

    name_map = dict(watchlist)
    results: list[TrendResult] = []

    # panel 按 symbol 分组 · 每组按 date 升序 · 喂 calc_trend
    for symbol, group in panel.groupby("symbol", sort=False):
        symbol_str = str(symbol)
        if symbol_str not in name_map:
            continue
        if group.empty:
            continue
        group = group.sort_values("date").reset_index(drop=True)
        name = name_map[symbol_str]
        try:
            result = calc_trend(group, symbol_str, name, candle=candle)
        except Exception as e:
            debug_log(__name__, f"cross-section calc_trend failed · symbol={symbol}", e)
            continue
        results.append(result)

    results.sort(key=lambda r: (-abs(r.streak), -abs(r.streak_pct)))
    return results

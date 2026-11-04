"""按收盘反向幅度确认波段；只使用窗口内已经发生的价格。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Literal

import numpy as np


def price_relation(left: float, right: float) -> int:
    """只消除复权乘除的浮点尾差；相对 1e-12 容差不是额外价格阈值。"""
    if isclose(left, right, rel_tol=1e-12, abs_tol=0):
        return 0
    return 1 if left > right else -1


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    kind: Literal["high", "low"]
    confirmed_index: int


@dataclass(frozen=True)
class SwingScan:
    pivots: list[Pivot]
    structure: int | None
    direction: int
    start_index: int
    extreme_index: int

    @property
    def count(self) -> int:
        return max(0, len(self.pivots) - 1)


def scan_swings(prices: np.ndarray, reversal_pct: float) -> SwingScan:
    """输入为完整正价格窗口；首段仅用于建立方向，不把边界锚点算作转折。

    上行从运行高点回落指定百分比时确认高点；下行从运行低点回升时确认
    低点。相同价格保留最后一次极值，确认时间单独记录，已确认点不重画。
    """
    threshold = reversal_pct / 100
    direction = 0
    low = high = start = extreme = 0
    pivots: list[Pivot] = []
    for index in range(1, len(prices)):
        price = prices[index]
        if direction == 0:
            if price_relation(price, prices[low]) <= 0:
                low = index
            if price_relation(price, prices[high]) >= 0:
                high = index
            if price_relation(price, prices[low]) > 0 and price_relation(price, prices[low] * (1 + threshold)) >= 0:
                direction, start, extreme = 1, low, index
            elif price_relation(price, prices[high]) < 0 and price_relation(price, prices[high] * (1 - threshold)) <= 0:
                direction, start, extreme = -1, high, index
        elif direction == 1:
            if price_relation(price, prices[extreme]) >= 0:
                extreme = index
            elif price_relation(price, prices[extreme] * (1 - threshold)) <= 0:
                pivots.append(Pivot(extreme, float(prices[extreme]), "high", index))
                direction, start, extreme = -1, extreme, index
        elif price_relation(price, prices[extreme]) <= 0:
            extreme = index
        elif price_relation(price, prices[extreme] * (1 + threshold)) >= 0:
            pivots.append(Pivot(extreme, float(prices[extreme]), "low", index))
            direction, start, extreme = 1, extreme, index

    highs = [pivot.price for pivot in pivots if pivot.kind == "high"]
    lows = [pivot.price for pivot in pivots if pivot.kind == "low"]
    structure = None
    if len(highs) >= 2 and len(lows) >= 2:
        high_change, low_change = price_relation(highs[-1], highs[-2]), price_relation(lows[-1], lows[-2])
        structure = high_change if high_change == low_change else 0
    return SwingScan(pivots, structure, direction, start, extreme)

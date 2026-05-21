from datetime import date

from pydantic import BaseModel


class Stock(BaseModel):
    symbol: str
    name: str
    added_at: date
    groups: dict[str, str | list[str]] = {}



class PeriodResult(BaseModel):
    period: int
    n_low: float
    n_high: float
    position_pct: float
    at_low: bool
    at_high: bool
    insufficient: bool = False
    trend: str = ""  # ↑ 反弹 / ↓ 下行 / → 持平


class StockScanResult(BaseModel):
    symbol: str
    name: str
    current_price: float
    scan_date: date
    periods: list[PeriodResult]
    low_resonance: int
    high_resonance: int
    is_st: bool = False
    limit_up: bool = False
    limit_down: bool = False


class VolumeState(BaseModel):
    """成交量异动状态 · 今日量 vs 近 window 日均量的比值。"""

    ratio: float   # 今日成交量 / 近 window 日均量
    label: str     # 明显放大 / 明显萎缩 / 量能平稳
    window: int    # 比较窗口(交易日数)

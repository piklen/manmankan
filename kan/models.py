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
    label: str     # 明显放大 / 温和放大 / 量能平稳 / 温和萎缩 / 明显萎缩
    window: int    # 比较窗口(交易日数)


class Board(BaseModel):
    """申万行业板块 · catalog 条目。"""

    code: str    # 申万代码 · 规范化无后缀 · 如 "801080"
    name: str    # 如 "半导体"
    level: int   # 1 | 2 | 3 (申万一/二/三级)
    size: int    # 成份个数


class Theme(BaseModel):
    """题材板块 · catalog 条目。

    跟 Board 字段不重合(无 level · 有 source) · 不复用 Board · 见 design §5.1。
    """

    code: str          # THS index_code "886108" | EM concept_code "BK1629"
    name: str          # "AI应用" / "白酒概念"
    source: str        # "ths" | "em"
    size: int | None = None  # 成分股数 · catalog 接口未必提供 · 可空

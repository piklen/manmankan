"""板块趋势与成员变化的稳定领域模型。

行业和题材都使用相同的 OHLC 连续趋势口径，但它们不是股票行，也不进入
``ScreenRow``。本模块只描述一次板块趋势查询及其可复核结果，持久化 Screen
仍负责成分股筛选、证据、候选和对比。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BoardModel(BaseModel):
    """板块契约统一拒绝未知字段，避免入口静默漂移。"""

    model_config = ConfigDict(extra="forbid")


class BoardKind(StrEnum):
    INDUSTRY = "industry"
    THEME = "theme"


class BoardTrendMode(StrEnum):
    CLOSE = "close"
    CANDLE = "candle"


class BoardTrendSort(StrEnum):
    STREAK = "streak"
    LATEST = "latest"
    MONEYFLOW = "moneyflow"


class BoardTrendQuery(BoardModel):
    """所有入口共用的板块趋势查询。"""

    kind: BoardKind = BoardKind.INDUSTRY
    mode: BoardTrendMode = BoardTrendMode.CLOSE
    up: Annotated[int | None, Field(ge=1, le=30)] = None
    down: Annotated[int | None, Field(ge=1, le=30)] = None
    min_streak: Annotated[int | None, Field(ge=1, le=30)] = None
    sort: BoardTrendSort = BoardTrendSort.STREAK
    level: Annotated[int, Field(ge=1, le=3)] = 1
    limit: Annotated[int | None, Field(ge=1, le=500)] = 30
    force: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> BoardTrendQuery:
        if self.up is not None and self.down is not None:
            raise ValueError("up 和 down 不能同时使用")
        if (
            self.sort is BoardTrendSort.MONEYFLOW
            and self.kind is BoardKind.INDUSTRY
            and self.level != 1
        ):
            raise ValueError("申万行业主力净额当前只支持一级行业")
        return self


class BoardDailyChange(BoardModel):
    date: str
    change_pct: float


class BoardTrendRow(BoardModel):
    rank: int
    kind: BoardKind
    code: str
    name: str
    current_price: float
    streak: int
    streak_pct: float
    direction: str
    latest_change_pct: float | None = None
    moneyflow_net: float | None = None
    daily_changes: list[BoardDailyChange] = Field(default_factory=list)

    @property
    def symbol(self) -> str:
        """兼容现有终端与导出渲染器的只读字段名。"""

        return self.code


class BoardTrendFailure(BoardModel):
    code: str
    name: str
    message: str


class BoardTrendCoverage(BoardModel):
    total: int
    evaluated: int
    matched: int
    returned: int
    errors: int


class BoardTrendSnapshot(BoardModel):
    schema_version: int = 1
    query: BoardTrendQuery
    source: str
    data_cutoff: str | None = None
    partial: bool = False
    coverage: BoardTrendCoverage
    rows: list[BoardTrendRow] = Field(default_factory=list)
    failures: list[BoardTrendFailure] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BoardPulseQuery(BoardModel):
    """查询一个行业/题材在最新完整交易日的成分股内部结构。"""

    kind: BoardKind
    value: Annotated[str, Field(min_length=1, max_length=80)]
    level: Annotated[int, Field(ge=1, le=3)] = 1
    limit: Annotated[int, Field(ge=1, le=10)] = 5
    force: bool = False


class BoardPulseMember(BoardModel):
    rank: int
    code: str
    name: str
    close: float
    change_pct: float


class BoardPulseCoverage(BoardModel):
    total: int
    evaluated: int
    up: int
    down: int
    flat: int
    missing: int


class BoardPulseSnapshot(BoardModel):
    """板块成分股同一交易日的涨跌分布，不表示权重贡献或新闻因果。"""

    schema_version: int = 1
    query: BoardPulseQuery
    board_code: str
    board_name: str
    source: str
    data_cutoff: str
    previous_date: str
    partial: bool = False
    coverage: BoardPulseCoverage
    up_ratio_pct: float
    down_ratio_pct: float
    median_change_pct: float
    top_up: list[BoardPulseMember] = Field(default_factory=list)
    top_down: list[BoardPulseMember] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "BoardDailyChange",
    "BoardKind",
    "BoardPulseCoverage",
    "BoardPulseMember",
    "BoardPulseQuery",
    "BoardPulseSnapshot",
    "BoardTrendCoverage",
    "BoardTrendFailure",
    "BoardTrendMode",
    "BoardTrendQuery",
    "BoardTrendRow",
    "BoardTrendSnapshot",
    "BoardTrendSort",
]

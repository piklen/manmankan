"""板块指数历史事件复核的稳定领域模型。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from kan.domain.board import BoardKind, BoardModel, BoardTrendMode


class BoardStudyDirection(StrEnum):
    UP = "up"
    DOWN = "down"


class BoardStudySamplePolicy(StrEnum):
    FIRST_HIT = "first_hit"
    NON_OVERLAPPING = "non_overlapping"


class BoardHistoryStudyQuery(BoardModel):
    """用户显式选择的历史事件定义，不含自动优化参数。"""

    kind: BoardKind
    value: Annotated[str, Field(min_length=1, max_length=80)]
    level: Annotated[int, Field(ge=1, le=3)] = 1
    mode: BoardTrendMode
    direction: BoardStudyDirection
    min_streak: Annotated[int, Field(ge=2, le=30)]
    forward_days: Annotated[int, Field(ge=1, le=60)]
    lookback_years: Annotated[int, Field(ge=1, le=15)]
    sample_policy: BoardStudySamplePolicy
    benchmark_code: str | None = "000300.SH"
    force: bool = False


class BoardHistoryCoverage(BoardModel):
    observations: int
    first_hits: int
    selected: int
    completed: int
    censored: int
    benchmark_aligned: int


class BoardHistoryEvent(BoardModel):
    event_date: str
    forward_date: str
    streak: int
    event_close: float
    forward_close: float
    return_pct: float
    benchmark_return_pct: float | None = None
    relative_return_pct: float | None = None


class ReturnDistribution(BoardModel):
    count: int
    positive: int
    negative: int
    flat: int
    positive_ratio_pct: float | None = None
    mean_pct: float | None = None
    median_pct: float | None = None
    p25_pct: float | None = None
    p75_pct: float | None = None
    min_pct: float | None = None
    max_pct: float | None = None


class PointInTimeAudit(BoardModel):
    scope: Literal["provider_board_index_series"] = "provider_board_index_series"
    uses_current_constituents: Literal[False] = False
    reconstructs_historical_stock_pool: Literal[False] = False
    provider_vintage_archive: Literal[False] = False
    benchmark_exact_date_alignment: Literal[True] = True
    notes: list[str] = Field(default_factory=list)


class BoardHistoryStudy(BoardModel):
    schema_version: int = 1
    query: BoardHistoryStudyQuery
    board_code: str
    board_name: str
    source: str
    benchmark_name: str | None = None
    benchmark_source: str | None = None
    data_start: str
    data_cutoff: str
    coverage: BoardHistoryCoverage
    events: list[BoardHistoryEvent] = Field(default_factory=list)
    raw_distribution: ReturnDistribution
    benchmark_distribution: ReturnDistribution
    relative_distribution: ReturnDistribution
    audit: PointInTimeAudit = Field(default_factory=PointInTimeAudit)
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "BoardHistoryCoverage",
    "BoardHistoryEvent",
    "BoardHistoryStudy",
    "BoardHistoryStudyQuery",
    "BoardStudyDirection",
    "BoardStudySamplePolicy",
    "PointInTimeAudit",
    "ReturnDistribution",
]

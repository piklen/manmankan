"""行业/题材每日趋势复看的稳定领域模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from kan.domain.board import (
    BoardKind,
    BoardModel,
    BoardTrendMode,
    BoardTrendSnapshot,
)


class BoardReviewChangeType(StrEnum):
    """两份同口径板块趋势快照之间的客观变化。"""

    DATA_APPEARED = "data_appeared"
    DATA_UNAVAILABLE = "data_unavailable"
    DIRECTION_CHANGED = "direction_changed"
    STREAK_EXTENDED = "streak_extended"
    STREAK_SHORTENED = "streak_shortened"


class BoardDailyReviewRequest(BoardModel):
    """创建每日复看的输入；不包含策略阈值或隐藏评分。"""

    mode: BoardTrendMode = BoardTrendMode.CLOSE
    industry_level: Annotated[int, Field(ge=1, le=3)] = 1
    force: bool = False


class BoardReviewSection(BoardModel):
    """一个板块类型的趋势事实，或该类型的明确失败。"""

    kind: BoardKind
    snapshot: BoardTrendSnapshot | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_hint: str | None = None

    @model_validator(mode="after")
    def require_snapshot_or_error(self) -> BoardReviewSection:
        if self.snapshot is None and self.error_code is None:
            raise ValueError("复看分区必须提供 snapshot 或 error")
        if self.snapshot is not None and self.error_code is not None:
            raise ValueError("复看分区不能同时提供 snapshot 和 error")
        if self.snapshot is not None and self.snapshot.query.kind is not self.kind:
            raise ValueError("复看分区 kind 与 snapshot 不一致")
        return self


class BoardReviewChange(BoardModel):
    kind: BoardKind
    code: str
    name: str
    change_type: BoardReviewChangeType
    previous_streak: int | None = None
    current_streak: int | None = None
    previous_rank: int | None = None
    current_rank: int | None = None


class BoardReviewChangeCounts(BoardModel):
    data_appeared: int = 0
    data_unavailable: int = 0
    direction_changed: int = 0
    streak_extended: int = 0
    streak_shortened: int = 0


class BoardReviewSectionSummary(BoardModel):
    kind: BoardKind
    source: str | None = None
    data_cutoff: str | None = None
    partial: bool = False
    total: int = 0
    evaluated: int = 0
    error_code: str | None = None
    error_message: str | None = None


class BoardDailyReview(BoardModel):
    """一次不可变的行业 + 题材日线趋势复看。"""

    schema_version: int = 1
    review_id: str
    created_at: datetime
    mode: BoardTrendMode
    industry_level: int
    result_hash: str
    previous_review_id: str | None = None
    partial: bool = False
    sections: list[BoardReviewSection] = Field(min_length=2, max_length=2)
    changes: list[BoardReviewChange] = Field(default_factory=list)
    change_counts: BoardReviewChangeCounts = Field(
        default_factory=BoardReviewChangeCounts
    )
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_both_board_kinds(self) -> BoardDailyReview:
        kinds = {section.kind for section in self.sections}
        if kinds != {BoardKind.INDUSTRY, BoardKind.THEME}:
            raise ValueError("每日复看必须同时描述行业与题材分区")
        return self


class BoardDailyReviewSummary(BoardModel):
    schema_version: int = 1
    review_id: str
    created_at: datetime
    mode: BoardTrendMode
    industry_level: int
    result_hash: str
    previous_review_id: str | None = None
    partial: bool = False
    sections: list[BoardReviewSectionSummary] = Field(min_length=2, max_length=2)
    change_counts: BoardReviewChangeCounts = Field(
        default_factory=BoardReviewChangeCounts
    )


__all__ = [
    "BoardDailyReview",
    "BoardDailyReviewRequest",
    "BoardDailyReviewSummary",
    "BoardReviewChange",
    "BoardReviewChangeCounts",
    "BoardReviewChangeType",
    "BoardReviewSection",
    "BoardReviewSectionSummary",
]

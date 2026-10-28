"""个人关注台的事实、观察笔记与复看记录。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from kan.domain.screen import Candidate, CandidateStatus, StrictModel


class FocusPeriod(StrictModel):
    period: int
    position_pct: float | None = None
    previous_position_pct: float | None = None
    change_pp: float | None = None
    low: float | None = None
    high: float | None = None


class FocusReviewEntry(StrictModel):
    reviewed_at: datetime
    data_cutoff: date
    note: str
    price: float
    positions: dict[str, float | None]
    data_hash: str = ""
    candidate_list_id: str | None = None


class FocusRow(StrictModel):
    symbol: str
    name: str
    sources: list[str]
    source: str = "local_cache"
    data_hash: str = ""
    available: bool = False
    message: str | None = None
    price: float | None = None
    change_pct: float | None = None
    data_cutoff: date | None = None
    previous_cutoff: date | None = None
    fetched_at: str | None = None
    stale: bool = True
    periods: list[FocusPeriod] = Field(default_factory=list)
    streak: int | None = None
    note: str = ""
    candidate_list_id: str | None = None
    candidate_status: CandidateStatus | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    reviewed: bool = False
    reviewed_at: datetime | None = None
    reviewed_data_cutoff: date | None = None
    review_history: list[FocusReviewEntry] = Field(default_factory=list)


class FocusSnapshot(StrictModel):
    generated_at: datetime
    expected_cutoff: date | None = None
    total: int
    available: int
    stale: int
    rows: list[FocusRow]
    warnings: list[str] = Field(default_factory=list)


class FocusAddRequest(StrictModel):
    symbol: str


class FocusNoteRequest(StrictModel):
    note: str = Field(max_length=2_000)
    list_id: str | None = None


class FocusReviewRequest(StrictModel):
    expected_data_hash: str | None = None
    expected_note: str | None = Field(default=None, max_length=2_000)

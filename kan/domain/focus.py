"""个人股票池的成员身份与观察笔记。"""

from datetime import datetime

from pydantic import Field

from kan.domain.workspace import Candidate, CandidateStatus, StrictModel


class FocusRow(StrictModel):
    symbol: str
    name: str
    sources: list[str]
    note: str = ""
    candidate_list_id: str | None = None
    candidate_status: CandidateStatus | None = None
    candidates: list[Candidate] = Field(default_factory=list)


class FocusSnapshot(StrictModel):
    generated_at: datetime
    total: int
    rows: list[FocusRow]


class FocusAddRequest(StrictModel):
    symbol: str


class FocusNoteRequest(StrictModel):
    note: str = Field(max_length=2_000)
    list_id: str | None = None

"""个人股票池与本地状态的边界模型。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """禁止入口静默吞掉未知字段。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CandidateStatus(StrEnum):
    RESEARCH = "research"
    WATCH = "watch"
    SELECTED = "selected"
    REJECTED = "rejected"


class Candidate(StrictModel):
    list_id: str
    symbol: str
    name: str
    status: CandidateStatus = CandidateStatus.RESEARCH
    note: str = Field(default="", max_length=2_000)
    source_run_id: str | None = None
    added_at: datetime
    updated_at: datetime


class CandidateList(StrictModel):
    list_id: str
    name: str
    candidates: list[Candidate] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

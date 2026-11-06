"""保存当时的观察与完整成员事实；复看不改写原记录。"""

from datetime import date, datetime

from pydantic import Field, model_validator

from kan.domain.discovery import (
    DiscoveryComparison,
    DiscoveryGroup,
    DiscoveryMember,
    DiscoveryQuery,
    DiscoveryTransition,
)
from kan.domain.market_study import StudyModel


class ObservationSnapshot(StudyModel):
    as_of: date
    current_start: date | None
    previous_as_of: date | None
    previous_start: date | None
    group: DiscoveryGroup
    members: list[DiscoveryMember]


class ObservationSaveRequest(StudyModel):
    title: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=4_000)
    query: DiscoveryQuery

    @model_validator(mode="after")
    def require_fixed_date(self) -> "ObservationSaveRequest":
        if self.query.as_of is None:
            raise ValueError("保存观察必须明确当时的截止日期")
        return self


class ObservationEditRequest(StudyModel):
    title: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=4_000)


class ObservationReviewRequest(StudyModel):
    as_of: date | None = None


class ObservationRecord(StudyModel):
    id: str
    title: str
    note: str
    created_at: datetime
    query: DiscoveryQuery
    scope_label: str
    snapshot: ObservationSnapshot


class ObservationSummary(StudyModel):
    id: str
    title: str
    note: str
    created_at: datetime
    as_of: date
    window: int
    scope_label: str
    total: int


class ObservationReviewResult(StudyModel):
    observation: ObservationRecord
    current: ObservationSnapshot
    comparison: DiscoveryComparison
    transitions: list[DiscoveryTransition]

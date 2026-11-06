"""市场观察：完整范围的分布、变化与可追溯成员。"""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from kan.domain.market_study import StudyModel

TransitionKey = Literal["up_up", "down_up", "up_down", "down_down", "flat", "unknown"]


class DiscoveryQuery(StudyModel):
    universe: Literal["all", "personal", "codes"] = "all"
    codes: list[str] = Field(default_factory=list, max_length=10_000)
    industries: list[str] = Field(default_factory=list, max_length=100)
    as_of: date | None = None
    window: int = Field(default=20, ge=2, le=120)

    @model_validator(mode="after")
    def validate_scope(self) -> "DiscoveryQuery":
        from kan.storage.watchlist_models import _normalize_symbol

        if self.universe == "codes":
            if not self.codes:
                raise ValueError("请至少填写一个股票代码")
            self.codes = list(dict.fromkeys(_normalize_symbol(code) for code in self.codes))
        elif self.codes:
            raise ValueError("仅代码池接受代码列表")
        self.industries = list(dict.fromkeys(name.strip() for name in self.industries if name.strip()))
        return self


class DiscoveryStats(StudyModel):
    total: int
    available: int
    missing: int
    up: int
    down: int
    flat: int
    positive_share: float | None
    median_return: float | None
    q25: float | None
    q75: float | None


class DiscoveryComparison(StudyModel):
    available: int
    missing: int
    current_positive_share: float | None
    previous_positive_share: float | None
    breadth_delta_pp: float | None
    current_median: float | None
    previous_median: float | None


class DiscoveryHistoryPoint(StudyModel):
    date: date
    available: int
    up: int
    down: int
    flat: int
    positive_share: float | None
    median_return: float | None


class DiscoveryTransition(StudyModel):
    key: TransitionKey
    label: str
    count: int


class DiscoveryBin(StudyModel):
    key: str
    label: str
    count: int


class DiscoveryObservation(StudyModel):
    kind: Literal["breadth", "distribution", "comparison", "coverage"]
    title: str
    detail: str


class DiscoveryMember(StudyModel):
    symbol: str
    name: str
    industry: str
    latest_available: bool
    return_pct: float | None
    previous_return_pct: float | None
    change_pct: float | None
    transition: TransitionKey
    distribution_bin: str | None
    source: str
    reason: str | None


class DiscoveryGroup(StudyModel):
    name: str
    total: int
    current: DiscoveryStats
    comparison: DiscoveryComparison
    history: list[DiscoveryHistoryPoint]
    history_available: int
    transitions: list[DiscoveryTransition]
    distribution: list[DiscoveryBin]
    observations: list[DiscoveryObservation]


class DiscoveryDataGap(StudyModel):
    date: date
    missing: int


class DiscoveryResult(StudyModel):
    query: DiscoveryQuery
    as_of: date
    current_start: date | None
    previous_as_of: date | None
    previous_start: date | None
    common_data_date: date | None
    common_data_count: int
    market: DiscoveryGroup
    industries: list[DiscoveryGroup]
    members: list[DiscoveryMember]
    data_gaps: list[DiscoveryDataGap]
    warnings: list[str]

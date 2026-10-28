"""市场研究实验台：一份条件贯通当前匹配与历史事件。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

StudyField = Literal[
    "change_pct", "gap_pct", "body_pct", "return_pct", "position", "low_age",
    "up_days", "down_days", "bull_days", "bear_days", "joint_up_days", "volume_ratio", "shape_distance",
]


class StudyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class StudyCondition(StudyModel):
    field: StudyField
    operator: Literal["gt", "gte", "lt", "lte", "eq"]
    value: float
    window: int | None = Field(default=None, ge=2, le=360)

    @model_validator(mode="after")
    def window_matches_field(self) -> StudyCondition:
        needs_window = self.field in {"return_pct", "position", "low_age", "volume_ratio", "shape_distance"}
        if needs_window != (self.window is not None):
            raise ValueError("区间收益、区间位置、低点距今、量比和形态距离必须指定窗口；其他条件不使用窗口")
        return self

    @property
    def key(self) -> str:
        return f"{self.field}.{self.window}" if self.window else self.field


class StudyReference(StudyModel):
    symbol: str
    as_of: date

    @model_validator(mode="after")
    def normalize_symbol(self) -> StudyReference:
        from kan.storage.watchlist_models import _normalize_symbol

        self.symbol = _normalize_symbol(self.symbol)
        return self


class StudyQuery(StudyModel):
    title: str = Field(default="日线研究", min_length=1, max_length=120)
    universe: Literal["all", "personal", "codes"] = "codes"
    codes: list[str] = Field(default_factory=list, max_length=10_000)
    lookback_days: int = Field(default=120, ge=5, le=1_260)
    as_of: date | None = None
    forward_days: int = Field(default=5, ge=1, le=60)
    sample_policy: Literal["first", "every", "non_overlapping"] = "first"
    conditions: list[StudyCondition] = Field(min_length=1, max_length=12)
    reference: StudyReference | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> StudyQuery:
        from kan.storage.watchlist_models import _normalize_symbol

        self.title = self.title.strip()
        if not self.title:
            raise ValueError("研究名称不能为空")
        if self.universe == "codes":
            if not self.codes:
                raise ValueError("请至少填写一个股票代码")
            self.codes = list(dict.fromkeys(_normalize_symbol(code) for code in self.codes))
        elif self.codes:
            raise ValueError("全市场或个人池不能同时传入代码列表")
        if any(item.field == "shape_distance" for item in self.conditions) != (self.reference is not None):
            raise ValueError("形态距离必须选择参照股票及日期；其他研究不使用形态参照")
        return self


class StudyRefreshRequest(StudyModel):
    universe: Literal["all", "personal", "codes"]
    codes: list[str] = Field(default_factory=list, max_length=10_000)
    days: int = Field(default=360, ge=180, le=1_500)

    @model_validator(mode="after")
    def validate_scope(self) -> StudyRefreshRequest:
        from kan.storage.watchlist_models import _normalize_symbol

        if self.universe == "codes":
            if not self.codes:
                raise ValueError("请至少填写一个股票代码")
            self.codes = list(dict.fromkeys(_normalize_symbol(code) for code in self.codes))
        elif self.codes:
            raise ValueError("全市场或个人池不能同时传入代码列表")
        return self


class StudyCoverage(StudyModel):
    total_symbols: int = 0
    cached_symbols: int = 0
    missing_symbols: int = 0
    calendar_days: int = 0
    historical_stock_days: int = 0
    valid_stock_days: int = 0
    evaluated_stock_days: int = 0
    matched_stock_days: int = 0
    selected_events: int = 0
    complete_events: int = 0
    pending_events: int = 0
    missing_events: int = 0
    current_evaluated: int = 0
    current_matches: int = 0
    current_missing: int = 0
    self_matches_excluded: int = 0


class StudyMatch(StudyModel):
    symbol: str
    name: str
    date: date
    close: float
    change_pct: float | None = None
    values: dict[str, float | None]
    lower_bounds: list[str] = Field(default_factory=list)


class StudyEvent(StudyModel):
    event_id: str
    symbol: str
    name: str
    event_date: date
    event_close: float
    forward_date: date | None = None
    status: Literal["complete", "pending", "missing"]
    return_pct: float | None = None
    max_return_pct: float | None = None
    min_return_pct: float | None = None
    values: dict[str, float | None]
    lower_bounds: list[str] = Field(default_factory=list)


class StudyBin(StudyModel):
    label: str
    count: int


class StudyDistribution(StudyModel):
    count: int = 0
    positive: int = 0
    negative: int = 0
    flat: int = 0
    positive_ratio_pct: float | None = None
    mean_pct: float | None = None
    median_pct: float | None = None
    p10_pct: float | None = None
    p90_pct: float | None = None
    min_pct: float | None = None
    max_pct: float | None = None
    bins: list[StudyBin] = Field(default_factory=list)


class StudyDiff(StudyModel):
    previous_run_id: str | None = None
    previous_as_of: date | None = None
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class StudyBar(StudyModel):
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class StudyResult(StudyModel):
    study_id: str
    run_id: str
    query: StudyQuery
    created_at: datetime
    as_of: date
    start_date: date
    universe_note: str
    coverage: StudyCoverage
    distribution: StudyDistribution
    current_matches: list[StudyMatch]
    events: list[StudyEvent]
    events_total: int
    unavailable_symbols: list[str] = Field(default_factory=list)
    reference_bars: list[StudyBar] = Field(default_factory=list)
    reference_source: str | None = None
    diff: StudyDiff = Field(default_factory=StudyDiff)
    warnings: list[str] = Field(default_factory=list)


class StudySummary(StudyModel):
    study_id: str
    title: str
    query: StudyQuery
    created_at: datetime
    last_run_at: datetime
    last_run_id: str
    as_of: date
    current_count: int
    event_count: int


class StudyEventPage(StudyModel):
    run_id: str
    total: int
    offset: int
    limit: int
    items: list[StudyEvent]


class StudyCheck(StudyModel):
    condition: StudyCondition
    actual: float | None = None
    bound: Literal["exact", "at_least"] = "exact"
    matched: bool | None = None


class StudyEvidence(StudyModel):
    run_id: str
    symbol: str
    name: str
    event_date: date
    source: str
    bars: list[StudyBar]
    reference_bars: list[StudyBar] = Field(default_factory=list)
    reference_source: str | None = None
    conditions: list[StudyCheck]
    outcome: StudyEvent | None = None
    warnings: list[str] = Field(default_factory=list)

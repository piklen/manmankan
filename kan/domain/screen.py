"""选股工作台的稳定领域模型。

这些模型同时服务 Python、CLI、HTTP、TypeScript 和 MCP。入口层可以改变呈现，
但不能重新定义股票池、筛选条件、排序、运行证据或候选状态。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """禁止入口静默吞掉未知字段。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class UniverseKind(StrEnum):
    ALL = "all"
    WATCHLIST = "watchlist"
    HOLDINGS = "holdings"
    CODES = "codes"
    INDUSTRY = "industry"
    THEME = "theme"


class MatchMode(StrEnum):
    ALL = "all"
    ANY = "any"


class ComparisonOperator(StrEnum):
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    EQ = "eq"
    NE = "ne"


class NullPolicy(StrEnum):
    EXCLUDE = "exclude"
    FAIL = "fail"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class CandidateStatus(StrEnum):
    RESEARCH = "research"
    WATCH = "watch"
    SELECTED = "selected"
    REJECTED = "rejected"


class FilterInputKind(StrEnum):
    SCALAR = "scalar"
    PERIOD = "period"
    RESONANCE = "resonance"


class ScreenFilterType(StrEnum):
    POS = "pos"
    RESONANCE = "resonance"
    GAIN = "gain"
    UP_DAYS = "up_days"
    MA_BIAS = "ma_bias"
    RS_INDEX = "rs_index"
    RS_BOARD = "rs_board"
    PE = "pe"
    PB = "pb"
    DV = "dv"
    ROE = "roe"
    TURNOVER = "turnover"
    MARKET_CAP = "market_cap"
    VOLUME_RATIO = "volume_ratio"
    MONEYFLOW = "moneyflow"
    MONEYFLOW_DAILY = "moneyflow_daily"
    MONEYFLOW_DAYS = "moneyflow_days"
    RSI = "rsi"
    MACD_DIF = "macd_dif"
    MACD = "macd"
    KDJ_J = "kdj_j"
    ATR_PCT = "atr_pct"
    WINNER = "winner"
    STREAK = "streak"
    HOLDERS = "holders"
    TOP10 = "top10"
    NORTH = "north"


PERIOD_FILTER_TYPES = {
    ScreenFilterType.POS,
    ScreenFilterType.GAIN,
    ScreenFilterType.MA_BIAS,
    ScreenFilterType.RS_INDEX,
    ScreenFilterType.RS_BOARD,
}


class UniverseSpec(StrictModel):
    kind: UniverseKind = UniverseKind.WATCHLIST
    value: str | None = None
    codes: list[str] = Field(default_factory=list, max_length=10_000)
    group: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> UniverseSpec:
        if self.kind is UniverseKind.CODES and not self.codes:
            raise ValueError("自定义代码池至少需要一只股票")
        if self.kind in {UniverseKind.INDUSTRY, UniverseKind.THEME} and not self.value:
            raise ValueError("行业或题材股票池必须提供名称")
        if self.kind is not UniverseKind.CODES and self.codes:
            raise ValueError("只有自定义代码池可以携带 codes")
        return self


class AsOfSpec(StrictModel):
    trade_date: date | Literal["latest_complete"] = "latest_complete"
    timezone: str = "Asia/Shanghai"
    adjustment: Literal["qfq"] = "qfq"
    freshness_policy: Literal["require_complete", "allow_stale"] = "allow_stale"


class ScreenCondition(StrictModel):
    type: ScreenFilterType
    operator: ComparisonOperator
    value: float
    period: Annotated[int | None, Field(ge=2, le=360)] = None
    level: Literal["low", "high"] | None = None
    null_policy: NullPolicy = NullPolicy.EXCLUDE

    @model_validator(mode="after")
    def validate_shape(self) -> ScreenCondition:
        if self.type in PERIOD_FILTER_TYPES:
            if self.period is None:
                raise ValueError(f"{self.type.value} 条件必须提供 period")
            if self.level is not None:
                raise ValueError(f"{self.type.value} 条件不能提供 level")
        elif self.type is ScreenFilterType.RESONANCE:
            if self.level is None:
                raise ValueError("resonance 条件必须提供 level")
            if self.period is not None:
                raise ValueError("resonance 条件不能提供 period")
            if not 0 <= self.value <= 10:
                raise ValueError("resonance 数值必须在 0–10")
        elif self.period is not None or self.level is not None:
            raise ValueError(f"{self.type.value} 条件只接受 operator/value")
        if self.type is ScreenFilterType.POS and not 0 <= self.value <= 100:
            raise ValueError("价格区间位置阈值必须在 0–100")
        return self

    def to_dsl(self) -> str:
        value = f"{self.value:g}"
        if self.type in PERIOD_FILTER_TYPES:
            return f"{self.period}:{self.operator.value}:{value}"
        if self.type is ScreenFilterType.RESONANCE:
            return f"{self.level}:{self.operator.value}:{value}"
        return f"{self.operator.value}:{value}"


class ScreenSort(StrictModel):
    field_id: str = Field(min_length=1, max_length=128)
    direction: SortDirection = SortDirection.ASC
    nulls: Literal["last"] = "last"


class ScreenSpec(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(default="未命名选股", min_length=1, max_length=80)
    universe: UniverseSpec = Field(default_factory=UniverseSpec)
    as_of: AsOfSpec = Field(default_factory=AsOfSpec)
    match_mode: MatchMode = MatchMode.ALL
    conditions: list[ScreenCondition] = Field(default_factory=list, max_length=12)
    exclude_st: bool = False
    exclude_star: bool = False
    exclude_bj: bool = False
    sort: list[ScreenSort] = Field(default_factory=list, max_length=3)
    columns: list[str] = Field(
        default_factory=lambda: [
            "symbol",
            "name",
            "price",
            "position.30d",
            "position.60d",
            "position.180d",
        ],
        max_length=40,
    )
    limit: Annotated[int, Field(ge=1, le=10_000)] = 100

    @model_validator(mode="after")
    def require_rule(self) -> ScreenSpec:
        if not self.conditions and not (
            self.exclude_st or self.exclude_star or self.exclude_bj
        ):
            raise ValueError("至少需要一个筛选条件或排除规则")
        return self


ScreenScalar = str | int | float | bool | None


class ScreenEvidence(StrictModel):
    evidence_ref: str
    filter_type: ScreenFilterType
    field_id: str
    operator: ComparisonOperator
    threshold: float
    actual: float
    unit: str = ""
    period: int | None = None
    level: Literal["low", "high"] | None = None
    data_date: date | None = None
    source: str | None = None
    formula_version: str = "find-v1"


class ScreenRow(StrictModel):
    symbol: str
    name: str
    rank: int
    price: float | None = None
    in_watchlist: bool = False
    values: dict[str, ScreenScalar] = Field(default_factory=dict)
    positions: dict[str, float | None] = Field(default_factory=dict)
    evidence: list[ScreenEvidence] = Field(default_factory=list)


class DataCoverage(StrictModel):
    universe_size: int = 0
    evaluated: int = 0
    matched: int = 0
    returned: int = 0
    missing: int = 0
    ratio: float = 0.0
    stale: bool = False
    data_cutoff: date | None = None


class RankChange(StrictModel):
    symbol: str
    previous_rank: int
    current_rank: int
    delta: int


class ScreenDiff(StrictModel):
    previous_run_id: str | None = None
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    rank_changes: list[RankChange] = Field(default_factory=list)


class ScreenRun(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    screen_id: str | None = None
    screen_version: int | None = None
    spec: ScreenSpec
    spec_hash: str
    snapshot_id: str
    result_hash: str
    created_at: datetime
    duration_ms: int
    coverage: DataCoverage
    warnings: list[str] = Field(default_factory=list)
    rows: list[ScreenRow] = Field(default_factory=list)
    diff: ScreenDiff = Field(default_factory=ScreenDiff)


class SavedScreen(StrictModel):
    screen_id: str
    name: str
    current_version: int
    spec: ScreenSpec
    spec_hash: str
    created_at: datetime
    updated_at: datetime


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


class CompareSet(StrictModel):
    compare_id: str
    name: str
    symbols: list[str] = Field(min_length=3, max_length=10)
    created_at: datetime
    updated_at: datetime

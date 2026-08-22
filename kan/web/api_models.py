"""Web API v1 的显式请求与元数据模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from kan.domain.screen import CandidateStatus, ScreenSpec, StrictModel


class ApiMeta(StrictModel):
    api_version: Literal["v1"] = "v1"
    product: Literal["manmankan"] = "manmankan"
    product_version: str
    local_only: bool = True
    capabilities: list[str]


class ScreenUpsertRequest(StrictModel):
    spec: ScreenSpec
    screen_id: str | None = None


class ScreenRunRequest(StrictModel):
    spec: ScreenSpec
    persist: bool = True


class CandidateListCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=80)


class CandidateUpsertRequest(StrictModel):
    name: str | None = Field(default=None, max_length=80)
    status: CandidateStatus = CandidateStatus.RESEARCH
    note: str = Field(default="", max_length=2_000)
    source_run_id: str | None = None


class CompareSetUpsertRequest(StrictModel):
    compare_id: str | None = None
    name: str = Field(default="临时对比", max_length=80)
    symbols: list[str] = Field(min_length=3, max_length=10)


class DeleteResponse(StrictModel):
    deleted: bool


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    api_version: Literal["v1"] = "v1"


class StockResearchResponse(StrictModel):
    available: bool
    data: dict[str, Any] | None = None
    message: str | None = None


class MarketSentimentResponse(StrictModel):
    ok: bool
    up_count: int | None = None
    down_count: int | None = None
    flat_count: int | None = None
    limit_up: int | None = None
    limit_down: int | None = None
    median_position_180: float | None = None
    trade_date: str | None = None
    error: str | None = None


class MarketOverviewResponse(StrictModel):
    scan: dict[str, Any] | None = None
    sentiment: MarketSentimentResponse
    message: str | None = None


class PortfolioAccountResponse(StrictModel):
    cash: float | None = None
    total_market_value: float | None = None
    total_assets: float | None = None
    total_position_pct: float | None = None
    daily_pnl: float | None = None
    total_pnl: float | None = None


class PortfolioRowResponse(StrictModel):
    code: str
    name: str
    cost: float | None = None
    shares: int
    price: float | None = None
    prev_close: float | None = None
    market_value: float | None = None
    daily_pnl: float | None = None
    daily_pnl_pct: float | None = None
    total_pnl: float | None = None
    total_pnl_pct: float | None = None
    weight_pct: float | None = None
    p30_pct: float | None = None
    p60_pct: float | None = None
    p180_pct: float | None = None
    price_source: str | None = None
    price_status: str | None = None
    position_alert: str | None = None
    breakeven_price: float | None = None
    distance_to_breakeven: float | None = None


class PortfolioResponse(StrictModel):
    ok: bool
    price_mode: str
    data_cutoff: str | None = None
    account: PortfolioAccountResponse
    rows: list[PortfolioRowResponse] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class CashUpdateRequest(StrictModel):
    cash: float = Field(ge=0)


class PositionCreateRequest(StrictModel):
    code: str
    cost: float = Field(gt=0)
    shares: int = Field(gt=0)
    name: str | None = None
    merge: bool = False


class SettingsFactsResponse(StrictModel):
    data_dir: str
    workspace_db: str
    kline_cache_files: int
    tushare_endpoint_domain: str
    tushare_configured: bool
    tushare_masked: str | None = None
    state_backend: Literal["sqlite", "legacy"]

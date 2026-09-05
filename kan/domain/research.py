"""终端与 AI 共用的研究事实包，不承载模型推断。"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from kan.domain.screen import StrictModel


class ResearchDimension(StrEnum):
    MARKET = "market"
    VALUATION = "valuation"
    FUNDAMENTALS = "fundamentals"
    MONEYFLOW = "moneyflow"
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    CHIP = "chip"
    SHAREHOLDER = "shareholder"


class ResearchRequest(StrictModel):
    codes: list[str] = Field(min_length=1, max_length=20)
    dimensions: list[ResearchDimension] = Field(
        default_factory=lambda: [
            ResearchDimension.MARKET,
            ResearchDimension.VALUATION,
            ResearchDimension.FUNDAMENTALS,
        ],
        min_length=1,
        max_length=8,
        description="请求的事实维度；市场行情是研究包必选基线。",
    )

    @field_validator("codes")
    @classmethod
    def normalize_codes(cls, codes: list[str]) -> list[str]:
        from kan.storage.positions import normalize_symbol

        return list(dict.fromkeys(normalize_symbol(code) for code in codes))

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, values: list[ResearchDimension]) -> list[ResearchDimension]:
        if ResearchDimension.MARKET not in values:
            raise ValueError("dimensions 必须包含 market 行情基线")
        return list(dict.fromkeys(values))


class ResearchFact(StrictModel):
    field_id: str
    label: str
    value: float | str | None
    unit: str
    window: int | None = None


class ResearchEvidence(StrictModel):
    evidence_ref: str
    symbol: str
    dimension: ResearchDimension
    source: str | None
    data_date: date | None = None
    report_period: date | None = None
    announcement_date: date | None = None
    fetched_at: str | None = None
    adjustment: Literal["qfq"] | None = None
    freshness: Literal["fresh", "stale", "unknown", "unavailable"]
    facts: list[ResearchFact]
    missing_fields: list[str]
    notes: list[str] = Field(default_factory=list)


class ResearchSubject(StrictModel):
    symbol: str
    name: str
    evidence_refs: list[str]


class ResearchFailure(StrictModel):
    symbol: str | None = None
    code: str
    message: str


class ResearchCoverage(StrictModel):
    requested_symbols: int
    available_symbols: int
    requested_sections: int
    available_sections: int
    fresh_sections: int
    missing_facts: int


class ResearchBundle(StrictModel):
    ok: bool
    command: Literal["research"] = "research"
    schema_version: Literal[1] = 1
    bundle_id: str
    generated_at: datetime
    expected_trade_date: date
    request: ResearchRequest
    status: Literal["complete", "partial", "unavailable"]
    subjects: list[ResearchSubject]
    evidence: list[ResearchEvidence]
    coverage: ResearchCoverage
    errors: list[ResearchFailure]
    limitations: list[str]
    disclaimer: str

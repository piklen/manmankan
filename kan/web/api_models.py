"""Web API v1 的显式请求与元数据模型。"""

from __future__ import annotations

from typing import Literal

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

"""本机持久任务状态模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from kan.domain.screen import StrictModel


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class MarketRefreshScope(StrEnum):
    DEFAULT = "default"
    ALL = "all"
    FOCUS = "focus"
    CODES = "codes"


class MarketRefreshRequest(StrictModel):
    scope: MarketRefreshScope = MarketRefreshScope.DEFAULT
    force: bool = False
    days: int = Field(default=360, ge=180, le=1_500)
    codes: list[str] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def validate_codes(self) -> MarketRefreshRequest:
        from kan.storage.watchlist_models import _normalize_symbol

        if self.scope is MarketRefreshScope.CODES:
            if not self.codes:
                raise ValueError("指定代码刷新需要至少一个股票代码")
            object.__setattr__(self, "codes", list(dict.fromkeys(_normalize_symbol(code) for code in self.codes)))
        elif self.codes:
            raise ValueError("只有指定代码刷新接受代码列表")
        return self


class WorkspaceJob(StrictModel):
    job_id: str
    kind: str
    status: JobStatus
    progress: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    watermark: str | None = None
    message: str = ""
    error: str | None = None
    result_ref: str | None = None
    created_at: datetime
    updated_at: datetime

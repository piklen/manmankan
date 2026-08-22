"""本机持久任务状态模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from kan.domain.screen import StrictModel


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


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

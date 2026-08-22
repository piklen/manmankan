"""持久任务、恢复与 SSE 契约测试。"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kan.domain.job import JobStatus
from kan.domain.screen import DataCoverage, ScreenRun, ScreenSpec
from kan.service import job_service, screen_service
from kan.service.screen_ai import ScreenRunInput
from kan.storage import paths, workspace_db
from kan.web.app import create_app
from kan.web.security import SESSION_QUERY_NAME


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))


def _run() -> ScreenRun:
    spec = ScreenSpec(name="任务规则", exclude_st=True)
    return ScreenRun(
        run_id="job-run",
        spec=spec,
        spec_hash=screen_service.content_hash(spec),
        snapshot_id="job-snapshot",
        result_hash="job-result",
        created_at=datetime.now(UTC),
        duration_ms=5,
        coverage=DataCoverage(returned=0),
    )


def _wait_terminal(job_id: str) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = workspace_db.get_job(job_id)
        if job is not None and job.status in job_service.TERMINAL_STATUSES:
            return
        time.sleep(0.01)
    raise AssertionError("job did not reach terminal state")


def test_screen_job_persists_progress_and_result_reference(
    isolated_workspace: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job_service, "run_from_input", lambda _request: _run())

    job = job_service.start_screen_run_job(
        ScreenRunInput(spec=ScreenSpec(name="任务规则", exclude_st=True))
    )
    _wait_terminal(job.job_id)
    completed = workspace_db.get_job(job.job_id)

    assert completed is not None
    assert completed.status is JobStatus.SUCCEEDED
    assert completed.progress == completed.total == 3
    assert completed.result_ref == "job-run"
    assert completed.watermark == "job-snapshot"


def test_recovery_marks_incomplete_jobs_interrupted(isolated_workspace: None) -> None:
    queued = workspace_db.create_job("screen_run")
    running = workspace_db.create_job("screen_run")
    workspace_db.update_job(running.job_id, status=JobStatus.RUNNING)

    assert job_service.recover_incomplete_jobs() == 2
    queued_after = workspace_db.get_job(queued.job_id)
    running_after = workspace_db.get_job(running.job_id)
    assert queued_after is not None
    assert running_after is not None
    assert queued_after.status is JobStatus.INTERRUPTED
    assert running_after.status is JobStatus.INTERRUPTED


def test_sse_accepts_session_query_and_closes_after_terminal(
    isolated_workspace: None,
) -> None:
    token = "job-test-session"
    app = create_app(session_token=token)
    job = workspace_db.create_job("screen_run", total=1)
    workspace_db.update_job(
        job.job_id,
        status=JobStatus.SUCCEEDED,
        progress=1,
        result_ref="run-1",
    )

    response = TestClient(app, base_url="http://127.0.0.1").get(
        f"/api/v1/jobs/{job.job_id}/events?{SESSION_QUERY_NAME}={token}"
    )

    assert response.status_code == 200
    assert "event: job" in response.text
    assert '"status":"succeeded"' in response.text
    assert '"result_ref":"run-1"' in response.text

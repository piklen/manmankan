"""持久任务、恢复与 SSE 契约测试。"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kan.data.fetcher import FetchProgress
from kan.domain.job import JobStatus, MarketRefreshRequest, MarketRefreshScope
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


def test_market_refresh_persists_partial_progress_and_resume_watermark(
    isolated_workspace: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        job_service,
        "_resolve_refresh_targets",
        lambda _request: ["600519", "000858"],
    )

    def fake_fetch(symbols, **kwargs):
        callback = kwargs["on_progress_state"]
        for index, symbol in enumerate(symbols, 1):
            callback(
                FetchProgress(
                    symbol=symbol,
                    ok=index == 1,
                    error=None if index == 1 else "upstream unavailable",
                    elapsed_seconds=0.01,
                    concurrency=1,
                    max_concurrency=1,
                    inflight=0,
                    completed=index,
                    total=len(symbols),
                )
            )
        return {"600519": object()}, {"000858": "upstream unavailable"}

    monkeypatch.setattr("kan.data.fetcher.fetch_batch", fake_fetch)
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date",
        lambda: date(2026, 8, 21),
    )
    job = workspace_db.create_job("market_refresh:default")

    job_service._execute_market_refresh(job.job_id, MarketRefreshRequest())
    completed = workspace_db.get_job(job.job_id)

    assert completed is not None
    assert completed.status is JobStatus.PARTIAL
    assert completed.progress == completed.total == 2
    assert completed.watermark == "2026-08-21"
    assert completed.result_ref == "market-cache:2026-08-21"
    assert completed.error is not None


def test_screen_job_records_partial_and_planning_failure(
    isolated_workspace: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial_run = _run().model_copy(update={"warnings": ["行情数据可能需要更新"]})
    monkeypatch.setattr(job_service, "run_from_input", lambda _request: partial_run)
    partial_job = workspace_db.create_job("screen_run", total=3)
    job_service._execute_screen_run(
        partial_job.job_id,
        ScreenRunInput(spec=ScreenSpec(name="任务规则", exclude_st=True)),
    )

    partial = workspace_db.get_job(partial_job.job_id)
    assert partial is not None
    assert partial.status is JobStatus.PARTIAL
    assert "1 项数据提示" in partial.message

    monkeypatch.setattr(
        job_service,
        "plan_screen",
        lambda _spec: SimpleNamespace(executable=False, warnings=["当前条件不可执行"]),
    )
    failed_job = workspace_db.create_job("screen_run", total=3)
    job_service._execute_screen_run(
        failed_job.job_id,
        ScreenRunInput(spec=ScreenSpec(name="失败规则", exclude_st=True)),
    )
    failed = workspace_db.get_job(failed_job.job_id)
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    assert failed.error == "当前条件不可执行"


def test_market_refresh_single_worker_success_and_failures(
    isolated_workspace: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PendingThread:
        def __init__(self, **_kwargs) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(job_service.threading, "Thread", PendingThread)
    monkeypatch.setattr(job_service, "_ACTIVE_REFRESH_JOB_ID", None)
    request = MarketRefreshRequest(scope=MarketRefreshScope.ALL)
    first = job_service.start_market_refresh_job(request)
    duplicate = job_service.start_market_refresh_job(request)
    assert duplicate.job_id == first.job_id

    workspace_db.update_job(first.job_id, status=JobStatus.SUCCEEDED)
    replacement = job_service.start_market_refresh_job(request)
    assert replacement.job_id != first.job_id
    monkeypatch.setattr(job_service, "_ACTIVE_REFRESH_JOB_ID", None)

    monkeypatch.setattr(
        job_service,
        "_resolve_refresh_targets",
        lambda _request: ["600519"],
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date",
        lambda: date(2026, 8, 21),
    )
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda _symbols, **_kwargs: ({"600519": object()}, {}),
    )
    success_job = workspace_db.create_job("market_refresh:all")
    job_service._execute_market_refresh(success_job.job_id, request)
    success = workspace_db.get_job(success_job.job_id)
    assert success is not None
    assert success.status is JobStatus.SUCCEEDED
    assert success.message == "全市场行情已更新 1 只"

    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda _symbols, **_kwargs: ({}, {"600519": "failed"}),
    )
    failed_job = workspace_db.create_job("market_refresh:all")
    job_service._execute_market_refresh(failed_job.job_id, request)
    failed = workspace_db.get_job(failed_job.job_id)
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    assert "全部更新失败" in (failed.error or "")

    monkeypatch.setattr(job_service, "_resolve_refresh_targets", lambda _request: [])
    empty_job = workspace_db.create_job("market_refresh:default")
    job_service._execute_market_refresh(empty_job.job_id, MarketRefreshRequest())
    empty = workspace_db.get_job(empty_job.job_id)
    assert empty is not None
    assert empty.status is JobStatus.FAILED
    assert empty.error == "默认池股票池为空"
    job_service._THREADS.clear()


def test_job_lookup_and_sse_wait_for_terminal_state(
    isolated_workspace: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="任务不存在"):
        job_service.get_job("missing")

    job = workspace_db.create_job("screen_run", total=1)

    def complete(_interval: float) -> None:
        workspace_db.update_job(
            job.job_id,
            status=JobStatus.SUCCEEDED,
            progress=1,
        )

    monkeypatch.setattr(job_service.time, "sleep", complete)
    events = list(job_service.iter_job_events(job.job_id, poll_interval=0))
    assert len(events) == 2
    assert '"status":"queued"' in events[0]
    assert '"status":"succeeded"' in events[1]


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

"""本机持久任务执行器与 SSE 事件流。"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator

from kan.domain.job import JobStatus, WorkspaceJob
from kan.infra.log import debug_log, redact_text
from kan.service.screen_ai import ScreenRunInput, plan_screen, run_from_input
from kan.storage import workspace_db

TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.INTERRUPTED,
}
_THREADS: dict[str, threading.Thread] = {}
_THREADS_LOCK = threading.Lock()


def recover_incomplete_jobs() -> int:
    """进程重启后把无法继续的内存执行标记为 interrupted。"""
    return workspace_db.interrupt_incomplete_jobs()


def start_screen_run_job(request: ScreenRunInput) -> WorkspaceJob:
    job = workspace_db.create_job(
        "screen_run",
        total=3,
        message="选股任务已排队",
    )
    thread = threading.Thread(
        target=_execute_screen_run,
        args=(job.job_id, request),
        daemon=True,
        name=f"kan-screen-{job.job_id[:8]}",
    )
    with _THREADS_LOCK:
        _THREADS[job.job_id] = thread
    thread.start()
    return job


def _execute_screen_run(job_id: str, request: ScreenRunInput) -> None:
    try:
        workspace_db.update_job(
            job_id,
            status=JobStatus.RUNNING,
            progress=1,
            message="正在校验规则与数据依赖",
        )
        if request.spec is not None:
            plan = plan_screen(request.spec)
            if not plan.executable:
                reason = "；".join(plan.warnings) or "当前规则不可执行"
                raise ValueError(reason)
        workspace_db.update_job(
            job_id,
            progress=2,
            message="正在读取数据并执行筛选",
        )
        run = run_from_input(request)
        workspace_db.update_job(
            job_id,
            status=JobStatus.SUCCEEDED,
            progress=3,
            watermark=run.snapshot_id,
            message=f"运行完成，返回 {run.coverage.returned} 只",
            result_ref=run.run_id,
        )
    except Exception as exc:
        debug_log(__name__, "screen job failed", exc)
        workspace_db.update_job(
            job_id,
            status=JobStatus.FAILED,
            message="选股任务失败",
            error=redact_text(str(exc))[:500],
        )
    finally:
        with _THREADS_LOCK:
            _THREADS.pop(job_id, None)


def get_job(job_id: str) -> WorkspaceJob:
    job = workspace_db.get_job(job_id)
    if job is None:
        raise ValueError(f"任务不存在: {job_id}")
    return job


def iter_job_events(job_id: str, *, poll_interval: float = 0.2) -> Iterator[str]:
    """发送当前状态与后续变化；终态事件后关闭连接。"""
    last_updated = ""
    while True:
        job = get_job(job_id)
        updated = job.updated_at.isoformat()
        if updated != last_updated:
            payload = json.dumps(
                job.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"event: job\nid: {updated}\ndata: {payload}\n\n"
            last_updated = updated
        if job.status in TERMINAL_STATUSES:
            return
        time.sleep(poll_interval)

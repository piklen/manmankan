"""Web 补数据后台任务。"""
from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from kan.core.stock_set import from_flags

FetchStatus = Literal["running", "done", "error"]
ProgressCallback = Callable[[str, int, int], None]
FetchRunner = Callable[[ProgressCallback], None]


@dataclass
class FetchJob:
    id: str
    status: FetchStatus = "running"
    stage: str = "准备"
    completed: int = 0
    total: int = 0
    error: str | None = None
    events: list[dict[str, object]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)

    def snapshot(self) -> dict[str, object]:
        return {
            "job": self.id,
            "status": self.status,
            "stage": self.stage,
            "completed": self.completed,
            "total": self.total,
            "error": self.error,
        }


_state_lock = threading.Lock()
_current_job: FetchJob | None = None


def start_fetch_job(runner: FetchRunner | None = None) -> FetchJob:
    """启动一个补数据任务；已有运行任务时返回同一个任务。"""
    global _current_job
    with _state_lock:
        if _current_job is not None and _current_job.status == "running":
            return _current_job
        job = FetchJob(id=uuid.uuid4().hex)
        _current_job = job
        _record(job, stage="准备", completed=0, total=0)
        threading.Thread(
            target=_run_job,
            args=(job, runner or _run_scan_fetch),
            name="kan-web-fetch",
            daemon=True,
        ).start()
        return job


def get_fetch_job(job_id: str) -> FetchJob | None:
    with _state_lock:
        if _current_job is not None and _current_job.id == job_id:
            return _current_job
    return None


def iter_sse(job: FetchJob) -> Iterator[str]:
    """按 text/event-stream 格式输出任务事件。"""
    index = 0
    while True:
        keepalive = False
        with job.condition:
            while index >= len(job.events) and job.status == "running":
                job.condition.wait(timeout=15)
                if index >= len(job.events) and job.status == "running":
                    keepalive = True
                    break
            events = job.events[index:]
            index = len(job.events)
            finished = job.status != "running" and index >= len(job.events)
        if keepalive:
            yield ": keep-alive\n\n"
        for event in events:
            yield _format_sse(event)
        if finished:
            break


def _run_job(job: FetchJob, runner: FetchRunner) -> None:
    try:
        runner(lambda stage, completed, total: _record(
            job,
            stage=stage,
            completed=completed,
            total=total,
        ))
        _record(
            job,
            stage="完成",
            completed=job.total,
            total=job.total,
            status="done",
        )
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web fetch failed", e)
        _record(
            job,
            stage="数据不可用",
            completed=job.completed,
            total=job.total,
            status="error",
            error="数据不可用",
        )


def _run_scan_fetch(progress: ProgressCallback) -> None:
    """检查本地池新鲜度并逐股拉取,把每只完成情况转成 SSE 进度事件。

    不走 run_scan:补数据只需要 resolve + fetch,跑整条 scan 管线是纯浪费,
    且 pipeline 内的 auto_fetch 进度是终端进度条,无法回流到 SSE。
    """
    from kan.core.pipeline import resolve_stock_set
    from kan.data.fetcher import fetch_batch, is_fresh

    progress("读取本地池", 0, 0)
    targets, _meta = resolve_stock_set(from_flags())
    stale = [(symbol, name) for symbol, name in targets if not is_fresh(symbol)]
    total = len(stale)
    if not stale:
        progress("本地数据已是最新", 0, 0)
        return

    name_map = dict(stale)
    done = 0

    def _on_done(symbol: str, _ok: bool, _err: str | None) -> None:
        nonlocal done
        done += 1
        progress(f"刷新 {name_map.get(symbol, symbol)}", done, total)

    progress("刷新本地数据", 0, total)
    _results, errors = fetch_batch(
        [symbol for symbol, _name in stale],
        force=True,
        on_progress=_on_done,
    )
    if errors:
        progress(f"刷新完成 · {len(errors)} 只未更新", done, total)


def _record(
    job: FetchJob,
    *,
    stage: str,
    completed: int,
    total: int,
    status: FetchStatus | None = None,
    error: str | None = None,
) -> None:
    with job.condition:
        if status is not None:
            job.status = status
        job.stage = stage
        job.completed = completed
        job.total = total
        job.error = error
        event = job.snapshot()
        event["ts"] = datetime.now(UTC).isoformat()
        job.events.append(event)
        job.condition.notify_all()


def _format_sse(event: dict[str, object]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: progress\ndata: {payload}\n\n"

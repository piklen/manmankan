"""Web 补数据后台任务。"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from kan.core.stock_set import from_flags

FetchStatus = Literal["running", "done", "partial", "error"]
ProgressCallback = Callable[[str, int, int], None]
WEB_REQUIRED_KLINE_ROWS = 180


@dataclass(frozen=True)
class FetchOutcome:
    status: Literal["done", "partial", "error"]
    stage: str
    completed: int
    total: int
    failed: int = 0
    error: str | None = None


FetchRunner = Callable[[ProgressCallback], FetchOutcome | None]


@dataclass
class FetchJob:
    id: str
    status: FetchStatus = "running"
    stage: str = "准备"
    completed: int = 0
    total: int = 0
    failed: int = 0
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
            "failed": self.failed,
            "error": self.error,
        }


_state_lock = threading.Lock()
_current_job: FetchJob | None = None

# SSE 消费端轮询节奏 · 测试会 monkeypatch 成 0 以免真等。
_SSE_POLL_SECONDS = 0.25
_SSE_KEEPALIVE_SECONDS = 15.0


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


async def iter_sse(job: FetchJob) -> AsyncIterator[str]:
    """按 text/event-stream 格式输出任务事件 · async 短轮询,不占 AnyIO 线程池。

    生产端(_record)在后台 daemon 线程里 append 事件;消费端在 event loop 里
    轮询快照。持 job.condition 锁只做 O(1) 读、与 _record 的原子写互斥,不阻塞;
    无新事件时 await asyncio.sleep 让出 event loop(不占线程池 worker),每
    _SSE_KEEPALIVE_SECONDS 发一次 keep-alive。客户端断开时生成器被 aclose,
    在 sleep 处干净退出。
    """
    index = 0
    idle = 0.0
    while True:
        with job.condition:
            events = job.events[index:]
            index = len(job.events)
            running = job.status == "running"
        for event in events:
            yield _format_sse(event)
        if not running:
            break
        if events:
            idle = 0.0
            continue
        await asyncio.sleep(_SSE_POLL_SECONDS)
        idle += _SSE_POLL_SECONDS
        if idle >= _SSE_KEEPALIVE_SECONDS:
            idle = 0.0
            yield ": keep-alive\n\n"


def _run_job(job: FetchJob, runner: FetchRunner) -> None:
    try:
        outcome = runner(lambda stage, completed, total: _record(
            job,
            stage=stage,
            completed=completed,
            total=total,
        ))
        if outcome is None:
            _record(
                job,
                stage="更新完成",
                completed=job.total,
                total=job.total,
                status="done",
            )
        else:
            _record(
                job,
                stage=outcome.stage,
                completed=outcome.completed,
                total=outcome.total,
                status=outcome.status,
                failed=outcome.failed,
                error=outcome.error,
            )
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web fetch failed", e)
        _record(
            job,
            stage="更新失败",
            completed=job.completed,
            total=job.total,
            status="error",
            error="更新失败 · 请检查网络或稍后重试",
        )


def _run_scan_fetch(progress: ProgressCallback) -> FetchOutcome:
    """检查本地池新鲜度并逐股拉取,把每只完成情况转成 SSE 进度事件。

    不走 run_scan:补数据只需要 resolve + fetch,跑整条 scan 管线是纯浪费,
    且 pipeline 内的 auto_fetch 进度是终端进度条,无法回流到 SSE。
    """
    from kan.core.pipeline import resolve_stock_set
    from kan.data.fetcher import fetch_batch, is_fresh

    progress("读取本地池", 0, 0)
    targets, _meta = resolve_stock_set(from_flags())
    if not targets:
        return FetchOutcome(
            status="error",
            stage="等待添加股票",
            completed=0,
            total=0,
            error="还没有自选或持仓 · 请先添加一只股票",
        )
    stale = [
        (symbol, name)
        for symbol, name in targets
        if not is_fresh(symbol, min_rows=WEB_REQUIRED_KLINE_ROWS)
    ]
    total = len(stale)
    if not stale:
        return FetchOutcome(
            status="done",
            stage="本地数据已是最新",
            completed=len(targets),
            total=len(targets),
        )

    name_map = dict(stale)
    done = 0

    def _on_done(symbol: str, _ok: bool, _err: str | None) -> None:
        nonlocal done
        done += 1
        progress(f"刷新 {name_map.get(symbol, symbol)}", done, total)

    progress("刷新本地数据", 0, total)
    results, errors = fetch_batch(
        [symbol for symbol, _name in stale],
        days=WEB_REQUIRED_KLINE_ROWS,
        force=True,
        on_progress=_on_done,
    )
    failed = len(errors)
    succeeded = len(results)
    if failed and succeeded:
        message = f"已更新 {succeeded} 只，{failed} 只未更新 · 可重试"
        return FetchOutcome(
            status="partial",
            stage=message,
            completed=done,
            total=total,
            failed=failed,
            error=message,
        )
    if failed:
        message = f"全部 {failed} 只更新失败 · 请检查网络或稍后重试"
        return FetchOutcome(
            status="error",
            stage="更新失败",
            completed=done,
            total=total,
            failed=failed,
            error=message,
        )
    return FetchOutcome(
        status="done",
        stage=f"已更新 {succeeded} 只",
        completed=done,
        total=total,
    )


def _record(
    job: FetchJob,
    *,
    stage: str,
    completed: int,
    total: int,
    status: FetchStatus | None = None,
    failed: int | None = None,
    error: str | None = None,
) -> None:
    with job.condition:
        if status is not None:
            job.status = status
        job.stage = stage
        job.completed = completed
        job.total = total
        if failed is not None:
            job.failed = failed
        job.error = error
        event = job.snapshot()
        event["ts"] = datetime.now(UTC).isoformat()
        job.events.append(event)
        job.condition.notify_all()


def _format_sse(event: dict[str, object]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: progress\ndata: {payload}\n\n"

"""本机持久任务执行器与 SSE 事件流。"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator

from kan.domain.job import (
    JobStatus,
    MarketRefreshRequest,
    MarketRefreshScope,
    WorkspaceJob,
)
from kan.infra.log import debug_log, redact_text
from kan.service.screen_ai import ScreenRunInput, plan_screen, run_from_input
from kan.storage import workspace_db

TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.PARTIAL,
    JobStatus.FAILED,
    JobStatus.INTERRUPTED,
}
_THREADS: dict[str, threading.Thread] = {}
_THREADS_LOCK = threading.Lock()
_ACTIVE_REFRESH_JOB_ID: str | None = None


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


def start_market_refresh_job(request: MarketRefreshRequest) -> WorkspaceJob:
    """启动至多一个市场缓存刷新任务；重复点击返回当前运行任务。"""
    global _ACTIVE_REFRESH_JOB_ID
    with _THREADS_LOCK:
        if _ACTIVE_REFRESH_JOB_ID is not None:
            current = workspace_db.get_job(_ACTIVE_REFRESH_JOB_ID)
            if current is not None and current.status not in TERMINAL_STATUSES:
                return current
            _ACTIVE_REFRESH_JOB_ID = None
        label = "全市场" if request.scope is MarketRefreshScope.ALL else "默认池"
        job = workspace_db.create_job(
            f"market_refresh:{request.scope.value}",
            message=f"{label}行情刷新已排队",
        )
        thread = threading.Thread(
            target=_execute_market_refresh,
            args=(job.job_id, request),
            daemon=True,
            name=f"kan-market-refresh-{job.job_id[:8]}",
        )
        _THREADS[job.job_id] = thread
        _ACTIVE_REFRESH_JOB_ID = job.job_id
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
        terminal_status = JobStatus.PARTIAL if run.warnings else JobStatus.SUCCEEDED
        message = f"运行完成，返回 {run.coverage.returned} 只"
        if run.warnings:
            message += f"；{len(run.warnings)} 项数据提示"
        workspace_db.update_job(
            job_id,
            status=terminal_status,
            progress=3,
            watermark=run.snapshot_id,
            message=message,
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


def _resolve_refresh_targets(request: MarketRefreshRequest) -> list[str]:
    from kan.core.pipeline import resolve_stock_set
    from kan.core.stock_set import from_flags

    stock_set = from_flags(
        all_stocks=request.scope is MarketRefreshScope.ALL,
        all_stocks_force=request.force,
    )
    pairs, _meta = resolve_stock_set(stock_set)
    return list(dict.fromkeys(symbol for symbol, _name in pairs))


def _execute_market_refresh(job_id: str, request: MarketRefreshRequest) -> None:
    """刷新缓存并把稀疏进度写入 SQLite；重新发起会复用已落盘缓存。"""
    global _ACTIVE_REFRESH_JOB_ID
    label = "全市场" if request.scope is MarketRefreshScope.ALL else "默认池"
    try:
        workspace_db.update_job(
            job_id,
            status=JobStatus.RUNNING,
            message=f"正在解析{label}股票池",
        )
        symbols = _resolve_refresh_targets(request)
        if not symbols:
            raise ValueError(f"{label}股票池为空")
        total = len(symbols)
        workspace_db.update_job(
            job_id,
            total=total,
            message=f"正在刷新{label}行情",
        )

        from kan.data.fetcher import FetchProgress, fetch_batch

        report_step = max(1, (total + 99) // 100)
        last_reported = 0
        last_reported_at = 0.0

        def on_progress(state: FetchProgress) -> None:
            nonlocal last_reported, last_reported_at
            now = time.monotonic()
            if (
                state.completed < total
                and state.completed - last_reported < report_step
                and now - last_reported_at < 1.0
            ):
                return
            last_reported = state.completed
            last_reported_at = now
            workspace_db.update_job(
                job_id,
                progress=state.completed,
                total=state.total,
                watermark=state.symbol,
                message=f"正在刷新{label}行情 {state.completed}/{state.total}",
            )

        results, errors = fetch_batch(
            symbols,
            days=request.days,
            force=request.force,
            on_progress_state=on_progress,
            market_wide=request.scope is MarketRefreshScope.ALL,
            retain_frames=False,
        )
        succeeded = len(results)
        failed = len(errors)
        from kan.core.trading_calendar import latest_trade_date

        cutoff = latest_trade_date().isoformat()
        if failed and succeeded:
            workspace_db.update_job(
                job_id,
                status=JobStatus.PARTIAL,
                progress=total,
                total=total,
                watermark=cutoff,
                message=f"{label}已更新 {succeeded} 只，{failed} 只未更新",
                error=f"{failed} 只股票未更新；重新发起会复用已完成缓存",
                result_ref=f"market-cache:{cutoff}",
            )
        elif failed:
            raise RuntimeError(f"{label} {failed} 只股票全部更新失败")
        else:
            workspace_db.update_job(
                job_id,
                status=JobStatus.SUCCEEDED,
                progress=total,
                total=total,
                watermark=cutoff,
                message=f"{label}行情已更新 {succeeded} 只",
                result_ref=f"market-cache:{cutoff}",
            )
    except Exception as exc:
        debug_log(__name__, "market refresh job failed", exc)
        workspace_db.update_job(
            job_id,
            status=JobStatus.FAILED,
            message=f"{label}行情刷新失败",
            error=redact_text(str(exc))[:500],
        )
    finally:
        with _THREADS_LOCK:
            _THREADS.pop(job_id, None)
            if job_id == _ACTIVE_REFRESH_JOB_ID:
                _ACTIVE_REFRESH_JOB_ID = None


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

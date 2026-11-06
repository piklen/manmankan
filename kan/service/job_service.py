"""本机持久任务执行器与 SSE 事件流。"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from datetime import date
from math import ceil
from typing import Any

from kan.domain.discovery import DiscoveryQuery
from kan.domain.job import (
    JobStatus,
    MarketRefreshRequest,
    MarketRefreshScope,
    WorkspaceJob,
)
from kan.infra.log import debug_log, redact_text
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
_ACTIVE_REFRESH_REQUEST: MarketRefreshRequest | None = None


def plan_discovery_data(query: DiscoveryQuery) -> dict[str, Any]:
    """把两个观察窗口映射到现有刷新参数，包括历史截止日距今的跨度。"""
    from kan.domain.market_study import StudyRefreshRequest
    from kan.service.market_study import resolve_market_calendar
    from kan.service.trend_search import TrendSearchQuery, _scope

    calendar, latest = resolve_market_calendar()
    calendar = [day for day in calendar if day <= latest]
    as_of = query.as_of or latest
    if as_of not in calendar:
        raise ValueError("观察截止日必须是已完成收盘的市场交易日")
    index = calendar.index(as_of)
    first = index - 2 * query.window
    if first < 0:
        raise ValueError("交易日历不足以覆盖这次观察的两个完整窗口")
    required_start = calendar[first]
    days = len(calendar) - first
    universe, codes = query.universe, query.codes
    if query.industries:
        members, _industries, _choices = _scope(TrendSearchQuery(
            universe=query.universe, codes=query.codes, industries=query.industries, as_of=as_of,
        ))
        codes = [symbol for symbol, _name in members]
        if not codes:
            raise ValueError("该行业与范围没有可更新的成员，请先核对观察范围")
        universe = "codes"
    if universe != "all":
        # 单股源以 days×1.8 个自然日回溯，确保开始日确实覆盖观察基日。
        days = max(days, ceil((date.today() - required_start).days / 1.8))
    days = max(2, days)
    if days > 1500:
        raise ValueError(f"这次历史观察至少需更新 {days} 日，超出当前 1500 日获取范围；请改用较近截止日或先导入所需历史行情。")
    refresh = StudyRefreshRequest(universe=universe, codes=codes, days=days)
    return {
        "query": query, "refresh": refresh, "required_start": str(required_start), "latest": str(latest),
        "message": f"为截至 {as_of} 的两个 {query.window} 交易日窗口准备行情，覆盖基日 {required_start} 至最近收盘 {latest}；本次请求 {days} 日。更新保留已有历史，已有较长缓存时实际范围会相应扩展。",
    }


def recover_incomplete_jobs() -> int:
    """进程重启后把无法继续的内存执行标记为 interrupted。"""
    return workspace_db.interrupt_incomplete_jobs()


def start_market_refresh_job(request: MarketRefreshRequest) -> WorkspaceJob:
    """启动至多一个市场缓存刷新任务；重复点击返回当前运行任务。"""
    global _ACTIVE_REFRESH_JOB_ID, _ACTIVE_REFRESH_REQUEST
    with _THREADS_LOCK:
        if _ACTIVE_REFRESH_JOB_ID is not None:
            current = workspace_db.get_job(_ACTIVE_REFRESH_JOB_ID)
            if current is not None and current.status not in TERMINAL_STATUSES:
                if request != _ACTIVE_REFRESH_REQUEST:
                    raise ValueError("已有另一份行情更新正在执行，请等它完成后再更新本研究的数据")
                return current
            _ACTIVE_REFRESH_JOB_ID = None
        label = _refresh_label(request.scope)
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
        _ACTIVE_REFRESH_REQUEST = request
    thread.start()
    return job


def _resolve_refresh_targets(request: MarketRefreshRequest) -> list[str]:
    if request.scope is MarketRefreshScope.CODES:
        return request.codes
    if request.scope is MarketRefreshScope.FOCUS:
        from kan.service.focus_service import focus_symbols

        return focus_symbols()
    from kan.core.pipeline import resolve_stock_set
    from kan.core.stock_set import from_flags

    stock_set = from_flags(
        all_stocks=request.scope is MarketRefreshScope.ALL,
        all_stocks_force=request.force,
    )
    pairs, _meta = resolve_stock_set(stock_set)
    return list(dict.fromkeys(symbol for symbol, _name in pairs))


def _refresh_label(scope: MarketRefreshScope) -> str:
    return {MarketRefreshScope.ALL: "全市场", MarketRefreshScope.DEFAULT: "默认池", MarketRefreshScope.FOCUS: "我的关注", MarketRefreshScope.CODES: "指定股票"}[scope]


def _execute_market_refresh(job_id: str, request: MarketRefreshRequest) -> None:
    """刷新缓存并把稀疏进度写入 SQLite；重新发起会复用已落盘缓存。"""
    global _ACTIVE_REFRESH_JOB_ID, _ACTIVE_REFRESH_REQUEST
    label = _refresh_label(request.scope)
    try:
        workspace_db.update_job(
            job_id,
            status=JobStatus.RUNNING,
            message=f"正在解析{label}股票池",
        )
        symbols = _resolve_refresh_targets(request)
        if not symbols:
            if request.scope is MarketRefreshScope.ALL:
                raise ValueError("无法取得完整 A 股名单；请先在数据页保存可用的来源，再更新日线。")
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
                error=f"{failed} 只股票未更新：{_refresh_errors(errors)}；重新发起会复用已完成缓存",
                result_ref=f"market-cache:{cutoff}",
            )
        elif failed:
            raise RuntimeError(f"{label} {failed} 只股票全部更新失败：{_refresh_errors(errors)}")
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
                _ACTIVE_REFRESH_REQUEST = None


def _refresh_errors(errors: dict[str, str]) -> str:
    """保留上游实际原因；重复原因不挤满任务卡，也不猜测错误类别。"""
    return "；".join(dict.fromkeys(redact_text(reason) for reason in errors.values()))[:400]


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

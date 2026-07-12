"""通用 provider fan-out 调度。

用于没有 provider-native batch 的逐实体接口。逻辑任务先经过 operation hard cap 与
provider AIMD lane，再交给固定数量 daemon worker；重试重新排队，不在 worker 内 sleep。
"""
from __future__ import annotations

import heapq
import itertools
import os
import queue
import random
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.data.scheduler import ProviderLane, _GlobalPermitPool
from kan.infra import circuit_breaker
from kan.infra.log import debug_log

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProviderJob(Generic[T]):
    """一个不可再批量化的 provider 调用。"""

    key: str
    provider: str
    call: Callable[[], ProviderFetchResult[T]]
    capabilities: ProviderCapabilities


@dataclass(frozen=True, slots=True)
class ProviderJobResult(Generic[T]):
    """逻辑任务结果，保留最终 attempt 和尝试次数。"""

    key: str
    provider: str
    result: ProviderFetchResult[T]
    attempts: int


@dataclass(frozen=True, slots=True)
class _Work(Generic[T]):
    job: ProviderJob[T]
    attempt: int


@dataclass(frozen=True, slots=True)
class _Done(Generic[T]):
    work: _Work[T]
    result: ProviderFetchResult[T]


def resolve_provider_workers(max_workers: int | None = None) -> int:
    """解析逐实体 provider 调用硬上限；与 K 线的 KAN_WORKERS 约定一致。"""
    if max_workers is not None:
        return min(20, max(1, max_workers))
    raw = os.environ.get("KAN_WORKERS")
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if 1 <= value <= 20:
            return value
    return min((os.cpu_count() or 4) * 2, 12)


def run_provider_jobs(
    jobs: Iterable[ProviderJob[T]],
    *,
    max_workers: int | None = None,
    on_result: Callable[[ProviderJobResult[T], int, int], None] | None = None,
    on_wait: Callable[[str, FetchFailure, int], None] | None = None,
    heartbeat: Callable[[int, int], None] | None = None,
    heartbeat_interval_seconds: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    jitter: Callable[[float], float] | None = None,
) -> dict[str, ProviderJobResult[T]]:
    """运行逐实体 provider jobs，并按 provider 独立动态调节并发。"""
    job_list = list(jobs)
    if not job_list:
        return {}
    if len({job.key for job in job_list}) != len(job_list):
        raise ValueError("provider job key 必须唯一")

    worker_cap = min(resolve_provider_workers(max_workers), len(job_list))
    permits = _GlobalPermitPool(worker_cap)
    capabilities: dict[str, ProviderCapabilities] = {}
    for job in job_list:
        current = capabilities.setdefault(job.provider, job.capabilities)
        if current != job.capabilities:
            raise ValueError(f"provider {job.provider} capabilities 不一致")
    lanes = {
        provider: ProviderLane(provider, caps, clock=clock)
        for provider, caps in capabilities.items()
    }

    work_queue: queue.Queue[_Work[T] | None] = queue.Queue()
    completions: queue.Queue[_Done[T]] = queue.Queue()

    def worker() -> None:
        while True:
            work = work_queue.get()
            if work is None:
                return
            permits.mark_running()
            try:
                result = work.job.call()
            except TimeoutError as exc:
                result = ProviderFetchResult.failed(FetchFailure(
                    FetchFailureKind.TIMEOUT,
                    message=str(exc),
                    retryable=True,
                    affects_circuit=True,
                ))
            except Exception as exc:
                debug_log(__name__, f"provider job {work.job.provider}", exc)
                result = ProviderFetchResult.failed(FetchFailure(
                    FetchFailureKind.TRANSPORT,
                    message=type(exc).__name__,
                    retryable=True,
                    affects_circuit=True,
                ))
            finally:
                lanes[work.job.provider].release()
                permits.release(was_running=True)
            completions.put(_Done(work, result))

    threads = [
        threading.Thread(target=worker, name=f"kan-provider-batch-{index}", daemon=True)
        for index in range(worker_cap)
    ]
    for thread in threads:
        thread.start()

    pending = [_Work(job, 1) for job in job_list]
    delayed: list[tuple[float, int, _Work[T]]] = []
    sequence = itertools.count()
    results: dict[str, ProviderJobResult[T]] = {}
    next_heartbeat = clock() + max(0.01, heartbeat_interval_seconds)
    jitter_fn = jitter or (lambda delay: random.uniform(0.5 * delay, delay))

    try:
        while len(results) < len(job_list):
            now = clock()
            while delayed and delayed[0][0] <= now:
                _, _, work = heapq.heappop(delayed)
                pending.append(work)

            remaining: list[_Work[T]] = []
            for work in pending:
                lane = lanes[work.job.provider]
                if permits.try_acquire():
                    if lane.try_acquire():
                        work_queue.put(work)
                        continue
                    permits.release(was_running=False)
                remaining.append(work)
            pending = remaining

            try:
                done = completions.get(timeout=0.05)
            except queue.Empty:
                now = clock()
                if heartbeat is not None and now >= next_heartbeat:
                    heartbeat(permits.running, len(pending) + len(delayed))
                    next_heartbeat = now + max(0.01, heartbeat_interval_seconds)
                continue

            failure = done.result.failure
            if not done.result.breaker_recorded and (
                failure is None or failure.affects_circuit
            ):
                circuit_breaker.get_breaker().record(
                    done.work.job.provider,
                    ok=failure is None,
                )
            lanes[done.work.job.provider].record(failure)
            permits.record(failure)
            caps = done.work.job.capabilities
            if failure is not None and failure.retryable and done.work.attempt < caps.max_attempts:
                base = min(
                    caps.backoff_cap_seconds,
                    caps.backoff_base_seconds * (2 ** max(0, done.work.attempt - 1)),
                )
                if failure.retry_after is not None:
                    base = max(base, failure.retry_after)
                delay = max(0.0, jitter_fn(base))
                heapq.heappush(
                    delayed,
                    (clock() + delay, next(sequence), _Work(done.work.job, done.work.attempt + 1)),
                )
                if on_wait is not None:
                    on_wait(done.work.job.provider, failure, done.work.attempt + 1)
                continue

            completed = len(results) + 1
            final = ProviderJobResult(
                done.work.job.key,
                done.work.job.provider,
                done.result,
                done.work.attempt,
            )
            results[final.key] = final
            if on_result is not None:
                on_result(final, completed, len(job_list))
    finally:
        for _ in threads:
            work_queue.put(None)
        for thread in threads:
            thread.join(timeout=0.2)

    return results


__all__ = [
    "ProviderJob",
    "ProviderJobResult",
    "resolve_provider_workers",
    "run_provider_jobs",
]

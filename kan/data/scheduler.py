"""K 线 provider 感知调度器。

调度器把逻辑任务、provider 并发窗口和不可取消的 SDK 调用分开：逻辑任务只有
拿到 lane permit 后才会交给固定数量 supervisor；soft timeout 只让逻辑任务降级，
provider slot 仍由底层调用持有到真实返回。
"""
from __future__ import annotations

import heapq
import itertools
import queue
import random
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kan.data.protocols import DetailedKlineSource, as_detailed_kline_source
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.infra import circuit_breaker
from kan.infra.log import debug_log

if TYPE_CHECKING:
    import pandas as pd

    from kan.infra.lifecycle import OperationLifecycle

Clock = Callable[[], float]
Sleeper = Callable[[float], None]
Jitter = Callable[[float], float]


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    """一次 provider 尝试的完整事实。"""

    provider: str
    attempt: int
    started_at: float
    elapsed_seconds: float
    data: pd.DataFrame | None = None
    failure: FetchFailure | None = None
    soft_timed_out: bool = False
    breaker_recorded: bool = False

    @property
    def succeeded(self) -> bool:
        return self.data is not None and self.failure is None


@dataclass(frozen=True, slots=True)
class KlineFetchResult:
    """一个逻辑 K 线任务的最终结果；attempts 保留 fallback 全链路。"""

    symbol: str
    data: pd.DataFrame | None
    source: str | None
    attempts: tuple[ProviderAttempt, ...]
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        return self.data is not None and not self.cancelled

    @property
    def failure(self) -> FetchFailure | None:
        if self.succeeded or not self.attempts:
            return None
        return self.attempts[-1].failure


@dataclass(frozen=True, slots=True)
class SchedulerProgress:
    """与渲染无关的批量调度进度快照。"""

    completed: int
    total: int
    active_calls: int
    delayed: int
    symbol: str | None = None
    provider: str | None = None
    succeeded: bool | None = None


class ProviderLane:
    """单 provider AIMD lane；并发、冷却和 active slot 均彼此独立。"""

    def __init__(self, name: str, capabilities: ProviderCapabilities, *, clock: Clock) -> None:
        self.name = name
        self.capabilities = capabilities
        maximum = 1 if capabilities.serializes_requests or name.lower() == "baostock" else capabilities.max_concurrency
        initial = int(getattr(capabilities, "initial_concurrency", maximum))
        self.maximum = max(1, maximum)
        self.limit = min(self.maximum, max(1, initial))
        self.active = 0
        self.blocked_until = 0.0
        self._healthy = 0
        self._clock = clock
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self._clock() < self.blocked_until or self.active >= self.limit:
                return False
            self.active += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self.active <= 0:
                raise RuntimeError(f"provider lane {self.name} slot underflow")
            self.active -= 1

    def record(self, failure: FetchFailure | None) -> None:
        """成功慢加一；限流减半；超时/传输失败仅减一；数据事实失败不降窗。"""
        with self._lock:
            if failure is None:
                self._healthy += 1
                if self._healthy >= max(2, self.limit) and self.limit < self.maximum:
                    self.limit += 1
                    self._healthy = 0
                return
            self._healthy = 0
            if failure.kind == FetchFailureKind.RATE_LIMIT:
                self.limit = max(1, self.limit // 2)
                cooldown = float(getattr(self.capabilities, "rate_limit_cooldown_seconds", 0.0))
                retry_after = failure.retry_after or 0.0
                self.blocked_until = max(self.blocked_until, self._clock() + max(cooldown, retry_after))
            elif failure.kind in {FetchFailureKind.TIMEOUT, FetchFailureKind.TRANSPORT}:
                self.limit = max(1, self.limit - 1)


class _GlobalPermitPool:
    """单次 operation 的全局 provider 调用 admission hard cap。"""

    def __init__(self, maximum: int, *, initial: int | None = None) -> None:
        self.maximum = max(1, maximum)
        self.limit = min(self.maximum, max(1, initial or self.maximum))
        self.active = 0
        self.running = 0
        self._healthy = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def mark_running(self) -> None:
        with self._lock:
            self.running += 1
            if self.running > self.active:
                raise RuntimeError("global provider running count exceeds admitted permits")

    def release(self, *, was_running: bool) -> None:
        with self._lock:
            if self.active <= 0:
                raise RuntimeError("global provider permit underflow")
            if was_running:
                if self.running <= 0:
                    raise RuntimeError("global provider running count underflow")
                self.running -= 1
            self.active -= 1

    def record(self, failure: FetchFailure | None) -> None:
        """operation 级 AIMD；provider lane 之外再约束总 admission window。"""
        with self._lock:
            if failure is None:
                self._healthy += 1
                if self._healthy >= max(2, self.limit) and self.limit < self.maximum:
                    self.limit += 1
                    self._healthy = 0
                return
            self._healthy = 0
            if failure.kind == FetchFailureKind.RATE_LIMIT:
                self.limit = max(1, self.limit // 2)


@dataclass(slots=True)
class _Job:
    symbol: str
    start: str
    groups: list[list[DetailedKlineSource]]
    group_index: int = 0
    attempts: list[ProviderAttempt] = field(default_factory=list)
    attempt_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    outstanding: set[str] = field(default_factory=set)
    delayed: set[str] = field(default_factory=set)
    done: bool = False
    reported: bool = False
    result: KlineFetchResult | None = None


@dataclass(frozen=True, slots=True)
class _Dispatch:
    job: _Job
    source: DetailedKlineSource
    attempt: int
    started_at: float
    permit_acquired: bool = False


@dataclass(frozen=True, slots=True)
class _Completion:
    dispatch: _Dispatch
    result: ProviderFetchResult[pd.DataFrame]
    elapsed: float
    soft_timed_out: bool = False


class _DaemonCallPool:
    """固定大小 daemon provider call pool。"""

    def __init__(
        self,
        source: DetailedKlineSource,
        workers: int,
        lane: ProviderLane,
        permits: _GlobalPermitPool,
    ) -> None:
        self.source = source
        self.lane = lane
        self.permits = permits
        self.tasks: queue.Queue[tuple[_Dispatch, queue.Queue[ProviderFetchResult[pd.DataFrame]]] | None] = queue.Queue()
        self.threads = [
            threading.Thread(target=self._worker, name=f"kan-provider-{source.name}-{index}", daemon=True)
            for index in range(workers)
        ]
        for thread in self.threads:
            thread.start()

    def submit(self, dispatch: _Dispatch, result_queue: queue.Queue[ProviderFetchResult[pd.DataFrame]]) -> None:
        self.tasks.put((dispatch, result_queue))

    def close(self, *, join_timeout: float) -> None:
        for _ in self.threads:
            self.tasks.put(None)
        deadline = time.monotonic() + max(0.0, join_timeout)
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))

    def _worker(self) -> None:
        while True:
            item = self.tasks.get()
            if item is None:
                return
            dispatch, result_queue = item
            self.permits.mark_running()
            try:
                result = self.source.fetch_detailed(
                    dispatch.job.symbol,
                    dispatch.job.start,
                    record_breaker=False,
                )
            except TimeoutError as exc:
                result = ProviderFetchResult.failed(
                    FetchFailure(FetchFailureKind.TIMEOUT, str(exc), retryable=True, affects_circuit=True)
                )
            except Exception as exc:
                result = ProviderFetchResult.failed(
                    FetchFailure(
                        FetchFailureKind.TRANSPORT,
                        f"{type(exc).__name__}: {exc}",
                        retryable=True,
                        affects_circuit=True,
                    )
                )
            finally:
                # 不可取消调用必须真实返回后才释放 provider slot 与全局 permit。
                self.lane.release()
                self.permits.release(was_running=True)
            result_queue.put(result)


class KlineScheduler:
    """固定线程、provider lane 独立的 K 线批量调度器。"""

    def __init__(
        self,
        sources: Iterable[DetailedKlineSource],
        *,
        supervisor_workers: int = 8,
        worker_cap: int | None = None,
        initial_concurrency: int | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleeper = time.sleep,
        jitter: Jitter | None = None,
        lifecycle: OperationLifecycle | None = None,
        on_progress: Callable[[SchedulerProgress], None] | None = None,
        on_result: Callable[[KlineFetchResult], None] | None = None,
        heartbeat_interval_seconds: float = 0.5,
    ) -> None:
        detailed = [as_detailed_kline_source(source) for source in sources]
        names = [source.name for source in detailed]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"provider name 必须唯一: {', '.join(duplicates)}")
        self.sources = sorted(detailed, key=lambda source: source.priority)
        self.clock = clock
        self.sleep = sleep
        self.jitter = jitter or (lambda delay: random.uniform(0.5 * delay, delay))
        self.lifecycle = lifecycle
        self.on_progress = on_progress
        self.on_result = on_result
        self.heartbeat_interval_seconds = max(0.01, heartbeat_interval_seconds)
        inferred_cap = sum(
            1 if source.capabilities.serializes_requests else source.capabilities.max_concurrency
            for source in self.sources
        )
        self.worker_cap = max(1, worker_cap or inferred_cap or supervisor_workers)
        self.permits = _GlobalPermitPool(self.worker_cap, initial=initial_concurrency)
        self.supervisor_workers = max(1, supervisor_workers)
        self.lanes: dict[str, ProviderLane] = {}
        self.pools: dict[str, _DaemonCallPool] = {}
        for source in self.sources:
            capabilities = source.capabilities
            lane = ProviderLane(source.name, capabilities, clock=clock)
            self.lanes[source.name] = lane
            self.pools[source.name] = _DaemonCallPool(source, lane.maximum, lane, self.permits)
        self._dispatch_queue: queue.Queue[_Dispatch | None] = queue.Queue()
        self._completions: queue.Queue[_Completion] = queue.Queue()
        self._heap_sequence = itertools.count()
        self._stop = threading.Event()
        self._close_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._closed = False
        self._supervisors = [
            threading.Thread(target=self._supervise, name=f"kan-supervisor-{index}", daemon=True)
            for index in range(self.supervisor_workers)
        ]
        for thread in self._supervisors:
            thread.start()

    @property
    def concurrency(self) -> int:
        """当前 operation 可用调度窗口，不超过用户 hard cap。"""
        return min(self.worker_cap, self.permits.limit)

    @property
    def active_calls(self) -> int:
        """当前正在执行的真实 provider 调用数。"""
        return self.permits.running

    def __enter__(self) -> KlineScheduler:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self, *, join_timeout: float = 1.0) -> None:
        """幂等关闭固定线程；运行中的 provider 调用仍在真实返回后释放 slot。"""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self.cancel()
            for _ in self._supervisors:
                self._dispatch_queue.put(None)
            deadline = time.monotonic() + max(0.0, join_timeout)
            for thread in self._supervisors:
                thread.join(max(0.0, deadline - time.monotonic()))
            remaining = max(0.0, deadline - time.monotonic())
            for pool in self.pools.values():
                pool.close(join_timeout=remaining)
                remaining = max(0.0, deadline - time.monotonic())

    def fetch(self, symbol: str, start: str) -> KlineFetchResult:
        """同步调度一个逻辑任务。"""
        return self.fetch_many([symbol], start)[symbol]

    def run(self, symbols: Iterable[str], start: str) -> dict[str, KlineFetchResult]:
        """``fetch_many`` 的语义化别名。"""
        return self.fetch_many(symbols, start)

    def fetch_many(self, symbols: Iterable[str], start: str) -> dict[str, KlineFetchResult]:
        if self._closed:
            raise RuntimeError("KlineScheduler 已关闭")
        symbol_list = list(symbols)
        if not symbol_list:
            return {}
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("同一 KlineScheduler 实例不支持并发运行")
        groups = self._groups()
        jobs = [_Job(symbol=symbol, start=start, groups=groups) for symbol in symbol_list]
        delayed: list[tuple[float, int, _Dispatch]] = []
        sequence = 0
        completed = 0
        next_heartbeat = self.clock() + self.heartbeat_interval_seconds
        try:
            while completed < len(jobs):
                if self._stop.is_set():
                    self._cancel_jobs(jobs)
                    break
                now = self.clock()
                while delayed and delayed[0][0] <= now:
                    _, _, dispatch = heapq.heappop(delayed)
                    dispatch.job.delayed.discard(dispatch.source.name)
                    self._try_dispatch(dispatch, delayed, sequence)
                    sequence += 1

                made_progress = False
                for job in jobs:
                    if job.done:
                        if not job.reported:
                            completed += 1
                            job.reported = True
                            self._report(job, completed, len(jobs), delayed)
                        continue
                    before = (job.group_index, len(job.outstanding), len(job.delayed))
                    self._advance_job(job, delayed, sequence)
                    sequence += 1
                    made_progress |= before != (job.group_index, len(job.outstanding), len(job.delayed))
                    if job.done:
                        completed += 1
                        job.reported = True
                        self._report(job, completed, len(jobs), delayed)

                try:
                    completion = self._completions.get(timeout=0.01 if made_progress else 0.05)
                except queue.Empty:
                    if self._stop.is_set():
                        continue
                    now = self.clock()
                    if now >= next_heartbeat:
                        self._heartbeat(delayed)
                        next_heartbeat = now + self.heartbeat_interval_seconds
                    if delayed and not made_progress:
                        self.sleep(max(0.0, min(0.05, delayed[0][0] - self.clock())))
                    continue
                job = completion.dispatch.job
                job.outstanding.discard(completion.dispatch.source.name)
                completion = self._validate_completion(completion)
                breaker_recorded = self._record_breaker(completion)
                attempt = ProviderAttempt(
                    provider=completion.dispatch.source.name,
                    attempt=completion.dispatch.attempt,
                    started_at=completion.dispatch.started_at,
                    elapsed_seconds=completion.elapsed,
                    data=completion.result.data,
                    failure=completion.result.failure,
                    soft_timed_out=completion.soft_timed_out,
                    breaker_recorded=breaker_recorded,
                )
                job.attempts.append(attempt)
                lane = self.lanes[completion.dispatch.source.name]
                lane.record(completion.result.failure)
                self.permits.record(completion.result.failure)
                if job.done:
                    continue
                if completion.result.data is not None:
                    job.done = True
                    job.result = KlineFetchResult(
                        job.symbol,
                        completion.result.data,
                        completion.dispatch.source.name,
                        tuple(job.attempts),
                    )
                    continue
                failure = completion.result.failure
                if failure is not None and self._should_retry(
                    completion.dispatch.source,
                    completion.dispatch.attempt,
                    failure,
                    soft_timed_out=completion.soft_timed_out,
                ):
                    delay = self._retry_delay(completion.dispatch.source, completion.dispatch.attempt, failure)
                    retry = _Dispatch(job, completion.dispatch.source, completion.dispatch.attempt + 1, self.clock())
                    job.delayed.add(completion.dispatch.source.name)
                    heapq.heappush(delayed, (self.clock() + delay, next(self._heap_sequence), retry))
                    sequence += 1
                # soft timeout 必须立即允许 fallback，不能等不可取消调用或 retry。
                if completion.soft_timed_out:
                    job.delayed.discard(completion.dispatch.source.name)
            return {job.symbol: job.result or self._failed_result(job) for job in jobs}
        except KeyboardInterrupt:
            self.cancel()
            self._cancel_jobs(jobs)
            raise
        finally:
            self._run_lock.release()

    def _cancel_jobs(self, jobs: Iterable[_Job]) -> None:
        """把尚未完成的逻辑任务确定性收口；底层调用仍自行释放 permit。"""
        for job in jobs:
            if job.done:
                continue
            job.done = True
            job.result = KlineFetchResult(job.symbol, None, None, tuple(job.attempts), cancelled=True)

    def cancel(self) -> None:
        """停止接收新调度并尽量清空尚未执行的 supervisor 队列。"""
        self._stop.set()
        while True:
            try:
                dispatch = self._dispatch_queue.get_nowait()
            except queue.Empty:
                break
            if dispatch is not None:
                dispatch.job.outstanding.discard(dispatch.source.name)
                self.lanes[dispatch.source.name].release()
                if dispatch.permit_acquired:
                    self.permits.release(was_running=False)

    def _groups(self) -> list[list[DetailedKlineSource]]:
        groups: list[list[DetailedKlineSource]] = []
        for source in self.sources:
            if not groups or groups[-1][0].priority != source.priority:
                groups.append([source])
            else:
                groups[-1].append(source)
        return groups

    def _advance_job(self, job: _Job, delayed: list[tuple[float, int, _Dispatch]], sequence: int) -> None:
        while not job.done and not job.outstanding and not job.delayed:
            if job.group_index >= len(job.groups):
                job.done = True
                job.result = self._failed_result(job)
                return
            group = job.groups[job.group_index]
            job.group_index += 1
            available: list[DetailedKlineSource] = []
            for source in group:
                try:
                    is_available = source.is_available()
                except Exception:
                    is_available = False
                if is_available:
                    available.append(source)
                else:
                    job.attempts.append(
                        ProviderAttempt(
                            source.name,
                            0,
                            self.clock(),
                            0.0,
                            failure=FetchFailure(FetchFailureKind.UNAVAILABLE, f"{source.name} is unavailable"),
                        )
                    )
            if not available:
                continue
            for offset, source in enumerate(available):
                dispatch = _Dispatch(job, source, 1, self.clock())
                self._try_dispatch(dispatch, delayed, sequence + offset)
            return

    def _try_dispatch(
        self,
        dispatch: _Dispatch,
        delayed: list[tuple[float, int, _Dispatch]],
        sequence: int,
    ) -> None:
        if dispatch.job.done or self._stop.is_set():
            return
        lane = self.lanes[dispatch.source.name]
        if self.permits.try_acquire():
            if lane.try_acquire():
                dispatch.job.outstanding.add(dispatch.source.name)
                dispatch.job.attempt_counts[dispatch.source.name] = dispatch.attempt
                self._dispatch_queue.put(
                    _Dispatch(
                        dispatch.job,
                        dispatch.source,
                        dispatch.attempt,
                        self.clock(),
                        permit_acquired=True,
                    )
                )
                return
            self.permits.release(was_running=False)
        due = max(self.clock() + 0.01, lane.blocked_until)
        dispatch.job.delayed.add(dispatch.source.name)
        heapq.heappush(delayed, (due, next(self._heap_sequence), dispatch))

    def _supervise(self) -> None:
        while not self._stop.is_set():
            try:
                dispatch = self._dispatch_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if dispatch is None:
                return
            if self._stop.is_set():
                dispatch.job.outstanding.discard(dispatch.source.name)
                self.lanes[dispatch.source.name].release()
                if dispatch.permit_acquired:
                    self.permits.release(was_running=False)
                continue
            result_queue: queue.Queue[ProviderFetchResult[pd.DataFrame]] = queue.Queue(maxsize=1)
            self.pools[dispatch.source.name].submit(dispatch, result_queue)
            timeout = getattr(dispatch.source.capabilities, "timeout_seconds", None)
            try:
                result = result_queue.get(timeout=timeout)
                elapsed = max(0.0, self.clock() - dispatch.started_at)
                self._completions.put(_Completion(dispatch, result, elapsed))
            except queue.Empty:
                elapsed = max(0.0, self.clock() - dispatch.started_at)
                failure = FetchFailure(
                    FetchFailureKind.TIMEOUT,
                    f"{dispatch.source.name} soft timeout",
                    retryable=True,
                    affects_circuit=True,
                )
                self._completions.put(
                    _Completion(dispatch, ProviderFetchResult.failed(failure), elapsed, soft_timed_out=True)
                )

    def _validate_completion(self, completion: _Completion) -> _Completion:
        data = completion.result.data
        if data is None:
            return completion
        required = {"date", "open", "high", "low", "close"}
        is_empty = bool(getattr(data, "empty", False))
        columns = set(getattr(data, "columns", ()))
        if not is_empty and required.issubset(columns):
            return completion
        if is_empty:
            kind = FetchFailureKind.EMPTY
            message = f"{completion.dispatch.source.name} returned no data"
        else:
            kind = getattr(FetchFailureKind, "INVALID_SCHEMA", FetchFailureKind.EMPTY)
            missing = ",".join(sorted(required - columns))
            message = f"{completion.dispatch.source.name} invalid schema: missing {missing}"
        failure = FetchFailure(kind, message=message)
        return _Completion(
            completion.dispatch,
            ProviderFetchResult.failed(failure),
            completion.elapsed,
            completion.soft_timed_out,
        )

    def _record_breaker(self, completion: _Completion) -> bool:
        result = completion.result
        if result.breaker_recorded:
            return True
        failure = result.failure
        if failure is not None and not failure.affects_circuit:
            return False
        circuit_breaker.get_breaker().record(
            completion.dispatch.source.name,
            ok=failure is None,
        )
        return True

    def _should_retry(
        self,
        source: DetailedKlineSource,
        attempt: int,
        failure: FetchFailure,
        *,
        soft_timed_out: bool,
    ) -> bool:
        if not failure.retryable or soft_timed_out:
            return False
        maximum = int(getattr(source.capabilities, "max_attempts", 1))
        return attempt < max(1, maximum)

    def _retry_delay(self, source: DetailedKlineSource, attempt: int, failure: FetchFailure) -> float:
        base = float(getattr(source.capabilities, "backoff_base_seconds", 0.5))
        cap = float(getattr(source.capabilities, "backoff_cap_seconds", 30.0))
        exponential = min(cap, base * (2 ** max(0, attempt - 1)))
        if failure.retry_after is not None:
            exponential = max(exponential, failure.retry_after)
        return max(0.0, self.jitter(exponential))

    def _failed_result(self, job: _Job) -> KlineFetchResult:
        return KlineFetchResult(job.symbol, None, None, tuple(job.attempts))

    def _heartbeat(self, delayed: list[tuple[float, int, _Dispatch]]) -> None:
        """等待期间只发存活快照，不伪装成业务进度。"""
        if self.lifecycle is not None:
            self.lifecycle.heartbeat(
                active_calls=self.active_calls,
                delayed=len(delayed),
            )

    def _report(
        self,
        job: _Job,
        completed: int,
        total: int,
        delayed: list[tuple[float, int, _Dispatch]],
    ) -> None:
        result = job.result or self._failed_result(job)
        if self.on_result is not None:
            try:
                self.on_result(result)
            except Exception as exc:
                debug_log(__name__, f"on_result {job.symbol}", exc)
        progress = SchedulerProgress(
            completed=completed,
            total=total,
            active_calls=self.active_calls,
            delayed=len(delayed),
            symbol=job.symbol,
            provider=result.source,
            succeeded=result.succeeded,
        )
        if self.on_progress is not None:
            self.on_progress(progress)
        if self.lifecycle is not None:
            self.lifecycle.progress(
                completed,
                total,
                message=job.symbol,
                provider=progress.provider or "",
                succeeded=bool(progress.succeeded),
            )
            self.lifecycle.heartbeat(active_calls=progress.active_calls, delayed=progress.delayed)

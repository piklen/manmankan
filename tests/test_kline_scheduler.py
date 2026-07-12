"""provider 感知 K 线调度器测试。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pandas as pd
import pytest

from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.data.scheduler import (
    KlineFetchResult,
    KlineScheduler,
    ProviderLane,
    _Dispatch,
    _GlobalPermitPool,
    _Job,
)


@pytest.fixture(autouse=True)
def _isolate_circuit_breaker(monkeypatch) -> None:
    breaker = type("NoopBreaker", (), {"record": lambda self, source, ok: None})()
    monkeypatch.setattr("kan.data.scheduler.circuit_breaker.get_breaker", lambda: breaker)


def _frame(value: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-01-01"],
            "open": [value],
            "high": [value],
            "low": [value],
            "close": [value],
        }
    )


@dataclass
class FakeSource:
    name: str
    priority: int
    handler: object
    capabilities: object

    def is_available(self) -> bool:
        return True

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        result = self.fetch_detailed(symbol, start)
        return result.data

    def fetch_detailed(
        self,
        symbol: str,
        start: str,
        *,
        record_breaker: bool = False,
    ) -> ProviderFetchResult[pd.DataFrame]:
        del record_breaker
        return self.handler(symbol, start)  # type: ignore[operator, no-any-return]


class FakeLifecycle:
    def __init__(self) -> None:
        self.heartbeats: list[dict[str, object]] = []
        self.progress_events: list[tuple[int | float, int | float | None]] = []
        self.heartbeat_seen = threading.Event()

    def heartbeat(self, message: str | None = None, **details: object) -> None:
        del message
        self.heartbeats.append(details)
        self.heartbeat_seen.set()

    def progress(
        self,
        completed: int | float,
        total: int | float | None = None,
        message: str | None = None,
        **details: object,
    ) -> None:
        del message, details
        self.progress_events.append((completed, total))


def _capabilities(**overrides: object) -> ProviderCapabilities:
    values = {
        "max_concurrency": 4,
        "initial_concurrency": 4,
        "timeout_seconds": 1.0,
        "max_attempts": 1,
        "backoff_base_seconds": 0.01,
        "backoff_cap_seconds": 0.1,
        "rate_limit_cooldown_seconds": 0.0,
        "supports_retry_after": True,
        "serializes_requests": False,
    }
    if "max_concurrency" in overrides and "initial_concurrency" not in overrides:
        values["initial_concurrency"] = overrides["max_concurrency"]
    values.update(overrides)
    return ProviderCapabilities(**values)  # type: ignore[arg-type]


def test_baostock_and_serial_provider_are_hard_capped_at_one() -> None:
    baostock = ProviderLane(
        "baostock",
        ProviderCapabilities(max_concurrency=8),
        clock=time.monotonic,
    )
    serial = ProviderLane(
        "custom",
        ProviderCapabilities(max_concurrency=1, serializes_requests=True),
        clock=time.monotonic,
    )

    assert baostock.maximum == baostock.limit == 1
    assert serial.maximum == serial.limit == 1
    assert baostock.try_acquire()
    assert not baostock.try_acquire()
    baostock.release()


def test_global_permit_pool_rejects_underflow() -> None:
    permits = _GlobalPermitPool(2)

    with pytest.raises(RuntimeError, match="permit underflow"):
        permits.release(was_running=False)

    assert permits.try_acquire()
    permits.mark_running()
    permits.release(was_running=True)
    assert permits.active == permits.running == 0


def test_lane_aimd_rate_limit_halves_8_to_4_to_2_to_1() -> None:
    now = 10.0
    lane = ProviderLane(
        "fast",
        _capabilities(max_concurrency=8, initial_concurrency=8),  # type: ignore[arg-type]
        clock=lambda: now,
    )
    limited = FetchFailure(FetchFailureKind.RATE_LIMIT, retryable=True)

    lane.record(limited)
    assert lane.limit == 4
    lane.record(limited)
    assert lane.limit == 2
    lane.record(limited)
    assert lane.limit == 1


def test_lane_healthy_results_slowly_add_one() -> None:
    lane = ProviderLane(
        "recovering",
        _capabilities(max_concurrency=4, initial_concurrency=2),
        clock=time.monotonic,
    )

    lane.record(None)
    assert lane.limit == 2
    lane.record(None)
    assert lane.limit == 3


def test_retry_after_uses_larger_of_header_and_cooldown() -> None:
    now = 100.0
    lane = ProviderLane(
        "limited",
        _capabilities(rate_limit_cooldown_seconds=7.0),  # type: ignore[arg-type]
        clock=lambda: now,
    )
    lane.record(
        FetchFailure(
            FetchFailureKind.RATE_LIMIT,
            retryable=True,
            retry_after=3.0,
        )
    )
    assert lane.blocked_until == 107.0

    now = 200.0
    lane.record(
        FetchFailure(
            FetchFailureKind.RATE_LIMIT,
            retryable=True,
            retry_after=11.0,
        )
    )
    assert lane.blocked_until == 211.0


def test_empty_and_unavailable_do_not_reduce_window() -> None:
    lane = ProviderLane(
        "facts",
        _capabilities(max_concurrency=8, initial_concurrency=8),  # type: ignore[arg-type]
        clock=time.monotonic,
    )
    lane.record(FetchFailure(FetchFailureKind.EMPTY))
    lane.record(FetchFailure(FetchFailureKind.UNAVAILABLE))
    assert lane.limit == 8


def test_duplicate_provider_names_are_rejected() -> None:
    first = FakeSource("same", 10, lambda symbol, start: ProviderFetchResult.succeeded(_frame()), _capabilities())
    second = FakeSource("same", 20, lambda symbol, start: ProviderFetchResult.succeeded(_frame()), _capabilities())

    with pytest.raises(ValueError, match="provider name 必须唯一"):
        KlineScheduler([first, second])


def test_scheduler_records_circuit_once_and_only_for_relevant_results(monkeypatch) -> None:
    records: list[tuple[str, bool]] = []
    breaker = type("Recorder", (), {"record": lambda self, source, ok: records.append((source, ok))})()
    monkeypatch.setattr("kan.data.scheduler.circuit_breaker.get_breaker", lambda: breaker)
    transport = FakeSource(
        "transport",
        10,
        lambda symbol, start: ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.TRANSPORT, retryable=False, affects_circuit=True)
        ),
        _capabilities(),
    )
    limited = FakeSource(
        "limited",
        20,
        lambda symbol, start: ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.RATE_LIMIT, retryable=False)
        ),
        _capabilities(),
    )
    empty = FakeSource(
        "empty",
        30,
        lambda symbol, start: ProviderFetchResult.failed(FetchFailure(FetchFailureKind.EMPTY)),
        _capabilities(),
    )
    success = FakeSource(
        "success",
        40,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame()),
        _capabilities(),
    )

    with KlineScheduler([transport, limited, empty, success], supervisor_workers=1) as scheduler:
        result = scheduler.fetch("600519", "20260101")

    assert records == [("transport", False), ("success", True)]
    assert [attempt.breaker_recorded for attempt in result.attempts] == [True, False, False, True]


def test_cancel_releases_permits_for_dispatches_still_queued() -> None:
    source = FakeSource(
        "queued",
        10,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame()),
        _capabilities(max_concurrency=1),
    )
    scheduler = KlineScheduler([source], supervisor_workers=1)
    scheduler._stop.set()
    for thread in scheduler._supervisors:
        thread.join(0.5)
    job = _Job("600519", "20260101", [])
    assert scheduler.lanes["queued"].try_acquire()
    job.outstanding.add("queued")
    scheduler._dispatch_queue.put(_Dispatch(job, source, 1, time.monotonic()))

    scheduler.cancel()

    assert scheduler.lanes["queued"].active == 0
    assert not job.outstanding
    scheduler.close()


@pytest.mark.parametrize("stop_method", ["cancel", "close"])
def test_external_stop_returns_cancelled_jobs_without_permit_underflow(stop_method: str) -> None:
    entered = threading.Event()
    release = threading.Event()

    def hanging(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del symbol, start
        entered.set()
        release.wait(2)
        return ProviderFetchResult.succeeded(_frame())

    source = FakeSource("blocking", 10, hanging, _capabilities(max_concurrency=1))
    scheduler = KlineScheduler([source], supervisor_workers=1)
    results: dict[str, KlineFetchResult] = {}
    errors: list[BaseException] = []

    def fetch() -> None:
        try:
            results.update(scheduler.fetch_many(["600519", "000001"], "20260101"))
        except BaseException as exc:  # pragma: no cover - 失败时保留线程异常
            errors.append(exc)

    thread = threading.Thread(target=fetch)
    thread.start()
    assert entered.wait(1)

    if stop_method == "close":
        scheduler.close(join_timeout=0.01)
    else:
        scheduler.cancel()
    thread.join(1)

    assert not thread.is_alive()
    assert not errors
    assert set(results) == {"600519", "000001"}
    assert all(result.cancelled for result in results.values())
    assert scheduler.lanes["blocking"].active == 1

    release.set()
    deadline = time.monotonic() + 1
    while scheduler.lanes["blocking"].active and time.monotonic() < deadline:
        time.sleep(0.005)
    assert scheduler.lanes["blocking"].active == 0
    scheduler.cancel()
    scheduler.close()
    assert scheduler.lanes["blocking"].active == 0


def test_waiting_emits_throttled_heartbeat_snapshot_without_progress() -> None:
    entered = threading.Event()
    release = threading.Event()
    lifecycle = FakeLifecycle()

    def hanging(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del symbol, start
        entered.set()
        release.wait(2)
        return ProviderFetchResult.succeeded(_frame())

    source = FakeSource("waiting", 10, hanging, _capabilities(max_concurrency=1))
    scheduler = KlineScheduler(
        [source],
        supervisor_workers=1,
        lifecycle=lifecycle,  # type: ignore[arg-type]
        heartbeat_interval_seconds=0.01,
    )
    results: dict[str, KlineFetchResult] = {}
    thread = threading.Thread(
        target=lambda: results.update(scheduler.fetch_many(["600519", "000001"], "20260101"))
    )
    thread.start()

    assert entered.wait(1)
    assert lifecycle.heartbeat_seen.wait(1)
    assert not lifecycle.progress_events
    assert lifecycle.heartbeats[0] == {"active_calls": 1, "delayed": 1}

    release.set()
    thread.join(1)
    assert not thread.is_alive()
    assert all(result.succeeded for result in results.values())
    scheduler.close()


def test_on_result_runs_in_fetch_many_thread_before_all_jobs_finish() -> None:
    release_second = threading.Event()
    first_callback = threading.Event()
    callback_threads: list[int] = []

    def handler(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del start
        if symbol == "000001":
            release_second.wait(2)
        return ProviderFetchResult.succeeded(_frame())

    source = FakeSource("stream", 10, handler, _capabilities(max_concurrency=2))

    def on_result(result: KlineFetchResult) -> None:
        callback_threads.append(threading.get_ident())
        if result.symbol == "600519":
            first_callback.set()

    scheduler = KlineScheduler([source], supervisor_workers=2, on_result=on_result)
    thread = threading.Thread(
        target=lambda: scheduler.fetch_many(["600519", "000001"], "20260101")
    )
    thread.start()

    assert first_callback.wait(1)
    assert thread.is_alive()
    assert callback_threads == [thread.ident]
    release_second.set()
    thread.join(1)
    assert not thread.is_alive()
    assert callback_threads == [thread.ident, thread.ident]
    scheduler.close()


def test_same_scheduler_rejects_concurrent_fetch_many_runs() -> None:
    entered = threading.Event()
    release = threading.Event()

    def hanging(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del symbol, start
        entered.set()
        release.wait(2)
        return ProviderFetchResult.succeeded(_frame())

    source = FakeSource("single-run", 10, hanging, _capabilities(max_concurrency=1))
    scheduler = KlineScheduler([source], supervisor_workers=1)
    first = threading.Thread(target=lambda: scheduler.fetch("600519", "20260101"))
    first.start()
    assert entered.wait(1)

    with pytest.raises(RuntimeError, match="不支持并发运行"):
        scheduler.fetch("000001", "20260101")

    release.set()
    first.join(1)
    assert not first.is_alive()
    assert scheduler.fetch("000001", "20260101").succeeded
    scheduler.close()


def test_soft_timeout_falls_back_but_slot_releases_only_after_real_return() -> None:
    release = threading.Event()

    def hanging(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del symbol, start
        release.wait(2)
        return ProviderFetchResult.succeeded(_frame(1.0))

    slow = FakeSource("slow", 10, hanging, _capabilities(max_concurrency=1, timeout_seconds=0.02))
    fallback = FakeSource(
        "fallback",
        20,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame(2.0)),
        _capabilities(max_concurrency=1),
    )
    scheduler = KlineScheduler([slow, fallback], supervisor_workers=2, jitter=lambda delay: delay)

    result = scheduler.fetch("600519", "20260101")

    assert result.succeeded
    assert result.source == "fallback"
    assert result.attempts[0].soft_timed_out
    assert scheduler.lanes["slow"].active == 1
    release.set()
    deadline = time.monotonic() + 1
    while scheduler.lanes["slow"].active and time.monotonic() < deadline:
        time.sleep(0.005)
    assert scheduler.lanes["slow"].active == 0


def test_empty_and_invalid_schema_continue_to_fallback_without_window_drop() -> None:
    empty = FakeSource(
        "empty",
        10,
        lambda symbol, start: ProviderFetchResult.succeeded(pd.DataFrame()),
        _capabilities(max_concurrency=3, initial_concurrency=3),
    )
    invalid = FakeSource(
        "invalid",
        20,
        lambda symbol, start: ProviderFetchResult.succeeded(pd.DataFrame({"date": ["2026-01-01"]})),
        _capabilities(max_concurrency=3, initial_concurrency=3),
    )
    fallback = FakeSource(
        "fallback",
        30,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame(3.0)),
        _capabilities(max_concurrency=1),
    )
    scheduler = KlineScheduler([empty, invalid, fallback], supervisor_workers=2)

    result = scheduler.fetch("600519", "20260101")

    assert result.source == "fallback"
    assert [attempt.failure.kind if attempt.failure else None for attempt in result.attempts] == [
        FetchFailureKind.EMPTY,
        FetchFailureKind.INVALID_SCHEMA,
        None,
    ]
    assert scheduler.lanes["empty"].limit == 3
    assert scheduler.lanes["invalid"].limit == 3


def test_same_priority_race_uses_lanes_and_late_loser_cannot_overwrite() -> None:
    release = threading.Event()

    def late(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del symbol, start
        release.wait(1)
        return ProviderFetchResult.succeeded(_frame(1.0))

    first = FakeSource("late", 10, late, _capabilities(max_concurrency=1, timeout_seconds=0.5))
    winner = FakeSource(
        "winner",
        10,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame(9.0)),
        _capabilities(max_concurrency=1),
    )
    scheduler = KlineScheduler([first, winner], supervisor_workers=2)

    result = scheduler.fetch("600519", "20260101")
    release.set()

    assert result.source == "winner"
    assert float(result.data["close"].iloc[0]) == 9.0  # type: ignore[index]
    assert scheduler.lanes["late"].active == 1


def test_provider_returned_timeout_retries_after_slot_release() -> None:
    calls = 0

    def timeout_then_success(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        nonlocal calls
        del symbol, start
        calls += 1
        if calls == 1:
            return ProviderFetchResult.failed(
                FetchFailure(FetchFailureKind.TIMEOUT, retryable=True, affects_circuit=True)
            )
        return ProviderFetchResult.succeeded(_frame())

    source = FakeSource(
        "timeout",
        10,
        timeout_then_success,
        _capabilities(max_concurrency=1, max_attempts=2, backoff_base_seconds=0.001),
    )
    with KlineScheduler([source], supervisor_workers=1, jitter=lambda delay: delay) as scheduler:
        result = scheduler.fetch("600519", "20260101")

    assert result.succeeded
    assert calls == 2
    assert [attempt.failure.kind if attempt.failure else None for attempt in result.attempts] == [
        FetchFailureKind.TIMEOUT,
        None,
    ]
    assert not any(attempt.soft_timed_out for attempt in result.attempts)


def test_fallback_success_preserves_all_attempts_and_retries_use_delayed_heap() -> None:
    calls = 0

    def limited(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        nonlocal calls
        del symbol, start
        calls += 1
        return ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.TRANSPORT, retryable=True, affects_circuit=True)
        )

    primary = FakeSource(
        "primary",
        10,
        limited,
        _capabilities(max_attempts=2, backoff_base_seconds=0.001),
    )
    fallback = FakeSource(
        "fallback",
        20,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame(2.0)),
        _capabilities(),
    )
    scheduler = KlineScheduler([primary, fallback], supervisor_workers=1, jitter=lambda delay: delay)

    result = scheduler.fetch("600519", "20260101")

    assert calls == 2
    assert result.source == "fallback"
    assert [attempt.provider for attempt in result.attempts] == ["primary", "primary", "fallback"]


def test_keyboard_interrupt_stops_scheduler_without_process_exit() -> None:
    primary = FakeSource(
        "limited",
        10,
        lambda symbol, start: ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.RATE_LIMIT, retryable=True)
        ),
        _capabilities(max_attempts=2, backoff_base_seconds=1.0, backoff_cap_seconds=1.0),
    )

    def interrupt(delay: float) -> None:
        del delay
        raise KeyboardInterrupt

    scheduler = KlineScheduler([primary], supervisor_workers=1, sleep=interrupt, jitter=lambda delay: delay)

    with pytest.raises(KeyboardInterrupt):
        scheduler.fetch("600519", "20260101")

    assert scheduler._stop.is_set()


def test_5500_jobs_do_not_create_per_job_threads() -> None:
    before = {thread.ident for thread in threading.enumerate()}
    scheduler = KlineScheduler([], supervisor_workers=3)

    results = scheduler.fetch_many((f"{index:06d}" for index in range(5500)), "20260101")
    after = [thread for thread in threading.enumerate() if thread.ident not in before]

    assert len(results) == 5500
    assert all(not result.succeeded for result in results.values())
    assert len([thread for thread in after if thread.name.startswith("kan-supervisor-")]) == 3


def test_close_is_idempotent_and_repeated_schedulers_do_not_leak_threads() -> None:
    before = {thread.ident for thread in threading.enumerate()}
    source = FakeSource(
        "closable",
        10,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame()),
        _capabilities(max_concurrency=2),
    )

    for _ in range(3):
        with KlineScheduler([source], supervisor_workers=2) as scheduler:
            assert scheduler.fetch("600519", "20260101").succeeded
        scheduler.close()

    deadline = time.monotonic() + 1.0
    alive: list[threading.Thread] = []
    while time.monotonic() < deadline:
        alive = [
            thread
            for thread in threading.enumerate()
            if thread.ident not in before
            and (thread.name.startswith("kan-supervisor-") or thread.name.startswith("kan-provider-closable-"))
        ]
        if not alive:
            break
        time.sleep(0.01)
    assert not alive
    with pytest.raises(RuntimeError, match="已关闭"):
        scheduler.fetch("600519", "20260101")


def test_thread_count_is_constant_in_job_count() -> None:
    source = FakeSource(
        "fixed",
        10,
        lambda symbol, start: ProviderFetchResult.succeeded(_frame()),
        _capabilities(max_concurrency=2),
    )
    before = {thread.ident for thread in threading.enumerate()}
    scheduler = KlineScheduler([source], supervisor_workers=3)
    after = [thread for thread in threading.enumerate() if thread.ident not in before]

    assert len([thread for thread in after if thread.name.startswith("kan-supervisor-")]) == 3
    assert len([thread for thread in after if thread.name.startswith("kan-provider-fixed-")]) == 2
    assert all(thread.daemon for thread in after)
    assert not hasattr(scheduler, "_jobs_threads")

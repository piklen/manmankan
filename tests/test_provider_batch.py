"""通用逐实体 provider 调度器回归。"""
from __future__ import annotations

import threading
import time

from kan.data.provider_batch import ProviderJob, run_provider_jobs
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)


def test_provider_jobs_run_concurrently_but_respect_hard_cap() -> None:
    lock = threading.Lock()
    active = 0
    peak = 0

    def call() -> ProviderFetchResult[int]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return ProviderFetchResult.succeeded(1)

    caps = ProviderCapabilities(max_concurrency=8, initial_concurrency=8)
    jobs = [ProviderJob(str(index), "test", call, caps) for index in range(8)]

    results = run_provider_jobs(jobs, max_workers=3)

    assert len(results) == 8
    assert 1 < peak <= 3


def test_rate_limit_retry_reenters_provider_lane() -> None:
    calls = 0
    waits: list[tuple[str, FetchFailureKind, int]] = []

    def call() -> ProviderFetchResult[int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ProviderFetchResult.failed(FetchFailure(
                FetchFailureKind.RATE_LIMIT,
                message="limited",
                retryable=True,
            ))
        return ProviderFetchResult.succeeded(42)

    caps = ProviderCapabilities(
        max_concurrency=2,
        initial_concurrency=2,
        max_attempts=2,
        backoff_base_seconds=0,
        backoff_cap_seconds=0,
        rate_limit_cooldown_seconds=0,
    )
    jobs = [ProviderJob("one", "test", call, caps)]

    results = run_provider_jobs(
        jobs,
        jitter=lambda _delay: 0,
        on_wait=lambda provider, failure, attempt: waits.append(
            (provider, failure.kind, attempt)
        ),
    )

    assert calls == 2
    assert results["one"].attempts == 2
    assert results["one"].result.data == 42
    assert waits == [("test", FetchFailureKind.RATE_LIMIT, 2)]


def test_provider_failure_does_not_cancel_other_jobs() -> None:
    caps = ProviderCapabilities(max_concurrency=2, initial_concurrency=2)
    jobs = [
        ProviderJob(
            "bad",
            "test",
            lambda: ProviderFetchResult.failed(FetchFailure(
                FetchFailureKind.EMPTY,
                message="empty",
            )),
            caps,
        ),
        ProviderJob(
            "good",
            "test",
            lambda: ProviderFetchResult.succeeded("ok"),
            caps,
        ),
    ]

    results = run_provider_jobs(jobs)

    assert results["bad"].result.failure is not None
    assert results["good"].result.data == "ok"

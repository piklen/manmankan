"""fetch_batch 自适应并发调度测试。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pandas as pd

from kan.data import fetcher
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)


def _kline_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": [date(2026, 6, 26)],
        "open": [10.0],
        "high": [10.5],
        "low": [9.8],
        "close": [10.2],
    })


@dataclass
class FakeDetailedSource:
    name: str
    handler: object
    priority: int = 10
    capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(
            max_concurrency=20,
            initial_concurrency=20,
            max_attempts=1,
        )
    )

    def is_available(self) -> bool:
        return True

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return self.fetch_detailed(symbol, start).data

    def fetch_detailed(
        self, symbol: str, start: str, *, record_breaker: bool = False,
    ) -> ProviderFetchResult[pd.DataFrame]:
        del record_breaker
        return self.handler(symbol, start)  # type: ignore[operator, no-any-return]


def _install_sources(monkeypatch, *sources: FakeDetailedSource) -> None:
    monkeypatch.setattr(
        fetcher,
        "default_kline_chain",
        lambda: SimpleNamespace(sources=list(sources)),
    )


def test_adaptive_controller_increases_after_healthy_windows():
    """连续健康窗口后提交窗口应确定性爬升,不是永远固定在初始值。

    直测控制器而非 fetch_batch 集成:集成层的时延来自真实时钟,慢 CI 上
    p90 抖动会误触降并发,曾导致偶发失败(issue #213)。控制器直测时钟无关。
    """
    controller = fetcher._AdaptiveConcurrency(initial=2, maximum=20)
    for _ in range(80):
        controller.record(ok=True, error=None, elapsed_seconds=0.001)
    # 80 个均匀成功 · 每满一个健康窗口 limit+1 · 必然离开初始值
    assert controller.limit > 2
    assert controller.limit <= 20


def test_fetch_batch_reports_full_progress_stream(monkeypatch, tmp_path):
    """fetch_batch 应完成全部任务并输出逐个进度状态(时序无关断言)。"""
    monkeypatch.delenv("KAN_WORKERS", raising=False)
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetcher, "resolve_max_workers", lambda: 2)

    df = _kline_df()
    _install_sources(
        monkeypatch,
        FakeDetailedSource(
            "fake",
            lambda symbol, start: ProviderFetchResult.succeeded(df.copy()),
        ),
    )

    states: list[fetcher.FetchProgress] = []
    results, errors = fetcher.fetch_batch(
        [f"{i:06d}" for i in range(80)],
        force=True,
        on_progress_state=states.append,
    )

    assert len(results) == 80
    assert errors == {}
    assert len(states) == 80
    assert states[-1].completed == 80
    assert all(state.max_concurrency == fetcher.DEFAULT_ADAPTIVE_MAX_WORKERS for state in states)


def test_fetch_batch_adaptive_workers_back_off_on_rate_limit(monkeypatch, tmp_path):
    """限流/背压类错误应快速降并发,避免继续按高并发冲上游。"""
    monkeypatch.delenv("KAN_WORKERS", raising=False)
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetcher, "resolve_max_workers", lambda: 8)
    limited = FetchFailure(
        FetchFailureKind.RATE_LIMIT,
        "40203 frequency limit",
        retryable=False,
    )
    _install_sources(
        monkeypatch,
        FakeDetailedSource(
            "limited",
            lambda symbol, start: ProviderFetchResult.failed(limited),
            capabilities=ProviderCapabilities(
                max_concurrency=8,
                initial_concurrency=8,
                max_attempts=1,
                rate_limit_cooldown_seconds=0,
            ),
        ),
    )

    states: list[fetcher.FetchProgress] = []

    results, errors = fetcher.fetch_batch(
        [f"{i:06d}" for i in range(16)],
        force=True,
        on_progress_state=states.append,
    )

    assert results == {}
    assert len(errors) == 16
    assert states
    assert min(state.concurrency for state in states) < 8


def test_fetch_batch_explicit_max_workers_is_hard_cap(monkeypatch, tmp_path):
    """调用方显式传 max_workers 时,自适应逻辑不能越过这个硬上限。"""
    monkeypatch.delenv("KAN_WORKERS", raising=False)
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)

    active = 0
    max_seen = 0
    lock = threading.Lock()

    def fake_fetch(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del symbol, start
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        try:
            time.sleep(0.01)
            return ProviderFetchResult.succeeded(_kline_df())
        finally:
            with lock:
                active -= 1

    capabilities = ProviderCapabilities(
        max_concurrency=10,
        initial_concurrency=10,
        max_attempts=1,
    )
    _install_sources(
        monkeypatch,
        FakeDetailedSource("first", fake_fetch, priority=10, capabilities=capabilities),
        FakeDetailedSource("second", fake_fetch, priority=10, capabilities=capabilities),
    )
    states: list[fetcher.FetchProgress] = []

    results, errors = fetcher.fetch_batch(
        [f"{i:06d}" for i in range(30)],
        force=True,
        max_workers=3,
        on_progress_state=states.append,
    )

    assert len(results) == 30
    assert errors == {}
    assert max_seen <= 3
    assert all(state.concurrency <= 3 for state in states)
    assert all(state.max_concurrency == 3 for state in states)

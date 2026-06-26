"""fetch_batch 自适应并发调度测试。"""
from __future__ import annotations

import threading
import time
from datetime import date

import pandas as pd

from kan.data import fetcher


def _kline_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": [date(2026, 6, 26)],
        "open": [10.0],
        "high": [10.5],
        "low": [9.8],
        "close": [10.2],
    })


def test_fetch_batch_adaptive_workers_increase_on_healthy_window(monkeypatch):
    """健康窗口内应从起跑并发继续向上探测,不是永远固定在初始值。"""
    monkeypatch.delenv("KAN_WORKERS", raising=False)
    monkeypatch.setattr(fetcher, "resolve_max_workers", lambda: 2)

    active = 0
    max_seen = 0
    lock = threading.Lock()

    def fake_fetch_kline(symbol: str, *, days: int, force: bool) -> pd.DataFrame:
        del symbol, days, force
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        try:
            time.sleep(0.01)
            return _kline_df()
        finally:
            with lock:
                active -= 1

    states: list[fetcher.FetchProgress] = []
    monkeypatch.setattr(fetcher, "fetch_kline", fake_fetch_kline)

    results, errors = fetcher.fetch_batch(
        [f"{i:06d}" for i in range(80)],
        force=True,
        on_progress_state=states.append,
    )

    assert len(results) == 80
    assert errors == {}
    assert max_seen > 2
    assert any(state.concurrency > 2 for state in states)
    assert all(state.max_concurrency == fetcher.DEFAULT_ADAPTIVE_MAX_WORKERS for state in states)


def test_fetch_batch_adaptive_workers_back_off_on_rate_limit(monkeypatch):
    """限流/背压类错误应快速降并发,避免继续按高并发冲上游。"""
    monkeypatch.delenv("KAN_WORKERS", raising=False)
    monkeypatch.setattr(fetcher, "resolve_max_workers", lambda: 8)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def fake_fetch_kline(symbol: str, *, days: int, force: bool) -> pd.DataFrame:
        del symbol, days, force
        raise RuntimeError("40203 frequency limit")

    states: list[fetcher.FetchProgress] = []
    monkeypatch.setattr(fetcher, "fetch_kline", fake_fetch_kline)

    results, errors = fetcher.fetch_batch(
        [f"{i:06d}" for i in range(16)],
        force=True,
        on_progress_state=states.append,
    )

    assert results == {}
    assert len(errors) == 16
    assert states
    assert min(state.concurrency for state in states) < 8


def test_fetch_batch_explicit_max_workers_is_hard_cap(monkeypatch):
    """调用方显式传 max_workers 时,自适应逻辑不能越过这个硬上限。"""
    monkeypatch.delenv("KAN_WORKERS", raising=False)

    active = 0
    max_seen = 0
    lock = threading.Lock()

    def fake_fetch_kline(symbol: str, *, days: int, force: bool) -> pd.DataFrame:
        del symbol, days, force
        nonlocal active, max_seen
        with lock:
            active += 1
            max_seen = max(max_seen, active)
        try:
            time.sleep(0.01)
            return _kline_df()
        finally:
            with lock:
                active -= 1

    states: list[fetcher.FetchProgress] = []
    monkeypatch.setattr(fetcher, "fetch_kline", fake_fetch_kline)

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

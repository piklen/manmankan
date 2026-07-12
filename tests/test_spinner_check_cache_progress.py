"""auto_fetch_stale 生命周期阶段与缓存检查进度测试。"""
from __future__ import annotations

import pytest

from kan.cli import helpers
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, operation


@pytest.fixture
def patched_dependencies(monkeypatch):
    """默认所有缓存新鲜，避免进入真实补数据。"""
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda sym: True)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: None)
    monkeypatch.setattr("kan.data.fetcher.fetch_batch", lambda symbols, **kw: ({}, {}))


def _run_with_lifecycle(pairs):
    reporter = CollectingReporter()
    with operation("test-auto-fetch", reporter=reporter) as lifecycle:
        helpers._auto_fetch_stale(pairs, lifecycle=lifecycle)
    return reporter.events


def test_cache_check_emits_three_phases_and_incremental_progress(patched_dependencies):
    pairs = [(f"{600000 + i:06d}", f"测试股{i}") for i in range(169)]

    events = _run_with_lifecycle(pairs)

    phases = [event.message for event in events if event.kind is LifecycleKind.PHASE]
    assert phases[:3] == ["加载数据模块", "加载交易日历", "检查缓存"]
    progress = [
        event for event in events
        if event.kind is LifecycleKind.PROGRESS and event.message == "检查缓存"
    ]
    assert len(progress) >= 5
    assert progress[-1].completed == 169
    assert progress[-1].total == 169


def test_cache_progress_aggregates_stale_count(monkeypatch):
    monkeypatch.setattr(
        "kan.data.fetcher.is_fresh",
        lambda sym: int(sym) % 2 == 0,
    )
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: None)
    monkeypatch.setattr("kan.data.fetcher.fetch_batch", lambda symbols, **kw: ({}, {}))

    events = _run_with_lifecycle([(f"{i:06d}", f"股{i}") for i in range(100)])

    cache_progress = [
        event for event in events
        if event.kind is LifecycleKind.PROGRESS and event.message == "检查缓存"
    ]
    assert cache_progress[-1].details["stale_count"] == 50
    waits = [event for event in events if event.kind is LifecycleKind.WAIT]
    assert waits[-1].details["stale_count"] == 50


def test_small_watchlist_reports_completion(patched_dependencies):
    pairs = [("600519", "茅台"), ("000001", "平安"), ("600000", "浦发")]

    events = _run_with_lifecycle(pairs)

    progress = [event for event in events if event.kind is LifecycleKind.PROGRESS]
    assert progress[-1].completed == 3
    assert progress[-1].total == 3


def test_empty_watchlist_emits_phases_without_crash(patched_dependencies):
    events = _run_with_lifecycle([])

    phases = [event.message for event in events if event.kind is LifecycleKind.PHASE]
    assert phases == ["加载数据模块", "加载交易日历", "检查缓存"]


def test_latest_trade_date_exception_keeps_lifecycle_alive(monkeypatch):
    def raise_for_pre_warm():
        raise RuntimeError("trade calendar unavailable (mock)")

    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", raise_for_pre_warm)
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda sym: True)

    events = _run_with_lifecycle([("600519", "茅台")])

    phases = [event.message for event in events if event.kind is LifecycleKind.PHASE]
    assert "检查缓存" in phases

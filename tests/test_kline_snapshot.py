"""kan.data.kline_snapshot · 全市场 K 线预计算快照测试。"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from kan.data import kline_snapshot
from kan.infra.lifecycle import (
    CollectingReporter,
    LifecycleKind,
    OperationState,
    operation,
)


def _daily(d: date, close: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol": "600519",
        "date": d,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 1000,
        "amount": 10000,
    }])


def test_fetch_kline_snapshot_builds_position_gain_and_up_days(monkeypatch, tmp_path):
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    days = [date(2026, 5, 25) + timedelta(days=i) for i in range(6)]
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)

    def fake_daily(td, *, symbols=None, force=False, minimum_rows=None):
        d = date.fromisoformat(f"{td[:4]}-{td[4:6]}-{td[6:]}")
        idx = days.index(d)
        return _daily(d, 100.0 + idx * 2)

    monkeypatch.setattr(kline_snapshot, "fetch_daily_bars", fake_daily)
    out = kline_snapshot.fetch_kline_snapshot("20260530", periods=[3, 5])
    assert len(out) == 1
    row = out.iloc[0]
    assert row["symbol"] == "600519"
    assert row["pos_3"] is not None
    assert row["gain_3"] > 0
    assert row["up_days"] == 6


def test_fetch_kline_snapshot_reports_fetch_and_compute_progress(monkeypatch, tmp_path):
    days = [date(2026, 5, 28), date(2026, 5, 29)]
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)
    monkeypatch.setattr(
        kline_snapshot,
        "fetch_daily_bars",
        lambda td, **_kw: _daily(datetime.strptime(td, "%Y%m%d").date(), 100.0),
    )
    reporter = CollectingReporter()

    out = kline_snapshot.fetch_kline_snapshot(
        "20260529", periods=[2], reporter=reporter
    )

    assert len(out) == 1
    progress = [event for event in reporter.events if event.kind is LifecycleKind.PROGRESS]
    assert any((event.completed, event.total) == (2, 2) for event in progress)
    assert any(event.message == "计算 K 线快照" for event in progress)
    assert reporter.events[-1].state is OperationState.SUCCEEDED


def test_fetch_kline_snapshot_cache_hit_skips_remote_progress(monkeypatch, tmp_path):
    cached = pd.DataFrame([{"symbol": "600519", "trade_date": date(2026, 5, 29)}])
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "_cache_fresh", lambda *_a: True)
    monkeypatch.setattr(kline_snapshot, "_load_cache", lambda _path: cached)
    monkeypatch.setattr(
        kline_snapshot,
        "fetch_daily_bars",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("不应触发远端获取")),
    )
    reporter = CollectingReporter()

    out = kline_snapshot.fetch_kline_snapshot("20260529", reporter=reporter)

    assert out.equals(cached)
    assert any(event.message == "命中 K 线快照缓存" for event in reporter.events)
    assert all(event.kind is not LifecycleKind.PROGRESS for event in reporter.events)


def test_build_snapshot_aggregates_symbol_failures(monkeypatch):
    good = _daily(date(2026, 5, 29), 100.0)
    bad = good.assign(symbol="000001")
    original = kline_snapshot.scan_stock

    def fake_scan(group, *args, **kwargs):
        if str(group.iloc[0]["symbol"]) == "000001":
            raise ValueError("broken")
        return original(group, *args, **kwargs)

    monkeypatch.setattr(kline_snapshot, "scan_stock", fake_scan)
    reporter = CollectingReporter()
    with operation("构造快照", reporter=reporter) as lifecycle:
        out = kline_snapshot._build_snapshot(
            pd.concat([good, bad]), periods=[2], end_date=date(2026, 5, 29), lifecycle=lifecycle
        )

    assert list(out["symbol"]) == ["600519"]
    degraded = [event for event in reporter.events if event.kind is LifecycleKind.DEGRADED]
    assert len(degraded) == 1
    assert degraded[0].details["failure_count"] == 1


def test_fetch_recent_daily_bars_merges_recent_dates_and_filters_symbols(monkeypatch, tmp_path):
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    days = [date(2026, 5, 27) + timedelta(days=i) for i in range(3)]
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)

    def fake_daily(td, *, symbols=None, force=False, minimum_rows=None):
        d = date.fromisoformat(f"{td[:4]}-{td[4:6]}-{td[6:]}")
        return pd.DataFrame([
            {
                "symbol": "600519",
                "date": d,
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000,
                "amount": 10000,
            },
            {
                "symbol": "000001",
                "date": d,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 2000,
                "amount": 20000,
            },
        ])

    monkeypatch.setattr(kline_snapshot, "fetch_daily_bars", fake_daily)
    out = kline_snapshot.fetch_recent_daily_bars(3, end_date="20260529", symbols=["600519"])

    assert len(out) == 3
    assert set(out["symbol"]) == {"600519"}
    assert list(out["date"]) == days


def test_fetch_recent_daily_bars_reports_progress(monkeypatch, tmp_path):
    """全市场日线 panel 拉取每个交易日完成后回调进度。"""
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    days = [date(2026, 5, 28), date(2026, 5, 29)]
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)

    def fake_daily(td, *, symbols=None, force=False, minimum_rows=None):
        d = date.fromisoformat(f"{td[:4]}-{td[4:6]}-{td[6:]}")
        return _daily(d, 100.0)

    events: list[tuple[int, int, date, int]] = []
    monkeypatch.setattr(kline_snapshot, "fetch_daily_bars", fake_daily)

    out = kline_snapshot.fetch_recent_daily_bars(
        2,
        end_date="20260529",
        symbols=["600519"],
        on_progress=lambda done, total, day, rows: events.append((done, total, day, rows)),
    )

    assert len(out) == 2
    assert events == [
        (1, 2, date(2026, 5, 28), 1),
        (2, 2, date(2026, 5, 29), 1),
    ]


def test_fetch_recent_daily_bars_parallelizes_large_history(monkeypatch, tmp_path):
    """全市场长窗口按交易日并发，且输出仍按日期排序。"""
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    days = [date(2026, 5, 1) + timedelta(days=i) for i in range(12)]
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_daily(td, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            trade_day = datetime.strptime(td, "%Y%m%d").date()
            return _daily(trade_day, 100.0)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(kline_snapshot, "fetch_daily_bars", fake_daily)

    out = kline_snapshot.fetch_recent_daily_bars(
        len(days),
        end_date="20260512",
        symbols=["600519"],
        max_workers=8,
    )

    assert 1 < peak <= 8
    assert list(out["date"]) == days


def test_fetch_recent_daily_bars_parallel_contract_failure_is_reported(
    monkeypatch, tmp_path,
):
    """并发窗口中任一交易日契约异常必须让整批明确失败。"""
    days = [date(2026, 5, 1) + timedelta(days=i) for i in range(8)]
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)

    def fake_daily(td, **_kwargs):
        if td == "20260503":
            raise kline_snapshot.TushareDataContractError("stk_factor_pro", "incomplete")
        return _daily(datetime.strptime(td, "%Y%m%d").date(), 100.0)

    monkeypatch.setattr(kline_snapshot, "fetch_daily_bars", fake_daily)
    reporter = CollectingReporter()

    with pytest.raises(RuntimeError, match="数据契约校验失败"):
        kline_snapshot.fetch_recent_daily_bars(
            len(days),
            end_date="20260508",
            symbols=["600519"],
            max_workers=4,
            reporter=reporter,
        )

    degraded = [event for event in reporter.events if event.kind is LifecycleKind.DEGRADED]
    assert degraded and degraded[-1].details["failure_count"] == 1


def test_fetch_recent_daily_bars_reports_real_stage_events(monkeypatch, tmp_path):
    days = [date(2026, 5, 28), date(2026, 5, 29)]
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)
    monkeypatch.setattr(
        kline_snapshot,
        "fetch_daily_bars",
        lambda td, **_kw: _daily(datetime.strptime(td, "%Y%m%d").date(), 100.0),
    )
    reporter = CollectingReporter()

    out = kline_snapshot.fetch_recent_daily_bars(
        2,
        end_date="20260529",
        symbols=["600519"],
        reporter=reporter,
    )

    assert len(out) == 2
    messages = [event.message for event in reporter.events]
    assert messages == [
        None,
        "解析交易日历",
        "交易日历就绪",
        "获取每日截面",
        "每日截面完成",
        "获取每日截面",
        "每日截面完成",
        "合并每日截面",
        "每日截面合并完成",
        "排序日线面板",
        "日线面板排序完成",
        "过滤目标股票",
        "目标股票过滤完成",
        None,
    ]
    final_daily = reporter.events[6]
    assert final_daily.kind is LifecycleKind.PROGRESS
    assert (final_daily.completed, final_daily.total) == (2, 2)
    assert final_daily.details["progress_unit"] == "个交易日"
    assert final_daily.details["progress_detail"] == (
        "2026-05-29 · 本日 1 只股票"
    )
    waiting_daily = reporter.events[5]
    assert waiting_daily.kind is LifecycleKind.PROGRESS
    assert (waiting_daily.completed, waiting_daily.total) == (1, 2)
    assert waiting_daily.details["progress_unit"] == "个交易日"
    assert waiting_daily.details["progress_detail"] == "正在获取 2026-05-29"
    assert reporter.events[7].kind is LifecycleKind.PHASE
    assert reporter.events[-1].state is OperationState.SUCCEEDED


def test_fetch_recent_daily_bars_empty_day_fails_operation(monkeypatch):
    trade_day = date(2026, 5, 29)
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: [trade_day])
    monkeypatch.setattr(kline_snapshot, "fetch_daily_bars", lambda *_a, **_kw: pd.DataFrame())
    reporter = CollectingReporter()

    with pytest.raises(RuntimeError, match="日线截面为空"):
        kline_snapshot.fetch_recent_daily_bars(
            1,
            end_date="20260529",
            reporter=reporter,
        )

    assert reporter.events[-2].kind is LifecycleKind.DEGRADED
    assert reporter.events[-1].state is OperationState.FAILED
    assert all(event.message != "每日截面完成" for event in reporter.events)


def test_fetch_daily_bars_rejects_incomplete_cross_section_before_cache(
    monkeypatch, tmp_path,
):
    trade_day = date(2026, 7, 20)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "ensure_dirs", lambda: None)
    monkeypatch.setattr(kline_snapshot, "_MIN_COMPLETE_DAILY_BARS", 2)
    monkeypatch.setattr(
        "kan.data.tushare._fetch_tushare_daily_bars",
        lambda _td: _daily(trade_day, 100.0),
    )

    with pytest.raises(
        kline_snapshot.TushareDataContractError,
        match=r"仅返回 1 只.*校验下界 2",
    ):
        kline_snapshot.fetch_daily_bars("20260720", force=True)

    assert not kline_snapshot._daily_cache_path("20260720").exists()


def test_fetch_daily_bars_uses_complete_raw_fallback_for_latest_day(
    monkeypatch, tmp_path,
):
    """最新日复权 generation 不完整时，用完整 daily 截面补齐。"""
    trade_day = date(2026, 7, 31)
    incomplete = _daily(trade_day, 100.0)
    complete = pd.concat([
        incomplete,
        _daily(trade_day, 20.0).assign(symbol="920000"),
    ], ignore_index=True)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "_MIN_COMPLETE_DAILY_BARS", 2)
    monkeypatch.setattr(kline_snapshot, "_latest_trade_date_str", lambda: "20260731")
    monkeypatch.setattr(
        "kan.data.tushare._fetch_tushare_daily_bars",
        lambda _td: incomplete,
    )
    monkeypatch.setattr(
        "kan.data.tushare._fetch_tushare_raw_daily_bars",
        lambda _td: complete,
    )

    out = kline_snapshot.fetch_daily_bars("20260731", force=True)

    assert set(out["symbol"]) == {"600519", "920000"}
    assert kline_snapshot._daily_cache_path("20260731").exists()


def test_fetch_daily_bars_never_uses_raw_fallback_for_historical_day(
    monkeypatch, tmp_path,
):
    """历史 raw 价格不能混入当前口径的前复权序列。"""
    trade_day = date(2026, 7, 30)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "_MIN_COMPLETE_DAILY_BARS", 2)
    monkeypatch.setattr(kline_snapshot, "_latest_trade_date_str", lambda: "20260731")
    monkeypatch.setattr(
        "kan.data.tushare._fetch_tushare_daily_bars",
        lambda _td: _daily(trade_day, 100.0),
    )
    monkeypatch.setattr(
        "kan.data.tushare._fetch_tushare_raw_daily_bars",
        lambda _td: (_ for _ in ()).throw(AssertionError("历史日不应走 raw daily")),
    )

    with pytest.raises(kline_snapshot.TushareDataContractError):
        kline_snapshot.fetch_daily_bars("20260730", force=True)


def test_daily_completeness_floor_scales_with_known_universe(monkeypatch):
    monkeypatch.setattr(kline_snapshot, "_MIN_COMPLETE_DAILY_BARS", 3)
    monkeypatch.setattr(kline_snapshot, "_MIN_DAILY_UNIVERSE_COVERAGE", 0.9)

    assert kline_snapshot._minimum_daily_rows([f"{code:06d}" for code in range(10)]) == 9


def test_daily_panel_freshness_uses_cross_section_cache_only(monkeypatch, tmp_path):
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date",
        lambda _symbol: (_ for _ in ()).throw(AssertionError("不应读取逐股 cutoff")),
    )
    monkeypatch.setattr(
        "kan.data.fetcher.cache_age",
        lambda _symbol: (_ for _ in ()).throw(AssertionError("不应读取逐股 mtime")),
    )
    days = [date(2026, 5, 28), date(2026, 5, 29)]
    panel = pd.concat([_daily(day, 100.0 + idx) for idx, day in enumerate(days)])
    timestamps = [1_780_000_000.0, 1_780_000_120.0]
    for day, timestamp in zip(days, timestamps, strict=True):
        path = kline_snapshot._daily_cache_path(day.strftime("%Y%m%d"))
        panel[panel["date"] == day].to_parquet(path)
        os.utime(path, (timestamp, timestamp))

    freshness = kline_snapshot.daily_panel_freshness(
        panel,
        symbols=["600519"],
        expected_cutoff=days[-1],
        required_rows=2,
    )

    assert freshness.data_cutoff == days[-1]
    assert freshness.fetched_at == datetime.fromtimestamp(timestamps[-1]).strftime(
        "%Y-%m-%d %H:%M"
    )
    assert freshness.current_count == 1
    assert freshness.missing_count == 0
    assert freshness.history_incomplete_count == 0
    assert freshness.is_stale is False


def test_daily_panel_freshness_uses_panel_cutoff_not_history_window_start(
    monkeypatch, tmp_path,
):
    """历史窗口第一天不能被误当成整个股票池的最旧截止日。"""
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    days = [date(2026, 6, 5), date(2026, 7, 20)]
    panel = pd.concat([_daily(day, 100.0 + idx) for idx, day in enumerate(days)])
    for day in days:
        kline_snapshot._daily_cache_path(day.strftime("%Y%m%d")).touch()

    freshness = kline_snapshot.daily_panel_freshness(
        panel,
        symbols=["600519"],
        expected_cutoff=days[-1],
        required_rows=2,
    )

    assert freshness.data_cutoff == days[-1]
    assert freshness.min_cutoff == days[-1]
    assert freshness.current_count == 1
    assert freshness.is_stale is False


def test_daily_panel_freshness_does_not_treat_suspension_as_market_lag(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    old_day = date(2026, 7, 17)
    latest_day = date(2026, 7, 20)
    active = _daily(old_day, 100.0)
    active = pd.concat([active, _daily(latest_day, 101.0)])
    suspended = _daily(old_day, 20.0).assign(symbol="000001")
    panel = pd.concat([active, suspended], ignore_index=True)
    for day in (old_day, latest_day):
        kline_snapshot._daily_cache_path(day.strftime("%Y%m%d")).touch()

    freshness = kline_snapshot.daily_panel_freshness(
        panel,
        symbols=["600519", "000001"],
        expected_cutoff=latest_day,
        required_rows=2,
    )

    assert freshness.data_cutoff == latest_day
    assert freshness.min_cutoff == latest_day
    assert freshness.current_count == 1
    assert freshness.history_incomplete_count == 1
    assert freshness.is_stale is False

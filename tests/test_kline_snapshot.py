"""全市场序列使用原始日线与因子；派生快照沿用同一复权基准。"""
from __future__ import annotations

import os
from datetime import date, datetime

import pandas as pd
import pytest

from kan.data import kline_snapshot, ohlc_history
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, OperationState, operation


def _daily(d: date, close: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol": "600519", "date": d, "open": close - 1,
        "high": close + 1, "low": close - 2, "close": close,
        "volume": 1000, "amount": 10000,
    }])


@pytest.fixture
def raw_facts(monkeypatch, tmp_path):
    """拆股跨日原始数据；所有读取和写入都在本轮临时目录。"""
    days = [date(2026, 9, day) for day in range(1, 5)]
    frames = {}
    for day, close, factor in zip(days, [9.5, 10.0, 5.1, 5.2], [1.0, 1.0, 2.0, 2.0], strict=True):
        td = day.strftime("%Y%m%d")
        frame = pd.DataFrame([
            {"ts_code": "600519.SH", "trade_date": td, "open": close - .1,
             "high": close + .2, "low": close - .2, "close": close,
             "pre_close": close, "pct_chg": 0.0, "vol": 1000., "amount": 10000., "adj_factor": factor},
            {"ts_code": "000001.SZ", "trade_date": td, "open": 20.,
             "high": 21., "low": 19., "close": 20.,
             "pre_close": 20., "pct_chg": 0.0, "vol": 2000., "amount": 20000., "adj_factor": 1.},
        ])
        frames[td] = frame
        frame.to_parquet(tmp_path / f"ohlc_facts_v1_{td}.parquet", index=False)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ohlc_history, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: days)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: days[-1])
    monkeypatch.setattr(ohlc_history, "_query", lambda *_args: pytest.fail("测试不得访问外部数据源"))
    return tmp_path, days, frames


def test_split_adjusted_panel_and_snapshot_use_same_basis(raw_facts):
    path, days, _frames = raw_facts
    # 旧版派生值不得因日期相同而直接用于新计算，资产本身仍保留。
    old_cache = path / "kline_snapshot_v2_20260904_3.parquet"
    pd.DataFrame([{"symbol": "600519", "close": 999., "pos_3": 0.}]).to_parquet(old_cache)

    panel = kline_snapshot.fetch_recent_daily_bars(4, end_date="20260904", symbols=["600519"])
    assert list(panel.date) == days
    assert list(panel.close) == pytest.approx([4.75, 5., 5.1, 5.2])
    assert set(panel.symbol) == {"600519"}
    assert panel.attrs["price_basis"] == "raw_adj_factor_v1"
    assert panel.attrs["price_basis_date"] == "2026-09-04"

    snapshot = kline_snapshot.fetch_kline_snapshot("20260904", symbols=["600519"], periods=[3])
    row = snapshot.iloc[0]
    assert row.close == pytest.approx(5.2)
    assert row.pos_3 == pytest.approx(60.)
    assert row.gain_3 == pytest.approx(9.47)
    assert row.up_days == 4
    assert old_cache.exists()


def test_same_raw_facts_rebase_to_requested_cutoff(raw_facts):
    _path, days, _frames = raw_facts
    earlier = kline_snapshot.fetch_recent_daily_bars(2, end_date="20260902", symbols=["600519"])
    later = kline_snapshot.fetch_recent_daily_bars(4, end_date="20260904", symbols=["600519"])

    assert list(earlier.date) == days[:2]
    assert list(earlier.close) == pytest.approx([9.5, 10.])
    assert list(later.close.iloc[:2]) == pytest.approx(earlier.close * .5)
    assert earlier.attrs["price_basis_date"] == "2026-09-02"
    assert later.attrs["price_basis_date"] == "2026-09-04"


def test_cache_reuse_and_explicit_refresh(raw_facts, monkeypatch):
    path, days, frames = raw_facts
    initial = kline_snapshot.fetch_kline_snapshot("20260904", symbols=["600519"], periods=[3])
    # 缓存命中不需要重新获取原始日线。
    for day in days:
        (path / f"ohlc_facts_v1_{day:%Y%m%d}.parquet").unlink()
    cached = kline_snapshot.fetch_kline_snapshot("20260904", symbols=["600519"], periods=[3])
    pd.testing.assert_frame_equal(initial, cached)

    calls = []
    def query(api, params, fields):
        calls.append((api, params["trade_date"]))
        frame = frames[params["trade_date"]].copy()
        if params["trade_date"] == "20260904":
            frame.loc[0, ["open", "high", "low", "close"]] += .2
        # 外部全市场接口的真实完整性门槛仍执行，不用测试开关绕过。
        extra = pd.DataFrame([frame.iloc[1].to_dict()] * 2998)
        extra["ts_code"] = [f"{700000 + i}.SH" for i in range(2998)]
        return pd.concat([frame, extra], ignore_index=True)[fields.split(",")]
    monkeypatch.setattr(ohlc_history, "_query", query)
    refreshed = kline_snapshot.fetch_kline_snapshot(
        "20260904", symbols=["600519"], periods=[3], force=True,
    )
    assert refreshed.iloc[0].close == pytest.approx(5.4)
    assert set(calls) == {(api, f"{day:%Y%m%d}") for day in days for api in ("daily", "adj_factor")}


def test_recent_panel_progress_and_source_failure(raw_facts, monkeypatch):
    path, days, _frames = raw_facts
    progress = []
    reporter = CollectingReporter()
    panel = kline_snapshot.fetch_recent_daily_bars(
        4, end_date="20260904", symbols=["600519"], max_workers=2,
        reporter=reporter,
        on_progress=lambda done, total, day, rows: progress.append((done, total, day, rows)),
    )
    assert len(panel) == 4
    assert {event[2] for event in progress} == set(days)
    assert progress[-1][:2] == (4, 4)
    assert reporter.events[-1].state is OperationState.SUCCEEDED

    # 原始事实缺失时，不回退到同日的旧 qfq 截面；明确传播真实数据源错误。
    (path / "ohlc_facts_v1_20260903.parquet").unlink()
    _daily(days[2], 999.).to_parquet(kline_snapshot._daily_cache_path("20260903"))
    def fail(*_args):
        raise kline_snapshot.TushareDataContractError("daily", "incomplete source")
    monkeypatch.setattr(ohlc_history, "_query", fail)
    failed = CollectingReporter()
    with pytest.raises(kline_snapshot.TushareDataContractError, match="incomplete source"):
        kline_snapshot.fetch_recent_daily_bars(4, end_date="20260904", reporter=failed)
    assert failed.events[-1].state is OperationState.FAILED


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
    monkeypatch.setattr(ohlc_history, "DATA_DIR", tmp_path)
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
        path = tmp_path / f"ohlc_facts_v1_{day:%Y%m%d}.parquet"
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
    monkeypatch.setattr(ohlc_history, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    days = [date(2026, 6, 5), date(2026, 7, 20)]
    panel = pd.concat([_daily(day, 100.0 + idx) for idx, day in enumerate(days)])
    for day in days:
        (tmp_path / f"ohlc_facts_v1_{day:%Y%m%d}.parquet").touch()

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
    monkeypatch.setattr(ohlc_history, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    old_day = date(2026, 7, 17)
    latest_day = date(2026, 7, 20)
    active = _daily(old_day, 100.0)
    active = pd.concat([active, _daily(latest_day, 101.0)])
    suspended = _daily(old_day, 20.0).assign(symbol="000001")
    panel = pd.concat([active, suspended], ignore_index=True)
    for day in (old_day, latest_day):
        (tmp_path / f"ohlc_facts_v1_{day:%Y%m%d}.parquet").touch()

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

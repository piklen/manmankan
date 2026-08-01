"""fetcher 测试 · 缓存逻辑 + AKShare mock + 多源 fallback (chain 架构)。

历史背景 fallback 走 KlineSourceChain · `_fetch_<source>` SOT 在各 source module:
- `_fetch_tushare`  在 `kan.data.tushare`
- `_fetch_<其余 4>` 在 `kan.data.sources`

测试 monkeypatch 路径同步迁移 · fetcher namespace 不再持有 `_fetch_*` 别名。
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from kan.core import trading_calendar
from kan.data import fetcher, sources, tushare
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.storage import paths


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    return tmp_path


def _no_data() -> ProviderFetchResult[pd.DataFrame]:
    return ProviderFetchResult.failed(FetchFailure(FetchFailureKind.EMPTY, "no data"))


@dataclass
class _DetailedSource:
    name: str
    handler: object
    priority: int = 10
    capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(
            max_concurrency=8,
            initial_concurrency=8,
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


def _install_chain(monkeypatch, sources_list: list[_DetailedSource]) -> None:
    monkeypatch.setattr(
        fetcher,
        "default_kline_chain",
        lambda: SimpleNamespace(sources=sources_list),
    )


@pytest.fixture
def force_eastmoney_path(monkeypatch):
    """绕过 tushare / baostock / 新浪 · 让 chain 落到东财 (priority 30 race · sina None 后只剩 eastmoney)。

    chain 架构 monkeypatch 路径:
    - `_fetch_tushare` SOT 在 `kan.data.tushare` (TushareKlineSource.fetch 调它)
    - `_fetch_baostock/_sina/_tencent` SOT 在 `kan.data.sources` (对应 class 调它)

    sina + eastmoney 同 priority 30 自动并发 race · 把 sina mock 成 None ·
    eastmoney 凭 patched akshare.stock_zh_a_hist 返 fake_akshare_df 中标。
    tushare/baostock 都 mock None 防止用户本地 token / baostock 装好时短路。
    """
    monkeypatch.setattr(tushare, "_fetch_tushare_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(sources, "_fetch_baostock_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(sources, "_fetch_sina_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(sources, "_fetch_tencent_detailed", lambda *a, **kw: _no_data())


@pytest.fixture
def fake_akshare_df():
    """模拟 AKShare 返回的 DataFrame"""
    return pd.DataFrame({
        "日期": ["2026-04-28", "2026-04-29", "2026-04-30"],
        "开盘": [100.0, 101.0, 102.0],
        "收盘": [101.0, 102.0, 103.0],
        "最高": [101.5, 102.5, 103.5],
        "最低": [99.5, 100.5, 101.5],
        "成交量": [10000, 11000, 12000],
        "成交额": [1e6, 1.1e6, 1.2e6],
        "其他列": ["x", "y", "z"],
    })


def test_fetch_kline_normalizes_columns(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        df = fetcher.fetch_kline("600519", days=180, force=True)

    assert set(df.columns) == {
        "date", "open", "high", "low", "close",
        "volume", "amount", "_source",
    }
    assert len(df) == 3
    assert (df["_source"] == "eastmoney").all()  # force_eastmoney_path fixture 走东财路径


def test_fetch_kline_writes_cache(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", force=True)
    assert (temp_data_dir / "600519.parquet").exists()


def test_fetch_kline_invalid_symbol_raises(temp_data_dir, force_eastmoney_path):
    empty_df = pd.DataFrame()
    with (
        patch("akshare.stock_zh_a_hist", return_value=empty_df),
        pytest.raises(ValueError, match="无效股票代码或无数据"),
    ):
        fetcher.fetch_kline("999999", force=True)


def test_is_fresh_no_cache(temp_data_dir):
    assert not fetcher.is_fresh("600519")


def test_is_fresh_today_cache(temp_data_dir, force_eastmoney_path, fake_akshare_df, monkeypatch):
    """背景: is_fresh 改为对比 K 线 date ≥ latest_trade_date()。

    fake_akshare_df 最后一行 = 2026-04-30 · mock latest_trade_date 同日返回，
    避免触发 akshare 网络请求 + 让测试与系统时间解耦。
    """
    monkeypatch.setattr(
        trading_calendar, "latest_trade_date",
        lambda *a, **kw: date(2026, 4, 30),
    )
    trading_calendar.clear_memo()

    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", days=30, force=True)
    assert fetcher.is_fresh("600519")
    assert not fetcher.is_fresh("600519", min_rows=360)


def test_short_new_listing_cache_is_current_after_full_period_request(
    temp_data_dir, force_eastmoney_path, fake_akshare_df, monkeypatch
):
    monkeypatch.setattr(
        trading_calendar,
        "latest_trade_date",
        lambda *a, **kw: date(2026, 4, 30),
    )
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        frame = fetcher.fetch_kline("600519", days=180, force=True)

    assert len(frame) == 3
    assert "_requested_days" not in frame.columns
    assert fetcher.is_fresh("600519", min_rows=180)


def test_is_fresh_rejects_future_cutoff_so_fetch_can_repair_cache(
    temp_data_dir, monkeypatch
):
    cache = temp_data_dir / "600519.parquet"
    pd.DataFrame({"date": [date(2026, 5, 24)]}).to_parquet(cache)
    monkeypatch.setattr(
        trading_calendar,
        "latest_trade_date",
        lambda *a, **kw: date(2026, 5, 23),
    )

    assert fetcher.is_fresh("600519") is False


def test_is_fresh_yesterday_cache(temp_data_dir):
    cache = temp_data_dir / "600519.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(cache)
    yesterday = (datetime.now() - timedelta(days=1)).timestamp()
    import os
    os.utime(cache, (yesterday, yesterday))
    assert not fetcher.is_fresh("600519")


def test_get_cached_returns_none_when_missing(temp_data_dir):
    assert fetcher.get_cached("600519") is None


def test_get_cached_returns_dataframe(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", force=True)
    df = fetcher.get_cached("600519")
    assert df is not None
    assert len(df) == 3


def test_has_cache(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    assert not fetcher.has_cache("600519")
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", force=True)
    assert fetcher.has_cache("600519")


def test_fetch_batch_continues_on_error(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    """批量拉取中某只失败不应中断其他股票"""
    def side_effect(symbol, **kwargs):
        if symbol == "FAIL":
            return pd.DataFrame()
        return fake_akshare_df

    with patch("akshare.stock_zh_a_hist", side_effect=side_effect), \
         patch("time.sleep"):
        results, errors = fetcher.fetch_batch(["600519", "FAIL", "000858"], force=True)

    assert "600519" in results
    assert "000858" in results
    assert "FAIL" in errors


def test_fetch_batch_fresh_cache_does_not_construct_scheduler(
    temp_data_dir, raw_kline_df, monkeypatch,
):
    cache = temp_data_dir / "600519.parquet"
    cached = fetcher._normalize_kline(raw_kline_df, source="cache", symbol="600519")
    cached.to_parquet(cache)
    monkeypatch.setattr(
        trading_calendar,
        "latest_trade_date",
        lambda *a, **kw: cached["date"].iloc[-1],
    )

    class UnexpectedScheduler:
        def __init__(self, *args, **kwargs):
            raise AssertionError("fresh cache must not construct scheduler")

    monkeypatch.setattr(fetcher, "KlineScheduler", UnexpectedScheduler)
    results, errors = fetcher.fetch_batch(["600519"], days=1)

    assert errors == {}
    assert list(results) == ["600519"]


def test_fetch_kline_scheduler_success_stamps_source_and_metadata(
    temp_data_dir, raw_kline_df, monkeypatch,
):
    import pyarrow.parquet as pq

    _install_chain(
        monkeypatch,
        [_DetailedSource("detailed", lambda symbol, start: ProviderFetchResult.succeeded(raw_kline_df))],
    )

    frame = fetcher.fetch_kline("600519", days=180, force=True)

    cache = temp_data_dir / "600519.parquet"
    metadata = pq.read_metadata(cache).metadata or {}
    assert (frame["_source"] == "detailed").all()
    assert metadata[b"kan.requested_days"] == b"180"


def test_fetch_kline_all_sources_failed_preserves_error_message(temp_data_dir, monkeypatch):
    _install_chain(monkeypatch, [_DetailedSource("failed", lambda symbol, start: _no_data())])

    with pytest.raises(ValueError, match=r"^无效股票代码或无数据: 600519$"):
        fetcher.fetch_kline("600519", force=True)


def test_fetch_batch_mixed_results_continue_and_callbacks_run_once_in_caller_thread(
    temp_data_dir, raw_kline_df, monkeypatch,
):
    import kan.storage.paths as storage_paths

    cached = fetcher._normalize_kline(raw_kline_df, source="cache", symbol="600519")
    cached.to_parquet(temp_data_dir / "600519.parquet")
    monkeypatch.setattr(
        trading_calendar,
        "latest_trade_date",
        lambda *a, **kw: cached["date"].iloc[-1],
    )

    def handler(symbol: str, start: str) -> ProviderFetchResult[pd.DataFrame]:
        del start
        if symbol == "000002":
            return _no_data()
        return ProviderFetchResult.succeeded(raw_kline_df.copy())

    _install_chain(monkeypatch, [_DetailedSource("mixed", handler)])
    original_normalize = fetcher._normalize_kline
    original_write = storage_paths.atomic_write_parquet

    def normalize(frame, source="unknown", symbol=None):
        if symbol == "000003":
            raise ValueError("normalize failed")
        return original_normalize(frame, source=source, symbol=symbol)

    def write(frame, path, **kwargs):
        if path.name == "000004.parquet":
            raise OSError("write failed")
        return original_write(frame, path, **kwargs)

    monkeypatch.setattr(fetcher, "_normalize_kline", normalize)
    monkeypatch.setattr(storage_paths, "atomic_write_parquet", write)
    caller_thread = threading.get_ident()
    callbacks: list[tuple[str, bool, int, bool]] = []

    def on_progress(symbol: str, ok: bool, error: str | None) -> None:
        del error
        callbacks.append(
            (symbol, ok, threading.get_ident(), (temp_data_dir / f"{symbol}.parquet").exists())
        )

    symbols = ["600519", "000001", "000002", "000003", "000004"]
    results, errors = fetcher.fetch_batch(symbols, days=1, on_progress=on_progress)

    assert set(results) == {"600519", "000001"}
    assert set(errors) == {"000002", "000003", "000004"}
    assert [item[0] for item in callbacks].count("600519") == 1
    assert len(callbacks) == len(symbols)
    assert all(item[2] == caller_thread for item in callbacks)
    assert all(item[3] for item in callbacks if item[1])


def test_fetcher_uses_dynamic_source_snapshot_and_keeps_first_duplicate_name(
    temp_data_dir, raw_kline_df, monkeypatch,
):
    snapshots = [
        SimpleNamespace(
            sources=[
                _DetailedSource("same", lambda symbol, start: ProviderFetchResult.succeeded(raw_kline_df.copy())),
                _DetailedSource("same", lambda symbol, start: (_ for _ in ()).throw(AssertionError())),
            ]
        ),
        SimpleNamespace(
            sources=[
                _DetailedSource("second", lambda symbol, start: ProviderFetchResult.succeeded(raw_kline_df.copy()))
            ]
        ),
    ]
    monkeypatch.setattr(fetcher, "default_kline_chain", lambda: snapshots.pop(0))

    first = fetcher.fetch_kline("600519", force=True)
    second = fetcher.fetch_kline("600519", force=True)

    assert (first["_source"] == "same").all()
    assert (second["_source"] == "second").all()


def test_fetch_batch_keyboard_interrupt_is_reraised_and_scheduler_closed(
    temp_data_dir, monkeypatch,
):
    closed = False

    class InterruptingScheduler:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            nonlocal closed
            del exc_type, exc, traceback
            closed = True

        def fetch_many(self, symbols, start):
            del symbols, start
            raise KeyboardInterrupt

    monkeypatch.setattr(fetcher, "KlineScheduler", InterruptingScheduler)
    monkeypatch.setattr(fetcher, "default_kline_chain", lambda: SimpleNamespace(sources=[]))

    with pytest.raises(KeyboardInterrupt):
        fetcher.fetch_batch(["600519"], force=True)
    assert closed


def test_fetch_batch_duplicate_symbol_emits_two_callbacks(temp_data_dir, raw_kline_df, monkeypatch):
    _install_chain(
        monkeypatch,
        [_DetailedSource("duplicate", lambda symbol, start: ProviderFetchResult.succeeded(raw_kline_df.copy()))],
    )
    callbacks: list[str] = []
    states: list[fetcher.FetchProgress] = []

    results, errors = fetcher.fetch_batch(
        ["600519", "600519"],
        force=True,
        on_progress=lambda symbol, ok, error: callbacks.append(symbol),
        on_progress_state=states.append,
    )

    assert errors == {}
    assert list(results) == ["600519"]
    assert callbacks == ["600519", "600519"]
    assert [state.symbol for state in states] == ["600519", "600519"]


def test_fetch_batch_market_wide_materializes_symbol_caches_concurrently(
    temp_data_dir, monkeypatch,
):
    """全市场路径把按日 panel 正确拆回逐股缓存并写入请求周期元数据。"""
    import pyarrow.parquet as pq

    days = [date(2026, 7, 30), date(2026, 7, 31)]
    panel = pd.DataFrame([
        {
            "symbol": symbol,
            "date": trade_day,
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 1000,
            "amount": 10000,
        }
        for symbol, close in (("600519", 100.0), ("920000", 20.0))
        for trade_day in days
    ])
    captured: dict[str, object] = {}

    def fake_recent(days_count: int, **kwargs):
        captured.update(days=days_count, **kwargs)
        return panel

    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        fake_recent,
    )
    caller = threading.get_ident()
    callbacks: list[tuple[str, bool, int]] = []
    from kan.infra.lifecycle import CollectingReporter, operation

    reporter = CollectingReporter()

    with operation("test market batch", reporter=reporter) as lifecycle:
        results, errors = fetcher.fetch_batch(
            ["600519", "920000"],
            days=2,
            force=True,
            max_workers=4,
            market_wide=True,
            lifecycle=lifecycle,
            on_progress=lambda symbol, ok, _error: callbacks.append(
                (symbol, ok, threading.get_ident())
            ),
        )

    assert errors == {}
    assert set(results) == {"600519", "920000"}
    assert captured["days"] == 2
    assert captured["symbols"] == ["600519", "920000"]
    assert captured["max_workers"] == 4
    assert captured["sort_by_symbol"] is False
    assert all((frame["_source"] == "tushare_market_batch").all() for frame in results.values())
    assert all(thread_id == caller for _symbol, _ok, thread_id in callbacks)
    assert {event.message for event in reporter.events} >= {
        "全市场批量拉取",
        "准备写入 2 只股票缓存",
    }
    write_progress = [
        event
        for event in reporter.events
        if event.message == "逐股缓存写入"
    ]
    assert write_progress
    assert (write_progress[-1].completed, write_progress[-1].total) == (2, 2)
    assert write_progress[-1].details["progress_unit"] == "只股票"
    assert write_progress[-1].details["progress_detail"] == (
        "总行情 4 行 · 并发 2"
    )
    for symbol in results:
        metadata = pq.read_metadata(temp_data_dir / f"{symbol}.parquet").metadata or {}
        assert metadata[b"kan.requested_days"] == b"2"


def test_fetch_batch_market_wide_fails_fast_without_serial_scheduler(
    temp_data_dir, monkeypatch,
):
    """批量源整体失败时不能把全市场静默降级到串行 Baostock。"""
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "batch unavailable: https://example.test/api?token=secret-token-123 "
                "/Users/private/data"
            )
        ),
    )

    class UnexpectedScheduler:
        def __init__(self, *args, **kwargs):
            raise AssertionError("全市场批量失败后不应构造逐股 scheduler")

    monkeypatch.setattr(fetcher, "KlineScheduler", UnexpectedScheduler)

    from kan.infra.lifecycle import CollectingReporter, LifecycleKind, operation

    reporter = CollectingReporter()
    with operation("test market batch failure", reporter=reporter) as lifecycle:
        results, errors = fetcher.fetch_batch(
            ["600519", "920000"],
            force=True,
            market_wide=True,
            lifecycle=lifecycle,
        )

    assert results == {}
    assert set(errors) == {"600519", "920000"}
    assert all("已停止耗时的串行降级" in message for message in errors.values())
    assert all("secret-token-123" not in message for message in errors.values())
    assert all("/Users/private" not in message for message in errors.values())
    assert all("token=<redacted>" in message for message in errors.values())
    assert any(event.kind is LifecycleKind.DEGRADED for event in reporter.events)


def test_fetch_batch_market_wide_fresh_cache_is_fast_and_callback_safe(
    temp_data_dir, raw_kline_df, monkeypatch,
):
    """全市场缓存命中不构造批量源，且用户回调失败不影响刷新结果。"""
    cached = fetcher._normalize_kline(raw_kline_df, source="cache", symbol="600519")
    cached.to_parquet(temp_data_dir / "600519.parquet")
    monkeypatch.setattr(
        trading_calendar,
        "latest_trade_date",
        lambda *_args, **_kwargs: cached["date"].iloc[-1],
    )
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("新鲜缓存不应请求批量源")
        ),
    )

    results, errors = fetcher.fetch_batch(
        ["600519"],
        days=1,
        market_wide=True,
        retain_frames=False,
        on_progress=lambda *_args: (_ for _ in ()).throw(RuntimeError("callback")),
    )

    assert errors == {}
    assert list(results) == ["600519"]
    assert results["600519"].empty


def test_fetch_batch_market_wide_can_release_success_frames_after_cache_write(
    temp_data_dir, monkeypatch,
):
    """CLI 只计成功数时，不在内存中再保留全市场历史面板副本。"""
    panel = pd.DataFrame({
        "symbol": ["600519", "920000"],
        "date": [date(2026, 7, 31), date(2026, 7, 31)],
        "open": [100.0, 20.0],
        "high": [101.0, 21.0],
        "low": [99.0, 19.0],
        "close": [100.5, 20.5],
        "volume": [1000.0, 2000.0],
        "amount": [10000.0, 20000.0],
    })
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: panel,
    )

    results, errors = fetcher.fetch_batch(
        ["600519", "920000"],
        days=1,
        force=True,
        market_wide=True,
        retain_frames=False,
    )

    assert errors == {}
    assert set(results) == {"600519", "920000"}
    assert all(frame.empty for frame in results.values())
    assert (temp_data_dir / "600519.parquet").exists()
    assert (temp_data_dir / "920000.parquet").exists()


def test_fetch_batch_market_wide_throttles_cache_write_progress(
    temp_data_dir, monkeypatch,
):
    """全市场逐股写入只发约 100 个进度事件，避免 UI 更新吞掉并发收益。"""
    symbols = [f"{600000 + index:06d}" for index in range(250)]
    panel = pd.DataFrame({
        "symbol": symbols,
        "date": [date(2026, 7, 31)] * len(symbols),
        "open": [10.0] * len(symbols),
        "high": [11.0] * len(symbols),
        "low": [9.0] * len(symbols),
        "close": [10.5] * len(symbols),
        "volume": [1000.0] * len(symbols),
        "amount": [10000.0] * len(symbols),
    })
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: panel,
    )
    monkeypatch.setattr(
        "kan.storage.paths.atomic_write_parquet",
        lambda *_args, **_kwargs: None,
    )
    from kan.infra.lifecycle import CollectingReporter, operation

    reporter = CollectingReporter()
    with operation("test throttled progress", reporter=reporter) as lifecycle:
        results, errors = fetcher.fetch_batch(
            symbols,
            days=1,
            force=True,
            max_workers=32,
            market_wide=True,
            retain_frames=False,
            lifecycle=lifecycle,
        )

    write_progress = [
        event
        for event in reporter.events
        if event.message == "逐股缓存写入"
    ]
    assert errors == {}
    assert len(results) == len(symbols)
    assert 1 < len(write_progress) <= 100
    assert (write_progress[-1].completed, write_progress[-1].total) == (250, 250)


# --- get_cached 补缺失列 ---


def test_get_cached_fills_missing_optional_columns(temp_data_dir):
    """手工/自定义源 parquet 缺 volume/amount · get_cached 补 NaN 防下游 KeyError。"""
    cache = temp_data_dir / "600519.parquet"
    old_df = pd.DataFrame({
        "date": [datetime(2026, 5, 8).date()],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
    })
    old_df.to_parquet(cache, index=False)

    df = fetcher.get_cached("600519")
    assert df is not None
    assert "volume" in df.columns
    assert "amount" in df.columns
    assert pd.isna(df["volume"].iloc[0])
    assert pd.isna(df["amount"].iloc[0])


# --- _normalize_kline ---


class TestNormalizeKline:
    def test_reorders_and_converts_types(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["100.5"], "volume": ["10000"], "amount": ["1e6"],
        })
        df = fetcher._normalize_kline(raw, source="test")
        assert list(df.columns) == fetcher.KLINE_COLUMNS
        assert df["close"].dtype == "float64"
        assert df["date"].iloc[0].__class__.__name__ == "date"
        assert df["_source"].iloc[0] == "test"

    def test_fills_missing_optional_columns(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": [100], "high": [101],
            "low": [99], "close": [100.5],
        })
        df = fetcher._normalize_kline(raw)
        assert "volume" in df.columns
        assert pd.isna(df["volume"].iloc[0])

    def test_raises_on_missing_required_column(self):
        raw = pd.DataFrame({"date": ["2026-05-08"], "open": [100]})
        with pytest.raises(ValueError, match="必需列"):
            fetcher._normalize_kline(raw)

    def test_drops_rows_with_nan_close(self):
        raw = pd.DataFrame({
            "date": ["2026-05-07", "2026-05-08"],
            "open": [100, 101], "high": [101, 102], "low": [99, 100],
            "close": [100.5, None],
        })
        df = fetcher._normalize_kline(raw)
        assert len(df) == 1

    def test_sorts_by_date(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08", "2026-05-06", "2026-05-07"],
            "open": [100, 98, 99], "high": [101, 99, 100], "low": [99, 97, 98],
            "close": [100.5, 98.5, 99.5],
        })
        df = fetcher._normalize_kline(raw)
        dates = list(df["date"])
        assert dates == sorted(dates)

    def test_clean_data_emits_no_warning(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["100.5"], "volume": ["10000"], "amount": ["1e6"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="baostock")
        assert caplog.records == []

    def test_unparseable_value_warns_with_source_and_column(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-07", "2026-05-08"],
            "open": ["100", "101"], "high": ["101", "102"], "low": ["99", "100"],
            "close": ["100.5", "N/A"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            df = fetcher._normalize_kline(raw, source="baostock")
        assert len(caplog.records) == 1
        msg = caplog.records[0].getMessage()
        assert "baostock" in msg
        assert "close" in msg
        assert len(df) == 1  # 垃圾 close 行被 dropna 丢掉

    def test_unparseable_warning_includes_symbol_when_provided(self, caplog):
        """历史背景 warning 末尾带 `[symbol]` · 调试时定位脏数据源头(批量 fetch 时一连串
        warning 没标 symbol → 用户实测无法判断是哪只股票的脏数据)。
        """
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["100.5"], "volume": ["bad"], "amount": ["1e6"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="baostock", symbol="600519")
        assert any("[600519]" in r.getMessage() for r in caplog.records)

    def test_preexisting_nan_does_not_warn(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-07", "2026-05-08"],
            "open": ["100", "101"], "high": ["101", "102"], "low": ["99", "100"],
            "close": ["100.5", "101.5"], "volume": ["10000", None],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="sina")
        assert caplog.records == []

    def test_blank_volume_amount_do_not_warn(self, caplog):
        """baostock 偶发 volume/amount 空串是缺口 · 不应刷成无法解析 warning。"""
        raw = pd.DataFrame({
            "date": ["2026-05-08"],
            "open": ["100"], "high": ["101"], "low": ["99"], "close": ["100.5"],
            "volume": [""], "amount": ["   "],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            df = fetcher._normalize_kline(raw, source="baostock", symbol="002131")
        assert caplog.records == []
        assert pd.isna(df["volume"].iloc[0])
        assert pd.isna(df["amount"].iloc[0])

    def test_multiple_bad_columns_single_warning(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-08"],
            "open": ["bad"], "high": ["101"], "low": ["99"],
            "close": ["100.5"], "volume": ["oops"], "amount": ["1e6"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="baostock")
        assert len(caplog.records) == 1
        msg = caplog.records[0].getMessage()
        assert "open×1" in msg
        assert "volume×1" in msg

    @pytest.mark.parametrize("source", ["sina", "eastmoney", "tencent"])
    def test_warning_carries_source_name(self, caplog, source):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["junk"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source=source)
        assert len(caplog.records) == 1
        assert source in caplog.records[0].getMessage()


# --- _fetch_baostock mock ---


def test_fetch_baostock_returns_dataframe(temp_data_dir):
    mock_rs = MagicMock()
    mock_rs.error_code = "0"
    mock_rs.next = MagicMock(side_effect=[True, True, False])
    mock_rs.get_row_data = MagicMock(side_effect=[
        ["2026-05-07", "100", "101", "99", "100.5", "10000", "1000000"],
        ["2026-05-08", "101", "102", "100", "101.5", "11000", "1100000"],
    ])

    login = type("LoginResult", (), {"error_code": "0"})()
    with patch("baostock.login", return_value=login), \
         patch("baostock.query_history_k_data_plus", return_value=mock_rs):
        sources._bs_logged_in = False
        df = sources._fetch_baostock("600519", "20260501")

    assert df is not None
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]


def test_fetch_baostock_returns_none_on_error(temp_data_dir):
    mock_rs = MagicMock()
    mock_rs.error_code = "1"
    mock_rs.error_msg = "error"

    login = type("LoginResult", (), {"error_code": "0"})()
    with patch("baostock.login", return_value=login), \
         patch("baostock.query_history_k_data_plus", return_value=mock_rs):
        sources._bs_logged_in = False
        df = sources._fetch_baostock("999999", "20260501")

    assert df is None


# --- 熔断器集成 ---


def test_circuit_skips_breaker_down_source(temp_data_dir, raw_kline_df, isolated_breaker, monkeypatch):
    """breaker 标记 baostock down → chain 跳过 BaostockKlineSource → 走 akshare race 档.

    背景: BaostockKlineSource.is_available() 看熔断器 · down 时返 False · chain skip。
    """
    monkeypatch.setattr(tushare, "_fetch_tushare_detailed", lambda *a, **kw: _no_data())
    isolated_breaker.record("baostock", ok=False)
    monkeypatch.setattr(sources, "_fetch_eastmoney_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(
        sources,
        "_fetch_sina_detailed",
        lambda *a, **kw: ProviderFetchResult.succeeded(raw_kline_df),
    )

    df = fetcher.fetch_kline("600519", force=True)
    assert (df["_source"] == "sina").all()


def test_circuit_records_down_on_source_exception(isolated_breaker):
    """源抛异常 → 被记 down."""
    with patch("akshare.stock_zh_a_hist", side_effect=Exception("timeout")):
        result = sources._fetch_eastmoney("600519", "20260501")
    assert result is None
    assert isolated_breaker.is_down("eastmoney")


def test_circuit_empty_result_not_recorded_down(isolated_breaker):
    """源返回空数据（无效代码/无数据）≠ 源挂 · 不记 down."""
    with patch("akshare.stock_zh_a_hist", return_value=pd.DataFrame()):
        result = sources._fetch_eastmoney("999999", "20260501")
    assert result is None
    assert not isolated_breaker.is_down("eastmoney")


# ── source stamping · _source column ───────────────────────────────────


@pytest.fixture
def raw_kline_df():
    """fetch_xxx 返回的 raw DataFrame (英文列 · normalize 前形态)."""
    return pd.DataFrame({
        "date": ["2026-04-28", "2026-04-29", "2026-04-30"],
        "open": [100.0, 101.0, 102.0],
        "high": [101.5, 102.5, 103.5],
        "low": [99.5, 100.5, 101.5],
        "close": [101.0, 102.0, 103.0],
        "volume": [10000, 11000, 12000],
        "amount": [1e6, 1.1e6, 1.2e6],
    })


@pytest.mark.parametrize("source,mock_target", [
    ("baostock", "_fetch_baostock_detailed"),
    ("sina", "_fetch_sina_detailed"),
    ("eastmoney", "_fetch_eastmoney_detailed"),
    ("tencent", "_fetch_tencent_detailed"),
])
def test_fetch_kline_stamps_source(temp_data_dir, raw_kline_df, source, mock_target, monkeypatch):
    """各源 fallback 标记正确 source · 其它源全 mock None 让目标源生效.

    chain monkeypatch 路径:
    - `_fetch_tushare` 在 `kan.data.tushare` namespace
    - `_fetch_baostock / _sina / _eastmoney / _tencent` 在 `kan.data.sources` namespace

    sina + eastmoney 同 priority 30 并发 race · 测试时其中之一 mock None ·
    另一个 mock raw_df 让结果确定 (不受 race 顺序影响)。
    """
    # 全 mock None · 再单独 mock 目标源为 raw_df (顺序覆盖)
    monkeypatch.setattr(tushare, "_fetch_tushare_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(sources, "_fetch_baostock_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(sources, "_fetch_sina_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(sources, "_fetch_eastmoney_detailed", lambda *a, **kw: _no_data())
    monkeypatch.setattr(sources, "_fetch_tencent_detailed", lambda *a, **kw: _no_data())

    monkeypatch.setattr(
        sources,
        mock_target,
        lambda *a, **kw: ProviderFetchResult.succeeded(raw_kline_df),
    )

    df = fetcher.fetch_kline("600519", force=True)
    assert (df["_source"] == source).all()


def test_read_cutoff_only_reads_date_no_rewrite(temp_data_dir):
    """_read_cutoff_from_parquet 只读 date 列 · 不改写文件(mtime 不变)。"""
    cache = temp_data_dir / "600519.parquet"
    old_df = pd.DataFrame({
        "date": [datetime(2026, 5, 7).date(), datetime(2026, 5, 8).date()],
        "open": [100.0, 101.0], "high": [101.0, 102.0],
        "low": [99.0, 100.0], "close": [100.5, 101.5],
    })
    old_df.to_parquet(cache, index=False)

    mtime_before = cache.stat().st_mtime
    last_date = fetcher._read_cutoff_from_parquet(cache)
    mtime_after = cache.stat().st_mtime

    assert last_date == datetime(2026, 5, 8).date()
    assert mtime_before == mtime_after


class TestTushareProDispatch:
    """背景: 配 token 时 tushare 顶替 baostock 作主路径；未配 token 行为不变"""

    @pytest.fixture
    def isolated_env(self, tmp_path, monkeypatch):
        from kan.infra import circuit_breaker
        from kan.storage import config
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(paths, "CIRCUIT_PATH", tmp_path / "circuit.json")
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
        monkeypatch.setattr(circuit_breaker, "_default", None)
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def test_no_token_path_unchanged(self, isolated_env, monkeypatch, fake_akshare_df):
        """未配 token → TushareKlineSource.is_available()=False → chain 跳过 · 走 akshare 档.

        背景: 未配 token 时 chain 直接 skip TushareKlineSource (不调 fetch) ·
        与 历史背景不同 (旧版本 fetch 内部检查 token · 调用一次返 None)。
        新行为更高效 · 不浪费一次 fetch 调用。
        """
        # 把 _fetch_tushare 设 spy 没必要 (chain 不会调它 · is_available 已 False)
        # 仅保留作为 safeguard · 确认 chain 真的没调用
        called = {"tushare": False}
        def spy_tushare(*a, **kw):
            called["tushare"] = True
            return _no_data()
        monkeypatch.setattr(tushare, "_fetch_tushare_detailed", spy_tushare)
        monkeypatch.setattr(sources, "_fetch_baostock_detailed", lambda *a, **kw: _no_data())
        monkeypatch.setattr(sources, "_fetch_sina_detailed", lambda *a, **kw: _no_data())
        with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
            df = fetcher.fetch_kline("600519", force=True)
        # 背景: 未配 token 时 chain skip TushareKlineSource · _fetch_tushare 不被调
        assert not called["tushare"]
        assert not df.empty

    def test_with_token_uses_tushare_first(self, isolated_env, monkeypatch):
        """配 token → TushareKlineSource priority=10 顶档命中 → chain 不再走 baostock"""
        from kan.storage import config
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        sample = pd.DataFrame({
            "date": [date(2026, 4, 28), date(2026, 4, 29)],
            "open": [100.0, 101.0],
            "high": [101.5, 102.5],
            "low": [99.5, 100.5],
            "close": [101.0, 102.0],
            "volume": [10000, 11000],
            "amount": [1010000.0, 1122000.0],
        })

        baostock_called = {"hit": False}
        def fake_baostock(*a, **kw):
            baostock_called["hit"] = True
            return _no_data()

        monkeypatch.setattr(
            tushare,
            "_fetch_tushare_detailed",
            lambda *a, **kw: ProviderFetchResult.succeeded(sample.copy()),
        )
        monkeypatch.setattr(sources, "_fetch_baostock_detailed", fake_baostock)

        df = fetcher.fetch_kline("600519", force=True)
        assert not baostock_called["hit"]
        assert (df["_source"] == "tushare").all()

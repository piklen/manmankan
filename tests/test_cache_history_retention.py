"""短窗口更新不得删除已有有效历史，也不得混接两套复权价格。"""

from datetime import date, datetime

import pandas as pd
import pyarrow.parquet as pq
import pytest

from kan.data import fetcher, ohlc_history
from kan.data.scheduler import KlineFetchResult
from kan.storage.paths import atomic_write_parquet


def bars(days, prices, basis):
    frame = pd.DataFrame({"date": days, "open": prices, "high": prices, "low": prices,
                          "close": prices, "volume": 100, "amount": 1000, "_source": "tushare"})
    frame.attrs.update(price_basis="raw_adj_factor_v1", price_basis_date=basis)
    return frame


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("old_basis", ["raw_adj_factor_v1", "unverified_factor_conflict", None])
def test_single_and_scheduler_batch_expand_request_and_reject_lost_valid_days(tmp_path, monkeypatch, batch, old_basis):
    days = pd.bdate_range("2026-01-05", periods=7).date.tolist()
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetcher, "_ensure_data_dir", lambda: None)
    monkeypatch.setattr(fetcher, "_ensure_no_proxy", lambda: None)
    monkeypatch.setattr(fetcher, "_kline_source_snapshot", lambda: [])

    class FixedNow(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 1, 20)

    monkeypatch.setattr(fetcher, "datetime", FixedNow)
    cache = tmp_path / "600001.parquet"
    old = bars(days[:-1], [100, 102, 104, 106, 108, 110], str(days[-2]))
    if old_basis is None:
        old.attrs.clear()
        atomic_write_parquet(old, cache)
    else:
        old.attrs["price_basis"] = old_basis
        atomic_write_parquet(old, cache, metadata=fetcher._price_basis_metadata(old))
    if old_basis != "raw_adj_factor_v1":
        assert fetcher.get_cached("600001") is None
    response = bars(days, [50, 51, 52, 53, 54, 55, 56], str(days[-1]))
    starts = []

    class Scheduler:
        concurrency = 1
        active_calls = 0

        def __init__(self, *args, on_result=None, **kwargs):
            self.on_result = on_result

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def fetch(self, symbol, start):
            starts.append(start)
            return KlineFetchResult(symbol, response.copy(), "tushare", ())

        def fetch_many(self, symbols, start):
            for symbol in symbols:
                self.on_result(self.fetch(symbol, start))

    monkeypatch.setattr(fetcher, "KlineScheduler", Scheduler)

    def run():
        if batch:
            results, errors = fetcher.fetch_batch(["600001"], days=2, force=True)
            if errors:
                raise ValueError(errors["600001"])
            return results["600001"]
        return fetcher.fetch_kline("600001", days=2, force=True)

    original = cache.read_bytes()
    full = response.copy()
    response = full.tail(2)
    with pytest.raises(ValueError, match="为保留较长历史，未覆盖原缓存"):
        run()
    assert cache.read_bytes() == original
    response = full
    result = run()
    assert starts == [days[0].strftime("%Y%m%d")] * 2
    assert result.close.tolist() == [50, 51, 52, 53, 54, 55, 56]
    assert fetcher.get_cached("600001").attrs["price_basis_date"] == str(days[-1])
    before = cache.read_bytes()
    full = response.copy()
    for invalid in (full.tail(2), full.drop(index=3), full.assign(high=[50, 51, 52, 0, 54, 55, 56])):
        response = invalid
        with pytest.raises(ValueError, match="为保留较长历史，未覆盖原缓存"):
            run()
        assert cache.read_bytes() == before


@pytest.mark.parametrize("old_basis", ["raw_adj_factor_v1", "unverified_factor_conflict"])
def test_market_short_refresh_recomputes_whole_history_on_new_basis_and_keeps_partial_failures(tmp_path, monkeypatch, old_basis):
    days = pd.bdate_range("2026-09-01", periods=5).date.tolist()
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ohlc_history, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: set(days))
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: days[-1])
    for day, close, factor in zip(days, [9., 10., 5., 5.2, 2.7], [1., 1., 2., 2., 4.], strict=True):
        frame = pd.DataFrame({"ts_code": ["600001.SH"], "trade_date": [day.strftime("%Y%m%d")],
                      "open": [close], "high": [close], "low": [close], "close": [close],
                      "vol": [100], "amount": [1000], "adj_factor": [factor]})
        frame.attrs["factor_scope"] = "trade_date"
        frame.to_parquet(tmp_path / f"ohlc_facts_v1_{day:%Y%m%d}.parquet", index=False)
    monkeypatch.setattr(ohlc_history, "_query", lambda *args: pytest.fail("已有原始事实不应联网"))
    assert not fetcher.fetch_batch(["600001"], days=4, market_wide=True, as_of=days[-2])[1]
    cache = tmp_path / "600001.parquet"
    old = pd.read_parquet(cache)
    old.attrs["price_basis"] = old_basis
    atomic_write_parquet(old, cache, metadata=fetcher._price_basis_metadata(old))
    if old_basis != "raw_adj_factor_v1":
        assert fetcher.get_cached("600001") is None
    results, errors = fetcher.fetch_batch(["600001"], days=2, market_wide=True, as_of=days[-1])
    assert not errors
    assert results["600001"].close.tolist() == [2.25, 2.5, 2.5, 2.6, 2.7]
    assert pq.read_metadata(cache).metadata[b"kan.requested_days"] == b"5"
    assert fetcher.get_cached("600001").attrs["price_basis_date"] == str(days[-1])
    before = cache.read_bytes()
    full = results["600001"]
    broken = full.drop(index=1).assign(symbol="600001")
    new_listing = full.tail(2).assign(symbol="000002")
    panel = pd.concat([broken, new_listing], ignore_index=True)
    requested = []

    def partial(count, **kwargs):
        requested.append(count)
        return panel

    monkeypatch.setattr("kan.data.kline_snapshot.fetch_recent_daily_bars", partial)
    results, errors = fetcher.fetch_batch(["600001", "000002"], days=2, force=True, market_wide=True, as_of=days[-1])
    assert requested == [5]
    assert set(results) == {"000002"} and len(results["000002"]) == 2
    assert "未覆盖原缓存" in errors["600001"]
    assert cache.read_bytes() == before


@pytest.mark.parametrize("old_kind", ["corrupt", "invalid_prices"])
def test_unusable_cache_can_be_rebuilt_and_new_listing_is_not_blocked(tmp_path, monkeypatch, old_kind):
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    path = tmp_path / "600001.parquet"
    if old_kind == "corrupt":
        path.write_bytes(b"invalid parquet")
    else:
        old = bars([date(2020, 1, 2)], [-1.], "2020-01-02")
        atomic_write_parquet(old, path, metadata=fetcher._price_basis_metadata(old))
    start = "20260901"
    assert fetcher._preserving_start(["600001"], start) == start
    new = bars([date(2026, 9, 1), date(2026, 9, 2)], [10., 11.], "2026-09-02")
    result = fetcher._finalize_kline_result(KlineFetchResult("600001", new, "tushare", ()), days=180)
    assert len(result) == 2
    assert fetcher.get_cached("600001").date.tolist() == new.date.tolist()


@pytest.mark.parametrize("damage", ["missing_day", "invalid_ohlc"])
def test_current_cache_gap_is_rebuilt_from_raw_facts_without_forcing_network(tmp_path, monkeypatch, damage):
    from kan.data import kline_snapshot

    days = pd.bdate_range(end="2026-11-06", periods=62).date.tolist()
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ohlc_history, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: set(days))
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: days[-1])
    for day in days:
        frame = pd.DataFrame({"ts_code": ["600001.SH"], "trade_date": [day.strftime("%Y%m%d")],
                      "open": [10.], "high": [11.], "low": [9.], "close": [10.],
                      "vol": [100], "amount": [1000], "adj_factor": [1.]})
        frame.attrs["factor_scope"] = "trade_date"
        frame.to_parquet(tmp_path / f"ohlc_facts_v1_{day:%Y%m%d}.parquet", index=False)
    old = bars(days, [10.] * len(days), str(days[-1]))
    if damage == "missing_day":
        old = old.drop(index=len(days) - 5)
    else:
        old.loc[len(days) - 5, "high"] = 0
    atomic_write_parquet(old, tmp_path / "600001.parquet", metadata={"kan.requested_days": "62", **fetcher._price_basis_metadata(old)})
    assert not fetcher.is_fresh("600001", min_rows=41)
    monkeypatch.setattr(ohlc_history, "_query", lambda *args: pytest.fail("物化缺口应复用已有 raw，不强刷上游"))
    original = kline_snapshot.fetch_recent_daily_bars
    calls = []

    def materialize(count, **kwargs):
        calls.append((count, kwargs["force"]))
        return original(count, **kwargs)

    monkeypatch.setattr(kline_snapshot, "fetch_recent_daily_bars", materialize)
    results, errors = fetcher.fetch_batch(["600001"], days=41, market_wide=True)
    assert not errors and len(results["600001"]) == 62
    assert calls == [(62, False)]
    assert set(fetcher.get_cached("600001").date) == set(days)
    assert fetcher.is_fresh("600001", min_rows=41)
    assert not fetcher.fetch_batch(["600001"], days=41, market_wide=True)[1]
    assert calls == [(62, False)]


def test_short_new_listing_is_fetched_once_without_inventing_pre_listing_gaps(tmp_path, monkeypatch):
    days = pd.bdate_range(end="2026-11-06", periods=62).date.tolist()
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: set(days))
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: days[-1])
    panel = bars(days[-2:], [10., 11.], str(days[-1])).assign(symbol="600001")
    calls = []

    def recent(count, **kwargs):
        calls.append(count)
        return panel

    monkeypatch.setattr("kan.data.kline_snapshot.fetch_recent_daily_bars", recent)
    assert not fetcher.fetch_batch(["600001"], days=41, market_wide=True)[1]
    assert fetcher.is_fresh("600001", min_rows=41)
    assert not fetcher.fetch_batch(["600001"], days=41, market_wide=True)[1]
    assert calls == [41]
    assert len(fetcher.get_cached("600001")) == 2

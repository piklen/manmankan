"""真实原价因子缓存 → 统一复权物化 → 公共读取的跨层回归。"""
from datetime import date

import pandas as pd
import pyarrow.parquet as pq
import pytest

from kan.data import fetcher, ohlc_history


def test_market_cache_rebuilds_at_explicit_cutoff_without_mixing_bases(monkeypatch, tmp_path):
    days = [date(2026, 9, day) for day in (1, 2, 3, 4)]
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ohlc_history, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: days)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: days[-1])
    for day, close, factor in zip(days, [9., 10., 5., 5.2], [1., 1., 2., 2.], strict=True):
        pd.DataFrame({
            "ts_code": ["600001.SH"], "trade_date": [day.strftime("%Y%m%d")],
            "open": [close], "high": [close + .2], "low": [close - .2], "close": [close],
            "vol": [100.], "amount": [1000.], "adj_factor": [factor],
        }).to_parquet(tmp_path / f"ohlc_facts_v1_{day:%Y%m%d}.parquet", index=False)
    monkeypatch.setattr(ohlc_history, "_query", lambda *args: pytest.fail("已有原始事实，不应请求网络"))

    results, errors = fetcher.fetch_batch(["600001"], days=4, market_wide=True, as_of=days[-1])
    assert set(results) == {"600001"} and not errors
    cache = fetcher.get_cached("600001")
    assert cache is not None and cache.close.tolist() == [4.5, 5., 5., 5.2]
    assert cache.attrs == {"price_basis": "raw_adj_factor_v1", "price_basis_date": "2026-09-04"}
    metadata = pq.read_metadata(tmp_path / "600001.parquet").metadata
    assert metadata[b"kan.price_basis"] == b"raw_adj_factor_v1"
    assert metadata[b"kan.price_basis_date"] == b"2026-09-04"
    assert fetcher.is_fresh("600001")

    # 固定过去截止日不得抹掉已经存在的较新事实；force 也不是删历史的授权。
    path = tmp_path / "600001.parquet"
    original = path.read_bytes()
    _, errors = fetcher.fetch_batch(["600001"], days=2, force=True, market_wide=True, as_of=days[1])
    assert "会丢失较新事实" in errors["600001"]
    assert path.read_bytes() == original
    assert fetcher.is_fresh("600001")


@pytest.mark.parametrize("source", ["tushare", "tushare_market_batch", "baostock"])
def test_unverified_tushare_cache_is_unavailable_without_deleting_assets(monkeypatch, tmp_path, source):
    day = date(2026, 9, 4)
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: day)
    path = tmp_path / "600001.parquet"
    pd.DataFrame({"date": [day], "open": [10.], "high": [11.], "low": [9.],
                  "close": [10.], "_source": [source]}).to_parquet(path, index=False)
    original = path.read_bytes()
    cached = fetcher.get_cached("600001")
    if source.startswith("tushare"):
        assert cached is None
        assert not fetcher.is_fresh("600001")
    else:
        assert cached is not None and cached.attrs["price_basis"] == "provider_adjusted"
        assert fetcher.is_fresh("600001")
    assert path.read_bytes() == original


def test_single_stock_missing_cutoff_factor_preserves_existing_cache(monkeypatch, tmp_path, isolated_breaker):
    from kan.data import tushare

    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetcher, "_kline_source_snapshot", lambda: [tushare.TushareKlineSource()])
    monkeypatch.setattr(tushare, "_resolve_config", lambda: ("test-token", "https://example.invalid"))
    cache_path = tmp_path / "600001.parquet"
    pd.DataFrame({"date": [date(2026, 9, 2)], "open": [10.], "high": [11.],
                  "low": [9.], "close": [10.], "_source": ["baostock"]}).to_parquet(cache_path, index=False)
    original = cache_path.read_bytes()

    def post(**kwargs):
        fields = kwargs["fields"].split(",")
        days = ["20260902", "20260903"] if kwargs["api_name"] == "daily" else ["20260902"]
        items = []
        for day in days:
            close = 10. if day == "20260902" else 5.
            row = {"ts_code": "600001.SH", "trade_date": day, "open": close,
                   "high": close + 1, "low": close - 1, "close": close,
                   "pre_close": close, "pct_chg": 0., "vol": 100., "amount": 1000., "adj_factor": 1.}
            items.append([row[field] for field in fields])
        return {"fields": fields, "items": items}, None

    monkeypatch.setattr(tushare, "_post_tushare_api", post)
    with pytest.raises(ValueError, match="无有效行情，未覆盖原缓存"):
        fetcher.fetch_kline("600001", days=2, force=True)
    assert cache_path.read_bytes() == original
    assert fetcher.get_cached("600001").close.tolist() == [10.]


@pytest.mark.parametrize("kind,reason", [
    ("absent", "缺少可用本地日线"),
    ("conflict", "原价与复权因子存在待核对冲突"),
    ("old_basis", "本地行情已存在但不可用"),
    ("corrupt", "本地行情文件无法读取"),
    ("empty", "本地日线文件为空"),
    ("missing_date", "本地日线缺少日期列"),
])
def test_research_reports_actual_unusable_cache_reason_without_changing_asset(tmp_path, monkeypatch, kind, reason):
    from kan.service.trend_search import prepare_cached_history
    from kan.storage.paths import atomic_write_parquet

    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    path = tmp_path / "600001.parquet"
    day = date(2026, 9, 4)
    if kind == "corrupt":
        path.write_bytes(b"not parquet")
    elif kind != "absent":
        frame = pd.DataFrame({"date": [day], "open": [10.], "high": [11.], "low": [9.],
                              "close": [10.], "_source": ["baostock"]})
        metadata = None
        if kind in {"conflict", "old_basis"}:
            frame["_source"] = "tushare"
            if kind == "conflict":
                metadata = {"kan.price_basis": "unverified_factor_conflict"}
        elif kind == "empty":
            frame = frame.iloc[:0]
        elif kind == "missing_date":
            frame = frame.drop(columns="date")
        atomic_write_parquet(frame, path, metadata=metadata)
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(ValueError, match=reason):
        prepare_cached_history("600001", [day])
    assert (path.read_bytes() if path.exists() else None) == before

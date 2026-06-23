"""kan.data.dividend · 除权除息事件归一化与区间查找。"""

from __future__ import annotations

import datetime
import os
import time

import pandas as pd

from kan.data import dividend


def test_normalize_dividend_keeps_ex_date_and_numeric_values():
    raw = pd.DataFrame(
        [
            {
                "symbol": "600519",
                "record_date": "20260528",
                "ex_date": "20260529",
                "cash_div_tax": "0.2",
                "cash_div": "0.18",
                "stk_div": "0",
                "div_proc": "实施",
            }
        ]
    )
    out = dividend._normalize_dividend(raw, "600519")
    row = out.iloc[0]
    assert row["ex_date"] == datetime.date(2026, 5, 29)
    assert row["record_date"] == datetime.date(2026, 5, 28)
    assert row["cash_div_tax"] == 0.2
    assert row["_source"] == "tushare_dividend"


def test_latest_event_between_returns_latest(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "symbol": "600519",
                "record_date": datetime.date(2026, 5, 20),
                "ex_date": datetime.date(2026, 5, 21),
                "cash_div_tax": 0.1,
            },
            {
                "symbol": "600519",
                "record_date": datetime.date(2026, 5, 28),
                "ex_date": datetime.date(2026, 5, 29),
                "cash_div_tax": 0.2,
            },
        ]
    )
    monkeypatch.setattr(dividend, "fetch_dividends", lambda _symbol: df)
    event = dividend.latest_event_between(
        "600519",
        datetime.date(2026, 5, 1),
        datetime.date(2026, 5, 30),
    )
    assert event["ex_date"] == datetime.date(2026, 5, 29)
    assert event["cash_div_tax"] == 0.2


def test_fetch_dividends_allows_stale_cache_without_network(monkeypatch, tmp_path):
    """scan 可读过期 dividend 缓存，不能触发逐股网络刷新。"""
    cache_dir = tmp_path / "data"
    cache_dir.mkdir()
    monkeypatch.setattr(dividend, "DATA_DIR", cache_dir)
    cache = cache_dir / "dividend_600519.parquet"
    cached = pd.DataFrame(
        [
            {
                "symbol": "600519",
                "record_date": datetime.date(2026, 5, 20),
                "ex_date": datetime.date(2026, 5, 21),
                "cash_div_tax": 0.1,
                "cash_div": 0.1,
                "stk_div": 0.0,
                "div_proc": "实施",
                "_source": "tushare_dividend",
            }
        ]
    )
    cached.to_parquet(cache)
    stale_mtime = time.time() - 8 * 24 * 3600
    os.utime(cache, (stale_mtime, stale_mtime))

    def fail_fetch(_symbol):
        raise AssertionError("stale cache path must not refresh from network")

    monkeypatch.setattr(dividend, "_fetch_tushare_dividend", fail_fetch)

    out = dividend.fetch_dividends("600519", allow_stale=True)

    assert out.iloc[0]["ex_date"] == datetime.date(2026, 5, 21)


def test_fetch_dividends_allow_stale_missing_cache_returns_empty(monkeypatch, tmp_path):
    cache_dir = tmp_path / "data"
    cache_dir.mkdir()
    monkeypatch.setattr(dividend, "DATA_DIR", cache_dir)

    def fail_fetch(_symbol):
        raise AssertionError("missing stale-tolerant cache path must not refresh")

    monkeypatch.setattr(dividend, "_fetch_tushare_dividend", fail_fetch)

    out = dividend.fetch_dividends("600519", allow_stale=True)

    assert out.empty
    assert list(out.columns) == dividend.DIVIDEND_COLUMNS

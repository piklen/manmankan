"""akshare 双源并发 fallback 测试 · _fetch_via_akshare"""

import pandas as pd
import pytest

from kan import fetcher


@pytest.fixture
def raw_df():
    """_fetch_* 返回的 raw DataFrame（英文列 · normalize 前形态）."""
    return pd.DataFrame({
        "date": ["2026-04-29", "2026-04-30"],
        "open": [100.0, 101.0],
        "high": [101.5, 102.5],
        "low": [99.5, 100.5],
        "close": [101.0, 102.0],
        "volume": [10000, 11000],
        "amount": [1e6, 1.1e6],
    })


def test_via_akshare_eastmoney_wins_when_sina_none(raw_df, monkeypatch):
    """新浪返 None · 东财出数 · 结果标 eastmoney."""
    monkeypatch.setattr(fetcher, "_fetch_sina", lambda *a, **kw: None)
    monkeypatch.setattr(fetcher, "_fetch_eastmoney", lambda *a, **kw: raw_df)

    result = fetcher._fetch_via_akshare("600519", "20260101")
    assert result is not None
    df, source = result
    assert source == "eastmoney"
    assert len(df) == 2


def test_via_akshare_sina_wins_when_eastmoney_none(raw_df, monkeypatch):
    """东财返 None · 新浪出数 · 结果标 sina."""
    monkeypatch.setattr(fetcher, "_fetch_eastmoney", lambda *a, **kw: None)
    monkeypatch.setattr(fetcher, "_fetch_sina", lambda *a, **kw: raw_df)

    result = fetcher._fetch_via_akshare("600519", "20260101")
    assert result is not None
    _, source = result
    assert source == "sina"


def test_via_akshare_both_fail_returns_none(monkeypatch):
    """双源都返 None · _fetch_via_akshare 返 None（上层降级腾讯）."""
    monkeypatch.setattr(fetcher, "_fetch_sina", lambda *a, **kw: None)
    monkeypatch.setattr(fetcher, "_fetch_eastmoney", lambda *a, **kw: None)

    assert fetcher._fetch_via_akshare("600519", "20260101") is None


def test_via_akshare_both_succeed_returns_one(raw_df, monkeypatch):
    """双源都出数 · 返回其一（race · 非确定）· source 合法."""
    monkeypatch.setattr(fetcher, "_fetch_sina", lambda *a, **kw: raw_df)
    monkeypatch.setattr(fetcher, "_fetch_eastmoney", lambda *a, **kw: raw_df)

    result = fetcher._fetch_via_akshare("600519", "20260101")
    assert result is not None
    df, source = result
    assert source in ("sina", "eastmoney")
    assert len(df) == 2


def test_via_akshare_source_exception_skipped(raw_df, monkeypatch):
    """一个源抛异常 · 不外泄 · 另一个源仍可中标."""
    def boom(*a, **kw):
        raise RuntimeError("source blew up")

    monkeypatch.setattr(fetcher, "_fetch_eastmoney", boom)
    monkeypatch.setattr(fetcher, "_fetch_sina", lambda *a, **kw: raw_df)

    result = fetcher._fetch_via_akshare("600519", "20260101")
    assert result is not None
    _, source = result
    assert source == "sina"

"""指数日线 akshare fallback 测试。"""
from __future__ import annotations

import sys
from datetime import date
from types import ModuleType

import pandas as pd

from kan.data import index as index_data


def _tushare_like_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": [date(2026, 7, 3)],
        "open": [3400.0],
        "high": [3420.0],
        "low": [3390.0],
        "close": [3410.0],
    })


def test_akshare_index_symbol_mapping():
    assert index_data._akshare_index_symbol("000001.SH") == "sh000001"
    assert index_data._akshare_index_symbol("399006.SZ") == "sz399006"
    assert index_data._akshare_index_symbol("000300.SH") == "sh000300"


def test_fetch_index_daily_prefers_tushare(monkeypatch):
    df = _tushare_like_df()
    monkeypatch.setattr(index_data, "_fetch_index_tushare", lambda *_a, **_kw: df)

    def _fail_akshare(*_a, **_kw):
        raise AssertionError("tushare 有数据时不应触发 akshare fallback")

    monkeypatch.setattr(index_data, "_fetch_index_akshare", _fail_akshare)
    result = index_data.fetch_index_daily("sh")
    assert result is df


def test_fetch_index_daily_falls_back_to_akshare(monkeypatch):
    df = _tushare_like_df()
    monkeypatch.setattr(index_data, "_fetch_index_tushare", lambda *_a, **_kw: None)
    monkeypatch.setattr(index_data, "_fetch_index_akshare", lambda *_a, **_kw: df)
    result = index_data.fetch_index_daily("sh")
    assert result is df


def _install_fake_akshare(monkeypatch, frame: pd.DataFrame | Exception) -> dict:
    calls: dict = {}
    fake = ModuleType("akshare")

    def stock_zh_index_daily(symbol: str) -> pd.DataFrame:
        calls["symbol"] = symbol
        if isinstance(frame, Exception):
            raise frame
        return frame

    fake.stock_zh_index_daily = stock_zh_index_daily  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "akshare", fake)
    return calls


def test_fetch_index_akshare_converts_schema(monkeypatch):
    raw = pd.DataFrame({
        "date": ["2026-07-01", "2026-07-02", "2026-07-03"],
        "open": ["3400", "3405", "3410"],
        "high": ["3410", "3415", "3420"],
        "low": ["3390", "3395", "3400"],
        "close": ["3405", "3410", "3415"],
        "volume": ["100", "110", "120"],
    })
    calls = _install_fake_akshare(monkeypatch, raw)

    df = index_data._fetch_index_akshare("000001.SH", days=2, end_date=date(2026, 7, 2))

    assert calls["symbol"] == "sh000001"
    assert df is not None
    # end_date 截断 + tail(days) 后只剩前两天
    assert list(df["date"]) == [date(2026, 7, 1), date(2026, 7, 2)]
    assert df["close"].tolist() == [3405.0, 3410.0]


def test_fetch_index_akshare_swallows_upstream_error(monkeypatch):
    _install_fake_akshare(monkeypatch, RuntimeError("upstream down"))
    assert index_data._fetch_index_akshare("000001.SH", days=30, end_date=None) is None


def test_fetch_index_akshare_rejects_empty_frame(monkeypatch):
    _install_fake_akshare(monkeypatch, pd.DataFrame())
    assert index_data._fetch_index_akshare("000001.SH", days=30, end_date=None) is None

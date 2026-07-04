"""kan.data.kline_snapshot · 全市场 K 线预计算快照测试。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from kan.data import kline_snapshot


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

    def fake_daily(td, *, symbols=None, force=False):
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


def test_fetch_recent_daily_bars_merges_recent_dates_and_filters_symbols(monkeypatch, tmp_path):
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", tmp_path)
    monkeypatch.setattr(kline_snapshot, "DATA_DIR", tmp_path)
    days = [date(2026, 5, 27) + timedelta(days=i) for i in range(3)]
    monkeypatch.setattr(kline_snapshot, "_recent_trade_dates", lambda _end, _count: days)

    def fake_daily(td, *, symbols=None, force=False):
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

    def fake_daily(td, *, symbols=None, force=False):
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

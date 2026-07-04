"""info/history service 契约测试。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from kan.core.scanner import SymbolHistoryEntry
from kan.service.history_service import HistoryRequest, get_symbol_history
from kan.service.info_service import InfoRequest, get_stock_info


def _kline(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="B").date
    close = [100.0 + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        "date": dates,
        "open": close,
        "high": [v + 1.0 for v in close],
        "low": [v - 1.0 for v in close],
        "close": close,
        "volume": [1000.0 + i for i in range(rows)],
        "amount": [100000.0 + i for i in range(rows)],
    })


def test_info_service_returns_single_stock_contract(monkeypatch) -> None:
    df = _kline()
    monkeypatch.setattr(
        "kan.storage.watchlist.resolve_symbol_or_name",
        lambda raw: ("600519", "贵州茅台"),
    )
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda symbol: True)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_kline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no network")),
    )
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda symbol: df)
    monkeypatch.setattr("kan.data.fetcher.data_cutoff_date", lambda symbol: date(2026, 4, 23))
    monkeypatch.setattr("kan.data.fetcher.cache_age", lambda symbol: "2026-04-23 16:00")
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 4, 23))
    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: type("Book", (), {"cash": 20000.0})(),
    )

    result = get_stock_info(InfoRequest(
        symbol_or_name="600519",
        allow_fetch=False,
        include_external_context=False,
        include_board_context=False,
    ))

    assert result.symbol == "600519"
    assert result.name == "贵州茅台"
    assert result.result.current_price > 0
    assert result.volume is not None
    assert result.stale is False
    assert result.data_cutoff == date(2026, 4, 23)


def test_history_service_returns_snapshot_contract(monkeypatch) -> None:
    entry = SymbolHistoryEntry(
        snapshot_date=date(2026, 5, 23),
        name="贵州茅台",
        periods={60: {"pct": 8.0, "at_low": False, "at_high": False}},
    )
    monkeypatch.setattr(
        "kan.core.scanner.snapshot_symbol_names",
        lambda: {"600519": "贵州茅台"},
    )
    monkeypatch.setattr("kan.core.scanner.load_symbol_history", lambda symbol: [entry])

    result = get_symbol_history(HistoryRequest(symbol_or_name="茅台", period=60))

    assert result.symbol == "600519"
    assert result.name == "贵州茅台"
    assert result.period == 60
    assert result.entries == [entry]

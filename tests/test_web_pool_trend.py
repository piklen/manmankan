"""web 首页池级位置趋势卡 payload 测试。"""
from __future__ import annotations

from datetime import date

from kan.core.scanner_history import PoolHistoryEntry
from kan.web import routes_api


def _entry(day: str, median: float, low: int = 10, high: int = 3, count: int = 190):
    return PoolHistoryEntry(
        snapshot_date=date.fromisoformat(day),
        stock_count=count,
        median_pct=median,
        low_count=low,
        high_count=high,
    )


def test_pool_trend_payload_shape_and_direction(monkeypatch) -> None:
    # load_pool_history 契约:新→旧
    entries = [
        _entry("2026-07-24", 30),
        _entry("2026-07-23", 24),
        _entry("2026-07-22", 20),
    ]
    monkeypatch.setattr(
        "kan.core.scanner_history.load_pool_history", lambda period: entries
    )

    payload = routes_api._pool_trend_payload()

    assert payload is not None
    assert payload["period"] == 180
    # days 旧→新
    assert [d["date"] for d in payload["days"]] == ["07-22", "07-23", "07-24"]
    assert payload["days"][-1]["median"] == 30
    assert payload["direction"] == "整体上行"
    assert payload["trend_text"] == "20% → 24% → 30%"


def test_pool_trend_payload_down_and_flat(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.core.scanner_history.load_pool_history",
        lambda period: [_entry("2026-07-23", 30), _entry("2026-07-22", 40)],
    )
    assert routes_api._pool_trend_payload()["direction"] == "整体下行"

    monkeypatch.setattr(
        "kan.core.scanner_history.load_pool_history",
        lambda period: [_entry("2026-07-23", 42), _entry("2026-07-22", 40)],
    )
    assert routes_api._pool_trend_payload()["direction"] == "横盘整理"


def test_pool_trend_payload_insufficient_days_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.core.scanner_history.load_pool_history",
        lambda period: [_entry("2026-07-24", 30)],
    )
    assert routes_api._pool_trend_payload() is None


def test_pool_trend_payload_fail_open(monkeypatch) -> None:
    def _boom(period):
        raise OSError("disk gone")

    monkeypatch.setattr("kan.core.scanner_history.load_pool_history", _boom)
    assert routes_api._pool_trend_payload() is None

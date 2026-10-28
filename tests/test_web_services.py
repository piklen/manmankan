"""当前数据管理页的持仓与设置行为。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from kan.core.positions import AccountView, PositionHealth, PositionsSummary, PositionView
from kan.core.trading_calendar import PHASE_INTRADAY
from kan.storage.positions import Position, PositionsBook
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME
from kan.web.serialize import empty_hold_payload, serialize_hold

_TEST_SESSION_TOKEN = "test-session-token"


def _client() -> TestClient:
    return TestClient(
        create_app(session_token=_TEST_SESSION_TOKEN, recover_jobs=False),
        base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: _TEST_SESSION_TOKEN},
    )


def _kline(rows: int = 220) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="B").date
    close = [100.0 + i * 0.2 for i in range(rows)]
    return pd.DataFrame({
        "date": dates,
        "open": close,
        "high": [v + 1.0 for v in close],
        "low": [v - 1.0 for v in close],
        "close": close,
        "volume": [1000.0 + i for i in range(rows)],
        "amount": [100000.0 + i for i in range(rows)],
    })


def test_hold_service_uses_realtime_and_computes_account(monkeypatch) -> None:
    from kan.data.realtime import RealtimeQuote
    from kan.service.hold_service import HoldRequest, build_hold_summary

    refresh_calls = []
    book = PositionsBook(
        cash=1000.0,
        positions=[
            Position(symbol="600519", name="贵州茅台", cost=90.0, shares=100, added_at=date(2026, 1, 1)),
            Position(symbol="000858", name="五粮液", cost=120.0, shares=10, added_at=date(2026, 1, 1)),
        ],
    )
    frames = {"600519": _kline(), "000858": _kline(1)}

    monkeypatch.setattr("kan.storage.positions.load_positions", lambda: book)
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda symbol: frames[symbol])
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: PHASE_INTRADAY)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 23))
    monkeypatch.setattr(
        "kan.data.realtime.fetch_realtime_quotes",
        lambda symbols: {
            "600519": RealtimeQuote(
                symbol="600519",
                name="贵州茅台",
                price=101.0,
                prev_close=100.0,
                source="fake_rt",
                trade_time="10:30:00",
            ),
            "000858": RealtimeQuote(
                symbol="000858",
                name="五粮液",
                price=110.0,
                prev_close=None,
                source="fake_rt",
            ),
        },
    )

    summary = build_hold_summary(HoldRequest(
        refresh_stale=lambda pairs, days: refresh_calls.append((pairs, days)),
        check_corporate_actions=False,
    ))

    assert refresh_calls == [([("600519", "贵州茅台"), ("000858", "五粮液")], 180)]
    assert summary.price_mode == "realtime"
    assert summary.account.total_market_value == 11200.0
    assert summary.account.total_assets == 12200.0
    assert summary.account.total_position_pct == 91.8
    assert summary.results[0].daily_pnl == 100.0
    assert summary.results[1].daily_pnl is None
    assert summary.results[0].weight_pct == 82.79
    assert summary.results[0].positions[180] is not None


def test_hold_service_resolves_placeholder_names(monkeypatch) -> None:
    from kan.service.hold_service import HoldRequest, build_hold_summary

    book = PositionsBook(
        cash=0.0,
        positions=[
            Position(symbol="600519", name="600519", cost=90.0, shares=100, added_at=date(2026, 1, 1)),
            Position(symbol="000858", name="自定义名", cost=120.0, shares=10, added_at=date(2026, 1, 1)),
        ],
    )
    monkeypatch.setattr("kan.storage.positions.load_positions", lambda: book)
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _symbol: _kline())
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 23))
    monkeypatch.setattr(
        "kan.storage.watchlist_names.load_stock_names_cache",
        lambda *, allow_stale: {"600519": "贵州茅台"},
    )

    summary = build_hold_summary(HoldRequest(no_refresh=True, check_corporate_actions=False))

    names = {row.symbol: row.name for row in summary.results}
    assert names["600519"] == "贵州茅台"
    assert names["000858"] == "自定义名"


def test_hold_service_empty_and_realtime_fail_soft_falls_back_to_close(monkeypatch) -> None:
    from kan.service.hold_service import HoldRequest, build_hold_summary

    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: PositionsBook(cash=2000.0, positions=[]),
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: PHASE_INTRADAY)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 23))

    empty = build_hold_summary()

    assert empty.results == []
    assert empty.account.total_assets == 2000.0
    assert empty.price_mode == "close"

    book = PositionsBook(
        cash=0.0,
        positions=[Position(symbol="600519", name="贵州茅台", cost=90.0, shares=100, added_at=date(2026, 1, 1))],
    )
    monkeypatch.setattr("kan.storage.positions.load_positions", lambda: book)
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _symbol: _kline())
    monkeypatch.setattr(
        "kan.data.realtime.fetch_realtime_quotes",
        lambda _symbols: (_ for _ in ()).throw(RuntimeError("rt down")),
    )

    fallback = build_hold_summary(HoldRequest(no_refresh=False, check_corporate_actions=False))

    assert fallback.price_mode == "close"
    assert fallback.results[0].price_source == "close_cache"


def test_hold_service_skips_empty_cache_and_can_raise_realtime(monkeypatch) -> None:
    from kan.service.hold_service import HoldRequest, build_hold_summary

    book = PositionsBook(
        cash=0.0,
        positions=[Position(symbol="600519", name="贵州茅台", cost=90.0, shares=100, added_at=date(2026, 1, 1))],
    )
    monkeypatch.setattr("kan.storage.positions.load_positions", lambda: book)
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _symbol: pd.DataFrame())
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: PHASE_INTRADAY)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 23))
    monkeypatch.setattr(
        "kan.data.realtime.fetch_realtime_quotes",
        lambda _symbols: (_ for _ in ()).throw(RuntimeError("rt hard fail")),
    )

    with pytest.raises(RuntimeError, match="rt hard fail"):
        build_hold_summary(HoldRequest(realtime_fail_soft=False))


def test_hold_service_refresh_stale_silent_filters_and_suppresses(monkeypatch) -> None:
    from kan.service.hold_service import _refresh_stale_silent

    calls = []
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda symbol, **_kwargs: symbol == "600519")
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, **kwargs: calls.append((symbols, kwargs)),
    )

    _refresh_stale_silent([("600519", "贵州茅台"), ("000858", "五粮液")], 180)

    assert calls == [(["000858"], {"days": 180, "force": True})]

    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda _symbol: False)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ignored")),
    )

    _refresh_stale_silent([("600519", "贵州茅台")], None)


def test_settings_facts_helpers(monkeypatch, tmp_path) -> None:
    from kan.storage import config
    from kan.web import workspace_views

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "600519.parquet").write_text("x", encoding="utf-8")
    (data_dir / "note.parquet").write_text("x", encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    config.save({**config.DEFAULT_CONFIG, "tushare_endpoint": "not-a-url"})
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", data_dir)
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)

    facts = workspace_views.settings_facts()

    assert facts["kline_cache_files"] == 1
    assert facts["tushare_endpoint_domain"]

    class BrokenDir:
        def glob(self, _pattern):
            raise OSError("bad fs")

    assert workspace_views._kline_cache_count(BrokenDir()) == 0
    assert workspace_views._endpoint_domain("http://[::1") == ""


def test_hold_api_unavailable_is_neutral(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.web.api_v1.build_hold_summary",
        lambda: (_ for _ in ()).throw(RuntimeError("hold down")),
    )

    response = _client().get("/api/v1/portfolio")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "持仓数据不可用"


def test_serialize_hold_preserves_missing_quotes() -> None:
    hold_payload = serialize_hold(PositionsSummary(
        results=[PositionView(
            symbol="600519",
            name="贵州 茅台",
            cost=90.12345,
            shares=100,
            price=None,
            prev_close=None,
            market_value=None,
            cost_value=9012.35,
            weight_pct=None,
            daily_pnl=None,
            daily_pnl_pct=None,
            total_pnl=None,
            total_pnl_pct=None,
            positions={},
            price_source="missing",
            price_status="missing",
        )],
        account=AccountView(1000.0, 0.0, 1000.0, None, None, None),
        health=PositionHealth(0, 0, 1, 0, 0, 1),
        price_mode="close",
        data_cutoff=None,
        notes=[],
    ))
    assert hold_payload["rows"][0]["p180_pct"] is None
    assert hold_payload["rows"][0]["name"] == "贵州茅台"
    assert empty_hold_payload(error="boom")["ok"] is False

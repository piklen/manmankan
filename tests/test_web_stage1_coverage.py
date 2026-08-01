"""Web stage1 diff coverage regression tests."""
from __future__ import annotations

import socket
import sys
from dataclasses import replace
from datetime import date
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kan.app import app as cli_app
from kan.core.models import PeriodResult, StockScanResult, ValuationContext, ValuationMetrics
from kan.core.pipeline import DataCtx, Freshness
from kan.core.positions import AccountView, PositionHealth, PositionsSummary, PositionView
from kan.core.scanner import SymbolHistoryEntry, TrendResult
from kan.core.trading_calendar import PHASE_INTRADAY
from kan.service.history_service import HistoryServiceError, HistoryServiceResult
from kan.service.index_service import (
    IndexPeriodView,
    IndexRow,
    IndexServiceError,
    IndexServiceResult,
)
from kan.service.info_service import (
    InfoDataUnavailableError,
    InfoFetchError,
    InfoRequest,
    InfoServiceResult,
)
from kan.service.scan_service import ScanServiceResult
from kan.storage.positions import Position, PositionsBook
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME

_TEST_SESSION_TOKEN = "test-session-token"


def _client() -> TestClient:
    return TestClient(
        create_app(session_token=_TEST_SESSION_TOKEN),
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


def _scan_result(
    symbol: str = "600519",
    name: str = "贵州 茅台",
    *,
    period: int = 180,
    position_pct: float = 50.0,
    insufficient: bool = False,
) -> StockScanResult:
    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=100.123,
        scan_date=date(2026, 5, 23),
        periods=[
            PeriodResult(
                period=period,
                n_low=80.0,
                n_high=120.0,
                position_pct=position_pct,
                at_low=position_pct <= 5,
                at_high=position_pct >= 95,
                insufficient=insufficient,
                gain_pct=1.234,
                distance_to_low_pct=25.0,
                distance_to_high_pct=-16.67,
            ),
        ],
        low_resonance=1,
        high_resonance=0,
        in_watchlist=True,
        in_holding=False,
    )


def _freshness() -> Freshness:
    return Freshness(
        data_cutoff=date(2026, 5, 23),
        fetched_at="2026-05-23T16:00:00",
        expected_cutoff=date(2026, 5, 23),
        is_stale=False,
        phase="post",
    )


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


def test_serialize_scan_info_history_hold_and_index_branches() -> None:
    from kan.web.serialize import (
        empty_hold_payload,
        serialize_history,
        serialize_hold,
        serialize_index,
        serialize_info,
        serialize_scan,
    )

    full = _scan_result(position_pct=96.0)
    insufficient = _scan_result("000858", "五粮 液", period=60, insufficient=True)
    scan_payload = serialize_scan(ScanServiceResult(
        ctx=DataCtx(
            targets=[("600519", "贵州茅台"), ("000858", "五粮液")],
            meta=None,
            results=[full, insufficient],
            freshness=_freshness(),
            source_name="自定义池",
        ),
        mode="low",
        all_results=[full, insufficient],
        results=[full, insufficient],
    ))
    assert scan_payload["periods"] == [60, 180]
    assert scan_payload["rows"][0]["name"] == "贵州茅台"
    assert scan_payload["rows"][1]["p60_pct"] is None
    assert scan_payload["heatmap"][1]["at_low"] is False

    history_short_payload = serialize_scan(ScanServiceResult(
        ctx=DataCtx(
            targets=[("600519", "贵州茅台")],
            meta=None,
            results=[full],
            freshness=replace(
                _freshness(),
                is_stale=True,
                history_incomplete_count=1,
                required_rows=180,
            ),
            source_name="自选",
        ),
        mode="low",
        all_results=[full],
        results=[full],
    ))
    assert history_short_payload["freshness"]["status"] == "stale"
    assert "历史数据不足 180 个交易日" in history_short_payload["freshness"]["detail"]

    info = InfoServiceResult(
        symbol="600519",
        name="贵州 茅台",
        result=full.model_copy(update={
            "valuation_trade_date": date(2026, 5, 22),
            "pe_ttm": 20.456,
            "in_watchlist": True,
        }),
        trend=TrendResult("600519", "贵州茅台", 100.0, 0, 0.0, []),
        volume=None,
        data_cutoff=None,
        fetched_at=None,
        stale=True,
        valuation=ValuationMetrics(
            trade_date=date(2026, 5, 23),
            pe_ttm=18.333,
            pb=3.21,
            ps_ttm=6.78,
            dv_ttm=1.23,
            turnover_rate=0.45,
            volume_ratio=1.5,
            total_mv=123456.789,
            circ_mv=98765.432,
        ),
    )
    info_payload = serialize_info(info)
    assert info_payload["change_pct"] is None
    assert info_payload["volume"] is None
    assert info_payload["in_watchlist"] is True
    assert info_payload["valuation"]["pe_ttm"] == 18.33
    assert info_payload["periods"][0]["position_pct"] == 96.0

    history_payload = serialize_history(HistoryServiceResult(
        symbol="600519",
        name="贵州 茅台",
        period=60,
        entries=[
            SymbolHistoryEntry(date(2026, 5, 22), "贵州茅台", {}),
            SymbolHistoryEntry(date(2026, 5, 23), "贵州茅台", {60: {"pct": 3.0, "at_low": True, "at_high": False}}),
        ],
    ))
    assert history_payload["series"][0]["position_pct"] is None
    assert history_payload["series"][1]["at_low"] is True

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

    index_payload = serialize_index(IndexServiceResult(
        periods=[30],
        rows=[
            IndexRow("000001.SH", "上证指数", True, date(2026, 5, 23), 3100.123, [IndexPeriodView(30, 12.34, None)]),
            IndexRow("399001.SZ", "深证成指", False, None, None, []),
        ],
    ))
    assert index_payload["ok"] is True
    assert index_payload["stats"]["missing"] == 1
    assert index_payload["rows"][1]["data_date"] is None


def test_routes_api_error_and_neutral_paths(monkeypatch, tmp_path) -> None:
    from kan.core.pipeline import StockSetResolveError
    from kan.storage import config

    monkeypatch.setattr(
        "kan.web.routes_api.run_scan",
        lambda _request: (_ for _ in ()).throw(StockSetResolveError(
            code="empty",
            message="没有候选股票",
            exit_code=2,
        )),
    )
    assert _client().get("/api/scan").status_code == 400
    fake_result = SimpleNamespace(
        ctx=SimpleNamespace(freshness=SimpleNamespace(data_cutoff=None, is_stale=False)),
        all_results=[],
    )
    monkeypatch.setattr("kan.web.routes_api.run_scan", lambda _request: fake_result)
    monkeypatch.setattr("kan.web.routes_api.serialize_scan", lambda _result: {"ok": True, "rows": []})
    monkeypatch.setattr("kan.web.routes_api.build_daily_overview", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("kan.web.routes_api.serialize_daily_overview", lambda _result: {"change_count": 0})
    monkeypatch.setattr("kan.web.routes_api._pool_trend_payload", lambda: None)
    assert _client().get("/api/scan").json() == {
        "ok": True,
        "rows": [],
        "overview": {"change_count": 0},
        "pool_trend": None,
    }

    monkeypatch.setattr("kan.web.routes_api.get_stock_info", lambda _request: (_ for _ in ()).throw(ValueError("bad code")))
    bad_info = _client().get("/api/info/bad")
    assert bad_info.status_code == 404
    assert "bad code" in bad_info.text

    monkeypatch.setattr(
        "kan.web.routes_api.get_stock_info",
        lambda _request: (_ for _ in ()).throw(InfoDataUnavailableError("000000")),
    )
    assert "本地缓存没有该股票数据" in _client().get("/api/info/000000").text

    monkeypatch.setattr(
        "kan.web.routes_api.get_symbol_history",
        lambda _request: (_ for _ in ()).throw(HistoryServiceError(
            code="invalid_period",
            message="周期不支持",
            exit_code=2,
        )),
    )
    assert _client().get("/api/history/600519?period=10").status_code == 400
    monkeypatch.setattr(
        "kan.web.routes_api.get_symbol_history",
        lambda _request: (_ for _ in ()).throw(HistoryServiceError(
            code="history_not_found",
            message="没有历史",
            exit_code=1,
        )),
    )
    no_history = _client().get("/api/history/600519?period=10")
    assert no_history.status_code == 200
    assert no_history.json()["series"] == []
    assert no_history.json()["message"] == "没有历史"

    monkeypatch.setattr("kan.web.routes_api.build_hold_summary", lambda: (_ for _ in ()).throw(RuntimeError("bad hold")))
    hold = _client().get("/api/hold")
    assert hold.status_code == 200
    assert hold.json()["error"] == "持仓数据不可用"

    assert _client().get("/api/fetch/events?job=missing").status_code == 404
    assert _client().get(
        "/api/fetch/events?job=missing",
        headers={"host": "evil.example"},
    ).status_code == 403

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    empty_token = _client().post("/api/config/token", headers={"X-Kan-Web": "1"}, json={"token": " "})
    assert empty_token.status_code == 400
    config.save({**config.DEFAULT_CONFIG, "tushare_token": "  token1234  "})
    assert _client().get("/api/config/token").json()["masked"] == "***1234"


def test_routes_api_settings_facts_helpers(monkeypatch, tmp_path) -> None:
    from kan.storage import config
    from kan.web import routes_api

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "600519.parquet").write_text("x", encoding="utf-8")
    (data_dir / "note.parquet").write_text("x", encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    config.save({**config.DEFAULT_CONFIG, "tushare_endpoint": "not-a-url"})
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", data_dir)
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)

    facts = routes_api.settings_facts()

    assert facts["kline_cache_files"] == 1
    assert facts["tushare_endpoint_domain"]

    class BrokenDir:
        def glob(self, _pattern):
            raise OSError("bad fs")

    assert routes_api._kline_cache_count(BrokenDir()) == 0
    assert routes_api._endpoint_domain("http://[::1") == ""


def test_routes_api_success_info_history_and_watchlist_errors(monkeypatch) -> None:
    info_result = InfoServiceResult(
        symbol="600519",
        name="贵州茅台",
        result=_scan_result(),
        trend=TrendResult("600519", "贵州茅台", 100.0, 1, 1.2, [("2026-05-23", 1.234)]),
        volume=SimpleNamespace(window=5, ratio=1.2, label="量能平稳", state="量平"),
        data_cutoff=date(2026, 5, 23),
        fetched_at="2026-05-23T16:00:00",
        stale=False,
    )
    monkeypatch.setattr("kan.web.routes_api.get_stock_info", lambda request: info_result)
    assert _client().get("/api/info/600519").json()["change_pct"] == 1.23

    history_result = HistoryServiceResult(
        symbol="600519",
        name="贵州茅台",
        period=60,
        entries=[SymbolHistoryEntry(date(2026, 5, 23), "贵州茅台", {60: {"pct": 10.0, "at_low": False, "at_high": False}})],
    )
    monkeypatch.setattr("kan.web.routes_api.get_symbol_history", lambda request: history_result)
    assert _client().get("/api/history/600519?period=60").json()["stats"]["shown"] == 1

    assert _client().post("/api/watchlist", headers={"X-Kan-Web": "1"}, json={"codes": "   "}).status_code == 400
    assert _client().post("/api/watchlist", headers={"X-Kan-Web": "1"}, json={"codes": ",， ,"}).status_code == 400

    monkeypatch.setattr("kan.web.routes_api.watchlist.remove", lambda _code: (False, "不存在"))
    missing = _client().delete("/api/watchlist/600519", headers={"X-Kan-Web": "1"})
    assert missing.status_code == 404


def test_refresh_info_fetches_missing_cache_without_changing_watchlist(monkeypatch) -> None:
    captured = {}
    info_result = InfoServiceResult(
        symbol="600519",
        name="贵州茅台",
        result=_scan_result(),
        trend=TrendResult("600519", "贵州茅台", 100.0, 0, 0.0, []),
        volume=None,
        data_cutoff=date(2026, 7, 31),
        fetched_at="2026-08-01T10:00:00",
        stale=False,
    )

    def fake_info(request):
        captured["request"] = request
        return info_result

    monkeypatch.setattr("kan.web.routes_api.get_stock_info", fake_info)
    response = _client().post(
        "/api/info/600519/refresh",
        headers={"X-Kan-Web": "1"},
    )

    assert response.status_code == 200
    assert response.json()["code"] == "600519"
    assert captured["request"].allow_fetch is True
    assert captured["request"].include_board_context is False


def test_compare_api_batches_enrichment_and_fetches_only_missing_cache(monkeypatch) -> None:
    calls = []
    enriched_batches = []

    def make_result(code: str) -> InfoServiceResult:
        return InfoServiceResult(
            symbol=code,
            name="贵州茅台" if code == "600519" else "五粮液",
            result=_scan_result(code, code),
            trend=TrendResult(code, code, 100.0, 0, 0.0, []),
            volume=None,
            data_cutoff=date(2026, 7, 31),
            fetched_at=None,
            stale=False,
        )

    def fake_info(request: InfoRequest):
        calls.append((request.symbol_or_name, request.allow_fetch))
        if request.symbol_or_name == "000858" and not request.allow_fetch:
            raise InfoDataUnavailableError("000858")
        return make_result(request.symbol_or_name)

    def fake_enrich(results):
        enriched_batches.append([item.symbol for item in results])
        return results

    monkeypatch.setattr("kan.web.routes_api.get_stock_info", fake_info)
    monkeypatch.setattr("kan.web.routes_api.enrich_info_results_best_effort", fake_enrich)

    response = _client().post(
        "/api/compare",
        headers={"X-Kan-Web": "1"},
        json={"codes": ["sh600519", "000858.SZ"]},
    )

    assert response.status_code == 200
    assert [row["code"] for row in response.json()["stocks"]] == ["600519", "000858"]
    assert calls == [("600519", False), ("000858", False), ("000858", True)]
    assert enriched_batches == [["600519", "000858"]]


@pytest.mark.parametrize(
    "codes",
    [
        None,
        ["600519"],
        ["600519", "bad"],
        ["600519", "600519"],
        ["sh600519", "600519.SH"],
    ],
)
def test_compare_api_rejects_invalid_code_sets(codes) -> None:
    response = _client().post(
        "/api/compare",
        headers={"X-Kan-Web": "1"},
        json={"codes": codes},
    )

    assert response.status_code == 400

def test_find_adapter_pool_filter_and_command_branches(monkeypatch) -> None:
    from kan.web.find_adapter import (
        _build_cli_command,
        _gap_message,
        _parse_filters,
        _parse_pool,
        run_web_find,
    )

    monkeypatch.setattr("kan.web.find_adapter.watchlist.load_stock_names_cache", lambda allow_stale=True: {"600519": "贵州茅台"})
    pool = _parse_pool({"type": "codes", "value": "sh600519,000858"})
    assert pool["code_pairs"] == [("600519", "贵州茅台"), ("000858", "000858")]

    for raw, detail in [
        ({"type": "codes", "value": "bad"}, "自定义代码含非法代码"),
        ({"type": "codes", "value": ""}, "请填写自定义代码"),
        ({"type": "industry", "value": ""}, "请填写行业名称"),
        ({"type": "theme", "value": ""}, "请填写题材名称"),
        ({"type": "bad"}, "请选择候选池"),
    ]:
        with pytest.raises(HTTPException) as exc_info:
            _parse_pool(raw)
        assert detail in str(exc_info.value.detail)

    for filters, detail in [
        ("bad", "筛选条件格式错误"),
        ([object()], "筛选条件格式错误"),
        ([{"type": "bad"}], "暂不支持这个筛选条件"),
        ([{"type": "pos", "period": "180", "op": "bad", "value": "20"}], "--pos 需要"),
        ([{"type": "resonance", "level": "mid", "value": "2"}], "--resonance 需要"),
        ([{"type": "pe", "op": "", "value": "20"}], "--pe 需要"),
        ([{"type": "moneyflow", "op": "lt", "value": ""}], "--moneyflow 需要"),
        ([{"type": "pe", "op": "lt", "value": "20"}] * 13, "最多同时填写"),
    ]:
        with pytest.raises(HTTPException) as exc_info:
            _parse_filters(filters)
        assert detail in str(exc_info.value.detail)

    captured = {}

    def fake_run(request):
        captured["request"] = request
        return object()

    monkeypatch.setattr("kan.web.find_adapter.run_find_kline", fake_run)
    with pytest.raises(HTTPException) as exc_info:
        run_web_find({
            "pool": {"type": "holdings"},
            "filters": [{"type": "resonance", "level": "low", "op": "gte", "value": "2"}],
            "exclude_st": True,
        })
    assert "没有可展示" in str(exc_info.value.detail)
    assert captured["request"].only_holdings is True

    command = _build_cli_command(
        {"type": "industry", "value": "半导体 龙头"},
        {"pos": ["180:lt:20"], "resonance": ["low:gte:2"], "pe": ["lt:30"], "moneyflow": ["gt:0"]},
        True,
    )
    assert command == "kan find --industry '半导体 龙头' --pos 180:lt:20 --resonance low:gte:2 --pe lt:30 --moneyflow gt:0 --exclude-st --format json"

    assert all(not values for values in _parse_filters(None).values())
    assert _parse_pool({"type": "theme", "value": "AI"})["theme"] == "AI"
    assert _build_cli_command({"type": "watchlist", "value": ""}, {"pos": [], "resonance": [], "pe": [], "moneyflow": []}, False) == "kan find --only-watchlist --format json"
    assert _build_cli_command({"type": "holdings", "value": ""}, {"pos": [], "resonance": [], "pe": [], "moneyflow": []}, False) == "kan find --only-holdings --format json"

    with pytest.raises(HTTPException) as parse_exc:
        run_web_find({
            "pool": {"type": "watchlist"},
            "filters": [{"type": "pe", "op": "lt", "value": "bad"}],
        })
    assert "bad" in str(parse_exc.value.detail)

    from kan.service.find_service import FindServiceError

    monkeypatch.setattr(
        "kan.web.find_adapter.run_find_kline",
        lambda _request: (_ for _ in ()).throw(FindServiceError(
            code="other",
            message="service failed",
            exit_code=1,
        )),
    )
    with pytest.raises(HTTPException) as service_exc:
        run_web_find({
            "pool": {"type": "watchlist"},
            "filters": [{"type": "pos", "period": "180", "op": "lt", "value": "20"}],
        })
    assert service_exc.value.detail == "service failed"
    assert _build_cli_command({"type": "theme", "value": "AI"}, {"pos": [], "resonance": [], "pe": [], "moneyflow": []}, False) == "kan find --theme AI --format json"
    assert _gap_message(0) is None


def test_security_host_origin_edges() -> None:
    from kan.web.security import host_allowed, mutating_request_error, origin_allowed

    assert host_allowed(None) is False
    assert host_allowed("localhost:8876") is True
    assert host_allowed("[127.0.0.1]:8876") is True
    assert host_allowed("[::1]:8876") is False
    assert origin_allowed("ftp://localhost") is False
    assert origin_allowed("http://") is False
    assert origin_allowed("http://[::1") is False
    assert origin_allowed("https://127.0.0.1:8876") is True
    assert origin_allowed(
        "http://127.0.0.1:8876",
        expected_host="127.0.0.1:8876",
    ) is True
    assert origin_allowed(
        "http://127.0.0.1:9999",
        expected_host="127.0.0.1:8876",
    ) is False
    assert mutating_request_error(SimpleNamespace(headers={"x-kan-web": "1", "host": "evil.example"})) == "host not allowed"
    assert mutating_request_error(SimpleNamespace(headers={"x-kan-web": "1", "host": "localhost", "origin": "ftp://localhost"})) == "origin not allowed"


def test_server_port_open_browser_and_cli_error(monkeypatch) -> None:
    from kan.web import server

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((server.WEB_HOST, 0))
        port = sock.getsockname()[1]
        with pytest.raises(RuntimeError):
            server._ensure_port_available(port)

    calls = {}
    monkeypatch.setattr(server.secrets, "token_urlsafe", lambda _size: "session-token")
    monkeypatch.setattr(server.webbrowser, "open", lambda url: calls.setdefault("browser", url))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda app_obj, **kwargs: calls.setdefault("uvicorn", kwargs)))

    server.run_server(port=port, open_browser=True)

    assert calls["browser"] == (
        f"http://{server.WEB_HOST}:{port}/?_kan_session=session-token"
    )
    assert calls["uvicorn"]["host"] == server.WEB_HOST
    assert calls["uvicorn"]["port"] == port

    def fake_run_server(*, port: int, open_browser: bool) -> None:
        calls["cli"] = (port, open_browser)

    monkeypatch.setattr("kan.web.server.run_server", fake_run_server)
    ok = CliRunner().invoke(cli_app, ["web", "--port", "9988", "--no-open"])
    assert ok.exit_code == 0
    assert calls["cli"] == (9988, False)

    monkeypatch.setattr(
        "kan.web.server.run_server",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("端口占用")),
    )
    failed = CliRunner().invoke(cli_app, ["web"])
    assert failed.exit_code == 1
    assert "端口占用" in failed.output


def test_fetch_jobs_edges(monkeypatch) -> None:
    from kan.web import fetch_jobs

    monkeypatch.setattr(fetch_jobs, "_current_job", fetch_jobs.FetchJob(id="known", status="done"))
    assert fetch_jobs.get_fetch_job("missing") is None

    import asyncio

    job = fetch_jobs.FetchJob(id="keep")
    monkeypatch.setattr(fetch_jobs, "_SSE_POLL_SECONDS", 0.0)
    monkeypatch.setattr(fetch_jobs, "_SSE_KEEPALIVE_SECONDS", 0.0)

    async def _drive() -> list[str]:
        chunks: list[str] = []
        stream = fetch_jobs.iter_sse(job)
        # 无事件 + keepalive 阈值=0 → 首个产出是 keep-alive
        chunks.append(await stream.__anext__())
        with job.condition:
            job.status = "done"
            job.condition.notify_all()
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    assert asyncio.run(_drive()) == [": keep-alive\n\n"]

    error_job = fetch_jobs.FetchJob(id="err")
    fetch_jobs._run_job(error_job, lambda _progress: (_ for _ in ()).throw(RuntimeError("boom")))
    assert error_job.status == "error"
    assert error_job.error == "更新失败 · 请检查网络或稍后重试"

    targets = [("600519", "贵州茅台"), ("000858", "五粮液")]
    monkeypatch.setattr(
        "kan.core.pipeline.resolve_stock_set", lambda _stock_set: (targets, None)
    )
    checked_rows = []

    def fake_is_fresh(_symbol, *, min_rows):
        checked_rows.append(min_rows)
        return False

    monkeypatch.setattr("kan.data.fetcher.is_fresh", fake_is_fresh)

    fetched_days = []

    def fake_fetch_batch(symbols, *, days, force, on_progress):
        fetched_days.append(days)
        for symbol in symbols:
            on_progress(symbol, symbol != "000858", None)
        return {"600519": object()}, {"000858": "boom"}

    monkeypatch.setattr("kan.data.fetcher.fetch_batch", fake_fetch_batch)
    events = []
    outcome = fetch_jobs._run_scan_fetch(
        lambda stage, completed, total: events.append((stage, completed, total))
    )
    assert events == [
        ("读取本地池", 0, 0),
        ("刷新本地数据", 0, 2),
        ("刷新 贵州茅台", 1, 2),
        ("刷新 五粮液", 2, 2),
    ]
    assert outcome.status == "partial"
    assert outcome.failed == 1
    assert "1 只未更新" in (outcome.error or "")
    assert checked_rows == [180, 180]
    assert fetched_days == [180]

    monkeypatch.setattr(
        "kan.data.fetcher.is_fresh",
        lambda _symbol, *, min_rows: min_rows == 180,
    )
    fresh_events = []
    fresh_outcome = fetch_jobs._run_scan_fetch(
        lambda stage, completed, total: fresh_events.append((stage, completed, total))
    )
    assert fresh_events == [("读取本地池", 0, 0)]
    assert fresh_outcome.status == "done"
    assert fresh_outcome.stage == "本地数据已是最新"

    monkeypatch.setattr(
        "kan.core.pipeline.resolve_stock_set", lambda _stock_set: ([], None)
    )
    empty_outcome = fetch_jobs._run_scan_fetch(lambda *_args: None)
    assert empty_outcome.status == "error"
    assert "请先添加一只股票" in (empty_outcome.error or "")


def test_finalizer_guard_fallback_and_no_del(monkeypatch) -> None:
    from kan.infra import finalizer_guard

    class MiniRacerNoDel:
        pass

    root = ModuleType("py_mini_racer")
    impl = ModuleType("py_mini_racer.py_mini_racer")
    impl.MiniRacer = MiniRacerNoDel
    root.py_mini_racer = impl
    monkeypatch.setitem(sys.modules, "py_mini_racer", root)
    monkeypatch.setitem(sys.modules, "py_mini_racer.py_mini_racer", impl)
    monkeypatch.setattr(finalizer_guard, "_defused", False)

    finalizer_guard.defuse_mini_racer_finalizer()

    assert getattr(MiniRacerNoDel, "__del__", None) is None

    root = ModuleType("py_mini_racer")
    impl = ModuleType("py_mini_racer.py_mini_racer")
    root.py_mini_racer = impl
    monkeypatch.setitem(sys.modules, "py_mini_racer", root)
    monkeypatch.setitem(sys.modules, "py_mini_racer.py_mini_racer", impl)
    monkeypatch.setattr(finalizer_guard, "_defused", False)

    finalizer_guard.defuse_mini_racer_finalizer()


def test_info_service_error_and_context_branches(monkeypatch) -> None:
    from kan.service import info_service
    from kan.service.info_service import get_stock_info

    monkeypatch.setattr("kan.storage.watchlist.resolve_symbol_or_name", lambda _raw: ("600519", "贵州茅台"))
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda _symbol: False)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_kline",
        lambda *_args, **_kwargs: None,
    )
    with pytest.raises(InfoFetchError) as status_exc:
        get_stock_info(InfoRequest(
            "600519",
            allow_fetch=True,
            fetch_status=lambda _symbol, _name: (_ for _ in ()).throw(RuntimeError("status failed")),
        ))
    assert "status failed" in str(status_exc.value.cause)

    monkeypatch.setattr(
        "kan.data.fetcher.fetch_kline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fetch failed")),
    )
    with pytest.raises(InfoFetchError) as exc_info:
        get_stock_info(InfoRequest("600519", allow_fetch=True))
    assert exc_info.value.symbol == "600519"
    assert exc_info.value.name == "贵州茅台"

    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda _symbol: True)
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _symbol: pd.DataFrame())
    with pytest.raises(InfoDataUnavailableError):
        get_stock_info(InfoRequest("600519", allow_fetch=False))

    base = _scan_result(position_pct=40.0)
    assert info_service._enrich_info_best_effort(base, enabled=False) == (None, None, None)
    monkeypatch.setattr(
        "kan.core.enrich.enrich_results",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("enrich down")),
    )
    assert info_service._enrich_info_best_effort(base, enabled=True) == (None, None, None)
    assert info_service._valuation_context_best_effort("600519", enabled=False) is None
    monkeypatch.setattr(
        "kan.core.valuation_context.build_valuation_context",
        lambda _symbol: ValuationContext(industry="白酒", pe_pct_rank=30.0),
    )
    assert info_service._valuation_context_best_effort("600519", enabled=True).industry == "白酒"
    monkeypatch.setattr(
        "kan.core.valuation_context.build_valuation_context",
        lambda _symbol: (_ for _ in ()).throw(RuntimeError("valuation down")),
    )
    assert info_service._valuation_context_best_effort("600519", enabled=True) is None

    assert info_service._build_board_position_context(_scan_result(insufficient=True)) is None
    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: {})
    assert info_service._build_board_position_context(base) is None

    board = SimpleNamespace(code="801120", level=1)
    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: {"600519": "白酒"})
    monkeypatch.setattr("kan.data.boards.search_industry", lambda _industry: board)
    monkeypatch.setattr(
        "kan.data.boards.get_industry_constituents",
        lambda _board: [("000001", "平安银行"), ("000002", "万科A"), ("000003", "测试股")],
    )

    def fake_scan(_df, code, name, periods):
        positions = {"000001": 10.0, "000002": 80.0, "000003": 30.0}
        return _scan_result(code, name, period=periods[0], position_pct=positions[code])

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _code: _kline())
    monkeypatch.setattr("kan.core.scanner.scan_stock", fake_scan)
    ctx = info_service._build_board_position_context(base)
    assert ctx is not None
    assert ctx.industry == "白酒"
    assert ctx.cached_sample == 4
    assert ctx.periods[0].sample == 4
    assert ctx.periods[0].rank_low_to_high == 3

    monkeypatch.setattr(
        "kan.data.boards.search_industry",
        lambda _industry: (_ for _ in ()).throw(RuntimeError("board down")),
    )
    assert info_service._build_board_position_context(base) is None

    mixed = StockScanResult(
        symbol="600519",
        name="贵州茅台",
        current_price=100.0,
        scan_date=date(2026, 5, 23),
        periods=[
            PeriodResult(period=180, n_low=80.0, n_high=120.0, position_pct=40.0, at_low=False, at_high=False),
            PeriodResult(period=60, n_low=0.0, n_high=0.0, position_pct=0.0, at_low=False, at_high=False, insufficient=True),
        ],
        low_resonance=0,
        high_resonance=0,
    )
    monkeypatch.setattr("kan.data.boards.search_industry", lambda _industry: board)
    monkeypatch.setattr(
        "kan.data.boards.get_industry_constituents",
        lambda _board: [("000001", "平安银行"), ("000002", "万科A")],
    )
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda code: pd.DataFrame() if code == "000001" else _kline())

    def sometimes_failing_scan(_df, code, name, periods):
        if code == "000002":
            raise RuntimeError("peer scan failed")
        return _scan_result(code, name, period=periods[0], position_pct=10.0)

    monkeypatch.setattr("kan.core.scanner.scan_stock", sometimes_failing_scan)
    assert info_service._build_board_position_context(mixed) is None

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _code: _kline())
    monkeypatch.setattr(
        "kan.core.scanner.scan_stock",
        lambda code_df, code, name, periods: _scan_result(code, name, period=periods[0], insufficient=True),
    )
    assert info_service._build_board_position_context(mixed) is None


def test_cli_hold_info_pipeline_scan_find_and_history_small_branches(monkeypatch) -> None:
    from kan.cli import hold_cmds
    from kan.core import pipeline
    from kan.core.find_dsl import ConditionSet
    from kan.core.stock_set import CodeListSet
    from kan.service.find_service import FindKlineRequest, FindOutputProfile, run_find_kline
    from kan.service.history_service import HistoryRequest, get_symbol_history, resolve_in_snapshots
    from kan.service.index_service import IndexRequest, get_index_reference
    from kan.service.scan_service import ScanRequest, run_scan

    captured_hold = {}
    monkeypatch.setattr(
        "kan.cli.helpers._auto_fetch_stale",
        lambda pairs, *, days: captured_hold.setdefault("refresh", (pairs, days)),
    )
    monkeypatch.setattr(
        "kan.service.hold_service.build_hold_summary",
        lambda request: captured_hold.setdefault("request", request),
    )
    request = hold_cmds._build_summary(no_refresh=True, check_corporate_actions=False)
    assert request.no_refresh is True
    assert request.check_corporate_actions is False
    assert request.realtime_fail_soft is False
    request.refresh_stale([("600519", "贵州茅台")], 180)
    assert captured_hold["refresh"] == ([("600519", "贵州茅台")], 180)

    fetch_calls = []
    stock_set = CodeListSet([("600519", "贵州茅台")])
    monkeypatch.setattr("kan.core.auto_fetch.auto_fetch_stale", lambda targets: fetch_calls.append(targets))
    monkeypatch.setattr(
        "kan.core.pipeline.freshness_of",
        lambda _symbols, **_kwargs: _freshness(),
    )
    ctx = pipeline.run_data_pipeline(
        stock_set,
        compute=lambda targets: [SimpleNamespace(symbol=targets[0][0])],
        show_progress=False,
    )
    assert fetch_calls == [[("600519", "贵州茅台")]]
    assert ctx.results[0].symbol == "600519"

    def fake_scan_pipeline(_stock_set, **kwargs):
        captured_hold["scan_kwargs"] = kwargs
        return DataCtx(
            targets=[("600519", "贵州茅台")],
            meta=None,
            results=[_scan_result()],
            freshness=_freshness(),
            source_name="自定义代码池",
        )

    monkeypatch.setattr("kan.core.pipeline.run_data_pipeline", fake_scan_pipeline)
    monkeypatch.setattr("kan.core.enrich.enrich_scan_rows", lambda results, *, data_cutoff: list(results))
    run_scan(ScanRequest(stock_set=stock_set, allow_auto_fetch=False, show_progress=False))
    assert captured_hold["scan_kwargs"]["auto_fetch"] is False

    def fake_find_pipeline(_stock_set, **kwargs):
        captured_hold["find_kwargs"] = kwargs
        return SimpleNamespace(
            targets=[("600519", "贵州茅台")],
            meta=None,
            results=[_scan_result()],
            freshness=_freshness(),
            source_name="自定义代码池",
        )

    monkeypatch.setattr("kan.service.find_service.run_data_pipeline", fake_find_pipeline)
    monkeypatch.setattr("kan.core.enrich.enrich_results", lambda results, **_kwargs: results)
    result = run_find_kline(FindKlineRequest(
        conditions=ConditionSet.from_flags(pos=["180:lt:99"]),
        output=FindOutputProfile(mode="json"),
        code_pairs=[("600519", "贵州茅台")],
        allow_auto_fetch=False,
    ))
    assert result.pools == ["codes:1"]
    assert captured_hold["find_kwargs"]["auto_fetch"] is False

    monkeypatch.setattr("kan.core.scanner.snapshot_symbol_names", lambda: {"600519": "贵州茅台"})
    monkeypatch.setattr("kan.core.scanner.load_symbol_history", lambda _symbol: [])
    with pytest.raises(HistoryServiceError, match="没有"):
        get_symbol_history(HistoryRequest("600519"))
    for raw in ("", "000001", "不存在"):
        with pytest.raises(HistoryServiceError):
            resolve_in_snapshots(raw, {"600519": "贵州茅台"})
    with pytest.raises(HistoryServiceError) as ambiguous:
        resolve_in_snapshots("测试", {f"00000{i}": f"测试 {i}" for i in range(9)})
    assert "等 9 只" in ambiguous.value.hint

    monkeypatch.setattr("kan.data.index.DEFAULT_INDEXES", [SimpleNamespace(code="sh")])
    monkeypatch.setattr("kan.data.index.normalize_index_code", lambda raw: "000001.SH")
    monkeypatch.setattr("kan.data.index.index_name", lambda _code: "上证指数")
    monkeypatch.setattr("kan.data.index.fetch_index_daily", lambda *_args, **_kwargs: None)
    index_result = get_index_reference()
    assert index_result.rows[0].data_available is False
    with pytest.raises(IndexServiceError):
        get_index_reference(IndexRequest(codes=["sh"], periods=[1]))


def test_info_cli_fetch_and_unavailable_errors(monkeypatch) -> None:
    def raise_fetch(request):
        """
        此前 test 断言 CLI 必须传 fetch_status callback，但 lifecycle 统一后
        CLI 用 operation 的 phase 展示拉取进度，不再需要嵌套 status spinner。
        """
        raise InfoFetchError("600519", "贵州茅台", RuntimeError("down"))

    monkeypatch.setattr("kan.service.info_service.get_stock_info", raise_fetch)
    fetch_result = CliRunner().invoke(cli_app, ["info", "600519"])
    assert fetch_result.exit_code == 1
    assert "拉取失败" in fetch_result.output

    monkeypatch.setattr(
        "kan.service.info_service.get_stock_info",
        lambda _request: (_ for _ in ()).throw(InfoDataUnavailableError("600519")),
    )
    unavailable = CliRunner().invoke(cli_app, ["info", "600519"])
    assert unavailable.exit_code == 1
    assert "无数据" in unavailable.output


def test_hold_page_unavailable_is_neutral(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.web.routes_pages.build_hold_summary",
        lambda: (_ for _ in ()).throw(RuntimeError("hold down")),
    )

    response = _client().get("/hold")

    assert response.status_code == 200
    assert '"ok": false' in response.text
    assert "\\u6301\\u4ed3\\u6570\\u636e\\u6682\\u4e0d\\u53ef\\u7528" in response.text


def test_history_period_out_of_range_maps_to_400() -> None:
    # 越界 period 交给 service 校验 → 400 + 范围 hint(不再被 Query 层拦成 422)。
    low = _client().get("/api/history/600519?period=1")
    assert low.status_code == 400
    assert "周期" in low.json()["detail"]
    high = _client().get("/api/history/600519?period=500")
    assert high.status_code == 400
    # 非数字仍由 int 类型校验拦成 422。
    assert _client().get("/api/history/600519?period=abc").status_code == 422


def test_watchlist_write_ops_are_lock_wrapped() -> None:
    from kan.storage import watchlist_items

    # add/remove/clear 必须被 with_watchlist_lock 包裹(functools.wraps 设 __wrapped__)。
    assert hasattr(watchlist_items.add, "__wrapped__")
    assert hasattr(watchlist_items.remove, "__wrapped__")
    assert hasattr(watchlist_items.clear, "__wrapped__")


def test_watchlist_lock_is_mutually_exclusive() -> None:
    import threading
    import time

    from kan.storage.watchlist_store import watchlist_lock

    order: list[str] = []
    started = threading.Event()

    def worker() -> None:
        started.wait()
        with watchlist_lock():
            order.append("B-in")

    thread = threading.Thread(target=worker)
    with watchlist_lock():
        thread.start()
        started.set()
        time.sleep(0.1)  # 给 B 抢锁的窗口:有锁时 B 必须阻塞
        order.append("A-holding")
    thread.join()

    # B 必须等 A 释放锁后才进入 → 证明跨 fd 互斥
    assert order == ["A-holding", "B-in"]

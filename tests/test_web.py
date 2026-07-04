"""kan web 本地页面与 API 测试。"""
from __future__ import annotations

import threading
from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from kan.render.base import DISCLAIMER, HOLD_DISCLAIMER_TEXT
from kan.web.app import create_app


def _scan_payload() -> dict:
    return {
        "ok": True,
        "source_name": "自选股+真实持仓",
        "mode": "low",
        "periods": [30, 60],
        "stats": {
            "targets": 1,
            "shown": 1,
            "data_cutoff": "2026-05-23",
            "stale": False,
        },
        "rows": [{
            "code": "600519",
            "name": "贵州茅台",
            "price": 100.0,
            "scan_date": "2026-05-23",
            "low_resonance": 1,
            "high_resonance": 0,
            "in_watchlist": True,
            "in_holding": False,
            "p30_pct": 4.0,
            "p30_at_low": True,
            "p30_at_high": False,
            "p60_pct": 30.0,
            "p60_at_low": False,
            "p60_at_high": False,
        }],
        "heatmap": [{
            "code": "600519",
            "name": "贵州茅台",
            "period": 30,
            "position_pct": 4.0,
            "at_low": True,
            "at_high": False,
        }],
    }


def test_index_contains_disclaimer(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_pages.default_scan_payload", _scan_payload)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/")

    assert response.status_code == 200
    assert DISCLAIMER.strip() in response.text
    assert "数据表" in response.text
    assert "位置热力图" in response.text
    assert "代码 / 名称" in response.text
    assert "看盘台" in response.text
    assert "持仓" in response.text
    assert "设置" in response.text
    assert "指数数据读取中" in response.text


def test_api_scan_is_web_shape_without_ai_schema(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_api.default_scan_payload", _scan_payload)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/api/scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "schema_version" not in payload
    assert "data_availability" not in payload


def test_mutating_api_requires_web_header() -> None:
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.post("/api/scan")

    assert 400 <= response.status_code < 500


def test_api_fetch_requires_web_header() -> None:
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.post("/api/fetch")

    assert response.status_code == 403


def _hold_summary():
    from kan.core.positions import AccountView, PositionHealth, PositionsSummary, PositionView

    row = PositionView(
        symbol="600519",
        name="贵州茅台",
        cost=1680.0,
        shares=100,
        price=1700.0,
        prev_close=1690.0,
        market_value=170000.0,
        cost_value=168000.0,
        weight_pct=70.0,
        daily_pnl=1000.0,
        daily_pnl_pct=0.59,
        total_pnl=2000.0,
        total_pnl_pct=1.19,
        positions={30: 20.0, 60: 50.0, 180: 80.0},
        price_source="realtime",
        price_status="ok",
    )
    return PositionsSummary(
        results=[row],
        account=AccountView(
            cash=73000.0,
            total_market_value=170000.0,
            total_assets=243000.0,
            total_position_pct=69.96,
            daily_pnl=1000.0,
            total_pnl=2000.0,
        ),
        health=PositionHealth(
            high_count=1,
            low_count=0,
            middle_count=0,
            profit_count=1,
            loss_count=0,
            flat_count=0,
        ),
        price_mode="realtime",
        data_cutoff=date(2026, 6, 5),
        notes=["盈亏按裸价差计算，未计佣金/印花税。"],
    )


def test_api_hold_returns_web_shape(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_api.build_hold_summary", lambda: _hold_summary())
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/api/hold")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["account"]["total_market_value"] == 170000.0
    assert payload["rows"][0]["daily_pnl"] == 1000.0
    assert payload["rows"][0]["p180_pct"] == 80.0


def test_hold_page_contains_hold_disclaimer(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_pages.build_hold_summary", lambda: _hold_summary())
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/hold")

    assert response.status_code == 200
    assert DISCLAIMER.strip() in response.text
    assert HOLD_DISCLAIMER_TEXT in response.text
    assert "名称代码" in response.text
    assert "脱敏" in response.text


def test_hold_page_empty_state(monkeypatch) -> None:
    from kan.web.serialize import empty_hold_payload

    monkeypatch.setattr("kan.web.routes_pages.serialize_hold", lambda _summary: empty_hold_payload())
    monkeypatch.setattr("kan.web.routes_pages.build_hold_summary", lambda: object())
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/hold")

    assert response.status_code == 200
    assert "kan hold add 600519 --cost 1680 --shares 100" in response.text


def test_api_index_returns_reference_rows(monkeypatch) -> None:
    from kan.service.index_service import IndexPeriodView, IndexRow, IndexServiceResult

    result = IndexServiceResult(
        periods=[30, 60, 180],
        rows=[IndexRow(
            code="000001.SH",
            name="上证指数",
            data_available=True,
            data_date=date(2026, 6, 5),
            close=3100.0,
            periods=[
                IndexPeriodView(30, 40.0, 1.0),
                IndexPeriodView(60, 50.0, 2.0),
                IndexPeriodView(180, 60.0, 3.0),
            ],
        )],
    )
    monkeypatch.setattr("kan.web.routes_api.get_index_reference", lambda _request: result)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/api/index")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["rows"][0]["name"] == "上证指数"
    assert payload["rows"][0]["periods"]["180"]["position_pct"] == 60.0


def test_api_index_unavailable_is_neutral(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.web.routes_api.get_index_reference",
        lambda _request: (_ for _ in ()).throw(RuntimeError("down")),
    )
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/api/index")

    assert response.status_code == 200
    assert response.json()["message"] == "指数数据不可用"


def test_settings_page_shows_masked_token_and_facts(tmp_path, monkeypatch) -> None:
    from kan.storage import config

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    config.save({**config.DEFAULT_CONFIG, "tushare_token": "abc12345"})
    monkeypatch.setattr(
        "kan.web.routes_pages.settings_facts",
        lambda: {
            "data_dir": "/tmp/kan/data",
            "kline_cache_files": 3,
            "tushare_endpoint_domain": "api.tushare.pro",
        },
    )
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/settings")

    assert response.status_code == 200
    assert "***2345" in response.text
    assert "abc12345" not in response.text
    assert "/tmp/kan/data" in response.text
    assert "api.tushare.pro" in response.text


def test_config_token_api_masks_full_token(tmp_path, monkeypatch) -> None:
    from kan.storage import config

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.post(
        "/api/config/token",
        headers={"X-Kan-Web": "1"},
        json={"token": "secret-token-abcd"},
    )

    assert response.status_code == 200
    text = response.text
    assert "secret-token-abcd" not in text
    payload = response.json()
    assert payload["configured"] is True
    assert payload["masked"] == "***abcd"

    get_response = client.get("/api/config/token")
    assert "secret-token-abcd" not in get_response.text
    assert get_response.json()["masked"] == "***abcd"


def test_config_token_mutations_require_web_header() -> None:
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    post_response = client.post("/api/config/token", json={"token": "secret-token-abcd"})
    delete_response = client.delete("/api/config/token")

    assert post_response.status_code == 403
    assert delete_response.status_code == 403


def test_config_token_delete_clears_value(tmp_path, monkeypatch) -> None:
    from kan.storage import config

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    config.save({**config.DEFAULT_CONFIG, "tushare_token": "secret-token-abcd"})
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.delete("/api/config/token", headers={"X-Kan-Web": "1"})

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert config.load()["tushare_token"] is None


def test_api_fetch_starts_single_background_job(monkeypatch) -> None:
    from kan.web import fetch_jobs

    release = threading.Event()
    done = threading.Event()

    def fake_runner(progress):
        progress("刷新本地数据", 0, 1)
        release.wait(timeout=2)
        progress("刷新本地数据", 1, 1)
        done.set()

    monkeypatch.setattr(fetch_jobs, "_current_job", None)
    monkeypatch.setattr(fetch_jobs, "_run_scan_fetch", fake_runner)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    first = client.post("/api/fetch", headers={"X-Kan-Web": "1"})
    second = client.post("/api/fetch", headers={"X-Kan-Web": "1"})
    release.set()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job"] == second.json()["job"]
    assert done.wait(timeout=2)


def test_fetch_events_streams_sse(monkeypatch) -> None:
    from kan.web import fetch_jobs

    def fake_runner(progress):
        progress("刷新本地数据", 1, 2)

    monkeypatch.setattr(fetch_jobs, "_current_job", None)
    job = fetch_jobs.start_fetch_job(fake_runner)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get(f"/api/fetch/events?job={job.id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in response.text
    assert '"stage":"刷新本地数据"' in response.text
    assert '"status":"done"' in response.text


def _info_payload() -> dict:
    return {
        "ok": True,
        "code": "600519",
        "name": "贵州茅台",
        "price": 100.0,
        "change_pct": 1.2,
        "scan_date": "2026-05-23",
        "data_cutoff": "2026-05-23",
        "fetched_at": None,
        "stale": False,
        "low_resonance": 1,
        "high_resonance": 0,
        "trend": {"streak": 1, "streak_pct": 1.2, "direction": "涨1天"},
        "volume": {"window": 5, "ratio": 1.0, "label": "量能平稳", "state": "量平·收涨"},
        "volume_price_state": "量平·收涨",
        "valuation": {
            "trade_date": None,
            "pe_ttm": None,
            "pb": None,
            "ps_ttm": None,
            "dv_ttm": None,
            "turnover_rate": None,
            "volume_ratio": None,
            "total_mv": None,
            "circ_mv": None,
        },
        "periods": [{
            "period": 30,
            "position_pct": 50.0,
            "at_low": False,
            "at_high": False,
            "n_low": 90.0,
            "n_high": 110.0,
            "gain_pct": 1.0,
            "distance_to_low_pct": 11.1,
            "distance_to_high_pct": -9.1,
        }],
    }


def test_stock_page_contains_disclaimer(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_pages.get_stock_info", lambda request: SimpleNamespace())
    monkeypatch.setattr("kan.web.routes_pages.serialize_info", lambda result: _info_payload())
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/stock/600519")

    assert response.status_code == 200
    assert DISCLAIMER.strip() in response.text
    assert "位置标尺" in response.text
    assert "位置走势" in response.text


def test_stock_page_unknown_code_is_neutral_404(monkeypatch) -> None:
    from kan.service.info_service import InfoDataUnavailableError

    def raise_missing(request):
        raise InfoDataUnavailableError("000000")

    monkeypatch.setattr("kan.web.routes_pages.get_stock_info", raise_missing)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/stock/000000")

    assert response.status_code == 404
    assert DISCLAIMER.strip() in response.text
    assert "本地缓存没有该代码数据" in response.text


def test_server_host_constant_and_uvicorn_host(monkeypatch) -> None:
    from kan.web import server

    calls = {}

    def fake_run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr(server, "_ensure_port_available", lambda port: None)
    monkeypatch.setattr("uvicorn.run", fake_run)

    assert server.WEB_HOST == "127.0.0.1"
    server.run_server(port=8877, open_browser=False)
    assert calls["host"] == server.WEB_HOST
    assert calls["access_log"] is False

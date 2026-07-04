"""kan web 本地页面与 API 测试。"""
from __future__ import annotations

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from kan.render.base import DISCLAIMER
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

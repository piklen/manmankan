"""kan web 本地页面与 API 测试。"""
from __future__ import annotations

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

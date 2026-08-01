"""kan web 本地页面与 API 测试。"""
from __future__ import annotations

import threading
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kan.render.base import DISCLAIMER, HOLD_DISCLAIMER_TEXT
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME, SESSION_QUERY_NAME, _safe_session_equal

_TEST_SESSION_TOKEN = "test-session-token"


def test_non_ascii_session_value_is_rejected_without_exception():
    assert not _safe_session_equal("测" * len(_TEST_SESSION_TOKEN), _TEST_SESSION_TOKEN)


def _client() -> TestClient:
    return TestClient(
        create_app(session_token=_TEST_SESSION_TOKEN),
        base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: _TEST_SESSION_TOKEN},
    )


def _raw_client(*, follow_redirects: bool = True) -> TestClient:
    return TestClient(
        create_app(session_token=_TEST_SESSION_TOKEN),
        base_url="http://127.0.0.1",
        follow_redirects=follow_redirects,
    )


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
        "freshness": {
            "status": "current",
            "title": "行情已更新至 2026-05-23",
            "detail": "以下概览均按该交易日收盘数据计算。",
            "action_label": "重新检查",
        },
        "overview": {
            "scanned_count": 1,
            "low_180_count": 0,
            "high_180_count": 0,
            "change_count": 0,
            "comparison_date": None,
            "changes": [],
            "low_180": [],
            "high_180": [],
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
    client = _client()

    response = client.get("/")

    assert response.status_code == 200
    assert DISCLAIMER.strip() in response.text
    assert "数据表" in response.text
    assert "位置热力图" in response.text
    assert "代码 / 名称" in response.text
    assert "今天先看这三件事" in response.text
    assert "我的持仓" in response.text
    assert "数据设置" in response.text
    assert "指数数据读取中" in response.text


def test_session_is_required_and_query_opens_authenticated_page() -> None:
    client = _raw_client(follow_redirects=False)

    unauthorized = client.get("/")
    assert unauthorized.status_code == 401
    assert "运行 kan web 的终端" in unauthorized.text

    page = client.get(f"/?{SESSION_QUERY_NAME}={_TEST_SESSION_TOKEN}")
    assert page.status_code == 200
    assert "set-cookie" not in page.headers
    assert f"/?{SESSION_QUERY_NAME}={_TEST_SESSION_TOKEN}" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert page.headers["referrer-policy"] == "no-referrer"


def test_api_requires_current_web_session() -> None:
    response = _raw_client().get("/api/scan")

    assert response.status_code == 401
    assert response.json()["error"] == "session required"


def test_api_accepts_session_header_and_sse_accepts_session_query(monkeypatch) -> None:
    from kan.web import fetch_jobs

    job = fetch_jobs.FetchJob(id="query-session", status="done")
    monkeypatch.setattr(fetch_jobs, "_current_job", job)

    api = _raw_client().get(
        "/api/scan",
        headers={SESSION_HEADER_NAME: _TEST_SESSION_TOKEN},
    )
    events = _raw_client().get(
        f"/api/fetch/events?job={job.id}&{SESSION_QUERY_NAME}={_TEST_SESSION_TOKEN}"
    )
    api_query = _raw_client().get(
        f"/api/scan?{SESSION_QUERY_NAME}={_TEST_SESSION_TOKEN}"
    )

    assert api.status_code == 200
    assert events.status_code == 200
    assert api_query.status_code == 401


def test_other_loopback_port_cannot_reuse_browser_session() -> None:
    response = _client().get(
        "/api/scan",
        headers={"Sec-Fetch-Site": "same-site"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "cross-site request not allowed"


def test_public_web_header_without_session_cannot_replay_write() -> None:
    response = _raw_client().post(
        "/api/config/token",
        headers={"X-Kan-Web": "1"},
        json={"token": "must-not-write"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "session required"


def test_mutating_api_rejects_other_loopback_origin() -> None:
    response = _client().post(
        "/api/fetch",
        headers={
            "X-Kan-Web": "1",
            "Origin": "http://127.0.0.1:9999",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin not allowed"


def test_api_scan_is_web_shape_without_ai_schema(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_api.default_scan_payload", _scan_payload)
    client = _client()

    response = client.get("/api/scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "schema_version" not in payload
    assert "data_availability" not in payload


def test_get_with_forged_host_is_forbidden(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_api.default_scan_payload", _scan_payload)
    client = _client()

    response = client.get("/api/scan", headers={"host": "evil.example"})

    assert response.status_code == 403
    assert response.json()["error"] == "host not allowed"


def test_mutating_api_requires_web_header() -> None:
    client = _client()

    response = client.post("/api/scan")

    assert 400 <= response.status_code < 500


def test_api_fetch_requires_web_header() -> None:
    client = _client()

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
    client = _client()

    response = client.get("/api/hold")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["account"]["total_market_value"] == 170000.0
    assert payload["rows"][0]["daily_pnl"] == 1000.0
    assert payload["rows"][0]["p180_pct"] == 80.0


def test_positions_api_add_update_delete_and_cash(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "kan.web.routes_api.positions.add_position",
        lambda code, *, cost, shares: (
            calls.append(("add", code, cost, shares))
            or SimpleNamespace(symbol=code, name="贵州茅台")
        ),
    )
    monkeypatch.setattr(
        "kan.web.routes_api.positions.update_position",
        lambda code, *, cost, shares: (
            calls.append(("update", code, cost, shares))
            or SimpleNamespace(symbol=code, name="贵州茅台")
        ),
    )
    monkeypatch.setattr(
        "kan.web.routes_api.positions.remove_position",
        lambda code: (
            calls.append(("delete", code))
            or SimpleNamespace(symbol=code, name="贵州茅台")
        ),
    )
    monkeypatch.setattr(
        "kan.web.routes_api.positions.set_cash",
        lambda amount: (
            calls.append(("cash", amount))
            or SimpleNamespace(cash=amount)
        ),
    )
    client = _client()
    headers = {"X-Kan-Web": "1"}

    added = client.post(
        "/api/positions",
        headers=headers,
        json={"code": "600519", "cost": "1680.5", "shares": "100"},
    )
    updated = client.put(
        "/api/positions/600519",
        headers=headers,
        json={"cost": 1660, "shares": 120},
    )
    deleted = client.delete("/api/positions/600519", headers=headers)
    cash = client.post("/api/positions/cash", headers=headers, json={"cash": 73000.12})

    assert [response.status_code for response in (added, updated, deleted, cash)] == [200] * 4
    assert calls == [
        ("add", "600519", 1680.5, 100),
        ("update", "600519", 1660.0, 120),
        ("delete", "600519"),
        ("cash", 73000.12),
    ]


@pytest.mark.parametrize(
    ("path", "method", "payload", "message"),
    [
        ("/api/positions", "post", {"code": "600519", "cost": 0, "shares": 100}, "持仓成本至少为 0.0001"),
        ("/api/positions", "post", {"code": "600519", "cost": 0.00001, "shares": 100}, "持仓成本至少为 0.0001"),
        ("/api/positions", "post", {"code": "600519", "cost": True, "shares": 100}, "持仓成本必须是数字"),
        ("/api/positions", "post", {"code": "600519", "cost": 10**400, "shares": 100}, "持仓成本必须是数字"),
        ("/api/positions", "post", {"code": "600519", "cost": 10, "shares": 1.5}, "持股数量必须是正整数"),
        ("/api/positions", "post", {"code": "600519", "cost": 10, "shares": 10**11}, "持股数量超出可录入范围"),
        ("/api/positions/cash", "post", {"cash": -1}, "可用现金不能小于 0"),
    ],
)
def test_positions_api_rejects_invalid_numbers(path, method, payload, message) -> None:
    client = _client()
    response = getattr(client, method)(path, headers={"X-Kan-Web": "1"}, json=payload)

    assert response.status_code == 400
    assert message in response.text


def test_positions_put_requires_web_header() -> None:
    client = _client()

    response = client.put(
        "/api/positions/600519",
        json={"cost": 10, "shares": 100},
    )

    assert response.status_code == 403


def test_positions_update_missing_is_404_and_invalid_delete_is_400(monkeypatch) -> None:
    from kan.storage.positions import PositionNotFoundError

    monkeypatch.setattr(
        "kan.web.routes_api.positions.update_position",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PositionNotFoundError("600519 没有持仓")
        ),
    )
    missing = _client().put(
        "/api/positions/600519",
        headers={"X-Kan-Web": "1"},
        json={"cost": 10, "shares": 100},
    )
    assert missing.status_code == 404

    monkeypatch.setattr(
        "kan.web.routes_api.positions.remove_position",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("股票代码必须是 6 位数字")),
    )
    invalid = _client().delete("/api/positions/bad", headers={"X-Kan-Web": "1"})
    assert invalid.status_code == 400


def test_positions_api_explains_corrupt_local_file(monkeypatch) -> None:
    from kan.storage.positions import PositionsCorruptError

    monkeypatch.setattr(
        "kan.web.routes_api.positions.set_cash",
        lambda _amount: (_ for _ in ()).throw(PositionsCorruptError("broken")),
    )

    response = _client().post(
        "/api/positions/cash",
        headers={"X-Kan-Web": "1"},
        json={"cash": 100},
    )

    assert response.status_code == 409
    assert "请先备份 positions.json" in response.text


def test_hold_page_contains_hold_disclaimer(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.routes_pages.build_hold_summary", lambda: _hold_summary())
    client = _client()

    response = client.get("/hold")

    assert response.status_code == 200
    assert DISCLAIMER.strip() in response.text
    assert HOLD_DISCLAIMER_TEXT in response.text
    assert "名称代码" in response.text
    assert "隐藏金额" in response.text
    assert "添加一只持仓" in response.text
    assert "hold-result-list" in response.text


def test_hold_page_empty_state(monkeypatch) -> None:
    from kan.web.serialize import empty_hold_payload

    monkeypatch.setattr("kan.web.routes_pages.serialize_hold", lambda _summary: empty_hold_payload())
    monkeypatch.setattr("kan.web.routes_pages.build_hold_summary", lambda: object())
    client = _client()

    response = client.get("/hold")

    assert response.status_code == 200
    assert "还没有持仓记录" in response.text
    assert "在上方录入第一只持仓" in response.text
    assert "kan hold add" not in response.text


def test_hold_page_error_state_explains_recovery_and_stops_writes(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.web.routes_pages.build_hold_summary",
        lambda: (_ for _ in ()).throw(RuntimeError("broken")),
    )

    response = _client().get("/hold")

    assert response.status_code == 200
    assert "\\u6301\\u4ed3\\u6570\\u636e\\u6682\\u4e0d\\u53ef\\u7528" in response.text
    assert "当前页面已停止写入" in response.text


def test_hold_page_corrupt_file_explains_backup_and_data_directory(monkeypatch) -> None:
    from kan.storage.positions import PositionsCorruptError

    monkeypatch.setattr(
        "kan.web.routes_pages.build_hold_summary",
        lambda: (_ for _ in ()).throw(PositionsCorruptError("broken")),
    )

    response = _client().get("/hold")

    assert response.status_code == 200
    assert "\\u6301\\u4ed3\\u6587\\u4ef6\\u65e0\\u6cd5\\u8bfb\\u53d6" in response.text
    assert "请先备份 positions.json" in response.text
    assert "本页已停止写入" in response.text
    assert "打开数据设置" in response.text


def test_index_page_unavailable_is_neutral(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.web.routes_pages.default_scan_payload",
        lambda: (_ for _ in ()).throw(RuntimeError("scan down")),
    )
    client = _client()

    response = client.get("/")

    assert response.status_code == 200
    assert "暂时无法读取本地行情" in response.text
    assert "还没有数据" in response.text


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
    client = _client()

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
    client = _client()

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
    client = _client()

    response = client.get("/settings")

    assert response.status_code == 200
    assert "***2345" in response.text
    assert "abc12345" not in response.text
    assert "/tmp/kan/data" in response.text
    assert "api.tushare.pro" in response.text


def test_settings_page_unavailable_is_neutral(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.web.routes_api._token_status",
        lambda: (_ for _ in ()).throw(RuntimeError("config down")),
    )
    client = _client()

    response = client.get("/settings")

    assert response.status_code == 200
    assert "数据暂不可用" in response.text


def test_config_token_api_masks_full_token(tmp_path, monkeypatch) -> None:
    from kan.storage import config

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    client = _client()

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
    client = _client()

    post_response = client.post("/api/config/token", json={"token": "secret-token-abcd"})
    delete_response = client.delete("/api/config/token")

    assert post_response.status_code == 403
    assert delete_response.status_code == 403


def test_config_token_delete_clears_value(tmp_path, monkeypatch) -> None:
    from kan.storage import config

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    config.save({**config.DEFAULT_CONFIG, "tushare_token": "secret-token-abcd"})
    client = _client()

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
    client = _client()

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
    client = _client()

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
        "in_watchlist": True,
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
        "moneyflow": {
            "trade_date": None,
            "net_amount": None,
            "net_amount_5d": None,
            "inflow_days": None,
            "outflow_days": None,
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
    client = _client()

    response = client.get("/stock/600519")

    assert response.status_code == 200
    assert DISCLAIMER.strip() in response.text
    assert "位置标尺" in response.text
    assert "位置走势" in response.text
    assert '"in_watchlist": true' in response.text


def test_stock_page_unknown_code_is_neutral_404(monkeypatch) -> None:
    from kan.service.info_service import InfoDataUnavailableError

    def raise_missing(request):
        raise InfoDataUnavailableError("000000")

    monkeypatch.setattr("kan.web.routes_pages.get_stock_info", raise_missing)
    client = _client()

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

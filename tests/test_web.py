"""本地 Web 会话边界、现行 API 访问与已构建页面。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME, SESSION_QUERY_NAME, _safe_session_equal

_TEST_SESSION_TOKEN = "test-session-token"


def test_non_ascii_session_value_is_rejected_without_exception():
    assert not _safe_session_equal("测" * len(_TEST_SESSION_TOKEN), _TEST_SESSION_TOKEN)


def _client() -> TestClient:
    return TestClient(
        create_app(session_token=_TEST_SESSION_TOKEN, recover_jobs=False),
        base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: _TEST_SESSION_TOKEN},
    )


def _raw_client(*, follow_redirects: bool = True) -> TestClient:
    return TestClient(
        create_app(session_token=_TEST_SESSION_TOKEN, recover_jobs=False),
        base_url="http://127.0.0.1",
        follow_redirects=follow_redirects,
    )


def test_index_serves_compiled_spa_shell() -> None:
    response = _client().get("/")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "/assets/index-" in response.text
    assert 'rel="icon"' in response.text
    assert 'name="kan-session" content="test-session-token"' in response.text
    assert "jinja" not in response.text.lower()


def test_session_is_required_and_query_opens_authenticated_page() -> None:
    client = _raw_client(follow_redirects=False)

    unauthorized = client.get("/")
    assert unauthorized.status_code == 401
    assert "运行 kan web 的终端" in unauthorized.text

    page = client.get(f"/?{SESSION_QUERY_NAME}={_TEST_SESSION_TOKEN}")
    assert page.status_code == 200
    assert "set-cookie" not in page.headers
    assert f'content="{_TEST_SESSION_TOKEN}"' in page.text
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert page.headers["referrer-policy"] == "no-referrer"


def test_api_requires_current_web_session() -> None:
    response = _raw_client().get("/api/v1/meta")

    assert response.status_code == 401
    assert response.json()["error"] == "session required"


def test_other_loopback_port_cannot_reuse_browser_session() -> None:
    response = _client().get(
        "/api/v1/meta",
        headers={"Sec-Fetch-Site": "same-site"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "cross-site request not allowed"


def test_public_web_header_without_session_cannot_replay_write() -> None:
    response = _raw_client().post(
        "/api/v1/portfolio/cash",
        headers={"X-Kan-Web": "1"},
        json={"token": "must-not-write"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "session required"


def test_mutating_api_rejects_other_loopback_origin() -> None:
    response = _client().post(
        "/api/v1/studies/refresh",
        headers={
            "X-Kan-Web": "1",
            "Origin": "http://127.0.0.1:9999",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin not allowed"


def test_get_with_forged_host_is_forbidden(monkeypatch) -> None:
    client = _client()

    response = client.get("/api/v1/meta", headers={"host": "evil.example"})

    assert response.status_code == 403
    assert response.json()["error"] == "host not allowed"


def test_mutating_api_requires_web_header() -> None:
    client = _client()

    response = client.post("/api/v1/meta")

    assert 400 <= response.status_code < 500


def test_spa_deep_routes_share_the_same_entry_shell() -> None:
    client = _client()

    responses = [client.get(path) for path in ("/research/600519", "/portfolio", "/candidates")]

    assert all(response.status_code == 200 for response in responses)
    assert all('<div id="root"></div>' in response.text for response in responses)


def test_server_host_constant_and_uvicorn_host(monkeypatch) -> None:
    from kan.web import server

    calls = {}
    monkeypatch.setattr(server, "create_app", lambda **_kwargs: object())

    def fake_run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr(server, "_ensure_port_available", lambda port: None)
    monkeypatch.setattr("uvicorn.run", fake_run)

    assert server.WEB_HOST == "127.0.0.1"
    server.run_server(port=8877, open_browser=False)
    assert calls["host"] == server.WEB_HOST
    assert calls["access_log"] is False

def test_api_header_and_job_event_query_session(monkeypatch) -> None:
    monkeypatch.setattr("kan.web.api_v1.workspace_db.get_job", lambda _id: object())
    monkeypatch.setattr(
        "kan.web.api_v1.job_service.iter_job_events",
        lambda _id: iter(['event: job\ndata: {"status":"succeeded"}\n\n']),
    )
    client = _raw_client()
    api = client.get("/api/v1/meta", headers={SESSION_HEADER_NAME: _TEST_SESSION_TOKEN})
    events = client.get(f"/api/v1/jobs/sample/events?{SESSION_QUERY_NAME}={_TEST_SESSION_TOKEN}")
    api_query = client.get(f"/api/v1/meta?{SESSION_QUERY_NAME}={_TEST_SESSION_TOKEN}")
    assert api.status_code == 200
    assert events.status_code == 200
    assert "succeeded" in events.text
    assert api_query.status_code == 401


def test_unversioned_api_is_not_served() -> None:
    response = _client().get("/api/scan")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"

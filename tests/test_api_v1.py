"""React 与 agent 共用的 Web API v1 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kan.storage import paths, workspace_db
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME

_SESSION = "api-v1-test-session"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    return TestClient(
        create_app(session_token=_SESSION),
        base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: _SESSION, "X-Kan-Web": "1"},
    )


def test_openapi_only_exposes_typed_v1_contract(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/screens" in schema["paths"]
    assert "/api/find" not in schema["paths"]
    assert "ScreenSpec" in schema["components"]["schemas"]
    assert "ScreenRun" in schema["components"]["schemas"]


def test_screen_crud_and_meta_round_trip(client: TestClient) -> None:
    meta = client.get("/api/v1/meta")
    created = client.post(
        "/api/v1/screens",
        json={"spec": {"name": "我的规则", "exclude_st": True}},
    )

    assert meta.status_code == 200
    assert meta.json()["api_version"] == "v1"
    assert created.status_code == 201
    screen_id = created.json()["screen_id"]
    assert client.get(f"/api/v1/screens/{screen_id}").json() == created.json()
    assert [item["screen_id"] for item in client.get("/api/v1/screens").json()] == [
        screen_id
    ]
    assert client.delete(f"/api/v1/screens/{screen_id}").json() == {"deleted": True}
    assert client.get(f"/api/v1/screens/{screen_id}").status_code == 404


def test_candidates_and_compare_sets_round_trip(client: TestClient) -> None:
    assert client.get("/api/v1/candidate-lists").json()[0]["list_id"] == (
        workspace_db.DEFAULT_CANDIDATE_LIST_ID
    )
    candidate = client.put(
        "/api/v1/candidate-lists/default/candidates/600519",
        json={"name": "贵州茅台", "status": "watch", "note": "补充研究"},
    )
    compare = client.post(
        "/api/v1/compare-sets",
        json={
            "name": "横向观察",
            "symbols": ["600519", "000858", "000568"],
        },
    )

    assert candidate.status_code == 200
    assert candidate.json()["symbol"] == "600519"
    assert compare.status_code == 201
    compare_id = compare.json()["compare_id"]
    assert client.get("/api/v1/compare-sets").json()[0]["symbols"] == [
        "600519",
        "000858",
        "000568",
    ]
    assert client.delete(f"/api/v1/compare-sets/{compare_id}").json() == {
        "deleted": True
    }


def test_compare_set_rejects_duplicate_symbols(client: TestClient) -> None:
    response = client.post(
        "/api/v1/compare-sets",
        json={"symbols": ["600519", "600519", "000858"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"

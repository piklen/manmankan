"""React 与 agent 共用的 Web API v1 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kan.storage import config, paths, positions, workspace_db
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME

_SESSION = "api-v1-test-session"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "POSITIONS_PATH", tmp_path / "positions.json")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(positions, "POSITIONS_PATH", tmp_path / "positions.json")
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
    assert "/api/v1/portfolio" in schema["paths"]
    assert "/api/v1/jobs/screen-runs" in schema["paths"]
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


def test_screen_versions_can_be_inspected_and_restored_as_new_version(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/v1/screens",
        json={"spec": {"name": "版本规则", "exclude_st": True}},
    ).json()
    screen_id = first["screen_id"]
    second = client.post(
        "/api/v1/screens",
        json={
            "screen_id": screen_id,
            "spec": {"name": "版本规则", "exclude_st": True, "exclude_bj": True},
        },
    ).json()

    versions = client.get(f"/api/v1/screens/{screen_id}/versions").json()
    restored = client.post(
        f"/api/v1/screens/{screen_id}/versions/1/restore"
    ).json()

    assert second["current_version"] == 2
    assert [item["version"] for item in versions] == [2, 1]
    assert restored["current_version"] == 3
    assert restored["spec"]["exclude_bj"] is False


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


def test_candidate_list_can_be_renamed_and_deleted(client: TestClient) -> None:
    created = client.post("/api/v1/candidate-lists", json={"name": "临时池"}).json()
    list_id = created["list_id"]

    renamed = client.patch(
        f"/api/v1/candidate-lists/{list_id}", json={"name": "长期观察"}
    )
    deleted = client.delete(f"/api/v1/candidate-lists/{list_id}")
    protected = client.delete("/api/v1/candidate-lists/default")

    assert renamed.json()["name"] == "长期观察"
    assert deleted.json()["deleted"] is True
    assert protected.status_code == 400


def test_compare_set_rejects_duplicate_symbols(client: TestClient) -> None:
    response = client.post(
        "/api/v1/compare-sets",
        json={"symbols": ["600519", "600519", "000858"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"


def test_stock_research_missing_cache_is_successful_availability_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.service.info_service import InfoDataUnavailableError

    monkeypatch.setattr(
        "kan.web.api_v1.get_stock_info",
        lambda _request: (_ for _ in ()).throw(InfoDataUnavailableError("600519")),
    )

    response = client.get("/api/v1/stocks/600519")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["data"] is None


def test_portfolio_mutations_use_typed_v1_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.web.api_models import PortfolioAccountResponse, PortfolioResponse

    empty = PortfolioResponse(
        ok=True,
        price_mode="cache",
        account=PortfolioAccountResponse(),
        rows=[],
    )
    calls: dict[str, object] = {}
    monkeypatch.setattr("kan.web.api_v1._portfolio_response", lambda: empty)
    monkeypatch.setattr(
        "kan.web.api_v1.positions.set_cash",
        lambda amount: calls.update(cash=amount),
    )
    monkeypatch.setattr(
        "kan.web.api_v1.positions.add_position",
        lambda symbol, **kwargs: calls.update(symbol=symbol, **kwargs),
    )

    cash = client.put("/api/v1/portfolio/cash", json={"cash": 12345})
    position = client.post(
        "/api/v1/portfolio/positions",
        json={"code": "600519", "cost": 1500, "shares": 100},
    )

    assert cash.status_code == 200
    assert position.status_code == 200
    assert calls["cash"] == 12345
    assert calls["symbol"] == "600519"
    assert calls["cost"] == 1500


def test_settings_never_returns_full_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kan.web.routes_api.settings_facts",
        lambda: {
            "data_dir": "/tmp/kan/data",
            "kline_cache_files": 3,
            "tushare_endpoint_domain": "api.tushare.pro",
        },
    )
    monkeypatch.setattr(
        "kan.web.routes_api._token_status",
        lambda: {"ok": True, "configured": True, "masked": "***2345"},
    )

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["tushare_masked"] == "***2345"
    assert "secret" not in response.text.lower()

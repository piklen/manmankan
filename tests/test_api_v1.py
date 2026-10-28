"""当前 Web 的数据管理与类型边界。"""
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
        "kan.web.workspace_views.settings_facts",
        lambda: {
            "data_dir": "/tmp/kan/data",
            "kline_cache_files": 3,
            "tushare_endpoint_domain": "api.tushare.pro",
        },
    )
    monkeypatch.setattr(
        "kan.web.workspace_views._token_status",
        lambda: {"ok": True, "configured": True, "masked": "***2345"},
    )

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["tushare_masked"] == "***2345"
    assert "secret" not in response.text.lower()


def test_study_and_map_contracts_are_discoverable(client):
    schema = client.get("/api/v1/openapi.json").json()
    request = schema["paths"]["/api/v1/studies/run"]["post"]["requestBody"]
    assert request["content"]["application/json"]["schema"]["$ref"].endswith("/StudyQuery")
    assert "/api/v1/trends/map" in schema["paths"]
    assert {"trend-map", "market-studies", "pattern-search"} <= set(client.get("/api/v1/meta").json()["capabilities"])


def test_personal_candidate_note_state_roundtrip(client):
    assert client.get("/api/v1/candidate-lists").json()[0]["list_id"] == workspace_db.DEFAULT_CANDIDATE_LIST_ID
    response = client.put("/api/v1/candidate-lists/default/candidates/000001", json={"name":"合成公司", "status":"watch", "note":"待核对事实"})
    assert response.status_code == 200
    candidate = client.get("/api/v1/candidate-lists").json()[0]["candidates"][0]
    assert candidate["note"] == "待核对事实" and candidate["status"] == "watch"
    assert client.delete("/api/v1/candidate-lists/default/candidates/000001").json() == {"deleted": True}

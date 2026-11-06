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


def test_settings_save_preserve_mask_and_environment_priority(client, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
    assert client.get("/api/v1/settings").json()["tushare_configured"] is False
    token = "isolated-token-123456789"
    saved = client.put("/api/v1/settings", json={"token": token})
    assert saved.status_code == 200 and token not in saved.text
    assert saved.json()["tushare_masked"] == "***6789"
    assert config.load()["tushare_token"] == token
    # 空字段不清除或重写已有凭据，单独更改端点保留 token。
    assert client.put("/api/v1/settings", json={"token": "", "endpoint": "https://example.test/api"}).status_code == 200
    assert config.load()["tushare_token"] == token
    monkeypatch.setenv("TUSHARE_TOKEN", "isolated-environment-token")
    actual = client.get("/api/v1/settings").json()
    assert actual["tushare_configured"] and actual["tushare_token_source"] == "environment"
    rejected = client.put("/api/v1/settings", json={"token": "attempted-replacement"})
    assert rejected.status_code == 400 and "环境变量" in rejected.text
    assert config.load()["tushare_token"] == token


def test_settings_rejects_invalid_or_cross_origin_writes_without_echo(client, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
    token = "isolated-confidential-value"
    for payload in ({"token": [token]}, {"token": token, "endpoint": "http://example.test"}, {"token": token, "unexpected": token}):
        rejected = client.put("/api/v1/settings", json=payload)
        assert rejected.status_code in {400, 422}
        assert token not in rejected.text
        assert not config.load()["tushare_token"]
    rejected = client.put("/api/v1/settings", json={"token": token}, headers={"Origin": "https://other.test"})
    assert rejected.status_code == 403
    assert not config.load()["tushare_token"]


def test_discovery_data_plan_preserves_scope_and_historical_date(client, monkeypatch):
    from datetime import date
    from math import ceil

    import pandas as pd

    calendar = list(pd.bdate_range(end=date.today(), periods=1700).date)
    monkeypatch.setattr("kan.service.market_study.resolve_market_calendar", lambda: (calendar, calendar[-1]))
    recent = client.post("/api/v1/discovery/data-plan", json={"universe": "all", "window": 20}).json()
    assert recent["refresh"]["days"] == 41
    assert recent["required_start"] == str(calendar[-41])
    query = {"universe": "codes", "codes": ["600519"], "window": 10, "as_of": str(calendar[-101])}
    response = client.post("/api/v1/discovery/data-plan", json=query)
    assert response.status_code == 200
    plan = response.json()
    assert plan["query"]["as_of"] == query["as_of"]
    assert plan["refresh"]["codes"] == query["codes"]
    assert plan["required_start"] == str(calendar[-121])
    assert plan["refresh"]["days"] == max(121, ceil((date.today() - calendar[-121]).days / 1.8))
    query["as_of"] = str(calendar[25])
    rejected = client.post("/api/v1/discovery/data-plan", json=query)
    assert rejected.status_code == 400 and "1500" in rejected.text


def test_study_and_search_contracts_are_discoverable(client):
    schema = client.get("/api/v1/openapi.json").json()
    request = schema["paths"]["/api/v1/studies/run"]["post"]["requestBody"]
    assert request["content"]["application/json"]["schema"]["$ref"].endswith("/StudyQuery")
    assert "/api/v1/trends/search" in schema["paths"]
    assert {"trend-search", "market-studies", "pattern-search"} <= set(client.get("/api/v1/meta").json()["capabilities"])


def test_data_preparation_retries_calendar_after_first_connection_failure(client, monkeypatch):
    from datetime import date

    import pandas as pd

    from kan.core import trading_calendar

    calendar = set(pd.bdate_range(end=date.today(), periods=50).date)
    attempts = iter([RuntimeError("isolated network failure"), calendar])

    def fetch_calendar():
        response = next(attempts)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(trading_calendar, "_trade_dates_memo", None)
    monkeypatch.setattr(trading_calendar, "_read_cache", lambda: None)
    monkeypatch.setattr(trading_calendar, "_write_cache", lambda _dates: None)
    monkeypatch.setattr(trading_calendar, "_fetch_from_akshare", fetch_calendar)
    monkeypatch.setattr(trading_calendar, "latest_trade_date", lambda *_a, **_kw: max(calendar))
    query = {"universe": "all", "window": 2}
    assert client.post("/api/v1/discovery", json=query).status_code == 422
    prepared = client.post("/api/v1/discovery/data-plan", json=query)
    assert prepared.status_code == 200
    assert prepared.json()["refresh"]["days"] == 5


def test_personal_candidate_note_state_roundtrip(client):
    assert client.get("/api/v1/candidate-lists").json()[0]["list_id"] == workspace_db.DEFAULT_CANDIDATE_LIST_ID
    response = client.put("/api/v1/candidate-lists/default/candidates/000001", json={"name":"合成公司", "status":"watch", "note":"待核对事实"})
    assert response.status_code == 200
    candidate = client.get("/api/v1/candidate-lists").json()[0]["candidates"][0]
    assert candidate["note"] == "待核对事实" and candidate["status"] == "watch"
    assert client.delete("/api/v1/candidate-lists/default/candidates/000001").json() == {"deleted": True}


def test_first_observation_configuration_refresh_and_return_use_real_services(client, tmp_path, monkeypatch):
    """只替换行情/日历 I/O；配置、任务、Parquet 与聚合走实际代码。"""
    from datetime import date
    from time import monotonic, sleep

    import pandas as pd

    from kan.data import fetcher, industry_map
    from kan.data.provider_contracts import ProviderCapabilities, ProviderFetchResult
    from kan.service import job_service

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sw_l1_map.json").write_text('{"000001":"样本行业"}')
    monkeypatch.setattr(fetcher, "DATA_DIR", data_dir)
    monkeypatch.setattr(industry_map, "DATA_DIR", data_dir)
    monkeypatch.setattr("kan.storage.watchlist.load_stock_names_cache", lambda **_kw: {})
    days = list(pd.bdate_range(end=date.today(), periods=91).date)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: set(days))
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda *_a, **_kw: days[-1])
    prices = [10 + index / 10 for index in range(len(days))]
    frame = pd.DataFrame({"date": days, "open": prices, "high": prices, "low": prices, "close": prices, "volume": 1000, "amount": 10000})

    class LocalFeed:
        name, priority = "isolated_fixture", 10
        capabilities = ProviderCapabilities(max_attempts=1, max_concurrency=1, initial_concurrency=1)

        def is_available(self):
            return bool(config.load()["tushare_token"])

        def fetch_detailed(self, _symbol, _start, **_kwargs):
            return ProviderFetchResult.succeeded(frame)

        def fetch(self, symbol, start):
            return self.fetch_detailed(symbol, start).data

    monkeypatch.setattr(fetcher, "_kline_source_snapshot", lambda: [LocalFeed()])
    query = {"universe": "codes", "codes": ["000001"], "window": 10, "as_of": str(days[-1])}
    before = client.post("/api/v1/discovery", json=query)
    assert before.status_code == 200 and before.json()["market"]["current"]["available"] == 0
    plan = client.post("/api/v1/discovery/data-plan", json=query).json()
    assert plan["refresh"]["days"] == 21
    assert client.put("/api/v1/settings", json={"token": "isolated-first-use-token"}).status_code == 200
    created = client.post("/api/v1/studies/refresh", json=plan["refresh"])
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    deadline = monotonic() + 5
    while (job := job_service.get_job(job_id)).status not in job_service.TERMINAL_STATUSES and monotonic() < deadline:
        sleep(.01)
    assert job.status.value == "succeeded", job.error
    assert (data_dir / "000001.parquet").is_file()
    after = client.post("/api/v1/discovery", json=query).json()
    assert after["query"]["as_of"] == query["as_of"]
    assert after["query"]["window"] == 10
    assert after["market"]["current"]["available"] == after["market"]["current"]["up"] == 1
    assert after["members"][0]["source"] == "isolated_fixture"

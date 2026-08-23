"""React 与 agent 共用的 Web API v1 契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kan.storage import config, paths, positions, workspace_db
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME

_SESSION = "api-v1-test-session"


def _board_review_model():
    from kan.domain.board import (
        BoardKind,
        BoardTrendCoverage,
        BoardTrendQuery,
        BoardTrendSnapshot,
    )
    from kan.domain.board_review import BoardDailyReview, BoardReviewSection

    sections = [
        BoardReviewSection(
            kind=kind,
            snapshot=BoardTrendSnapshot(
                query=BoardTrendQuery(kind=kind, limit=None),
                source="sw" if kind is BoardKind.INDUSTRY else "tushare",
                data_cutoff="2026-08-21",
                coverage=BoardTrendCoverage(
                    total=1,
                    evaluated=1,
                    matched=1,
                    returned=1,
                    errors=0,
                ),
            ),
        )
        for kind in (BoardKind.INDUSTRY, BoardKind.THEME)
    ]
    return BoardDailyReview(
        review_id="review-1",
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        mode="close",
        industry_level=1,
        result_hash="a" * 64,
        sections=sections,
    )


def _board_history_study_model():
    from kan.domain.board_history import (
        BoardHistoryCoverage,
        BoardHistoryStudy,
        BoardHistoryStudyQuery,
        ReturnDistribution,
    )

    query = BoardHistoryStudyQuery(
        kind="industry",
        value="电子",
        mode="close",
        direction="up",
        min_streak=3,
        forward_days=5,
        lookback_years=5,
        sample_policy="first_hit",
    )
    empty = ReturnDistribution(count=0, positive=0, negative=0, flat=0)
    return BoardHistoryStudy(
        query=query,
        board_code="801080",
        board_name="电子",
        source="sw_index_history",
        benchmark_name="沪深300",
        benchmark_source="fixture",
        data_start="2021-08-21",
        data_cutoff="2026-08-21",
        coverage=BoardHistoryCoverage(
            observations=1200,
            first_hits=0,
            selected=0,
            completed=0,
            censored=0,
            benchmark_aligned=0,
        ),
        raw_distribution=empty,
        benchmark_distribution=empty,
        relative_distribution=empty,
    )


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
    assert "/api/v1/boards/trends" in schema["paths"]
    assert "/api/v1/boards/{kind}/{value}/pulse" in schema["paths"]
    assert "/api/v1/board-reviews" in schema["paths"]
    assert "/api/v1/board-reviews/{review_id}" in schema["paths"]
    assert "/api/v1/board-history-studies" in schema["paths"]
    assert "/api/v1/portfolio" in schema["paths"]
    assert "/api/v1/jobs/screen-runs" in schema["paths"]
    assert "/api/v1/jobs/market-refresh" in schema["paths"]
    assert "/api/find" not in schema["paths"]
    assert "ScreenSpec" in schema["components"]["schemas"]
    assert "ScreenRun" in schema["components"]["schemas"]
    assert "BoardTrendSnapshot" in schema["components"]["schemas"]
    assert "BoardPulseSnapshot" in schema["components"]["schemas"]
    assert "BoardDailyReview" in schema["components"]["schemas"]
    assert "BoardHistoryStudy" in schema["components"]["schemas"]


def test_board_trends_uses_shared_typed_query(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_query(query):
        captured["query"] = query
        return {
            "query": query.model_dump(mode="json"),
            "source": "sw",
            "data_cutoff": "2026-08-21",
            "partial": False,
            "coverage": {
                "total": 31,
                "evaluated": 31,
                "matched": 1,
                "returned": 1,
                "errors": 0,
            },
            "rows": [
                {
                    "rank": 1,
                    "kind": "industry",
                    "code": "801080",
                    "name": "电子",
                    "current_price": 5123.4,
                    "streak": 3,
                    "streak_pct": 4.2,
                    "direction": "涨3天",
                    "latest_change_pct": 1.1,
                    "daily_changes": [
                        {"date": "2026-08-21", "change_pct": 1.1}
                    ],
                }
            ],
        }

    monkeypatch.setattr(
        "kan.web.api_v1.board_service.query_board_trends",
        fake_query,
    )

    response = client.get(
        "/api/v1/boards/trends?kind=industry&mode=close&up=3&sort=latest&limit=12"
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["latest_change_pct"] == 1.1
    query = captured["query"]
    assert query.kind.value == "industry"
    assert query.up == 3
    assert query.sort.value == "latest"
    assert query.limit == 12


def test_board_trends_rejects_conflicting_directions(client: TestClient) -> None:
    response = client.get("/api/v1/boards/trends?up=3&down=3")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"


def test_board_pulse_uses_shared_typed_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_pulse(query):
        captured["query"] = query
        return {
            "query": query.model_dump(mode="json"),
            "board_code": "801080",
            "board_name": "电子",
            "source": "tushare_daily_bars",
            "data_cutoff": "2026-08-21",
            "previous_date": "2026-08-20",
            "partial": False,
            "coverage": {
                "total": 100,
                "evaluated": 100,
                "up": 62,
                "down": 35,
                "flat": 3,
                "missing": 0,
            },
            "up_ratio_pct": 62.0,
            "down_ratio_pct": 35.0,
            "median_change_pct": 0.8,
            "top_up": [
                {
                    "rank": 1,
                    "code": "000001",
                    "name": "甲",
                    "close": 11.0,
                    "change_pct": 10.0,
                }
            ],
            "top_down": [],
        }

    monkeypatch.setattr(
        "kan.web.api_v1.board_service.query_board_pulse",
        fake_pulse,
    )

    response = client.get(
        "/api/v1/boards/industry/%E7%94%B5%E5%AD%90/pulse?level=1&limit=3"
    )

    assert response.status_code == 200
    assert response.json()["coverage"]["up"] == 62
    assert response.json()["top_up"][0]["name"] == "甲"
    query = captured["query"]
    assert query.kind.value == "industry"
    assert query.value == "电子"
    assert query.limit == 3


def test_board_pulse_maps_missing_board_to_not_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.service.board_service import BoardPulseServiceError

    monkeypatch.setattr(
        "kan.web.api_v1.board_service.query_board_pulse",
        lambda _query: (_ for _ in ()).throw(
            BoardPulseServiceError("board_not_found", "没有找到板块")
        ),
    )

    response = client.get("/api/v1/boards/theme/missing/pulse")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "board_not_found"


def test_board_review_create_list_and_get_use_shared_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.service.board_review_service import summarize_board_review

    review = _board_review_model()
    captured: dict[str, object] = {}

    def create(payload):
        captured["payload"] = payload
        return review

    def listing(*, limit: int):
        captured["limit"] = limit
        return [summarize_board_review(review)]

    monkeypatch.setattr(
        "kan.web.api_v1.board_review_service.create_board_review",
        create,
    )
    monkeypatch.setattr(
        "kan.web.api_v1.board_review_service.list_board_reviews",
        listing,
    )
    monkeypatch.setattr(
        "kan.web.api_v1.board_review_service.get_board_review",
        lambda review_id: review if review_id == "review-1" else None,
    )

    created = client.post(
        "/api/v1/board-reviews",
        json={"mode": "candle", "industry_level": 2, "force": True},
    )
    listed = client.get("/api/v1/board-reviews?limit=5")
    fetched = client.get("/api/v1/board-reviews/review-1")

    assert created.status_code == 201
    assert created.json()["review_id"] == "review-1"
    assert captured["payload"].mode.value == "candle"
    assert captured["payload"].industry_level == 2
    assert captured["payload"].force is True
    assert listed.status_code == 200
    assert listed.json()[0]["sections"][0]["evaluated"] == 1
    assert captured["limit"] == 5
    assert fetched.status_code == 200
    assert fetched.json()["result_hash"] == "a" * 64


def test_board_review_errors_map_to_recoverable_http_status(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.service.board_review_service import BoardReviewServiceError

    monkeypatch.setattr(
        "kan.web.api_v1.board_review_service.get_board_review",
        lambda _review_id: (_ for _ in ()).throw(
            BoardReviewServiceError("review_not_found", "记录不存在")
        ),
    )
    missing = client.get("/api/v1/board-reviews/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "review_not_found"

    monkeypatch.setattr(
        "kan.web.api_v1.board_review_service.create_board_review",
        lambda _payload: (_ for _ in ()).throw(
            BoardReviewServiceError("data_unavailable", "数据不可用")
        ),
    )
    unavailable = client.post("/api/v1/board-reviews", json={})
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "data_unavailable"


def test_board_history_study_uses_typed_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study = _board_history_study_model()
    captured: dict[str, object] = {}

    def fake(payload):
        captured["payload"] = payload
        return study

    monkeypatch.setattr(
        "kan.web.api_v1.board_history_service.study_board_history",
        fake,
    )
    response = client.post(
        "/api/v1/board-history-studies",
        json={
            "kind": "industry",
            "value": "电子",
            "level": 1,
            "mode": "close",
            "direction": "up",
            "min_streak": 3,
            "forward_days": 5,
            "lookback_years": 5,
            "sample_policy": "first_hit",
            "benchmark_code": "000300.SH",
            "force": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["audit"]["uses_current_constituents"] is False
    payload = captured["payload"]
    assert payload.min_streak == 3
    assert payload.sample_policy.value == "first_hit"


def test_board_history_study_maps_invalid_benchmark(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.service.board_history_service import BoardHistoryServiceError

    monkeypatch.setattr(
        "kan.web.api_v1.board_history_service.study_board_history",
        lambda _payload: (_ for _ in ()).throw(
            BoardHistoryServiceError("invalid_benchmark", "基准代码错误")
        ),
    )
    payload = _board_history_study_model().query.model_dump(mode="json")
    response = client.post("/api/v1/board-history-studies", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_benchmark"


@pytest.mark.parametrize(
    ("code", "status"),
    [("board_not_found", 404), ("data_unavailable", 503)],
)
def test_board_history_study_maps_stable_service_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    status: int,
) -> None:
    from kan.service.board_history_service import BoardHistoryServiceError

    monkeypatch.setattr(
        "kan.web.api_v1.board_history_service.study_board_history",
        lambda _payload: (_ for _ in ()).throw(BoardHistoryServiceError(code, "失败")),
    )
    response = client.post(
        "/api/v1/board-history-studies",
        json=_board_history_study_model().query.model_dump(mode="json"),
    )

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


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


def test_market_refresh_uses_persistent_job_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kan.web.api_v1.job_service.start_market_refresh_job",
        lambda request: workspace_db.create_job(
            f"market_refresh:{request.scope.value}",
            message="全市场行情刷新已排队",
        ),
    )

    response = client.post(
        "/api/v1/jobs/market-refresh",
        json={"scope": "all", "force": False, "days": 360},
    )

    assert response.status_code == 202
    assert response.json()["kind"] == "market_refresh:all"
    assert response.json()["status"] == "queued"

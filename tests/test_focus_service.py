"""个人股票池成员、来源身份和笔记不依赖行情。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kan.core.models import Stock
from kan.data import fetcher
from kan.domain.job import MarketRefreshRequest
from kan.domain.workspace import CandidateStatus
from kan.service import focus_service, job_service
from kan.storage import paths, workspace_db
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME


@pytest.fixture
def focus_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    monkeypatch.setattr(focus_service.watchlist, "load_watchlist", lambda: SimpleNamespace(stocks=[]))
    monkeypatch.setattr(focus_service.positions, "load_positions", lambda: SimpleNamespace(positions=[]))
    monkeypatch.setattr(focus_service.watchlist, "load_stock_names_cache", lambda **kwargs: {})
    def unexpected_network(*args, **kwargs):
        raise AssertionError("focus must not fetch")

    monkeypatch.setattr(fetcher, "fetch_kline", unexpected_network)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", unexpected_network)
    monkeypatch.setattr(fetcher, "get_cached", unexpected_network)


def test_merge_sources_keeps_all_candidate_notes_and_missing_members(focus_env, monkeypatch):
    stock = Stock(symbol="000001", name="合成一", added_at=date(2026, 1, 1))
    monkeypatch.setattr(focus_service.watchlist, "load_watchlist", lambda: SimpleNamespace(stocks=[stock]))
    monkeypatch.setattr(focus_service.positions, "load_positions", lambda: SimpleNamespace(positions=[stock]))
    default = workspace_db.upsert_candidate(list_id="default", symbol="000001", name="合成一", note="核对收入")
    other = workspace_db.create_candidate_list("观察二组")
    workspace_db.upsert_candidate(list_id=other.list_id, symbol="000001", name="合成一", note="核对现金流")
    workspace_db.upsert_candidate(list_id="default", symbol="000002", name="缺行情")
    workspace_db.upsert_candidate(list_id="default", symbol="000003", name="已排除", status=CandidateStatus.REJECTED)

    result = focus_service.build_focus_snapshot()

    assert result.total == 2
    row = next(item for item in result.rows if item.symbol == "000001")
    assert row.sources == ["watchlist", "holding", "candidate"]
    assert {item.note for item in row.candidates} == {"核对收入", "核对现金流"}
    assert row.note == default.note
    assert {item.symbol for item in result.rows} == {"000001", "000002"}
    assert workspace_db.get_state("focus_reviews.v1:000001") is None


def test_note_and_repeated_add_preserve_status_source_and_other_list(focus_env):
    default = workspace_db.upsert_candidate(
        list_id="default", symbol="000001", name="合成一", status=CandidateStatus.SELECTED,
        note="已有观察",
    )
    other = workspace_db.create_candidate_list("其他观察")
    workspace_db.upsert_candidate(list_id=other.list_id, symbol="000001", name="合成一", note="保持原样")

    assert focus_service.add_focus("sz000001") == default
    changed = focus_service.update_focus_note("000001", "新的待验证事实")

    assert changed.status is CandidateStatus.SELECTED
    assert changed.added_at == default.added_at
    rows = workspace_db.list_candidate_lists()
    assert next(item for item in rows if item.list_id == other.list_id).candidates[0].note == "保持原样"
    focus_service.update_focus_note("000001", "只修改第二组", list_id=other.list_id)
    assert focus_service.build_focus_snapshot().rows[0].note == "新的待验证事实"


def test_focus_refresh_scope_matches_focus_members_only(focus_env):
    focus_service.add_focus("000001")
    focus_service.add_focus("000002")
    assert set(job_service._resolve_refresh_targets(MarketRefreshRequest(scope="focus"))) == {"000001", "000002"}


def test_focus_api_roundtrip_and_input_validation(focus_env):
    client = TestClient(
        create_app(session_token="focus-test"), base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: "focus-test", "X-Kan-Web": "1"},
    )
    assert client.post("/api/v1/focus", json={"symbol": "000001"}).status_code == 201
    response = client.put("/api/v1/candidate-lists/default/candidates/000001", json={"note":"等待核对", "status":"watch"})
    assert response.status_code == 200 and response.json()["note"] == "等待核对"
    snapshot = client.get("/api/v1/focus").json()
    assert snapshot["rows"][0]["note"] == "等待核对"
    assert client.post("/api/v1/focus", json={"symbol": "invalid"}).status_code == 400
    assert client.put("/api/v1/candidate-lists/default/candidates/000001", json={"note": "字" * 2_001}).status_code == 422


def test_explicit_default_note_does_not_overwrite_another_list(focus_env):
    other = workspace_db.create_candidate_list("另一个列表")
    workspace_db.upsert_candidate(list_id=other.list_id, symbol="000001", name="合成一", note="原列表笔记")
    saved = focus_service.update_focus_note("000001", "默认池笔记", list_id="default")
    assert saved.list_id == "default"
    row = focus_service.build_focus_snapshot().rows[0]
    assert {item.note for item in row.candidates} == {"原列表笔记", "默认池笔记"}


def test_rejected_candidate_note_remains_accessible_for_watchlist_member(focus_env, monkeypatch):
    stock = Stock(symbol="000001", name="合成一", added_at=date(2026, 1, 1))
    monkeypatch.setattr(focus_service.watchlist, "load_watchlist", lambda: SimpleNamespace(stocks=[stock]))
    workspace_db.upsert_candidate(list_id="default", symbol="000001", name="合成一", note="已排除理由", status=CandidateStatus.REJECTED)
    row = focus_service.build_focus_snapshot().rows[0]
    assert row.sources == ["watchlist"]
    assert row.note == "已排除理由" and row.candidates[0].status is CandidateStatus.REJECTED

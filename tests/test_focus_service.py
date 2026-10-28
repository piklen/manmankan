"""个人关注的离线闭环：同源事实、笔记保留与显式复看。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from kan.core.models import Stock
from kan.data import fetcher
from kan.domain.job import MarketRefreshRequest
from kan.domain.screen import CandidateStatus, DataCoverage, ScreenRun, ScreenSpec
from kan.service import focus_service, job_service
from kan.storage import paths, workspace_db
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME


def bars(count: int = 181) -> pd.DataFrame:
    """完全合成行情，只用于断言日期和同基准位置变化。"""
    close = [10 + index / 10 for index in range(count)]
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=count, freq="B"),
        "open": close,
        "close": close,
        "high": [value + 1 for value in close],
        "low": [value - 1 for value in close],
        "volume": [100] * count,
        "amount": [1_000] * count,
        "_source": ["fixture"] * count,
    })


@pytest.fixture
def focus_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    monkeypatch.setattr(focus_service.watchlist, "load_watchlist", lambda: SimpleNamespace(stocks=[]))
    monkeypatch.setattr(focus_service.positions, "load_positions", lambda: SimpleNamespace(positions=[]))
    monkeypatch.setattr(focus_service.watchlist, "load_stock_names_cache", lambda **kwargs: {})
    frames = {"000001": bars()}
    monkeypatch.setattr(fetcher, "get_cached", frames.get)
    monkeypatch.setattr(fetcher, "cache_age", lambda symbol: "2026-09-10 16:00")
    monkeypatch.setattr(focus_service, "_cached_expected_cutoff", lambda: frames["000001"]["date"].iloc[-1].date())

    def unexpected_network(*args, **kwargs):
        raise AssertionError("focus must not fetch")

    monkeypatch.setattr(fetcher, "fetch_kline", unexpected_network)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", unexpected_network)
    return frames


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

    assert result.total == 2 and result.available == 1
    row = next(item for item in result.rows if item.symbol == "000001")
    assert row.sources == ["watchlist", "holding", "candidate"]
    assert {item.note for item in row.candidates} == {"核对收入", "核对现金流"}
    assert row.note == default.note
    assert row.source == "fixture"
    assert result.rows[1].price is None and not result.rows[1].available
    assert result.rows[1].message
    assert workspace_db.get_state("focus_reviews.v1:000001") is None


def test_changes_use_same_cached_series_and_insufficient_history_stays_null(focus_env):
    focus_service.add_focus("000001")
    focus_env["000001"] = bars(30)

    row = focus_service.build_focus_snapshot().rows[0]

    assert row.change_pct == pytest.approx((12.9 / 12.8 - 1) * 100, abs=0.0001)
    assert row.previous_cutoff < row.data_cutoff
    assert row.periods[0].position_pct is not None
    assert row.periods[0].previous_position_pct is None
    assert row.periods[0].change_pp is None
    assert row.periods[1].position_pct is None
    assert row.periods[1].low is None


def test_invalid_cache_does_not_hide_other_members(focus_env):
    focus_service.add_focus("000001")
    focus_service.add_focus("000002")
    focus_env["000002"] = bars().assign(close=float("nan"))

    result = focus_service.build_focus_snapshot()

    assert result.available == 1 and result.total == 2
    bad = next(row for row in result.rows if row.symbol == "000002")
    assert not bad.available and bad.price is None and bad.message


def test_note_and_repeated_add_preserve_status_source_and_other_list(focus_env):
    workspace_db.save_run(ScreenRun(
        run_id="source-run", spec=ScreenSpec(name="来源规则", exclude_st=True),
        spec_hash="spec", snapshot_id="snapshot", result_hash="result",
        created_at=datetime.now(UTC), duration_ms=1, coverage=DataCoverage(),
    ))
    default = workspace_db.upsert_candidate(
        list_id="default", symbol="000001", name="合成一", status=CandidateStatus.SELECTED,
        note="已有观察", source_run_id="source-run",
    )
    other = workspace_db.create_candidate_list("其他观察")
    workspace_db.upsert_candidate(list_id=other.list_id, symbol="000001", name="合成一", note="保持原样")

    assert focus_service.add_focus("sz000001") == default
    changed = focus_service.update_focus_note("000001", "新的待验证事实")

    assert changed.status is CandidateStatus.SELECTED
    assert changed.source_run_id == "source-run"
    assert changed.added_at == default.added_at
    rows = workspace_db.list_candidate_lists()
    assert next(item for item in rows if item.list_id == other.list_id).candidates[0].note == "保持原样"
    focus_service.update_focus_note("000001", "只修改第二组", list_id=other.list_id)
    assert focus_service.build_focus_snapshot().rows[0].note == "新的待验证事实"


def test_review_is_explicit_idempotent_and_new_data_needs_review(focus_env):
    focus_service.add_focus("000001")
    focus_service.update_focus_note("000001", "核对本次事实")
    assert not focus_service.build_focus_snapshot().rows[0].reviewed

    first = focus_service.mark_focus_reviewed("000001")
    duplicate = focus_service.mark_focus_reviewed("000001")
    assert duplicate == first
    assert focus_service.build_focus_snapshot().rows[0].reviewed
    focus_env["000001"] = bars(182)
    row = focus_service.build_focus_snapshot().rows[0]
    assert not row.reviewed and row.reviewed_data_cutoff == first.data_cutoff
    assert row.review_history[0].note == "核对本次事实"

    second = focus_service.mark_focus_reviewed("000001")
    assert second.data_cutoff > first.data_cutoff
    row = focus_service.build_focus_snapshot().rows[0]
    assert row.reviewed and len(row.review_history) == 2
    focus_service.update_focus_note("000001", "补充观察")
    assert not focus_service.build_focus_snapshot().rows[0].reviewed


def test_review_without_data_is_rejected(focus_env):
    focus_service.add_focus("000002")
    with pytest.raises(ValueError, match="暂无完整行情"):
        focus_service.mark_focus_reviewed("000002")
    assert workspace_db.get_state("focus_reviews.v1:000002") is None


def test_focus_refresh_scope_matches_focus_members_only(focus_env):
    focus_service.add_focus("000001")
    focus_service.add_focus("000002")
    assert set(job_service._resolve_refresh_targets(MarketRefreshRequest(scope="focus"))) == {"000001", "000002"}


def test_unknown_calendar_is_explicit_without_network(focus_env, monkeypatch):
    focus_service.add_focus("000001")
    monkeypatch.setattr(focus_service, "_cached_expected_cutoff", lambda: None)
    snapshot = focus_service.build_focus_snapshot()
    assert snapshot.expected_cutoff is None
    assert snapshot.stale == 1 and snapshot.warnings
    assert snapshot.rows[0].data_cutoff is not None


def test_empty_focus_has_no_irrelevant_freshness_warning(focus_env, monkeypatch):
    monkeypatch.setattr(focus_service, "_cached_expected_cutoff", lambda: None)
    snapshot = focus_service.build_focus_snapshot()
    assert snapshot.total == 0 and snapshot.warnings == []


def test_focus_api_roundtrip_and_input_validation(focus_env):
    client = TestClient(
        create_app(session_token="focus-test"),
        base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: "focus-test", "X-Kan-Web": "1"},
    )
    assert client.post("/api/v1/focus", json={"symbol": "000001"}).status_code == 201
    response = client.put("/api/v1/focus/000001/note", json={"note": "等待核对"})
    assert response.status_code == 200 and response.json()["note"] == "等待核对"
    assert client.post("/api/v1/focus/000001/review").status_code == 200
    snapshot = client.get("/api/v1/focus").json()
    assert snapshot["rows"][0]["reviewed"]
    assert snapshot["rows"][0]["review_history"][0]["note"] == "等待核对"
    assert client.post("/api/v1/focus", json={"symbol": "invalid"}).status_code == 400
    assert client.put("/api/v1/focus/000001/note", json={"note": "字" * 2_001}).status_code == 422
    schema = client.get("/api/v1/openapi.json").json()
    assert "FocusSnapshot" in schema["components"]["schemas"]
    assert "focus" in schema["components"]["schemas"]["MarketRefreshScope"]["enum"]


@pytest.mark.parametrize(("hour", "cutoff"), [(14, "2026-10-28"), (16, "2026-10-29")])
def test_unknown_calendar_still_excludes_intraday_and_future_rows(focus_env, monkeypatch, hour, cutoff):
    focus_service.add_focus("000001")
    focus_env["000001"] = bars(3).assign(date=pd.to_datetime(["2026-10-28", "2026-10-29", "2026-10-30"]))
    monkeypatch.setattr(focus_service, "_cached_expected_cutoff", lambda: None)
    monkeypatch.setattr(focus_service, "_shanghai_now", lambda: datetime(2026, 10, 29, hour, tzinfo=ZoneInfo("Asia/Shanghai")))
    row = focus_service.build_focus_snapshot().rows[0]
    assert str(row.data_cutoff) == cutoff
    assert row.stale


def test_nonconsecutive_rows_keep_actual_comparison_date_and_adjustment_basis(focus_env):
    focus_service.add_focus("000001")
    frame = bars(200).drop(index=[197, 198]).reset_index(drop=True)
    focus_env["000001"] = frame
    original = focus_service.build_focus_snapshot().rows[0]
    assert original.previous_cutoff == frame["date"].iloc[-2].date()
    assert (original.data_cutoff - original.previous_cutoff).days > 1

    for field in ("open", "close", "high", "low"):
        frame[field] *= 0.5
    scaled = focus_service.build_focus_snapshot().rows[0]
    assert scaled.change_pct == original.change_pct
    assert [(item.position_pct, item.change_pp) for item in scaled.periods] == [
        (item.position_pct, item.change_pp) for item in original.periods
    ]


def test_review_hash_rejects_unseen_same_day_data_but_allows_saved_note(focus_env):
    focus_service.add_focus("000001")
    viewed = focus_service.build_focus_snapshot().rows[0]
    focus_service.update_focus_note("000001", "刚保存的观察")
    assert focus_service.build_focus_snapshot().rows[0].data_hash == viewed.data_hash
    entry = focus_service.mark_focus_reviewed(
        "000001", expected_data_hash=viewed.data_hash, expected_note="刚保存的观察",
    )
    focus_env["000001"].loc[180, "close"] = 28.2
    with pytest.raises(ValueError, match="行情已变化"):
        focus_service.mark_focus_reviewed("000001", expected_data_hash=viewed.data_hash)
    row = focus_service.build_focus_snapshot().rows[0]
    assert row.data_cutoff == entry.data_cutoff and not row.reviewed
    assert row.review_history == [entry]
    with pytest.raises(ValueError, match="笔记已在其他窗口修改"):
        focus_service.mark_focus_reviewed("000001", expected_data_hash=row.data_hash, expected_note="旧笔记")


def test_source_change_is_visible_and_unknown_source_is_not_invented(focus_env):
    focus_service.add_focus("000001")
    first = focus_service.mark_focus_reviewed("000001")
    focus_env["000001"]["_source"] = float("nan")
    row = focus_service.build_focus_snapshot().rows[0]
    assert row.source == "local_cache"
    assert row.data_hash != first.data_hash and not row.reviewed
    focus_env["000001"]["_source"] = focus_env["000001"]["_source"].astype(object)
    focus_env["000001"].loc[180, "_source"] = "another_provider"
    assert focus_service.build_focus_snapshot().rows[0].source == "local_cache / another_provider"


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


def test_review_api_checks_observed_hash(focus_env):
    focus_service.add_focus("000001")
    client = TestClient(
        create_app(session_token="focus-test"), base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: "focus-test", "X-Kan-Web": "1"},
    )
    seen = client.get("/api/v1/focus").json()["rows"][0]
    response = client.post("/api/v1/focus/000001/review", json={"expected_data_hash": seen["data_hash"]})
    assert response.status_code == 200
    focus_env["000001"].loc[180, "close"] = 28.2
    response = client.post("/api/v1/focus/000001/review", json={"expected_data_hash": seen["data_hash"]})
    assert response.status_code == 400 and "行情已变化" in response.json()["detail"]["message"]

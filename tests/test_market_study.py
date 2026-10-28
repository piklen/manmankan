"""研究引擎的算例、未来边界与完整持久主路径。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kan.domain.market_study import StudyQuery
from kan.service import market_study as study
from kan.storage import paths


def bars(close=None):
    prices = close or [10, 9, 10, 12, 11, 13, 14, 15]
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-05", periods=len(prices)),
        "open": [value - .5 for value in prices], "close": prices,
        "high": [value + 1 for value in prices], "low": [value - 1 for value in prices],
        "volume": [100 + index * 10 for index in range(len(prices))], "_source": "synthetic",
    })


def query(**changes):
    return StudyQuery.model_validate({
        "title": "合成算例", "universe": "codes", "codes": ["000001"],
        "lookback_days": 8, "forward_days": 2, "sample_policy": "every",
        "conditions": [{"field": "up_days", "operator": "gte", "value": 2}],
        **changes,
    })


def evaluate(frame, request=None, extra=()):
    sessions = [item.date() for item in bars().date]
    return study.evaluate_study(request or query(), [("000001", "合成公司", frame), *extra], sessions, sessions[-1])


def test_hand_calculated_events_and_denominators():
    result, _events, _frozen = evaluate(bars())
    assert result.coverage.matched_stock_days == 3
    assert result.coverage.selected_events == 3
    assert result.coverage.complete_events == 1
    assert result.coverage.pending_events == 2
    assert result.coverage.missing_events == 0
    assert result.distribution.count == 1
    assert result.distribution.mean_pct == pytest.approx((13 / 12 - 1) * 100)
    assert result.distribution.positive == 1
    assert sum(item.count for item in result.distribution.bins) == 1
    assert result.current_matches[0].values["up_days"] == 3
    assert result.events[-1].max_return_pct == pytest.approx((14 / 12 - 1) * 100)
    assert result.events[-1].min_return_pct == pytest.approx((10 / 12 - 1) * 100)
    assert evaluate(bars(), query(sample_policy="first"))[0].events_total == 2
    assert evaluate(bars(), query(sample_policy="non_overlapping"))[0].events_total == 2


def test_missing_data_remains_in_scope_and_future_missing_is_not_pending():
    frame = bars().drop(index=4)
    result, _events, _frozen = evaluate(frame, extra=[("000002", "无缓存", None)])
    coverage = result.coverage
    assert coverage.total_symbols == 2 and coverage.missing_symbols == 1
    assert coverage.historical_stock_days == 16 and coverage.valid_stock_days == 7
    assert result.unavailable_symbols == ["000002"]
    assert coverage.missing_events == 1 and coverage.pending_events == 1
    assert result.distribution.count == 0
    assert result.events[-1].status == "missing" and result.events[-1].return_pct is None


def test_metrics_use_past_only_and_common_adjustment_scale():
    original = bars()
    days = [item.date() for item in original.date]
    fields = [("position", 3), ("return_pct", 2), ("low_age", 3), ("volume_ratio", 2), ("gap_pct", None), ("joint_up_days", None)]
    before, _exact = study.calculate_metrics(study.prepare_history(original, days), fields)
    assert before["position.3"].iloc[3] == pytest.approx((12 - 8) / (13 - 8) * 100)
    assert before["return_pct.2"].iloc[3] == pytest.approx((12 / 9 - 1) * 100)
    assert before["low_age.3"].iloc[3] == 2
    assert before["volume_ratio.2"].iloc[3] == pytest.approx(130 / 115)
    changed = original.copy()
    changed.loc[4:, ["open", "high", "low", "close", "volume"]] *= 5
    after, _exact = study.calculate_metrics(study.prepare_history(changed, days), fields)
    pd.testing.assert_frame_equal(before.iloc[:4], after.iloc[:4])
    scaled = original.copy()
    scaled[["open", "high", "low", "close"]] *= .5
    scale_metrics, _exact = study.calculate_metrics(study.prepare_history(scaled, days), fields)
    pd.testing.assert_frame_equal(before, scale_metrics)


def test_streak_boundary_does_not_claim_exact_duration_or_first_event():
    increasing = bars([10, 11, 12, 13, 14, 15, 16, 17])
    exact_query = query(conditions=[{"field": "up_days", "operator": "eq", "value": 2}])
    result = evaluate(increasing, exact_query)[0]
    assert result.events_total == 0
    lower = evaluate(increasing)[0]
    assert lower.current_matches[0].lower_bounds == ["up_days"]
    assert evaluate(increasing, query(sample_policy="first"))[0].events_total == 0


@pytest.fixture
def saved_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    frame = bars()
    monkeypatch.setattr(study, "resolve_study_members", lambda universe, codes: [("000001", "合成公司")])
    days = [item.date() for item in frame.date]
    monkeypatch.setattr(study, "resolve_market_calendar", lambda as_of=None: (days, days[-1]))
    state = {"frame": frame}
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda symbol: state["frame"])
    return state


def test_saved_research_paging_frozen_evidence_and_rerun(saved_env):
    first = study.run_study(query())
    assert study.list_studies()[0].last_run_id == first.run_id
    assert study.get_study(first.study_id) == first
    page = study.study_events(first.run_id, offset=1, limit=1)
    assert page.total == 3 and len(page.items) == 1
    assert page.items[0].event_id == first.events[1].event_id
    event = first.events[-1]
    evidence = study.study_evidence(first.run_id, event.symbol, event.event_date)
    assert evidence.conditions[0].actual == 2
    assert evidence.outcome == event and evidence.source == "synthetic"
    assert len(evidence.bars) == 6

    saved_env["frame"].loc[7, ["open", "close", "low"]] = [13, 13, 12]
    second = study.rerun_study(first.study_id)
    assert second.diff.previous_run_id == first.run_id
    assert second.diff.removed == ["000001"] and second.diff.unavailable == []
    assert study.study_evidence(first.run_id, "000001", date(2026, 1, 14)).bars[-1].close == 15
    saved_env["frame"] = None
    third = study.rerun_study(first.study_id)
    assert third.diff.removed == []
    assert study.list_studies()[0].created_at == first.created_at


def test_lost_current_data_is_not_reported_as_removed(saved_env):
    first = study.run_study(query())
    saved_env["frame"] = None
    second = study.rerun_study(first.study_id)
    assert second.diff.removed == [] and second.diff.unavailable == ["000001"]
    assert study.study_events(second.run_id).total == 0


def test_leaving_personal_scope_is_not_a_condition_failure(saved_env, monkeypatch):
    members = [("000001", "对象甲"), ("000002", "对象乙")]
    monkeypatch.setattr(study, "resolve_study_members", lambda universe, codes: list(members))
    first = study.run_study(query(universe="personal", codes=[]))
    members.pop(0)
    second = study.rerun_study(first.study_id)
    assert second.diff.removed == [] and second.diff.unavailable == ["000001"]
    assert second.coverage.total_symbols == 1 and second.coverage.current_missing == 0
    assert any("000001" in warning and "不在本次股票池" in warning for warning in second.warnings)


@pytest.mark.parametrize("fixed_at_creation", [False, True])
def test_fixed_date_advances_only_on_explicit_latest_action(saved_env, monkeypatch, fixed_at_creation):
    days = [item.date() for item in saved_env["frame"].date]
    original_date = days[-1]
    monkeypatch.setattr(study, "resolve_market_calendar", lambda as_of=None: (days, as_of or days[-1]))
    first = study.run_study(query(as_of=str(original_date) if fixed_at_creation else None))
    saved_env["frame"] = bars([10, 9, 10, 12, 11, 13, 14, 15, 16])
    days.append(saved_env["frame"].date.iloc[-1].date())
    fixed = study.rerun_study(first.study_id)
    assert fixed.as_of == original_date and fixed.query.as_of == original_date
    latest = study.rerun_study(first.study_id, latest=True)
    assert latest.as_of == days[-1] and latest.query.as_of is None
    assert latest.query.conditions == first.query.conditions


def test_http_and_cli_use_same_research_contract(saved_env):
    from kan.cli import app
    from kan.web.app import create_app

    client = TestClient(create_app(session_required=False), base_url="http://127.0.0.1", headers={"X-Kan-Web": "1"})
    response = client.post("/api/v1/studies/run", json=query().model_dump(mode="json"))
    assert response.status_code == 201, response.text
    result = response.json()
    assert client.get(f"/api/v1/studies/{result['study_id']}").json() == result
    assert client.get(f"/api/v1/studies/runs/{result['run_id']}/events?offset=1&limit=1").json()["total"] == 3
    evidence = client.get(f"/api/v1/studies/runs/{result['run_id']}/evidence", params={"symbol": "000001", "date": "2026-01-08"})
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["conditions"][0]["actual"] == 2
    assert client.post("/api/v1/studies/run", json=query().model_dump(mode="json") | {"conditions": []}).status_code == 422
    command = CliRunner().invoke(app, ["study", "show", result["study_id"], "--format", "json"])
    assert command.exit_code == 0, command.output
    import json
    assert json.loads(command.stdout)["run_id"] == result["run_id"]


def test_shape_distance_is_scale_free_retrospective_and_excludes_self():
    reference = bars([10, 11, 9, 10, 11, 9])
    target = reference.copy()
    target[["open", "close", "high", "low"]] *= 2
    days = [item.date() for item in reference.date]
    request = query(
        codes=["000001", "000002"], lookback_days=6, forward_days=1,
        conditions=[{"field": "shape_distance", "operator": "lte", "value": .001, "window": 3}],
        reference={"symbol": "000001", "as_of": str(days[2])},
    )
    result, _events, _frozen = study.evaluate_study(
        request, [("000001", "参照", reference), ("000002", "另一公司", target)], days, days[-1], reference_history=reference,
    )
    assert result.coverage.self_matches_excluded == 1
    assert result.events_total == 3
    assert {row.symbol for row in result.current_matches} == {"000001", "000002"}
    assert all(row.values["shape_distance.3"] == pytest.approx(0) for row in result.current_matches)
    assert len(result.reference_bars) == 3 and result.reference_bars[-1].close == 9
    assert all(event.event_id != f"000001-{days[2]}" for event in result.events)
    assert any("事后形态检索" in warning for warning in result.warnings)
    with pytest.raises(ValueError, match="参照股票窗口有行情缺口"):
        study.evaluate_study(request, [], days, days[-1], reference_history=reference.drop(index=1))


def test_self_match_does_not_consume_non_overlapping_sample_window():
    reference = bars([10] * 9)
    days = [item.date() for item in reference.date]
    request = query(
        lookback_days=9, forward_days=2, sample_policy="non_overlapping",
        conditions=[{"field": "shape_distance", "operator": "lte", "value": .001, "window": 2}],
        reference={"symbol": "000001", "as_of": str(days[1])},
    )
    result, _, _ = study.evaluate_study(request, [("000001", "参照", reference)], days, days[-1], reference_history=reference)
    assert [days.index(item.event_date) for item in reversed(result.events)] == [2, 5, 8]
    assert result.coverage.self_matches_excluded == 1


def test_short_lookback_keeps_enough_history_for_long_streak():
    frame = bars([100, *range(90, 150)])
    days = [item.date() for item in frame.date]
    request = query(lookback_days=5, conditions=[{"field": "up_days", "operator": "gte", "value": 40}])
    result, _, _ = study.evaluate_study(request, [("000001", "合成", frame)], days, days[-1])
    assert result.coverage.current_matches == 1 and result.coverage.current_missing == 0
    row = result.current_matches[0]
    assert row.values["up_days"] >= 40
    assert row.lower_bounds == ["up_days"]


def test_rerun_preserves_reference_even_if_its_cache_changes_or_disappears(saved_env, monkeypatch):
    histories = {"000001": bars([10, 11, 9, 10, 11, 9]), "000002": bars([20, 22, 18, 20, 22, 18])}
    days = [item.date() for item in histories["000001"].date]
    monkeypatch.setattr(study, "resolve_market_calendar", lambda as_of=None: (days, as_of or days[-1]))
    monkeypatch.setattr(study, "resolve_study_members", lambda universe, codes: [("000002", "目标")])
    monkeypatch.setattr("kan.data.fetcher.get_cached", histories.get)
    request = query(
        codes=["000002"], lookback_days=6, forward_days=1,
        conditions=[{"field": "shape_distance", "operator": "lte", "value": .001, "window": 3}],
        reference={"symbol": "000001", "as_of": str(days[2])},
    )
    first = study.run_study(request)
    histories["000001"] = bars([10, 11, 10, 10, 11, 9])
    revised = study.rerun_study(first.study_id)
    assert revised.reference_bars == first.reference_bars
    assert revised.reference_source == first.reference_source
    assert revised.diff.removed == [] and len(revised.current_matches) == 1
    del histories["000001"]
    missing = study.rerun_study(first.study_id)
    assert missing.reference_bars == first.reference_bars and len(missing.current_matches) == 1


def test_pagination_keeps_full_distribution_and_frozen_reference(saved_env, monkeypatch):
    frame = bars([10 + index / 10 for index in range(100)])
    days = [item.date() for item in frame.date]
    saved_env["frame"] = frame
    monkeypatch.setattr(study, "resolve_market_calendar", lambda as_of=None: (days, days[-1]))
    request = query(lookback_days=100, conditions=[{"field": "body_pct", "operator": "gt", "value": 0}])
    result = study.run_study(request)
    assert len(result.events) == 50 and result.events_total == 100
    assert result.distribution.count == 98
    assert len(study.study_events(result.run_id, offset=50, limit=100).items) == 50
    shape_request = query(
        lookback_days=100,
        conditions=[{"field": "shape_distance", "operator": "lte", "value": 100, "window": 3}],
        reference={"symbol": "000001", "as_of": str(days[2])},
    )
    shape_result = study.run_study(shape_request)
    sample = shape_result.events[-1]
    with pytest.raises(ValueError, match="同日窗口已排除"):
        study.study_evidence(shape_result.run_id, "000001", days[2])
    saved_env["frame"] = bars([100] * 100)
    evidence = study.study_evidence(shape_result.run_id, sample.symbol, sample.event_date)
    assert evidence.reference_bars[-1].close == 10.2
    assert evidence.conditions[0].matched


def test_refresh_uses_explicit_unfiltered_codes(saved_env, monkeypatch):
    from kan.domain.job import MarketRefreshScope
    from kan.service import job_service
    from kan.storage import workspace_db
    from kan.web.app import create_app

    received = []
    monkeypatch.setattr(job_service, "start_market_refresh_job", lambda request: received.append(request) or workspace_db.create_job("market_refresh:codes"))
    client = TestClient(create_app(session_required=False), base_url="http://127.0.0.1", headers={"X-Kan-Web": "1"})
    response = client.post("/api/v1/studies/refresh", json={"universe": "codes", "codes": ["000001", "000002"]})
    assert response.status_code == 202
    assert received[0].scope is MarketRefreshScope.CODES
    assert job_service._resolve_refresh_targets(received[0]) == ["000001", "000002"]

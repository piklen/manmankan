"""同源条件、行情边界与不创建研究的当前筛选主路径。"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kan.domain.market_study import StudyCondition, StudyQuery
from kan.service import market_study as study
from kan.service import trend_search as search
from kan.storage import paths, workspace_db


def bars(prices):
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-05", periods=len(prices)),
        "open": [value + .2 for value in prices], "close": prices,
        "high": [value + 1 for value in prices], "low": [value - 1 for value in prices],
        "volume": 1000., "_source": "synthetic",
    })


def metrics(frame, days=None):
    days = days or frame.date.dt.date.tolist()
    fields = [("up_days", None), ("down_days", None), ("bear_days", None), ("previous_down_days", None), ("previous_up_days", None), ("rising_days", 4), ("falling_days", 4)]
    return study.calculate_metrics(study.prepare_history(frame, days), fields)


def test_reversal_counts_daily_counts_and_exact_boundaries():
    frame = bars([15, 16, 14, 12, 13, 14])
    values, exact = metrics(frame)
    final = values.iloc[-1]
    assert final.up_days == 2 and final.previous_down_days == 2
    assert final.previous_up_days == 0 and final.bear_days == 6
    assert final["rising_days.4"] == 2 and final["falling_days.4"] == 2
    assert exact.previous_down_days.iloc[-1]
    # 前一跌段开始于缓存边界，只能确认至少两天，不能宣称恰好两天。
    values, exact = metrics(frame.iloc[1:])
    assert values.previous_down_days.iloc[-1] == 2 and not exact.previous_down_days.iloc[-1]
    assert not study.evaluate_condition(StudyCondition(field="previous_down_days", operator="eq", value=2), values, exact)[1].iloc[-1]
    assert study.evaluate_condition(StudyCondition(field="previous_down_days", operator="gte", value=2), values, exact)[0].iloc[-1]
    # 平盘会隔开前后段；缺行不会压缩成连续的市场交易日。
    flat, _ = metrics(bars([15, 16, 14, 12, 12, 14]))
    assert flat.previous_down_days.iloc[-1] == 0
    gap, _ = metrics(frame.drop(index=3), frame.date.dt.date.tolist())
    assert pd.isna(gap.previous_down_days.iloc[-1])
    assert pd.isna(gap["rising_days.4"].iloc[-1])
    # 对称的先涨后跌也使用同样边界。
    mirrored, mirror_exact = metrics(bars([15, 14, 16, 18, 17, 16]))
    assert mirrored.previous_up_days.iloc[-1] == 2 and mirror_exact.previous_up_days.iloc[-1]


@pytest.fixture
def market(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    frames = {
        "000001": bars([15, 16, 14, 12, 13, 14]),
        "000002": bars([15, 14, 16, 18, 17, 16]),
        "000003": bars([15, 16, 14, 12, 13]),
        "000004": None,
    }
    days = frames["000001"].date.dt.date.tolist()
    members = [(symbol, symbol) for symbol in frames]
    for service in (study, search):
        monkeypatch.setattr(service, "resolve_market_calendar", lambda as_of=None: (days, as_of or days[-1]))
        monkeypatch.setattr(service, "resolve_study_members", lambda universe, codes: [(code, code) for code in codes] if universe == "codes" else members)
    monkeypatch.setattr(search, "_industries", lambda: {"000001": "甲", "000002": "甲", "000003": "甲", "000004": "乙"})
    monkeypatch.setattr("kan.data.fetcher.get_cached", frames.get)
    return days, frames


def test_search_coverage_evidence_scope_and_study_use_same_conditions(market):
    days, frames = market
    query = search.TrendSearchQuery(universe="all", industries=["甲"], conditions=[
        StudyCondition(field="up_days", operator="gte", value=2),
        StudyCondition(field="previous_down_days", operator="eq", value=2),
    ])
    result = search.search_trends(query)
    assert result.coverage.model_dump() == {"total": 3, "evaluated": 2, "matched": 1, "missing": 1, "self_matches_excluded": 0}
    assert result.scope_codes == ["000001", "000002", "000003"]
    assert result.common_data_date == days[-1] and result.common_data_count == 2
    row = result.rows[0]
    assert row.current_segment.start_date == days[-2] and row.current_segment.base_date == days[-3]
    assert row.current_segment.return_pct == pytest.approx((14 / 12 - 1) * 100)
    assert row.sparkline[-1].date == days[-1] and row.positions["180"] is None
    evidence = search.trend_search_evidence(query, row.symbol)
    assert [item.actual for item in evidence.conditions] == [2, 2]
    assert evidence.bars[-1].change_pct > 0 and evidence.bars[-1].body_pct < 0
    study_query = StudyQuery(universe="codes", codes=result.scope_codes, conditions=query.conditions, lookback_days=5)
    historical = study.evaluate_study(study_query, [(code, code, frames[code]) for code in result.scope_codes], days, days[-1])[0]
    assert [item.symbol for item in historical.current_matches] == [row.symbol]
    assert historical.current_matches[0].values == {condition.key: row.values[condition.key] for condition in query.conditions}
    assert study.list_studies() == []


def test_explicit_date_shape_and_no_silent_stale_fallback(market, monkeypatch):
    days, frames = market
    frames["000001"] = bars([10, 11, 9, 10, 11, 9])
    frames["000002"] = bars([20, 22, 18, 20, 22, 18])
    query = search.TrendSearchQuery(universe="codes", codes=["000001", "000002"], reference={"symbol": "000001", "as_of": days[-1]}, conditions=[
        StudyCondition(field="shape_distance", operator="lte", value=.001, window=3),
    ])
    result = search.search_trends(query)
    assert result.coverage.self_matches_excluded == 1 and [row.symbol for row in result.rows] == ["000002"]
    evidence = search.trend_search_evidence(query, "000002")
    assert evidence.reference_bars[-1].close == 9 and evidence.conditions[0].actual == pytest.approx(0)
    old = search.TrendSearchQuery(universe="codes", codes=["000001"], as_of=days[3])
    before = search.search_trends(old)
    frames["000001"].loc[4:, ["open", "high", "low", "close"]] *= 10
    assert search.search_trends(old) == before
    for symbol in ("000001", "000002"):
        frames[symbol] = frames[symbol].iloc[:-1]
    with monkeypatch.context() as scoped:
        scoped.setattr(search, "calculate_metrics", lambda *args: pytest.fail("缺少截止日的对象不应计算指标"))
        stale = search.search_trends(search.TrendSearchQuery(universe="all"))
        with pytest.raises(ValueError, match="所选日期缺少有效行情"):
            search.trend_search_evidence(search.TrendSearchQuery(universe="all"), "000001")
    assert stale.rows == [] and stale.coverage.missing == 4
    assert stale.common_data_date == days[-2] and stale.common_data_count == 3
    assert stale.as_of == days[-1]


def test_saved_filter_http_cli_and_mcp_have_no_history_side_effect(market, monkeypatch):
    from kan.cli import app
    from kan.mcp.server import TOOLS
    from kan.web.app import create_app

    client = TestClient(create_app(session_required=False), base_url="http://127.0.0.1", headers={"X-Kan-Web": "1"})
    query = search.TrendSearchQuery(universe="codes", codes=["000001"], conditions=[StudyCondition(field="up_days", operator="gte", value=2)])
    # 保存的权限和成本只是保存条件，不应碰日历、行情或历史任务。
    with monkeypatch.context() as scoped:
        scoped.setattr(search, "resolve_market_calendar", lambda *args: pytest.fail("保存条件不应读取行情"))
        saved = client.post("/api/v1/trends/saved", json={"title": "先跌后涨观察", "query": query.model_dump(mode="json")})
        assert saved.status_code == 201, saved.text
        assert client.get("/api/v1/trends/saved").json()[0] == saved.json()
    response = client.post("/api/v1/trends/search", json=query.model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["coverage"]["matched"] == 1
    evidence = client.post("/api/v1/trends/search/evidence", json={"query": query.model_dump(mode="json"), "symbol": "000001"})
    assert evidence.status_code == 200 and evidence.json()["conditions"][0]["actual"] == 2
    run = CliRunner().invoke(app, ["trend", "--codes", "000001", "--up-days", "2", "--format", "json"])
    assert run.exit_code == 0, run.output
    assert json.loads(run.stdout) == response.json()
    at_most = CliRunner().invoke(app, ["trend", "--universe", "all", "--up-days", "2", "--comparison", "lte", "--format", "json"])
    assert at_most.exit_code == 0, at_most.output
    assert [row["symbol"] for row in json.loads(at_most.stdout)["rows"]] == ["000001"]
    zero = CliRunner().invoke(app, ["trend", "--codes", "000002", "--rising-days", "0", "--window", "2", "--comparison", "lte", "--format", "json"])
    assert zero.exit_code == 0, zero.output
    assert [row["symbol"] for row in json.loads(zero.stdout)["rows"]] == ["000002"]
    assert CliRunner().invoke(app, ["trend", "--up-days", "2"]).exit_code == 1
    assert CliRunner().invoke(app, ["trend", "--codes", "000001"]).exit_code == 1
    assert CliRunner().invoke(app, ["trend", "--down"]).exit_code != 0
    mcp = TOOLS["kan_trend"].handler(query.model_dump(mode="json"))
    assert json.loads(mcp["stdout"]) == response.json()
    compared = query.model_copy(update={"compare_to": "previous_session"})
    compared_response = client.post("/api/v1/trends/search", json=compared.model_dump(mode="json"))
    assert compared_response.json()["comparison"]["coverage"]["entered"] == 1
    compared_cli = CliRunner().invoke(app, ["trend", "--codes", "000001", "--up-days", "2", "--compare-to", "previous_session", "--format", "json"])
    assert compared_cli.exit_code == 0, compared_cli.output
    assert json.loads(compared_cli.stdout) == compared_response.json()
    assert json.loads(TOOLS["kan_trend"].handler(compared.model_dump(mode="json"))["stdout"]) == compared_response.json()
    prior_evidence = client.post("/api/v1/trends/search/evidence", json={"query": compared.model_dump(mode="json"), "symbol": "000001", "at": market[0][-2].isoformat()})
    assert prior_evidence.status_code == 200 and prior_evidence.json()["conditions"][0]["actual"] == 1
    assert study.list_studies() == [] and workspace_db.get_state("market_studies:index") is None
    assert client.delete(f"/api/v1/trends/saved/{saved.json()['id']}").json() == {"deleted": True}
    assert client.get("/api/v1/trends/saved").json() == []


def test_display_work_is_only_for_matches_browse_and_evidence_are_single_pass(market, monkeypatch):
    calls = []
    original = search.calculate_metrics

    def record(frame, fields, reference_prices=None):
        calls.append((frame, list(fields)))
        return original(frame, fields, reference_prices)

    monkeypatch.setattr(search, "calculate_metrics", record)
    query = search.TrendSearchQuery(universe="codes", codes=["000001", "000002"], conditions=[StudyCondition(field="up_days", operator="gte", value=2)])
    selected = search.search_trends(query)
    assert len(selected.rows) == 1
    assert calls[0][1] == calls[2][1] == [("up_days", None)]
    assert calls[0][0] is calls[1][0]
    assert ("up_days", None) not in calls[1][1]
    assert ("position", 180) in calls[1][1]
    calls.clear()
    browsed = search.search_trends(query.model_copy(update={"conditions": []}))
    assert len(calls) == 2 and all(("position", 180) in fields for frame, fields in calls)
    assert browsed.rows[0] == selected.rows[0]
    calls.clear()
    evidence = search.trend_search_evidence(query, "000001")
    assert len(calls) == 1 and ("position", 180) in calls[0][1]
    assert evidence.row == selected.rows[0]


def test_two_dates_share_one_read_and_unknown_never_becomes_entry_or_exit(market, monkeypatch):
    days, frames = market
    frames.clear()
    frames.update({
        "000001": bars([15, 16, 14, 12, 13, 14]),  # 1 → 2，新出现
        "000002": bars([15, 14, 12, 13, 14, 15]),  # 2 → 3，持续
        "000003": bars([15, 14, 12, 13, 14, 13]),  # 2 → 0，退出
        "000004": bars([15, 14, 13, 12, 11, 10]),  # 两日都不满足
        "000005": bars([15, 16, 14, 12, 13, 14]).drop(index=2),  # 至少 1 → 至少 2，不能叫新出现
        "000006": bars([15, 14, 12, 13, 14, 15]).iloc[:-1],  # 旧日满足、当前缺行，不能叫退出
        "000007": None,
    })
    reads = []
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda symbol: reads.append(symbol) or frames[symbol])
    query = search.TrendSearchQuery(universe="codes", codes=list(frames), compare_to="previous_session", conditions=[StudyCondition(field="up_days", operator="gte", value=2)])
    result = search.search_trends(query)
    changes = result.comparison
    assert changes.as_of == days[-2]  # 周一的上一交易日为周五，不能用自然日前一天。
    assert reads == list(frames)
    assert changes.coverage.model_dump() == {"comparable": 4, "entered": 1, "continued": 1, "exited": 1, "unchanged": 1, "uncertain": 3, "excluded": 0}
    assert result.coverage.total == changes.coverage.comparable + changes.coverage.uncertain + changes.coverage.excluded
    actual = {row.symbol: row for row in changes.rows}
    assert {code: row.status for code, row in actual.items()} == {"000001": "entered", "000002": "continued", "000003": "exited", "000005": "uncertain", "000006": "uncertain", "000007": "uncertain"}
    assert [row.symbol for row in result.rows] == ["000001", "000002", "000005"]
    assert actual["000003"].previous.conditions[0].actual == 2
    assert actual["000003"].current.conditions[0].actual == 0
    assert "要求 ≥ 2天" in actual["000003"].current.reason
    assert actual["000005"].previous.matched is None and actual["000005"].current.matched is True
    assert actual["000006"].previous.close == 14 and actual["000006"].current.close is None
    previous = search.trend_search_evidence(query, "000006", changes.as_of)
    assert previous.as_of == previous.bars[-1].date == changes.as_of
    assert previous.conditions[0].actual == 2
    with pytest.raises(ValueError, match="所选日期缺少有效行情"):
        search.trend_search_evidence(query, "000006")
    with pytest.raises(ValueError, match="本次截止日或对照日"):
        search.trend_search_evidence(query, "000001", days[-3])
    assert study.list_studies() == []


def test_comparison_dates_fixed_shape_and_prior_evidence_do_not_leak_later_prices(market):
    days, frames = market
    frames["000001"] = bars([10, 11, 9, 10, 11, 9])
    frames["000002"] = bars([20, 22, 18, 20, 22, 18])
    query = search.TrendSearchQuery(universe="codes", codes=["000001", "000002"], compare_to=days[-2], reference={"symbol": "000001", "as_of": days[-1]}, conditions=[StudyCondition(field="shape_distance", operator="lte", value=.001, window=3)])
    result = search.search_trends(query)
    assert result.comparison.coverage.entered == 1 and result.comparison.coverage.excluded == 1
    assert result.comparison.excluded_rows[0].symbol == "000001"
    assert any("事后形态检索" in warning for warning in result.warnings)
    evidence = search.trend_search_evidence(query, "000002", days[-2])
    assert evidence.reference_bars[-1].date == days[-1]
    assert evidence.bars[-1].date == days[-2]
    assert evidence.conditions[0].matched is False
    assert any("事后形态核对" in warning for warning in evidence.warnings)
    frames["000002"].loc[5, ["open", "high", "low", "close"]] *= 10
    assert search.trend_search_evidence(query, "000002", days[-2]) == evidence
    after = search.search_trends(query).comparison.coverage
    assert after.unchanged == 1 and after.entered == after.exited == 0
    for invalid in (days[-1], days[-1] + pd.Timedelta(days=1), days[-2] + pd.Timedelta(days=1)):
        with pytest.raises(ValueError, match="对照日必须"):
            search.search_trends(query.model_copy(update={"compare_to": invalid}))

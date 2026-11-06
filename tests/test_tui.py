"""真实研究终端路径；行情输入隔离，SQLite/Parquet、服务和界面一起运行。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest
from textual.widgets import DataTable, Input, Static
from typer.testing import CliRunner

from kan.cli import app as cli_app
from kan.domain.market_study import StudyCondition, StudyQuery
from kan.service import market_study
from kan.storage import paths
from kan.storage.positions import PositionsBook
from kan.storage.watchlist_models import Watchlist
from kan.tui.app import StudyApp


@pytest.fixture
def research_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    sessions = list(pd.bdate_range(end="2026-10-28", periods=220).date)
    prices = [10.0 + index * 0.1 for index in range(220)]
    frame = pd.DataFrame({
        "date": sessions, "open": [p - 0.05 for p in prices], "close": prices,
        "high": [p + 0.2 for p in prices], "low": [p - 0.2 for p in prices],
        "volume": [1000.0] * 220, "_source": ["synthetic_fixture"] * 220,
    })
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: set(sessions))
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda *_args, **_kwargs: sessions[-1])
    monkeypatch.setattr("kan.storage.watchlist.load_stock_names_cache", lambda **_kwargs: {"600519": "研究样本"})
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda symbol: frame.copy() if symbol == "600519" else None)
    monkeypatch.setattr("kan.storage.watchlist.load_watchlist", Watchlist)
    monkeypatch.setattr("kan.storage.positions.load_positions", PositionsBook)
    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda **_kwargs: {"600519": "合成行业"})
    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", lambda **_kwargs: [("600519", "研究样本"), ("000858", "缺行情样本")])
    query = StudyQuery(
        title="五日上涨研究", codes=["600519"], lookback_days=90, forward_days=5,
        sample_policy="every",
        conditions=[StudyCondition(field="return_pct", window=5, operator="gte", value=0)],
    )
    return query, frame


def test_saved_study_rerun_history_and_frozen_evidence(research_workspace) -> None:
    from kan.service.focus_service import add_focus

    query, frame = research_workspace
    original = market_study.run_study(query)
    add_focus("600519")

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("f")
            assert app.view == "screen"
            assert app.screen_result is None
            await pilot.press("t")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen_result.query.universe == "personal"
            assert app.screen_result.query.conditions == []
            assert app.screen_result.coverage.total == app.screen_result.coverage.matched == 1
            await pilot.press("slash")
            app.query_one(Input).value = "600519"
            await pilot.press("enter")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "filter_evidence"
            assert app.screen_evidence.row.symbol == "600519"
            assert app.screen_evidence.row.positions["180"] is not None
            await pilot.press("escape")
            assert app.query_one(Input).value == "600519"
            await pilot.press("a")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen_result.coverage.total == 2 and app.screen_result.coverage.missing == 1
            assert app.screen_result.query.universe == "all" and app.screen_result.query.conditions == []
            await pilot.press("l")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(DataTable).row_count == 1
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "current"
            assert app.result.run_id == original.run_id
            assert app.query_one(DataTable).row_count == 1
            await pilot.press("2")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "history"
            assert app.query_one(DataTable).row_count == 50
            await pilot.press("n")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.event_offset == 50
            assert app.query_one(DataTable).row_count == original.events_total - 50
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "evidence"
            evidence = app.evidence
            assert evidence.event_date < original.as_of
            assert evidence.conditions[0].actual >= 0
            assert evidence.outcome.status == "complete"
            assert evidence.source == "synthetic_fixture"
            old_close = evidence.outcome.event_close
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert app.query_one("#detail").size.height >= 3
            assert app.query_one("#back").region.right <= 80
            await pilot.press("escape")
            assert app.view == "history"
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.event_offset == 0
            await pilot.press("1")
            assert app.view == "current"
            # 改变上游缓存后同条件重跑；旧事件仍从封存材料读取。
            frame.loc[frame.index[-1], ["open", "close", "high", "low"]] = [9.9, 10, 10.2, 9.8]
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "current"
            assert app.result.run_id != original.run_id
            assert app.result.query.model_dump(exclude={"as_of"}) == query.model_dump(exclude={"as_of"})
            assert app.result.as_of == original.as_of
            assert app.result.current_matches == []
            assert app.result.diff.removed == ["600519"]
            frozen = market_study.study_evidence(original.run_id, "600519", evidence.event_date)
            assert frozen.outcome.event_close == old_close
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "studies"
            assert app.studies[0].last_run_id == app.result.run_id
            await pilot.press("q")

    asyncio.run(scenario())


def test_empty_search_help_and_rerun_error_preserve_saved_result(research_workspace, monkeypatch) -> None:
    query, _frame = research_workspace

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#empty").display
            assert "Ctrl+Enter" in str(app.query_one("#empty", Static).render())
            await pilot.press("escape")
            await pilot.press("?")
            assert app.view == "help"
            assert "kan study --help" in str(app.query_one("#detail-content", Static).render())
            await pilot.press("escape")
            result = market_study.run_study(query)
            await pilot.press("l")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("slash")
            app.query_one(Input).value = "没有这个研究"
            await pilot.pause()
            assert app.query_one("#empty").display
            await pilot.press("escape")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.result.run_id == result.run_id

            def unavailable(_study_id):
                raise ValueError("研究所需交易日历不可用")

            monkeypatch.setattr(market_study, "rerun_study", unavailable)
            await pilot.click("#rerun")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "交易日历不可用" in str(app.query_one("#status", Static).render())
            assert app.result.run_id == result.run_id
            assert app.query_one(DataTable).row_count == 1
            assert not app.query_one("#rerun", Button).disabled

    from textual.widgets import Button

    asyncio.run(scenario())


def test_non_tty_cannot_open_interactive_study(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(StudyApp, "run", lambda _self: pytest.fail("non-TTY must not hang"))
    result = CliRunner().invoke(cli_app, ["tui"])
    assert result.exit_code == 2
    assert "需要交互终端" in result.output
    assert "kan study --help" in result.output


def test_keyboard_filter_save_and_explicit_history(research_workspace) -> None:
    from textual.widgets import Select

    from kan.service import trend_search

    async def settled(app, pilot):
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f")
            assert app.screen_result is None
            assert app.query_one("#filter-kind", Select).value is Select.BLANK
            await pilot.press("ctrl+enter")
            assert "选择" in str(app.query_one("#status", Static).render())
            # 真键盘：选择上涨、全市场、填写3天，再执行。
            await pilot.press("enter", "down", "down", "down", "down", "down", "down", "enter", "tab", "enter", "down", "enter", "tab", "3", "ctrl+enter")
            await settled(app, pilot)
            assert app.screen_result is not None
            assert app.screen_result.query.universe == "all"
            assert app.screen_result.query.conditions[0].field == "up_days"
            assert app.screen_result.query.conditions[0].value == 3
            assert app.screen_result.coverage.total == 2
            assert app.screen_result.coverage.matched == app.screen_result.coverage.missing == 1
            assert market_study.list_studies() == []
            assert all(button.region.right <= 80 for button in app.query("#toolbar Button") if button.display)
            assert app.query_one(DataTable).region.right <= 80
            assert app.query_one(DataTable).size.height >= 3
            await pilot.press("m")
            assert app.view == "missing"
            assert "缺少" in str(app.query_one(DataTable).get_row_at(0)[2])
            await pilot.press("escape", "enter")
            await settled(app, pilot)
            assert app.view == "filter_evidence"
            assert app.screen_evidence.conditions[0].actual >= 3
            assert app.screen_evidence.row.current_segment.days >= 3
            assert app.screen_evidence.bars[-1].change_pct > 0
            await pilot.press("escape", "s")
            app.query_one("#save-title", Input).value = "连续上涨条件"
            await pilot.press("enter")
            await settled(app, pilot)
            assert len(trend_search.list_saved_trends()) == 1
            assert market_study.list_studies() == []
            await pilot.press("g")
            await settled(app, pilot)
            assert app.view == "saved_filters"
            await pilot.press("enter")
            await settled(app, pilot)
            assert app.view == "screen"
            await pilot.press("h")
            assert app.history_edit
            await pilot.press("ctrl+enter")
            assert market_study.list_studies() == []
            assert "回看" in str(app.query_one("#status", Static).render())
            app.query_one("#history-lookback", Input).value = "90"
            app.query_one("#history-forward", Input).value = "5"
            await pilot.click("#history-run")
            await settled(app, pilot)
            assert app.view == "history"
            assert len(market_study.list_studies()) == 1
            assert set(app.result.query.codes) == {"600519", "000858"}
            assert app.result.query.lookback_days == 90 and app.result.query.forward_days == 5
            await pilot.press("ctrl+q")

    asyncio.run(scenario())


def test_two_segments_counts_and_maximum_excludes_wrong_direction(research_workspace) -> None:
    from textual.widgets import Select

    _query, frame = research_workspace
    for index, price in zip(frame.index[-6:], [31.4, 31., 30., 29., 30., 31.], strict=True):
        frame.loc[index, ["open", "high", "low", "close"]] = [price - .1, price + .2, price - .2, price]

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("f")
            app.query_one("#filter-kind", Select).value = "down_then_up"
            app.query_one("#filter-universe", Select).value = "codes"
            app.query_one("#filter-codes", Input).value = "600519, 000858"
            app.query_one("#filter-operator", Select).value = "eq"
            app.query_one("#filter-days", Input).value = "2"
            app.query_one("#filter-other", Input).value = "3"
            await pilot.pause()
            await pilot.press("ctrl+enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen_result.coverage.matched == 1
            assert app.screen_result.rows[0].values["previous_down_days"] == 3
            assert app.screen_result.rows[0].values["up_days"] == 2
            await pilot.press("f")
            app.query_one("#filter-kind", Select).value = "falling"
            app.query_one("#filter-days", Input).value = "5"
            app.query_one("#filter-other", Input).value = "3"
            await pilot.pause()
            await pilot.press("ctrl+enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen_result.coverage.matched == 1
            assert app.screen_result.rows[0].values["falling_days.5"] == 3
            await pilot.press("f")
            app.query_one("#filter-kind", Select).value = "down_days"
            app.query_one("#filter-operator", Select).value = "lte"
            app.query_one("#filter-days", Input).value = "3"
            await pilot.pause()
            await pilot.press("ctrl+enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen_result.coverage.matched == 0
            assert any(c.field == "down_days" and c.operator == "gt" and c.value == 0 for c in app.screen_result.query.conditions)

    asyncio.run(scenario())


def test_saved_conditions_keep_dates_order_and_advanced_filters(research_workspace) -> None:
    from textual.widgets import Select

    from kan.service.trend_search import TrendSearchQuery
    from kan.tui.conditions import TrendFilterForm

    _query, frame = research_workspace
    day, previous = frame.date.iloc[-1], frame.date.iloc[-2]

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f")
            form = app.query_one(TrendFilterForm)
            # Web 使用前段→当前段顺序；TUI 仍能完整回填并保留两个日期。
            saved = TrendSearchQuery(universe="codes", codes=["600519"], as_of=day, compare_to=previous, conditions=[
                StudyCondition(field="previous_down_days", operator="gte", value=3),
                StudyCondition(field="up_days", operator="gte", value=2),
            ])
            form.set_query(saved)
            await pilot.pause()
            restored = form.read_query()
            assert restored.as_of == day and restored.compare_to == previous
            assert {c.key: c.value for c in restored.conditions} == {"up_days": 2, "previous_down_days": 3}
            assert app.query_one("#filter-kind", Select).value == "down_then_up"
            # > 0 是真实涨幅条件，不是连续段的合成方向限制。
            advanced = saved.model_copy(update={"as_of": None, "conditions": [
                StudyCondition(field="up_days", operator="gte", value=3),
                StudyCondition(field="return_pct", window=20, operator="gt", value=0),
            ]})
            form.set_query(advanced)
            await pilot.pause()
            assert app.query_one("#filter-kind", Select).disabled
            assert form.read_query() == advanced
            app.query_one("#filter-as-of", Input).value = str(day)
            assert form.read_query().conditions == advanced.conditions
            assert form.read_query().as_of == day
            # 单独的 <= 3 允许零；不能在编辑时偷偷补成 1–3。
            unbounded = TrendSearchQuery(universe="codes", codes=["600519"], conditions=[StudyCondition(field="up_days", operator="lte", value=3)])
            form.set_query(unbounded)
            await pilot.pause()
            assert form.read_query() == unbounded
            assert app.query_one("#filter-kind", Select).disabled
            bounded = unbounded.model_copy(update={"conditions": [*unbounded.conditions, StudyCondition(field="up_days", operator="gt", value=0)]})
            form.set_query(bounded)
            await pilot.pause()
            assert not app.query_one("#filter-kind", Select).disabled
            assert form.read_query() == bounded
            await pilot.press("ctrl+n")
            assert not app.query_one("#filter-kind", Select).disabled
            assert app.query_one("#filter-kind", Select).value is Select.BLANK
            assert app.query_one("#filter-as-of", Input).value == ""
            assert app.query_one("#filter-compare", Select).value == "none"

    asyncio.run(scenario())


def test_swing_cli_form_evidence_and_historical_parameters(research_workspace) -> None:
    import json

    from textual.widgets import Select

    from kan.service.trend_search import TrendSearchQuery
    from kan.tui.conditions import TrendFilterForm

    _query, frame = research_workspace
    prices = [10, 11, 12, 11, 10.8, 12, 13, 12, 11.5, 13, 14, 13, 12.5, 14, 15, 14, 13.5, 15, 16, 15, 14.5, 15.5]
    tail = frame.index[-len(prices):]
    frame.loc[tail, "close"] = prices
    frame.loc[tail, "open"] = [price - .05 for price in prices]
    frame.loc[tail, "high"] = [price + .2 for price in prices]
    frame.loc[tail, "low"] = [price - .2 for price in prices]
    args = ["trend", "--codes", "600519", "--window", "22", "--swing", "up", "--reversal-pct", "4", "--format", "json"]
    run = CliRunner().invoke(cli_app, args)
    assert run.exit_code == 0, run.output
    result = json.loads(run.stdout)
    assert result["coverage"]["matched"] == 1
    saved = TrendSearchQuery.model_validate(result["query"])
    assert saved.swing_reversal_pct == 4
    factors = CliRunner().invoke(cli_app, ["trend", "--codes", "600519", "--window", "15", "--bull-excess", "0", "--return-above", "0", "--format", "json"])
    assert factors.exit_code == 0, factors.output
    assert [(c["field"], c["operator"], c["value"]) for c in json.loads(factors.stdout)["query"]["conditions"]] == [("candle_balance", "gt", 0), ("return_pct", "gt", 0)]
    assert CliRunner().invoke(cli_app, ["trend", "--codes", "600519", "--swing", "up"]).exit_code == 1

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f")
            form = app.query_one(TrendFilterForm)
            form.set_query(saved)
            await pilot.pause()
            assert app.query_one("#filter-kind", Select).value == "swing_up"
            assert not app.query_one("#filter-kind", Select).disabled
            assert form.read_query() == saved
            assert app.query_one("#filter-reversal", Input).display
            assert not app.query_one("#filter-operator", Select).display
            assert app.query_one("#filter-run").region.right <= 80
            await pilot.press("ctrl+enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen_result.coverage.matched == 1
            assert "上升结构" in str(app.query_one(DataTable).get_row_at(0)[3])
            assert "已确认点关系：上升结构" in str(app.query_one(DataTable).get_row_at(0)[2])
            assert "回撤" not in str(app.query_one(DataTable).get_row_at(0)[2])
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen_evidence.swings[0].structure == 1
            assert app.screen_evidence.swings[0].reversal_pct == 4
            assert all(p.confirmed_at > p.date for p in app.screen_evidence.swings[0].pivots)
            await pilot.press("escape", "h")
            app.query_one("#history-lookback", Input).value = "30"
            app.query_one("#history-forward", Input).value = "3"
            await pilot.click("#history-run")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.result.query.swing_reversal_pct == 4
            # 高阶混合条件仍无损保留，不用简易表单擅自重写。
            advanced = saved.model_copy(update={"conditions": [*saved.conditions, StudyCondition(field="trend_efficiency", operator="gte", value=.2, window=15)]})
            form.set_query(advanced)
            await pilot.pause()
            assert form.read_query() == advanced
            assert app.query_one("#filter-kind", Select).disabled

    asyncio.run(scenario())


def test_swing_rendering_distinguishes_confirmed_structure_from_current_break() -> None:
    from kan.domain.market_study import SwingEvidence
    from kan.render.trend import swing_phase
    from kan.tui.screens import swing_view

    for structure, direction, intact, crossed in ((1, -1, "当前回撤", "已越过最近确认波谷"), (-1, 1, "当前反弹", "已越过最近确认波峰")):
        listed = swing_phase({"swing_structure.60": structure, "swing_direction.60": direction}, 60)
        assert "已确认点关系" in listed and intact not in listed
        evidence = SwingEvidence(window=60, reversal_pct=5, structure=structure, direction=direction)
        assert intact not in swing_view(evidence).renderables[0].plain
        evidence.structure_broken = False
        assert intact in swing_view(evidence).renderables[0].plain
        evidence.structure_broken = True
        title = swing_view(evidence).renderables[0].plain
        assert crossed in title and intact not in title


def test_stale_day_change_review_and_both_daily_evidence(research_workspace, monkeypatch) -> None:
    from datetime import timedelta

    from textual.widgets import Select

    _query, base = research_workspace
    day, previous = base.date.iloc[-1], base.date.iloc[-2]
    frames = {}
    for code, prices in {
        "600519": [10, 11, 10, 9, 10, 11],  # 首次达到连续两日
        "000858": [10, 11, 9, 10, 11, 12],  # 两日均满足
        "000001": [10, 11, 9, 10, 11, 10],  # 当前已不满足
        "000002": [10, 11, 9, 10, 11, 12],  # 当前缺行情，不算退出
    }.items():
        frame = base.copy()
        for index, price in zip(frame.index[-6:], prices, strict=True):
            frame.loc[index, ["open", "high", "low", "close"]] = [price - .1, price + .2, price - .2, price]
        frames[code] = frame.iloc[:-1] if code == "000002" else frame
    sessions = [*base.date, day + timedelta(days=1)]
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: set(sessions))
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda *_a, **_k: sessions[-1])
    monkeypatch.setattr("kan.data.fetcher.get_cached", frames.get)

    async def settled(app, pilot):
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f")
            app.query_one("#filter-kind", Select).value = "up_days"
            app.query_one("#filter-universe", Select).value = "codes"
            app.query_one("#filter-codes", Input).value = ",".join(frames)
            app.query_one("#filter-days", Input).value = "2"
            app.query_one("#filter-compare", Select).value = "previous_session"
            await pilot.press("ctrl+enter")
            await settled(app, pilot)
            assert app.screen_result.coverage.evaluated == 0
            assert "暂无可判断" in str(app.query_one("#empty", Static).render())
            assert str(day) in str(app.query_one("#common-date-text", Static).render())
            assert app.query_one("#use-common-date").region.right <= 80
            await pilot.press("d")
            await settled(app, pilot)
            result = app.screen_result
            assert result.as_of == day and result.comparison.as_of == previous
            assert result.coverage.matched == 2
            assert {r.status for r in result.comparison.rows} == {"entered", "continued", "exited", "uncertain"}
            assert app.query_one("#filter-as-of", Input).value == str(day)
            assert all(button.region.right <= 80 for button in app.query("#toolbar Button") if button.display)
            await pilot.press("c")
            assert app.view == "changes" and app.query_one(DataTable).row_count == 4
            assert all(button.region.right <= 80 for button in app.query("#toolbar Button") if button.display)
            app.query_one("#change-mode", Select).value = "entered"
            await pilot.pause()
            assert app.query_one(DataTable).row_count == 1
            await pilot.press("enter", "2")
            await settled(app, pilot)
            assert app.view == "filter_evidence" and app.screen_evidence.as_of == previous
            assert app.screen_evidence.conditions[0].matched is False
            assert all(button.region.right <= 80 for button in app.query("#toolbar Button") if button.display)
            await pilot.press("escape", "1")
            await settled(app, pilot)
            assert app.screen_evidence.as_of == day and app.screen_evidence.conditions[0].matched is True
            await pilot.press("escape", "escape")
            assert app.view == "changes"
            app.query_one("#change-mode", Select).value = "uncertain"
            await pilot.pause()
            await pilot.press("enter", "1")
            assert app.view == "change_detail"
            assert "缺少有效日线" in str(app.query_one("#status", Static).render())
            await pilot.press("2")
            await settled(app, pilot)
            assert app.screen_evidence.as_of == previous and app.screen_evidence.row.symbol == "000002"
            assert market_study.list_studies() == []

    asyncio.run(scenario())


def test_discovery_default_drilldown_and_advanced_state_at_80_columns(research_workspace, monkeypatch) -> None:
    from datetime import timedelta

    from kan.service import discovery
    from kan.service.trend_search import TrendSearchQuery
    from kan.tui.conditions import TrendFilterForm
    from kan.tui.discovery import DiscoveryScreen

    _query, frame = research_workspace
    data_day = frame.date.iloc[-1]
    latest = data_day + timedelta(days=1)
    monkeypatch.setattr("kan.core.trading_calendar.get_trade_dates", lambda: {*frame.date, latest})
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda *_a, **_kw: latest)

    async def settle(app, pilot):
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def scenario() -> None:
        app = StudyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            assert isinstance(screen, DiscoveryScreen)
            assert screen.result.as_of == latest and screen.result.market.current.available == 0
            assert screen.result.common_data_date == data_day
            assert screen.query_one("#discovery-common").display
            assert screen.query_one("#discovery-run").region.right <= 80
            assert screen.query_one("#discovery-results").size.height >= 3
            screen.query_one("#discovery-window", Input).value = "10"
            await pilot.press("d")
            await settle(app, pilot)
            assert screen.result.as_of == data_day
            assert screen.query_one("#discovery-date", Input).value == str(data_day)
            assert screen.result.query.window == 10
            assert screen.result.market.current.available == screen.result.market.current.missing == 1
            screen.query_one("#discovery-window", Input).value = "15"
            await pilot.press("ctrl+enter")
            await settle(app, pilot)
            assert screen.result.query.window == 15
            assert app.screen_result is None  # 父应用快捷键不能在观察页背后运行筛选。
            await pilot.press("v")
            assert screen.view == "profile"
            assert screen.query_one("#discovery-detail").size.height >= 3
            await pilot.press("escape", "enter")
            assert screen.view == "members" and screen.industry == "合成行业"
            await pilot.press("enter")
            await settle(app, pilot)
            assert screen.view == "evidence"
            await pilot.press("escape", "escape")
            assert screen.view == "industries"
            observed = screen.result

            def unavailable(_query):
                raise ValueError("日历资料暂不可用")

            monkeypatch.setattr(discovery, "discover_market", unavailable)
            await pilot.press("ctrl+enter")
            await settle(app, pilot)
            assert screen.result is observed
            assert "日历资料暂不可用" in str(screen.query_one("#discovery-status", Static).render())
            await pilot.press("f")
            advanced = TrendSearchQuery(universe="codes", codes=["600519"], as_of=data_day, conditions=[StudyCondition(field="return_pct", operator="gt", value=0, window=10)])
            app.query_one(TrendFilterForm).set_query(advanced)
            await pilot.press("ctrl+enter")
            await settle(app, pilot)
            filtered = app.screen_result
            assert filtered.coverage.matched == 1
            await pilot.press("o")
            assert app.screen is screen
            assert screen.result is observed
            await pilot.press("f")
            assert app.screen_result is filtered
            assert app.query_one(TrendFilterForm).read_query() == advanced
            assert market_study.list_studies() == []

    asyncio.run(scenario())

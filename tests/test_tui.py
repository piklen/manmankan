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
            assert app.screen_result is None
            assert app.query_one("#filter-kind", Select).value is Select.BLANK
            await pilot.press("ctrl+enter")
            assert "选择" in str(app.query_one("#status", Static).render())
            # 真键盘：选择上涨、全市场、填写3天，再执行。
            await pilot.press("enter", "down", "enter", "tab", "enter", "down", "enter", "tab", "3", "ctrl+enter")
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

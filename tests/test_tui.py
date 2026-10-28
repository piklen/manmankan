"""真实 Textual 事件路径：键盘浏览、笔记持久化、失败与退出任务边界。"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

import pytest
from textual.widgets import DataTable, Input, Static, TextArea
from typer.testing import CliRunner

from kan.cli import app as cli_app
from kan.domain.focus import FocusPeriod, FocusRow
from kan.domain.job import JobStatus
from kan.domain.screen import CandidateStatus
from kan.service import focus_service, job_service
from kan.storage import paths, workspace_db
from kan.storage.positions import PositionsBook
from kan.storage.watchlist_models import Watchlist
from kan.tui.app import FocusApp
from kan.tui.screens import AddFocusScreen, DetailScreen, HelpScreen


@pytest.fixture
def focus_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    monkeypatch.setattr(focus_service.watchlist, "load_watchlist", Watchlist)
    monkeypatch.setattr(focus_service.positions, "load_positions", PositionsBook)
    monkeypatch.setattr(focus_service.watchlist, "load_stock_names_cache", lambda **_: {})
    monkeypatch.setattr(focus_service, "_cached_expected_cutoff", lambda: date(2026, 10, 28))

    def fill(row: FocusRow, _expected: date | None) -> None:
        row.available = True
        row.stale = False
        row.price = 100.0
        row.change_pct = 1.0
        row.data_cutoff = date(2026, 10, 28)
        row.previous_cutoff = date(2026, 10, 27)
        row.source = "test_fixture"
        row.periods = [
            FocusPeriod(
                period=period, position_pct=50.0, previous_position_pct=48.0,
                change_pp=2.0, low=80, high=120,
            )
            for period in (30, 60, 180)
        ]

    monkeypatch.setattr(focus_service, "_fill_market", fill)
    for symbol, name in (("600519", "贵州茅台"), ("000858", "五粮液")):
        workspace_db.upsert_candidate(
            list_id="default", symbol=symbol, name=name,
            status=CandidateStatus.WATCH, note="核对下一期财报",
        )
    return tmp_path


def test_tui_non_tty_fails_without_starting_application(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*_args, **_kwargs) -> None:
        pytest.fail("non-TTY invocation opened the TUI")

    monkeypatch.setattr(FocusApp, "run", fail_run)
    result = CliRunner().invoke(cli_app, ["tui"])
    assert result.exit_code == 2
    assert "需要交互终端" in result.output
    assert "kan daily --format json" in result.output


def test_tui_entry_does_not_launch_background_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.cli import main as cli_runtime

    def unexpected(*_args, **_kwargs):
        pytest.fail("TUI startup registered background network work")

    monkeypatch.setattr(sys, "argv", ["kan", "tui"])
    monkeypatch.setattr(cli_runtime, "app", lambda: None)
    monkeypatch.setattr("kan.storage.stock_names_refresh.maybe_start_stock_names_refresh", unexpected)
    monkeypatch.setattr("atexit.register", unexpected)
    cli_runtime.cli_main()


def test_tui_tty_entry_runs_application(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.cli.tui_cmds import tui

    called: list[bool] = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(FocusApp, "run", lambda _self: called.append(True))
    tui()
    assert called == [True]


def test_keyboard_browse_search_note_and_review(focus_workspace: Path) -> None:
    async def scenario() -> None:
        app = FocusApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one(DataTable)
            assert table.row_count == 2
            initial = app.selected_symbol
            await pilot.press("down", "enter")
            assert isinstance(app.screen, DetailScreen)
            assert app.screen.row.symbol != initial
            selected = app.screen.row.symbol
            editor = app.screen.query_one(TextArea)
            editor.load_text("[观察] 收入与现金流还需核对")
            editor.focus()
            await pilot.press("ctrl+s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            saved = workspace_db.list_candidate_lists()[0].candidates
            assert next(row for row in saved if row.symbol == selected).note == editor.text
            assert "已保存" in str(app.screen.query_one("#note-status", Static).render())
            await pilot.press("escape")
            assert not isinstance(app.screen, DetailScreen)
            await pilot.press("v")
            await app.workers.wait_for_complete()
            assert next(row for row in app.snapshot.rows if row.symbol == selected).reviewed
            await pilot.press("slash")
            app.query_one(Input).value = "600519"
            await pilot.pause()
            assert table.row_count == 1
            assert app.visible_rows[0].symbol == "600519"
            await pilot.press("escape")
            assert table.row_count == 2
            await pilot.press("?")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert len(table.columns) == 6
            assert table.size.height > 2
            assert app.query_one("#update-data").region.right <= 80
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, DetailScreen)
            assert app.screen.query_one("#save-note").region.bottom <= 24
            assert app.screen.query_one("#detail-close").region.bottom <= 24
            assert app.screen.query_one("#detail-evidence").size.height >= 4
            history = str(app.screen.query_one("#detail-history", Static).render())
            assert "当时收盘 100.00" in history
            assert "30日 50.00% / 60日 50.00% / 180日 50.00%" in history
            assert "当时观察：[观察] 收入与现金流还需核对" in history

    asyncio.run(scenario())


def test_add_empty_and_invalid_code(focus_workspace: Path) -> None:
    for candidate in workspace_db.list_candidate_lists()[0].candidates:
        workspace_db.remove_candidate("default", candidate.symbol)

    async def scenario() -> None:
        app = FocusApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#empty").display
            await pilot.press("a")
            assert isinstance(app.screen, AddFocusScreen)
            app.screen.query_one(Input).value = "oops"
            await pilot.press("enter")
            assert isinstance(app.screen, AddFocusScreen)
            assert "6 位" in str(app.screen.query_one("#add-error", Static).render())
            app.screen.query_one(Input).value = "600519"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(DataTable).row_count == 1
            assert app.selected_symbol == "600519"
            assert workspace_db.list_candidate_lists()[0].candidates[0].symbol == "600519"

    asyncio.run(scenario())


def test_load_and_save_errors_keep_existing_records(
    focus_workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = FocusApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("n")
            assert isinstance(app.screen, DetailScreen)
            app.screen.query_one(TextArea).load_text("尚未保存的观察")

            def fail_save(*_args, **_kwargs) -> None:
                raise OSError("disk full")

            monkeypatch.setattr(focus_service, "update_focus_note", fail_save)
            await pilot.press("ctrl+s")
            assert "保存失败" in str(app.screen.query_one("#note-status", Static).render())
            assert all(row.note == "核对下一期财报" for row in workspace_db.list_candidate_lists()[0].candidates)
            await pilot.press("escape")
            assert isinstance(app.screen, DetailScreen)
            await pilot.press("escape")
            assert not isinstance(app.screen, DetailScreen)

            def fail_load():
                raise OSError("cannot read cache")

            monkeypatch.setattr(focus_service, "build_focus_snapshot", fail_load)
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "读取失败" in str(app.query_one("#status", Static).render())
            assert app.query_one(DataTable).row_count == 2

    asyncio.run(scenario())


def test_buttons_save_limits_and_review_saved_note(focus_workspace: Path) -> None:
    async def scenario() -> None:
        app = FocusApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#add-focus")
            await pilot.click("#add-cancel")
            assert app.query_one(DataTable).row_count == 2
            await pilot.click("#add-focus")
            app.screen.query_one(Input).value = "300750"
            await pilot.click("#add-submit")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(DataTable).row_count == 3
            await pilot.press("enter")
            editor = app.screen.query_one(TextArea)
            editor.load_text("a" * 2001)
            await pilot.click("#save-note")
            assert "最多 2000 字" in str(app.screen.query_one("#note-status", Static).render())
            editor.load_text("先核对现金流")
            await pilot.click("#review-row")
            assert "先保存" in str(app.screen.query_one("#note-status", Static).render())
            await pilot.click("#save-note")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#review-row")
            await app.workers.wait_for_complete()
            assert app.screen.query_one("#review-row").disabled
            row = next(item for item in focus_service.build_focus_snapshot().rows if item.symbol == "300750")
            assert row.reviewed
            assert row.review_history[0].note == "先核对现金流"
            await pilot.click("#detail-close")
            await pilot.press("?")
            await pilot.click("#help-close")
            assert not isinstance(app.screen, HelpScreen)

    asyncio.run(scenario())


def test_first_load_failure_recovers_and_missing_market_is_explained(
    focus_workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = focus_service.build_focus_snapshot

    def fail_load():
        raise OSError("cache unavailable")

    monkeypatch.setattr(focus_service, "build_focus_snapshot", fail_load)

    async def scenario() -> None:
        app = FocusApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "读取失败" in str(app.query_one("#status", Static).render())
            assert app.query_one("#empty").display
            await pilot.press("v")
            monkeypatch.setattr(focus_service, "build_focus_snapshot", loader)

            def missing(row: FocusRow, _expected: date | None) -> None:
                row.message = "尚无本地行情，请更新"

            monkeypatch.setattr(focus_service, "_fill_market", missing)
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one(DataTable).focus()
            await pilot.press("slash")
            app.query_one(Input).value = "不存在"
            await pilot.press("enter")
            assert app.query_one("#empty").display
            await pilot.press("escape", "enter")
            assert isinstance(app.screen, DetailScreen)
            assert app.screen.query_one("#review-row").disabled
            assert "尚无行情" in str(app.screen.query_one("#detail-facts", Static).render())

    asyncio.run(scenario())


def test_refresh_start_and_poll_errors_do_not_disable_browsing(
    focus_workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cannot_start(_request):
        raise OSError("queue unavailable")

    monkeypatch.setattr(job_service, "start_market_refresh_job", cannot_start)

    async def scenario() -> None:
        app = FocusApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#update-data")
            assert "queue unavailable" in str(app.query_one("#status", Static).render())
            assert not app.query_one("#update-data").disabled
            job = workspace_db.create_job("market_refresh:focus")
            monkeypatch.setattr(job_service, "start_market_refresh_job", lambda _request: job)
            await pilot.click("#update-data")
            app.action_update()
            assert app.refresh_job_id == job.job_id
            real_get = job_service.get_job

            def cannot_poll(_job_id):
                raise OSError("busy database")

            monkeypatch.setattr(job_service, "get_job", cannot_poll)
            app._poll_job()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "busy database" in str(app.query_one("#status", Static).render())
            assert app.query_one(DataTable).row_count == 2
            monkeypatch.setattr(job_service, "get_job", real_get)

    asyncio.run(scenario())


def test_refresh_failure_remains_visible_and_quit_closes_only_own_job(
    focus_workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = workspace_db.create_job("market_refresh:focus", message="正在更新测试数据")
    unrelated = workspace_db.create_job("market_refresh:all", message="另一个进程的任务")
    monkeypatch.setattr(job_service, "start_market_refresh_job", lambda _request: owned)

    async def scenario() -> None:
        app = FocusApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("u")
            assert app.refresh_job_id == owned.job_id
            assert app.query_one("#update-data").disabled
            await pilot.press("down", "enter")
            assert isinstance(app.screen, DetailScreen)
            await pilot.press("escape", "q")
        assert workspace_db.get_job(owned.job_id).status is JobStatus.INTERRUPTED
        assert workspace_db.get_job(unrelated.job_id).status is JobStatus.QUEUED

        failed = workspace_db.create_job("market_refresh:focus")
        workspace_db.update_job(failed.job_id, status=JobStatus.FAILED, error="provider unavailable")
        monkeypatch.setattr(job_service, "start_market_refresh_job", lambda _request: failed)
        app = FocusApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("u")
            app._poll_job()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.refresh_job_id is None
            assert "provider unavailable" in str(app.query_one("#status", Static).render())
            assert not app.query_one("#update-data").disabled

        partial = workspace_db.create_job("market_refresh:focus")
        workspace_db.update_job(
            partial.job_id, status=JobStatus.PARTIAL,
            message="已更新 1 只，1 只未更新", error="1 只未更新",
        )
        monkeypatch.setattr(job_service, "start_market_refresh_job", lambda _request: partial)
        app = FocusApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("u")
            app._poll_job()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.refresh_job_id is None
            assert "1 只未更新" in str(app.query_one("#status", Static).render())
            assert app.query_one(DataTable).row_count == 2

    asyncio.run(scenario())

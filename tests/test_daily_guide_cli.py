from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import PeriodResult, StockScanResult
from kan.core.pipeline import Freshness


def _row(symbol: str, name: str, pos_180: float, *, permission: str | None = None, vp_state: str | None = None):
    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=10.0,
        scan_date=date(2026, 6, 18),
        periods=[
            PeriodResult(
                period=180,
                n_low=8,
                n_high=12,
                position_pct=pos_180,
                at_low=pos_180 <= 5,
                at_high=pos_180 >= 95,
            )
        ],
        low_resonance=1 if pos_180 <= 10 else 0,
        high_resonance=1 if pos_180 >= 90 else 0,
        permission_note=permission,
        volume_price_state=vp_state,
    )


def test_guide_runs_and_lists_copyable_commands() -> None:
    result = CliRunner().invoke(app, ["guide", "--topic", "holdings"])
    assert result.exit_code == 0
    assert "kan hold add" in result.output
    assert "kan hold cash" in result.output


def test_daily_json_uses_fact_summary(monkeypatch) -> None:
    rows = [
        _row("600519", "Alpha", 5),
        _row("688981", "Star", 95, permission="需科创板权限"),
    ]
    freshness = Freshness(
        data_cutoff=date(2026, 6, 18),
        fetched_at="2026-06-18 23:41",
        expected_cutoff=date(2026, 6, 18),
        is_stale=False,
        phase="post",
    )
    from kan.infra.lifecycle import CollectingReporter

    fake_result = SimpleNamespace(
        results=rows,
        ctx=SimpleNamespace(freshness=freshness),
    )
    reporter = CollectingReporter()
    monkeypatch.setattr("kan.infra.progress.operation_reporter", lambda: reporter)
    monkeypatch.setattr(
        "kan.service.scan_service.run_scan",
        lambda request, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist",
        lambda: SimpleNamespace(stocks=[object(), object()]),
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: SimpleNamespace(positions=[object()], cash=10000),
    )

    result = CliRunner().invoke(app, ["daily", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["pool"]["watchlist_count"] == 2
    assert payload["pool"]["holding_count"] == 1
    assert payload["facts"]["period_180_low_lte_10_count"] == 1
    assert payload["facts"]["period_180_high_gte_90_count"] == 1
    assert payload["facts"]["permission_note_count"] == 1
    assert len({event.operation_id for event in reporter.events}) == 1
    assert reporter.events[-1].state.value == "succeeded"


def _stub_daily_env(monkeypatch, rows) -> None:
    from kan.infra.lifecycle import CollectingReporter

    freshness = Freshness(
        data_cutoff=date(2026, 6, 18),
        fetched_at="2026-06-18 23:41",
        expected_cutoff=date(2026, 6, 18),
        is_stale=False,
        phase="post",
    )
    fake_result = SimpleNamespace(
        results=rows,
        ctx=SimpleNamespace(freshness=freshness),
    )
    monkeypatch.setattr(
        "kan.infra.progress.operation_reporter", lambda: CollectingReporter()
    )
    monkeypatch.setattr(
        "kan.service.scan_service.run_scan",
        lambda request, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist",
        lambda: SimpleNamespace(stocks=[object()]),
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: SimpleNamespace(positions=[], cash=0),
    )


def test_daily_json_includes_direction_counts(monkeypatch) -> None:
    rows = [
        _row("600519", "Alpha", 50, vp_state="量增·收涨"),
        _row("000858", "Beta", 50, vp_state="量缩·收跌"),
        _row("002594", "Gamma", 50, vp_state="量平·收平"),
        _row("601318", "Delta", 50, vp_state=None),
    ]
    _stub_daily_env(monkeypatch, rows)

    result = CliRunner().invoke(app, ["daily", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["facts"]["direction_up"] == 1
    assert payload["facts"]["direction_down"] == 1
    assert payload["facts"]["direction_flat"] == 1


def test_daily_terminal_shows_direction_line(monkeypatch) -> None:
    rows = [
        _row("600519", "Alpha", 50, vp_state="量平·收涨"),
        _row("000858", "Beta", 50, vp_state="量平·收跌"),
        _row("002594", "Gamma", 50, vp_state="量平·收跌"),
    ]
    _stub_daily_env(monkeypatch, rows)

    result = CliRunner().invoke(app, ["daily"], env={"COLUMNS": "100"})

    assert result.exit_code == 0, result.output
    assert "涨 1" in result.output
    assert "跌 2" in result.output
    assert "平 0" in result.output


def test_daily_wrap_names_hanging_indent() -> None:
    """长名单折行时续行悬挂缩进,不顶格;markup 标签不计入显示宽。"""
    from kan.cli.daily_cmds import _wrap_names

    prefix = "  180日位置 [green]<=10%[/green] · [bold]42[/bold] 只: "
    names = [f"股票{i:02d} 60{i:04d}" for i in range(10)]

    out = _wrap_names(prefix, names, 60)

    lines = out.split("\n")
    assert len(lines) > 1  # 确实折行
    for cont in lines[1:]:
        assert cont.startswith("    ")  # 续行悬挂缩进
    from rich.text import Text
    for line in lines:
        assert Text.from_markup(line).cell_len <= 60

    # 短名单不折行 · 空名单出占位符
    assert "\n" not in _wrap_names("p: ", ["甲 600519"], 80)
    assert _wrap_names("p: ", [], 80) == "p: -"

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import PeriodResult, StockScanResult
from kan.core.pipeline import Freshness


def _row(symbol: str, name: str, pos_180: float, *, permission: str | None = None):
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
    fake_result = SimpleNamespace(
        results=rows,
        ctx=SimpleNamespace(freshness=freshness),
    )
    monkeypatch.setattr("kan.service.scan_service.run_scan", lambda request: fake_result)
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

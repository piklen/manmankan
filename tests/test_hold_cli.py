"""`kan hold` CLI 测试。"""
from __future__ import annotations

import json
from datetime import date

import pytest
from typer.testing import CliRunner

from kan.cli import app


@pytest.fixture
def isolated_hold_storage(tmp_path, monkeypatch):
    from kan.cli import hold_cmds
    from kan.storage import positions

    base = tmp_path / "kan"
    monkeypatch.setattr(positions, "POSITIONS_PATH", base / "positions.json")
    monkeypatch.setattr(positions, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        positions,
        "_load_cached_names",
        lambda: {"600519": "贵州茅台", "000858": "五粮液"},
    )
    monkeypatch.setattr(hold_cmds, "_cached_market_value", lambda _symbol, shares: shares * 1680.0)
    return positions


def _fake_summary():
    from kan.core.positions import AccountView, PositionHealth, PositionsSummary, PositionView

    row = PositionView(
        symbol="600519",
        name="贵州茅台",
        cost=1680.5,
        shares=100,
        price=1700.0,
        prev_close=1690.0,
        market_value=170000.0,
        cost_value=168050.0,
        weight_pct=70.0,
        daily_pnl=1000.0,
        daily_pnl_pct=0.59,
        total_pnl=1950.0,
        total_pnl_pct=1.16,
        positions={30: 20.0, 60: 50.0, 180: 80.0},
        price_source="realtime",
        price_status="ok",
    )
    return PositionsSummary(
        results=[row],
        account=AccountView(
            cash=73000.0,
            total_market_value=170000.0,
            total_assets=243000.0,
            total_position_pct=69.96,
            daily_pnl=1000.0,
            total_pnl=1950.0,
        ),
        health=PositionHealth(
            high_count=1,
            low_count=0,
            middle_count=0,
            profit_count=1,
            loss_count=0,
            flat_count=0,
        ),
        price_mode="realtime",
        data_cutoff=date(2026, 6, 5),
        notes=["盈亏按裸价差计算，未计佣金/印花税。"],
    )


def test_hold_add_cash_import_and_echo(isolated_hold_storage) -> None:
    positions = isolated_hold_storage
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["hold", "add", "600519", "--cost", "1680.5", "--shares", "100", "--name", "贵州茅台"],
    )
    assert result.exit_code == 0, result.output
    assert "已录入:贵州茅台 600519" in result.output
    assert "成本 1680.5 × 100 股" in result.output
    assert "市值 16.8万" in result.output

    result = runner.invoke(app, ["hold", "cash", "73000"])
    assert result.exit_code == 0, result.output
    assert "已更新现金:7.3万" in result.output

    result = runner.invoke(
        app,
        ["hold", "import", "-"],
        input="名称,代码,成本,股数\n五粮液,000858,150,200\n",
    )
    assert result.exit_code == 0, result.output
    assert "录入 1 只" in result.output

    book = positions.load_positions()
    assert book.cash == 73000.0
    assert [p.symbol for p in book.positions] == ["600519", "000858"]


def test_hold_json_mask_keeps_disclaimer(monkeypatch) -> None:
    from kan.cli import hold_cmds

    monkeypatch.setattr(hold_cmds, "_build_summary", lambda *, no_refresh: _fake_summary())

    result = CliRunner().invoke(app, ["hold", "--format", "json", "--mask"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "hold"
    assert payload["masked"] is True
    assert payload["price_mode"] == "realtime"
    assert payload["data_cutoff"] == "2026-06-05"
    assert payload["results"][0]["cost"] is None
    assert payload["results"][0]["shares"] is None
    assert payload["results"][0]["price"] == 1700.0
    assert payload["account"]["cash"] is None
    assert "不构成买卖建议" in payload["disclaimer"]


def test_hold_scan_delegates_to_only_holdings(monkeypatch) -> None:
    captured = {}

    def fake_scan(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("kan.cli.scan_cmds.scan", fake_scan)

    result = CliRunner().invoke(app, ["hold", "scan", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert captured["only_holdings"] is True
    assert captured["only_watchlist"] is False

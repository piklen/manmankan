"""kan board rank CLI tests."""

from __future__ import annotations

import json
from datetime import date

from typer.testing import CliRunner

from kan.cli import app
from kan.data.board_leaderboard import BoardRankRow


def _stub_board_rows(monkeypatch):
    rows = [
        BoardRankRow(
            kind="industry",
            code="801120",
            name="食品饮料",
            close=1234.5,
            position_pct=18.2,
            gain_pct=4.5,
            moneyflow_net=120000.0,
            data_date=date(2026, 5, 29),
        ),
        BoardRankRow(
            kind="industry",
            code="801080",
            name="电子",
            close=900.0,
            position_pct=30.0,
            gain_pct=2.0,
            moneyflow_net=50000.0,
            data_date=date(2026, 5, 29),
        ),
    ]
    monkeypatch.setattr(
        "kan.data.board_leaderboard.load_board_leaderboard",
        lambda **_kw: (rows, []),
    )
    return rows


def test_board_rank_terminal(monkeypatch):
    _stub_board_rows(monkeypatch)
    result = CliRunner().invoke(app, ["board", "rank", "--limit", "2"])
    assert result.exit_code == 0
    assert "食品饮料" in result.output
    assert "主力净额" in result.output


def test_board_rank_json(monkeypatch):
    _stub_board_rows(monkeypatch)
    result = CliRunner().invoke(app, ["board", "rank", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "board_rank"
    assert payload["results"][0]["moneyflow_net"] == 120000.0
    assert "disclaimer" in payload


def test_board_rank_accepts_360_period(monkeypatch):
    captured = {}
    rows = _stub_board_rows(monkeypatch)

    def fake_loader(**kw):
        captured.update(kw)
        return rows, []

    monkeypatch.setattr(
        "kan.data.board_leaderboard.load_board_leaderboard",
        fake_loader,
    )
    result = CliRunner().invoke(
        app,
        ["board", "rank", "--by", "pos", "--period", "360", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    assert captured["period"] == 360


def test_board_rank_json_empty_error_envelope(monkeypatch):
    monkeypatch.setattr(
        "kan.data.board_leaderboard.load_board_leaderboard",
        lambda **_kw: ([], []),
    )
    result = CliRunner().invoke(app, ["board", "rank", "--format", "json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "board_rank"
    assert payload["error"]["code"] == "data_unavailable"
    assert "例:" in payload["error"]["hint"]

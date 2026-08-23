"""`kan board trend` 行业 / 题材统一入口测试。"""
from __future__ import annotations

import json

from typer.testing import CliRunner

from kan.cli import app
from kan.core.scanner import TrendResult


def _rows() -> list[TrendResult]:
    return [
        TrendResult(
            "801080",
            "电子",
            1234.5,
            4,
            5.6,
            [("2026-08-21", 1.2), ("2026-08-20", 1.1)],
        ),
        TrendResult(
            "801120",
            "食品饮料",
            900.0,
            -3,
            -4.2,
            [("2026-08-21", -1.0), ("2026-08-20", -1.2)],
        ),
    ]


def _stub_loader(monkeypatch, *, rows=None, captured=None, source="sw"):
    result_rows = _rows() if rows is None else rows

    def fake_loader(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return result_rows, [], source, None

    monkeypatch.setattr("kan.data.board_trend.load_board_trends", fake_loader)


def test_board_trend_industry_up_json(monkeypatch):
    _stub_loader(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["board", "trend", "--kind", "industry", "--up", "3", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["command"] == "board_trend"
    assert payload["kind"] == "industry"
    assert payload["mode"] == "close"
    assert payload["filters"] == {"up": 3, "down": None, "min_streak": None}
    assert payload["stats"]["total"] == 2
    assert [row["code"] for row in payload["results"]] == ["801080"]
    assert payload["results"][0]["streak"] == 4
    assert payload["data_cutoff"] == "2026-08-21"


def test_board_trend_theme_candle_routes_exact_contract(monkeypatch):
    captured = {}
    _stub_loader(monkeypatch, captured=captured, source="tushare")

    result = CliRunner().invoke(
        app,
        [
            "board", "trend", "--kind", "theme", "--up", "3", "--candle",
            "--format", "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert captured["kind"] == "theme"
    assert captured["candle"] is True
    assert payload["kind"] == "theme"
    assert payload["level"] is None
    assert payload["mode"] == "candle"
    assert payload["source"] == "tushare"


def test_board_trend_terminal_includes_index_code(monkeypatch):
    _stub_loader(monkeypatch)

    result = CliRunner().invoke(app, ["board", "trend", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert "申万行业连续涨跌榜" in result.output
    assert "电子 801080" in result.output
    assert "涨4天" in result.output
    assert "历史价格不预示未来" in result.output


def test_board_trend_csv(monkeypatch):
    _stub_loader(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["board", "trend", "--kind", "industry", "--format", "csv"],
    )

    assert result.exit_code == 0, result.output
    lines = result.output.lstrip("\ufeff").splitlines()
    assert lines[0] == "排名,申万行业,代码,现价,连续,累计%"
    assert lines[1] == "1,电子,801080,1234.50,涨4天,5.60"


def test_board_trend_mutually_exclusive_json(monkeypatch):
    result = CliRunner().invoke(
        app,
        ["board", "trend", "--up", "3", "--down", "3", "--format", "json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "board_trend"
    assert payload["error"]["code"] == "mutually_exclusive_filters"


def test_board_trend_rejects_unsupported_industry_moneyflow_level():
    result = CliRunner().invoke(
        app,
        [
            "board", "trend", "--kind", "industry", "--level", "2",
            "--sort", "moneyflow", "--format", "json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "unsupported_moneyflow_level"


def test_board_trend_empty_filter_is_successful_json(monkeypatch):
    _stub_loader(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["board", "trend", "--up", "10", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["results"] == []
    assert payload["stats"]["total"] == 2
    assert payload["data_cutoff"] == "2026-08-21"

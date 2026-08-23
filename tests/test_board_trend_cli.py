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


def _stub_loader(
    monkeypatch,
    *,
    rows=None,
    errors=None,
    captured=None,
    source="sw",
    diagnosis=None,
):
    result_rows = _rows() if rows is None else rows
    result_errors = [] if errors is None else errors

    def fake_loader(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return result_rows, result_errors, source, diagnosis

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
        [
            "board", "trend", "--kind", "industry", "--latest", "2",
            "--format", "csv",
        ],
    )

    assert result.exit_code == 0, result.output
    lines = result.output.lstrip("\ufeff").splitlines()
    assert lines[0] == "排名,申万行业,代码,现价,连续,累计%,08-21,08-20"
    assert lines[1] == "1,电子,801080,1234.50,涨4天,5.60,1.20,1.10"


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


def test_board_trend_rejects_invalid_days_in_terminal():
    result = CliRunner().invoke(app, ["board", "trend", "--up", "31"])

    assert result.exit_code == 2
    assert "--up 的值必须在 1-30 之间" in result.output
    assert "例: kan board trend --kind theme --up 3" in result.output


def test_board_trend_data_unavailable_json(monkeypatch):
    from kan.data import boards

    def raise_unavailable(**kwargs):
        raise boards.BoardDataUnavailableError("申万不可用")

    monkeypatch.setattr("kan.data.board_trend.load_board_trends", raise_unavailable)

    result = CliRunner().invoke(app, ["board", "trend", "--format", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "data_unavailable"
    assert "申万不可用" in payload["error"]["message"]


def test_board_trend_no_source_rows_json(monkeypatch):
    _stub_loader(monkeypatch, rows=[])

    result = CliRunner().invoke(app, ["board", "trend", "--format", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "data_unavailable"
    assert "无可用指数 K 线" in payload["error"]["message"]


def test_board_trend_theme_failure_diagnosis_terminal(monkeypatch):
    from kan.data.theme_leaderboard import LeaderboardDiagnosis

    diagnosis = LeaderboardDiagnosis(
        tushare_attempted=False,
        em_attempted=True,
        em_total=395,
        em_failed_count=395,
    )
    _stub_loader(
        monkeypatch,
        rows=[],
        source="em",
        diagnosis=diagnosis,
    )

    result = CliRunner().invoke(app, ["board", "trend", "--kind", "theme"])

    assert result.exit_code == 1
    assert "题材榜无数据" in result.output
    assert "TuShare Pro: 未尝试" in result.output


def test_board_trend_moneyflow_markdown(monkeypatch):
    _stub_loader(monkeypatch)
    monkeypatch.setattr(
        "kan.data.board_trend.board_trend_moneyflow_map",
        lambda kind, rows, **kwargs: {"801080": 12345.0},
    )

    result = CliRunner().invoke(
        app,
        [
            "board", "trend", "--sort", "moneyflow", "--latest", "2",
            "--format", "md",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "按主力净额排序" in result.output
    assert "主力净额(万)" in result.output
    assert "12,345" in result.output
    assert "08-21" in result.output
    assert "+1.20%" in result.output
    assert "-1.00%" in result.output


def test_board_trend_down_latest_markdown(monkeypatch):
    _stub_loader(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "board", "trend", "--down", "3", "--min-streak", "3",
            "--sort", "latest", "--format", "md",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "连跌≥3天" in result.output
    assert "连续≥3天" in result.output
    assert "按最新单日涨幅排序" in result.output
    assert "食品饮料" in result.output


def test_board_trend_empty_filter_terminal(monkeypatch):
    _stub_loader(monkeypatch)

    result = CliRunner().invoke(app, ["board", "trend", "--up", "10"])

    assert result.exit_code == 0
    assert "没有连续上涨 ≥10 天的申万行业" in result.output


def test_board_trend_theme_terminal_shows_partial_and_narrow_details(monkeypatch):
    from kan.core.models import Theme

    unavailable = Theme(code="885999", name="缺数据题材", source="tushare")
    _stub_loader(
        monkeypatch,
        errors=[(unavailable, RuntimeError("partial"))],
        source="tushare",
    )

    result = CliRunner().invoke(
        app,
        [
            "board", "trend", "--kind", "theme", "--candle", "--latest", "30",
            "--limit", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "概念题材连续涨跌榜" in result.output
    assert "显示前 1/2" in result.output
    assert "1 个概念题材数据不可用:缺数据题材" in result.output
    assert "阳线阴线口径" in result.output
    assert "窄屏模式" in result.output
    assert "TuShare Pro" in result.output


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

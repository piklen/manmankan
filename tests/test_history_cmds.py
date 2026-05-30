"""kan history · 位置历史回溯测试 (v0.0.6.6)。

两层:
- reader 层 (load_symbol_history / snapshot_symbol_names / history_mark) · 直接喂快照文件
- 命令层 (CliRunner) · symbol 解析 / period 校验 / 空历史两提示 / 缺周期 / 共振 / --format

纯离线:只读 snapshots/*.json · 不触网络。SNAPSHOTS_DIR monkeypatch 到 tmp。
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.scanner import (
    history_mark,
    history_resonance,
    load_symbol_history,
    snapshot_symbol_names,
)
from kan.storage import paths


@pytest.fixture
def snap_dir(tmp_path, monkeypatch):
    """SNAPSHOTS_DIR 指向 tmp · reader/命令都从这里读。"""
    d = tmp_path / "snapshots"
    d.mkdir()
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", d)
    return d


def _write(snap_dir, date_str: str, items: list[dict]) -> None:
    (snap_dir / f"{date_str}.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )


def _entry(symbol="600519", name="贵州茅台", periods=None) -> dict:
    if periods is None:
        periods = {"30": {"pct": 4.0, "at_low": True, "at_high": False}}
    return {"symbol": symbol, "name": name, "periods": periods}


# ── reader 层 ──────────────────────────────────────────────────────────


def test_reader_extracts_across_days_descending(snap_dir):
    _write(snap_dir, "2026-05-20", [_entry(periods={"30": {"pct": 25.0, "at_low": False, "at_high": False}})])
    _write(snap_dir, "2026-05-22", [_entry(periods={"30": {"pct": 12.0, "at_low": False, "at_high": False}})])
    _write(snap_dir, "2026-05-23", [_entry(periods={"30": {"pct": 4.0, "at_low": True, "at_high": False}})])

    entries = load_symbol_history("600519")
    assert [e.snapshot_date.isoformat() for e in entries] == [
        "2026-05-23", "2026-05-22", "2026-05-20",
    ]
    assert entries[0].periods[30]["pct"] == 4.0
    assert entries[0].name == "贵州茅台"


def test_reader_symbol_absent_returns_empty(snap_dir):
    _write(snap_dir, "2026-05-23", [_entry(symbol="000858", name="五粮液")])
    assert load_symbol_history("600519") == []


def test_reader_skips_corrupt_file(snap_dir):
    _write(snap_dir, "2026-05-23", [_entry()])
    (snap_dir / "2026-05-22.json").write_text("{ broken json", encoding="utf-8")
    entries = load_symbol_history("600519")
    assert len(entries) == 1
    assert entries[0].snapshot_date.isoformat() == "2026-05-23"


def test_reader_skips_invalid_date_filename(snap_dir):
    _write(snap_dir, "2026-05-23", [_entry()])
    (snap_dir / "notadate.json").write_text(json.dumps([_entry()]), encoding="utf-8")
    entries = load_symbol_history("600519")
    assert len(entries) == 1


def test_reader_no_snapshots_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "does-not-exist")
    assert load_symbol_history("600519") == []


def test_reader_period_keys_are_int(snap_dir):
    _write(snap_dir, "2026-05-23", [_entry(periods={"60": {"pct": 8.0, "at_low": False, "at_high": False}})])
    entries = load_symbol_history("600519")
    assert 60 in entries[0].periods
    assert all(isinstance(k, int) for k in entries[0].periods)


def test_snapshot_symbol_names_latest_name_wins(snap_dir):
    _write(snap_dir, "2026-05-20", [_entry(symbol="600519", name="旧名")])
    _write(snap_dir, "2026-05-23", [_entry(symbol="600519", name="贵州茅台")])
    names = snapshot_symbol_names()
    assert names["600519"] == "贵州茅台"


def test_history_resonance_and_mark():
    periods = {
        5: {"pct": 3.0, "at_low": True, "at_high": False},
        30: {"pct": 4.0, "at_low": True, "at_high": False},
        60: {"pct": 2.0, "at_low": True, "at_high": False},
    }
    assert history_resonance(periods) == (3, 0)
    assert history_mark(periods) == (3, "low")


def test_history_mark_high_and_tie_and_zero():
    high = {5: {"pct": 97.0, "at_low": False, "at_high": True}}
    assert history_mark(high) == (1, "high")
    tie = {
        5: {"pct": 3.0, "at_low": True, "at_high": False},
        30: {"pct": 97.0, "at_low": False, "at_high": True},
    }
    assert history_mark(tie) == (1, "low")  # 平局取 low
    zero = {5: {"pct": 50.0, "at_low": False, "at_high": False}}
    assert history_mark(zero) == (0, "")


# ── 命令层 ─────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_empty_history_dir_errors(snap_dir, runner):
    result = runner.invoke(app, ["history", "600519"])
    assert result.exit_code == 1
    assert "还没有任何扫描历史" in result.output


def test_history_terminal_ok(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [_entry()])
    result = runner.invoke(app, ["history", "600519"])
    assert result.exit_code == 0
    assert "600519" in result.output
    assert "创新低" in result.output  # DISCLAIMER


def test_symbol_not_in_snapshots_errors(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [_entry(symbol="000858", name="五粮液")])
    result = runner.invoke(app, ["history", "600519"])
    assert result.exit_code == 1
    assert "没有" in result.output


def test_name_resolution_single(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [_entry(symbol="600519", name="贵州茅台")])
    result = runner.invoke(app, ["history", "茅台"])
    assert result.exit_code == 0
    assert "600519" in result.output


def test_name_resolution_multi_errors(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [
        _entry(symbol="601318", name="中国平安"),
        _entry(symbol="601988", name="中国银行"),
    ])
    result = runner.invoke(app, ["history", "中国"])
    assert result.exit_code == 1
    assert "匹配到 2 只" in result.output


def test_invalid_period_errors(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [_entry()])
    result = runner.invoke(app, ["history", "600519", "--period", "13"])
    assert result.exit_code == 2
    assert "周期不支持" in result.output


def test_missing_period_shows_dash(snap_dir, runner):
    # 该日只有 5 日周期 · 默认 30 日缺 → md 单元格 "-"
    _write(snap_dir, "2026-05-23", [
        _entry(periods={"5": {"pct": 50.0, "at_low": False, "at_high": False}}),
    ])
    result = runner.invoke(app, ["history", "600519", "--format", "md"])
    assert result.exit_code == 0
    assert "| - |" in result.output


def test_format_json_structure(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [
        _entry(periods={
            "30": {"pct": 4.0, "at_low": True, "at_high": False},
            "60": {"pct": 6.0, "at_low": False, "at_high": False},
        }),
    ])
    result = runner.invoke(app, ["history", "600519", "--period", "30", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "history"
    assert payload["symbol"] == "600519"
    assert payload["period"] == 30
    assert len(payload["series"]) == 1
    row = payload["series"][0]
    assert row["date"] == "2026-05-23"
    assert row["position_pct"] == 4.0
    assert row["at_low"] is True
    assert row["low_resonance"] == 1
    assert row["resonance"] == 1
    assert row["direction"] == "low"


def test_format_json_missing_period_is_null(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [
        _entry(periods={"5": {"pct": 50.0, "at_low": False, "at_high": False}}),
    ])
    result = runner.invoke(app, ["history", "600519", "--period", "30", "--format", "json"])
    assert result.exit_code == 0
    row = json.loads(result.output)["series"][0]
    assert row["position_pct"] is None
    assert row["at_low"] is None


def test_format_md_structure(snap_dir, runner):
    _write(snap_dir, "2026-05-23", [_entry()])
    result = runner.invoke(app, ["history", "600519", "--format", "md"])
    assert result.exit_code == 0
    assert "# 慢慢看 · 贵州茅台 600519 · 30日位置回溯" in result.output
    assert "| 日期 | 30日位置 | 共振 | 标记 |" in result.output
    assert "[4%]" in result.output  # at_low → 方括号
    assert "> ⚠️" in result.output  # disclaimer 引用块

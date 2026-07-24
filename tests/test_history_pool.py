"""kan history --pool · 池级位置趋势测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner


def _write_snapshot(snap_dir: Path, day: str, rows: list[tuple[str, float]]) -> None:
    snap_dir.mkdir(parents=True, exist_ok=True)
    data = [
        {"symbol": sym, "name": sym, "periods": {"180": {"pct": pct, "at_low": pct <= 5, "at_high": pct >= 95}}}
        for sym, pct in rows
    ]
    (snap_dir / f"{day}.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture()
def pool_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    snap_dir = tmp_path / "snapshots"
    # 两个完整快照日 + 一个残缺日(自定义周期遗留 · 无 180 周期,应被跳过)
    _write_snapshot(snap_dir, "2026-07-22", [(f"60000{i}", p) for i, p in enumerate([10, 30, 50, 70, 90])])
    _write_snapshot(snap_dir, "2026-07-23", [(f"60000{i}", p) for i, p in enumerate([15, 25, 45, 65, 85])])
    snap_dir.mkdir(exist_ok=True)
    (snap_dir / "2026-07-24.json").write_text(
        json.dumps([{"symbol": "600519", "name": "x", "periods": {"3": {"pct": 50.0}}}]),
        encoding="utf-8",
    )
    import kan.storage.paths as paths

    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", snap_dir)
    return snap_dir


def test_load_pool_history_aggregates_and_skips_incomplete(pool_env) -> None:
    from kan.core.scanner_history import load_pool_history

    entries = load_pool_history(180)

    assert [e.snapshot_date.isoformat() for e in entries] == ["2026-07-23", "2026-07-22"]
    # 07-23: [15,25,45,65,85] · 中位 45 · 低位(<=20) 1 · 高位(>=80) 1
    assert entries[0].median_pct == 45
    assert entries[0].low_count == 1
    assert entries[0].high_count == 1
    assert entries[0].stock_count == 5
    # 残缺日(只有 3 日周期)被跳过,不冒充池状态
    assert "2026-07-24" not in [e.snapshot_date.isoformat() for e in entries]


def test_load_pool_history_min_stocks_threshold(pool_env) -> None:
    from kan.core.scanner_history import load_pool_history

    assert load_pool_history(180, min_stocks=6) == []


def test_history_pool_json(pool_env) -> None:
    from kan.cli import app

    result = CliRunner().invoke(app, ["history", "--pool", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["mode"] == "pool"
    assert payload["period"] == 180
    assert len(payload["entries"]) == 2
    assert payload["entries"][0]["date"] == "2026-07-23"
    assert payload["entries"][0]["median_pct"] == 45


def test_history_pool_terminal(pool_env) -> None:
    from kan.cli import app

    result = CliRunner().invoke(app, ["history", "--pool"])

    assert result.exit_code == 0, result.output
    assert "池内 180日位置趋势" in result.output
    assert "趋势(旧→新)" in result.output


def test_history_pool_period_override(pool_env) -> None:
    from kan.cli import app

    result = CliRunner().invoke(app, ["history", "--pool", "-p", "60", "--format", "json"])

    assert result.exit_code == 1  # 无 60 周期快照 → no_pool_history
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "no_pool_history"


def test_history_without_symbol_errors() -> None:
    from kan.cli import app

    result = CliRunner().invoke(app, ["history", "--format", "json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "missing_symbol"

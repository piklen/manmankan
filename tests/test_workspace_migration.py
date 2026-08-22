"""旧 JSON 用户状态到 SQLite 的迁移、幂等与回滚测试。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import Stock
from kan.storage import config, paths, positions, watchlist, workspace_db
from kan.storage.workspace_migration import (
    migrate_workspace_state,
    rollback_workspace_state,
)


@pytest.fixture
def legacy_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(paths, "POSITIONS_PATH", tmp_path / "positions.json")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(positions, "POSITIONS_PATH", tmp_path / "positions.json")
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))

    (tmp_path / "config.json").write_text(
        json.dumps({**config.DEFAULT_CONFIG, "auto_update": False, "tushare_token": "secret"}),
        encoding="utf-8",
    )
    (tmp_path / "watchlist.json").write_text(
        json.dumps(
            {
                "version": 2,
                "default": "自选",
                "groups": {
                    "自选": {
                        "stocks": [
                            {
                                "symbol": "600519",
                                "name": "贵州茅台",
                                "added_at": "2026-08-01",
                                "groups": {},
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "positions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "cash": 10000,
                "positions": [
                    {
                        "symbol": "000858",
                        "name": "五粮液",
                        "cost": 120,
                        "shares": 100,
                        "added_at": "2026-08-01",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_migration_is_idempotent_and_preserves_original_backups(
    legacy_workspace: Path,
) -> None:
    original_config = (legacy_workspace / "config.json").read_bytes()

    first = migrate_workspace_state()
    second = migrate_workspace_state()

    assert first.backend == "sqlite"
    assert first.migrated == ("config", "watchlist", "positions")
    assert second.migrated == first.migrated
    assert (legacy_workspace / "config.json.vnext-backup").read_bytes() == original_config
    assert config.load()["auto_update"] is False
    assert watchlist.load_grouped_watchlist().groups["自选"][0].symbol == "600519"
    assert positions.load_positions().positions[0].symbol == "000858"
    assert workspace_db.get_state("config") is not None


def test_rollback_exports_current_sqlite_state_without_losing_changes(
    legacy_workspace: Path,
) -> None:
    migrate_workspace_state()
    config.update(auto_update=True)
    positions.set_cash(23456)
    grouped = watchlist.load_grouped_watchlist()
    grouped.groups[grouped.default].append(
        Stock(symbol="000858", name="五粮液", added_at=date(2026, 8, 2))
    )
    watchlist.save_grouped_watchlist(grouped)

    report = rollback_workspace_state()

    assert report.backend == "legacy"
    assert set(report.exported) == {"config", "watchlist", "positions"}
    assert workspace_db.get_state("config") is None
    assert json.loads((legacy_workspace / "config.json").read_text())["auto_update"] is True
    assert json.loads((legacy_workspace / "positions.json").read_text())["cash"] == 23456
    groups = json.loads((legacy_workspace / "watchlist.json").read_text())["groups"]
    assert {item["symbol"] for item in groups["自选"]["stocks"]} == {"600519", "000858"}


def test_workspace_cli_reports_backend_without_exposing_state(
    legacy_workspace: Path,
) -> None:
    result = CliRunner().invoke(app, ["workspace", "migrate", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["backend"] == "sqlite"
    assert payload["migrated"] == ["config", "watchlist", "positions"]
    assert "secret" not in result.stdout

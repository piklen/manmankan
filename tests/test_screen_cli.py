"""``kan screen`` CLI 契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.storage import paths


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    return CliRunner()


def _write_spec(tmp_path: Path) -> Path:
    path = tmp_path / "screen.json"
    path.write_text(
        json.dumps({"name": "CLI 规则", "exclude_st": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_save_list_show_delete_json_round_trip(
    runner: CliRunner, tmp_path: Path
) -> None:
    source = _write_spec(tmp_path)

    saved = runner.invoke(app, ["screen", "save", str(source), "--format", "json"])
    assert saved.exit_code == 0, saved.output
    screen_id = json.loads(saved.stdout)["screen"]["screen_id"]

    listed = runner.invoke(app, ["screen", "list", "--format", "json"])
    shown = runner.invoke(
        app, ["screen", "show", screen_id, "--format", "json"]
    )
    deleted = runner.invoke(
        app,
        ["screen", "delete", screen_id, "--yes", "--format", "json"],
    )

    assert json.loads(listed.stdout)["screens"][0]["screen_id"] == screen_id
    assert json.loads(shown.stdout)["screen"]["name"] == "CLI 规则"
    assert json.loads(deleted.stdout)["deleted"] is True


def test_save_accepts_stdin(runner: CliRunner) -> None:
    result = runner.invoke(
        app,
        ["screen", "save", "-", "--format", "json"],
        input='{"name":"stdin 规则","exclude_bj":true}',
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["screen"]["name"] == "stdin 规则"


def test_versions_and_restore_append_a_new_version(
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    source = _write_spec(tmp_path)
    saved = runner.invoke(app, ["screen", "save", str(source), "--format", "json"])
    screen_id = json.loads(saved.stdout)["screen"]["screen_id"]
    source.write_text(
        json.dumps(
            {"name": "CLI 规则", "exclude_st": True, "exclude_bj": True},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    runner.invoke(
        app,
        ["screen", "save", str(source), "--id", screen_id, "--format", "json"],
    )

    versions = runner.invoke(
        app,
        ["screen", "versions", screen_id, "--format", "json"],
    )
    restored = runner.invoke(
        app,
        ["screen", "restore", screen_id, "1", "--format", "json"],
    )

    assert [item["version"] for item in json.loads(versions.stdout)["versions"]] == [2, 1]
    assert json.loads(restored.stdout)["screen"]["current_version"] == 3
    assert json.loads(restored.stdout)["screen"]["spec"]["exclude_bj"] is False


def test_invalid_spec_returns_machine_error(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / "invalid.json"
    source.write_text("{}", encoding="utf-8")

    result = runner.invoke(
        app, ["screen", "save", str(source), "--format", "json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "invalid_spec"


def test_filter_catalog_is_discoverable_as_json(runner: CliRunner) -> None:
    result = runner.invoke(app, ["screen", "filters", "--format", "json"])

    assert result.exit_code == 0
    types = {
        option["type"]
        for group in json.loads(result.stdout)["groups"]
        for option in group["options"]
    }
    assert {"pos", "pe", "moneyflow", "rsi", "north"} <= types

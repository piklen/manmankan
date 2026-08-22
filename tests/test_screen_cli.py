"""``kan screen`` CLI 契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.domain.screen import DataCoverage
from kan.service import screen_service
from kan.storage import paths, workspace_db


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


def test_terminal_screen_lifecycle_is_inspectable(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_spec(tmp_path)
    assert "还没有保存的 Screen" in runner.invoke(app, ["screen", "list"]).output
    assert "价格区间位置" in runner.invoke(app, ["screen", "filters"]).output

    saved_result = runner.invoke(app, ["screen", "save", str(source)])
    saved = workspace_db.list_screens()[0]
    assert saved_result.exit_code == 0
    assert saved.screen_id in saved_result.output
    assert saved.screen_id in runner.invoke(app, ["screen", "list"]).output
    assert "规则哈希" in runner.invoke(
        app, ["screen", "show", saved.screen_id]
    ).output
    assert "v1" in runner.invoke(
        app, ["screen", "versions", saved.screen_id]
    ).output

    coverage = DataCoverage(
        universe_size=2,
        evaluated=2,
        matched=0,
        returned=0,
        ratio=1,
    )
    monkeypatch.setattr(
        screen_service,
        "_run_engine",
        lambda _spec: ([], coverage),
    )
    run_result = runner.invoke(app, ["screen", "run", saved.screen_id])
    run = workspace_db.list_runs(screen_id=saved.screen_id)[0]
    assert run_result.exit_code == 0
    assert "覆盖 2/2" in run_result.output
    assert run.run_id in runner.invoke(
        app, ["screen", "runs", saved.screen_id]
    ).output
    shown = runner.invoke(
        app,
        ["screen", "show-run", run.run_id, "--format", "json"],
    )
    assert json.loads(shown.stdout)["run"]["run_id"] == run.run_id

    direct = runner.invoke(app, ["screen", "run-spec", str(source), "--no-persist"])
    assert direct.exit_code == 0
    assert "CLI 规则" in direct.output
    restored = runner.invoke(app, ["screen", "restore", saved.screen_id, "1"])
    assert restored.exit_code == 0
    assert "v1" in restored.output
    deleted = runner.invoke(app, ["screen", "delete", saved.screen_id, "--yes"])
    assert deleted.exit_code == 0
    assert "已删除" in deleted.output


def test_terminal_screen_errors_are_actionable(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_path = tmp_path / "missing.json"
    missing_save = runner.invoke(app, ["screen", "save", str(missing_path)])
    missing_run_spec = runner.invoke(app, ["screen", "run-spec", str(missing_path)])
    missing_show = runner.invoke(app, ["screen", "show", "missing"])
    missing_versions = runner.invoke(app, ["screen", "versions", "missing"])
    missing_restore = runner.invoke(app, ["screen", "restore", "missing", "1"])
    missing_run = runner.invoke(app, ["screen", "show-run", "missing"])
    confirmation = runner.invoke(app, ["screen", "delete", "missing"])
    absent_delete = runner.invoke(app, ["screen", "delete", "missing", "--yes"])

    assert missing_save.exit_code == 1
    assert missing_run_spec.exit_code == 1
    assert missing_show.exit_code == 1
    assert missing_versions.exit_code == 1
    assert missing_restore.exit_code == 1
    assert missing_run.exit_code == 1
    assert confirmation.exit_code == 2
    assert "Screen 不存在" in absent_delete.output

    def fail_with_hint(_screen_id: str):
        raise screen_service.ScreenServiceError(
            "data_unavailable",
            "没有可用数据",
            hint="先更新数据",
        )

    monkeypatch.setattr(screen_service, "run_saved_screen", fail_with_hint)
    failed = runner.invoke(app, ["screen", "run", "screen-id"])
    assert failed.exit_code == 1
    assert "没有可用数据" in failed.output
    assert "先更新数据" in failed.output

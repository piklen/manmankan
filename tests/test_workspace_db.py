"""vNext 工作台 SQLite 持久化测试。"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kan.domain.screen import (
    CandidateStatus,
    DataCoverage,
    ScreenRow,
    ScreenRun,
    ScreenSpec,
)
from kan.service.screen_service import content_hash
from kan.storage import paths, workspace_db


@pytest.fixture
def isolated_workspace_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    return tmp_path / paths.WORKSPACE_DB_NAME


def _spec(name: str, *, exclude_st: bool = True, exclude_bj: bool = False) -> ScreenSpec:
    return ScreenSpec(name=name, exclude_st=exclude_st, exclude_bj=exclude_bj)


def _run(screen_id: str, screen_version: int, spec: ScreenSpec) -> ScreenRun:
    return ScreenRun(
        run_id="run-1",
        screen_id=screen_id,
        screen_version=screen_version,
        spec=spec,
        spec_hash=content_hash(spec),
        snapshot_id="snapshot-1",
        result_hash="result-1",
        created_at=datetime.now(UTC),
        duration_ms=12,
        coverage=DataCoverage(
            universe_size=1,
            evaluated=1,
            matched=1,
            returned=1,
            ratio=1,
        ),
        rows=[
            ScreenRow(
                symbol="600519",
                name="贵州茅台",
                rank=1,
                price=1500,
                values={"pe": 21.5},
            )
        ],
    )


def test_screen_versions_are_append_only_and_idempotent(
    isolated_workspace_db: Path,
) -> None:
    first_spec = _spec("观察池")
    first = workspace_db.save_screen(first_spec, content_hash(first_spec))
    unchanged = workspace_db.save_screen(
        first_spec, content_hash(first_spec), screen_id=first.screen_id
    )
    changed_spec = _spec("观察池", exclude_bj=True)
    changed = workspace_db.save_screen(
        changed_spec, content_hash(changed_spec), screen_id=first.screen_id
    )

    assert first.current_version == 1
    assert unchanged.current_version == 1
    assert changed.current_version == 2
    assert workspace_db.get_screen(first.screen_id) == changed
    assert os.stat(isolated_workspace_db).st_mode & 0o777 == 0o600


def test_run_candidate_and_compare_round_trip(isolated_workspace_db: Path) -> None:
    spec = _spec("研究池")
    saved = workspace_db.save_screen(spec, content_hash(spec))
    run = _run(saved.screen_id, saved.current_version, spec)

    workspace_db.save_run(run)
    candidate = workspace_db.upsert_candidate(
        list_id=workspace_db.DEFAULT_CANDIDATE_LIST_ID,
        symbol="600519",
        name="贵州茅台",
        source_run_id=run.run_id,
        status=CandidateStatus.WATCH,
        note="等待补充研究证据",
    )
    compare = workspace_db.save_compare_set(
        "白酒横向观察", ["600519", "000858", "000568"]
    )

    assert workspace_db.get_run(run.run_id) == run
    assert workspace_db.latest_run_for_screen(saved.screen_id) == run
    assert workspace_db.list_candidate_lists()[0].candidates == [candidate]
    assert workspace_db.list_compare_sets() == [compare]
    assert workspace_db.remove_candidate(candidate.list_id, candidate.symbol) is True
    assert workspace_db.remove_candidate(candidate.list_id, candidate.symbol) is False

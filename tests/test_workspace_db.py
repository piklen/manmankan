"""用户状态持久化与已有资产保留。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from kan.domain.workspace import CandidateStatus
from kan.storage import paths, workspace_db


@pytest.fixture
def isolated_workspace_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    return tmp_path / paths.WORKSPACE_DB_NAME


def test_candidate_list_rename_delete_and_default_protection(
    isolated_workspace_db: Path,
) -> None:
    created = workspace_db.create_candidate_list("初始名称")
    renamed = workspace_db.rename_candidate_list(created.list_id, "长期观察")

    assert renamed.name == "长期观察"
    assert workspace_db.delete_candidate_list(created.list_id) is True
    with pytest.raises(ValueError, match="默认研究候选池不能删除"):
        workspace_db.delete_candidate_list(workspace_db.DEFAULT_CANDIDATE_LIST_ID)


def test_schema_upgrade_adds_job_result_reference(
    isolated_workspace_db: Path,
) -> None:
    with sqlite3.connect(isolated_workspace_db) as conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                watermark TEXT,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("PRAGMA user_version = 2")

    assert workspace_db.list_jobs() == []
    with sqlite3.connect(isolated_workspace_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert "result_ref" in columns
    assert version == workspace_db.SCHEMA_VERSION


def test_candidate_edits_preserve_retired_run_and_review_records(isolated_workspace_db: Path) -> None:
    # 模拟已有数据库中的旧事实；新版本不再执行 Screen，但不能丢失用户记录。
    with workspace_db.transaction() as conn:
        conn.execute("""INSERT INTO screen_runs(
            run_id,spec_json,spec_hash,snapshot_id,result_hash,coverage_json,
            warnings_json,diff_json,duration_ms,created_at
        ) VALUES ('retired-run','{}','spec','snapshot','result','{}','[]','{}',1,'2026-01-01')""")
        conn.execute("""INSERT INTO compare_sets VALUES (
            'retired-comparison','原对比组','["600519","000858","000568"]','2026-01-01','2026-01-01')""")
    workspace_db.put_state("focus_reviews.v1:600519", {"items": [{"note": "原复看记录"}]})
    candidate = workspace_db.upsert_candidate(
        list_id="default", symbol="600519", name="贵州茅台", source_run_id="retired-run",
        status=CandidateStatus.WATCH, note="原观察",
    )
    changed = workspace_db.upsert_candidate(
        list_id="default", symbol="600519", name="贵州茅台", note="新观察",
    )
    assert changed.added_at == candidate.added_at
    assert changed.source_run_id == "retired-run"
    assert workspace_db.list_candidate_lists()[0].candidates == [changed]
    with sqlite3.connect(isolated_workspace_db) as conn:
        assert conn.execute("SELECT spec_json FROM screen_runs").fetchone()[0] == "{}"
        assert conn.execute("SELECT name FROM compare_sets").fetchone()[0] == "原对比组"
    assert workspace_db.get_state("focus_reviews.v1:600519")["items"] == [{"note": "原复看记录"}]
    assert os.stat(isolated_workspace_db).st_mode & 0o777 == 0o600
    assert workspace_db.remove_candidate("default", "600519")

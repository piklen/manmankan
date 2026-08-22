"""选股工作台 SQLite repository。

行情仍保存在 Parquet；SQLite 只承载需要事务、版本和关系查询的用户状态。
所有公开函数自行打开短连接，CLI 与本地 Web 可跨进程共享 WAL 数据库。
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from kan.domain.job import JobStatus, WorkspaceJob
from kan.domain.screen import (
    Candidate,
    CandidateList,
    CandidateStatus,
    CompareSet,
    SavedScreen,
    ScreenRun,
    ScreenSpec,
)
from kan.storage import paths

SCHEMA_VERSION = 3
DEFAULT_CANDIDATE_LIST_ID = "default"
DEFAULT_CANDIDATE_LIST_NAME = "研究候选"


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _database_path() -> Path:
    return paths.workspace_db_path()


def database_path() -> Path:
    """公开只读路径，供设置页与诊断输出。"""
    return _database_path()


def _connect() -> sqlite3.Connection:
    paths.ensure_dirs()
    path = _database_path()
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    _ensure_schema(conn)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return conn


@contextlib.contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"工作台数据库版本 {version} 高于当前支持版本 {SCHEMA_VERSION}"
        )
    if version == SCHEMA_VERSION:
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS screens (
            screen_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            current_version INTEGER NOT NULL,
            spec_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS screen_versions (
            screen_id TEXT NOT NULL REFERENCES screens(screen_id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            spec_json TEXT NOT NULL,
            spec_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (screen_id, version)
        );

        CREATE TABLE IF NOT EXISTS screen_runs (
            run_id TEXT PRIMARY KEY,
            screen_id TEXT REFERENCES screens(screen_id) ON DELETE SET NULL,
            screen_version INTEGER,
            spec_json TEXT NOT NULL,
            spec_hash TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            result_hash TEXT NOT NULL,
            coverage_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            diff_json TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_screen_runs_screen_created
        ON screen_runs(screen_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS screen_run_members (
            run_id TEXT NOT NULL REFERENCES screen_runs(run_id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            rank INTEGER NOT NULL,
            name TEXT NOT NULL,
            row_json TEXT NOT NULL,
            PRIMARY KEY (run_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS candidate_lists (
            list_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidates (
            list_id TEXT NOT NULL REFERENCES candidate_lists(list_id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT NOT NULL,
            source_run_id TEXT REFERENCES screen_runs(run_id) ON DELETE SET NULL,
            added_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (list_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS compare_sets (
            compare_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            symbols_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            watermark TEXT,
            message TEXT NOT NULL DEFAULT '',
            error TEXT,
            result_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS migrations (
            name TEXT PRIMARY KEY,
            source_hash TEXT,
            details_json TEXT NOT NULL,
            completed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workspace_state (
            namespace TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            source_hash TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workspace_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    job_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "result_ref" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN result_ref TEXT")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    now = _now().isoformat()
    conn.execute(
        """
        INSERT OR IGNORE INTO candidate_lists(list_id, name, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (DEFAULT_CANDIDATE_LIST_ID, DEFAULT_CANDIDATE_LIST_NAME, now, now),
    )
    conn.commit()


def _screen_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> SavedScreen:
    version_row = conn.execute(
        """
        SELECT spec_json FROM screen_versions
        WHERE screen_id = ? AND version = ?
        """,
        (row["screen_id"], row["current_version"]),
    ).fetchone()
    if version_row is None:
        raise RuntimeError(f"Screen {row['screen_id']} 缺少当前版本")
    return SavedScreen(
        screen_id=row["screen_id"],
        name=row["name"],
        current_version=row["current_version"],
        spec=ScreenSpec.model_validate_json(version_row["spec_json"]),
        spec_hash=row["spec_hash"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def save_screen(spec: ScreenSpec, spec_hash: str, *, screen_id: str | None = None) -> SavedScreen:
    now = _now()
    actual_id = screen_id or uuid4().hex
    with transaction() as conn:
        current = conn.execute(
            "SELECT * FROM screens WHERE screen_id = ?", (actual_id,)
        ).fetchone()
        if current is None:
            version = 1
            conn.execute(
                """
                INSERT INTO screens(screen_id, name, current_version, spec_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (actual_id, spec.name, version, spec_hash, now.isoformat(), now.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO screen_versions(screen_id, version, spec_json, spec_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (actual_id, version, spec.model_dump_json(), spec_hash, now.isoformat()),
            )
        elif current["spec_hash"] == spec_hash:
            version = int(current["current_version"])
            conn.execute(
                "UPDATE screens SET name = ?, updated_at = ? WHERE screen_id = ?",
                (spec.name, now.isoformat(), actual_id),
            )
        else:
            version = int(current["current_version"]) + 1
            conn.execute(
                """
                INSERT INTO screen_versions(screen_id, version, spec_json, spec_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (actual_id, version, spec.model_dump_json(), spec_hash, now.isoformat()),
            )
            conn.execute(
                """
                UPDATE screens
                SET name = ?, current_version = ?, spec_hash = ?, updated_at = ?
                WHERE screen_id = ?
                """,
                (spec.name, version, spec_hash, now.isoformat(), actual_id),
            )
        row = conn.execute(
            "SELECT * FROM screens WHERE screen_id = ?", (actual_id,)
        ).fetchone()
        assert row is not None
        return _screen_from_row(conn, row)


def list_screens() -> list[SavedScreen]:
    with contextlib.closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM screens ORDER BY updated_at DESC").fetchall()
        return [_screen_from_row(conn, row) for row in rows]


def get_screen(screen_id: str) -> SavedScreen | None:
    with contextlib.closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM screens WHERE screen_id = ?", (screen_id,)
        ).fetchone()
        return None if row is None else _screen_from_row(conn, row)


def delete_screen(screen_id: str) -> bool:
    with transaction() as conn:
        cursor = conn.execute("DELETE FROM screens WHERE screen_id = ?", (screen_id,))
        return cursor.rowcount > 0


def save_run(run: ScreenRun) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO screen_runs(
                run_id, screen_id, screen_version, spec_json, spec_hash,
                snapshot_id, result_hash, coverage_json, warnings_json,
                diff_json, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.screen_id,
                run.screen_version,
                run.spec.model_dump_json(),
                run.spec_hash,
                run.snapshot_id,
                run.result_hash,
                run.coverage.model_dump_json(),
                _json(run.warnings),
                run.diff.model_dump_json(),
                run.duration_ms,
                run.created_at.isoformat(),
            ),
        )
        conn.executemany(
            """
            INSERT INTO screen_run_members(run_id, symbol, rank, name, row_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (run.run_id, row.symbol, row.rank, row.name, row.model_dump_json())
                for row in run.rows
            ],
        )


def _run_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> ScreenRun:
    members = conn.execute(
        """
        SELECT row_json FROM screen_run_members
        WHERE run_id = ? ORDER BY rank ASC
        """,
        (row["run_id"],),
    ).fetchall()
    from kan.domain.screen import DataCoverage, ScreenDiff, ScreenRow

    return ScreenRun(
        run_id=row["run_id"],
        screen_id=row["screen_id"],
        screen_version=row["screen_version"],
        spec=ScreenSpec.model_validate_json(row["spec_json"]),
        spec_hash=row["spec_hash"],
        snapshot_id=row["snapshot_id"],
        result_hash=row["result_hash"],
        created_at=datetime.fromisoformat(row["created_at"]),
        duration_ms=row["duration_ms"],
        coverage=DataCoverage.model_validate_json(row["coverage_json"]),
        warnings=json.loads(row["warnings_json"]),
        rows=[ScreenRow.model_validate_json(item["row_json"]) for item in members],
        diff=ScreenDiff.model_validate_json(row["diff_json"]),
    )


def get_run(run_id: str) -> ScreenRun | None:
    with contextlib.closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM screen_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if row is None else _run_from_row(conn, row)


def latest_run_for_screen(screen_id: str) -> ScreenRun | None:
    with contextlib.closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT * FROM screen_runs
            WHERE screen_id = ? ORDER BY created_at DESC LIMIT 1
            """,
            (screen_id,),
        ).fetchone()
        return None if row is None else _run_from_row(conn, row)


def list_runs(*, screen_id: str | None = None, limit: int = 50) -> list[ScreenRun]:
    with contextlib.closing(_connect()) as conn:
        if screen_id is None:
            rows = conn.execute(
                "SELECT * FROM screen_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM screen_runs
                WHERE screen_id = ? ORDER BY created_at DESC LIMIT ?
                """,
                (screen_id, limit),
            ).fetchall()
        return [_run_from_row(conn, row) for row in rows]


def list_candidate_lists() -> list[CandidateList]:
    with contextlib.closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM candidate_lists ORDER BY created_at ASC"
        ).fetchall()
        out: list[CandidateList] = []
        for row in rows:
            members = conn.execute(
                "SELECT * FROM candidates WHERE list_id = ? ORDER BY added_at DESC",
                (row["list_id"],),
            ).fetchall()
            out.append(
                CandidateList(
                    list_id=row["list_id"],
                    name=row["name"],
                    candidates=[
                        Candidate(
                            list_id=item["list_id"],
                            symbol=item["symbol"],
                            name=item["name"],
                            status=CandidateStatus(item["status"]),
                            note=item["note"],
                            source_run_id=item["source_run_id"],
                            added_at=datetime.fromisoformat(item["added_at"]),
                            updated_at=datetime.fromisoformat(item["updated_at"]),
                        )
                        for item in members
                    ],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            )
        return out


def create_candidate_list(name: str) -> CandidateList:
    actual_name = name.strip()
    if not actual_name:
        raise ValueError("候选池名称不能为空")
    list_id = uuid4().hex
    now = _now()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO candidate_lists(list_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (list_id, actual_name, now.isoformat(), now.isoformat()),
        )
    return CandidateList(
        list_id=list_id,
        name=actual_name,
        candidates=[],
        created_at=now,
        updated_at=now,
    )


def upsert_candidate(
    *,
    list_id: str,
    symbol: str,
    name: str,
    source_run_id: str | None = None,
    status: CandidateStatus = CandidateStatus.RESEARCH,
    note: str = "",
) -> Candidate:
    now = _now()
    with transaction() as conn:
        exists = conn.execute(
            "SELECT 1 FROM candidate_lists WHERE list_id = ?", (list_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(f"候选池不存在: {list_id}")
        old = conn.execute(
            "SELECT added_at FROM candidates WHERE list_id = ? AND symbol = ?",
            (list_id, symbol),
        ).fetchone()
        added_at = old["added_at"] if old is not None else now.isoformat()
        conn.execute(
            """
            INSERT INTO candidates(
                list_id, symbol, name, status, note, source_run_id, added_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(list_id, symbol) DO UPDATE SET
                name = excluded.name,
                status = excluded.status,
                note = excluded.note,
                source_run_id = COALESCE(excluded.source_run_id, candidates.source_run_id),
                updated_at = excluded.updated_at
            """,
            (
                list_id,
                symbol,
                name,
                status.value,
                note,
                source_run_id,
                added_at,
                now.isoformat(),
            ),
        )
        conn.execute(
            "UPDATE candidate_lists SET updated_at = ? WHERE list_id = ?",
            (now.isoformat(), list_id),
        )
    return Candidate(
        list_id=list_id,
        symbol=symbol,
        name=name,
        status=status,
        note=note,
        source_run_id=source_run_id,
        added_at=datetime.fromisoformat(added_at),
        updated_at=now,
    )


def remove_candidate(list_id: str, symbol: str) -> bool:
    with transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM candidates WHERE list_id = ? AND symbol = ?",
            (list_id, symbol),
        )
        if cursor.rowcount:
            conn.execute(
                "UPDATE candidate_lists SET updated_at = ? WHERE list_id = ?",
                (_now().isoformat(), list_id),
            )
        return cursor.rowcount > 0


def save_compare_set(name: str, symbols: list[str], *, compare_id: str | None = None) -> CompareSet:
    if not 3 <= len(symbols) <= 10:
        raise ValueError("对比组合必须包含 3–10 只股票")
    actual_id = compare_id or uuid4().hex
    actual_name = name.strip() or "临时对比"
    now = _now()
    with transaction() as conn:
        existing = conn.execute(
            "SELECT created_at FROM compare_sets WHERE compare_id = ?", (actual_id,)
        ).fetchone()
        created_at = existing["created_at"] if existing is not None else now.isoformat()
        conn.execute(
            """
            INSERT INTO compare_sets(compare_id, name, symbols_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(compare_id) DO UPDATE SET
                name = excluded.name,
                symbols_json = excluded.symbols_json,
                updated_at = excluded.updated_at
            """,
            (actual_id, actual_name, _json(symbols), created_at, now.isoformat()),
        )
    return CompareSet(
        compare_id=actual_id,
        name=actual_name,
        symbols=symbols,
        created_at=datetime.fromisoformat(created_at),
        updated_at=now,
    )


def list_compare_sets() -> list[CompareSet]:
    with contextlib.closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM compare_sets ORDER BY updated_at DESC").fetchall()
        return [
            CompareSet(
                compare_id=row["compare_id"],
                name=row["name"],
                symbols=json.loads(row["symbols_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]


def delete_compare_set(compare_id: str) -> bool:
    with transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM compare_sets WHERE compare_id = ?", (compare_id,)
        )
        return cursor.rowcount > 0


def _job_from_row(row: sqlite3.Row) -> WorkspaceJob:
    return WorkspaceJob(
        job_id=row["job_id"],
        kind=row["kind"],
        status=JobStatus(row["status"]),
        progress=row["progress"],
        total=row["total"],
        watermark=row["watermark"],
        message=row["message"],
        error=row["error"],
        result_ref=row["result_ref"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def create_job(kind: str, *, total: int = 0, message: str = "") -> WorkspaceJob:
    now = _now()
    job = WorkspaceJob(
        job_id=uuid4().hex,
        kind=kind,
        status=JobStatus.QUEUED,
        progress=0,
        total=total,
        message=message,
        created_at=now,
        updated_at=now,
    )
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO jobs(
                job_id, kind, status, progress, total, watermark,
                message, error, result_ref, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.kind,
                job.status.value,
                job.progress,
                job.total,
                job.watermark,
                job.message,
                job.error,
                job.result_ref,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )
    return job


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress: int | None = None,
    total: int | None = None,
    watermark: str | None = None,
    message: str | None = None,
    error: str | None = None,
    result_ref: str | None = None,
) -> WorkspaceJob:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise ValueError(f"任务不存在: {job_id}")
        current = _job_from_row(row)
        updated = current.model_copy(
            update={
                "status": status if status is not None else current.status,
                "progress": progress if progress is not None else current.progress,
                "total": total if total is not None else current.total,
                "watermark": watermark if watermark is not None else current.watermark,
                "message": message if message is not None else current.message,
                "error": error if error is not None else current.error,
                "result_ref": result_ref if result_ref is not None else current.result_ref,
                "updated_at": _now(),
            }
        )
        conn.execute(
            """
            UPDATE jobs SET
                status = ?, progress = ?, total = ?, watermark = ?,
                message = ?, error = ?, result_ref = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (
                updated.status.value,
                updated.progress,
                updated.total,
                updated.watermark,
                updated.message,
                updated.error,
                updated.result_ref,
                updated.updated_at.isoformat(),
                job_id,
            ),
        )
        return updated


def get_job(job_id: str) -> WorkspaceJob | None:
    with contextlib.closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return None if row is None else _job_from_row(row)


def list_jobs(*, limit: int = 50) -> list[WorkspaceJob]:
    with contextlib.closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_job_from_row(row) for row in rows]


def interrupt_incomplete_jobs() -> int:
    now = _now().isoformat()
    with transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = ?, message = ?, updated_at = ?
            WHERE status IN (?, ?)
            """,
            (
                JobStatus.INTERRUPTED.value,
                "进程退出前任务未完成，可重新发起",
                now,
                JobStatus.QUEUED.value,
                JobStatus.RUNNING.value,
            ),
        )
        return cursor.rowcount


def get_state(namespace: str) -> dict[str, object] | None:
    with contextlib.closing(_connect()) as conn:
        row = conn.execute(
            "SELECT payload_json FROM workspace_state WHERE namespace = ?",
            (namespace,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise RuntimeError(f"工作台状态 {namespace} 不是 JSON object")
        return payload


def put_state(
    namespace: str,
    payload: dict[str, object],
    *,
    source_hash: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    values = (namespace, _json(payload), source_hash, _now().isoformat())
    if conn is not None:
        conn.execute(
            """
            INSERT INTO workspace_state(namespace, payload_json, source_hash, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace) DO UPDATE SET
                payload_json = excluded.payload_json,
                source_hash = excluded.source_hash,
                updated_at = excluded.updated_at
            """,
            values,
        )
        return
    with transaction() as owned:
        put_state(namespace, payload, source_hash=source_hash, conn=owned)


def delete_state(namespace: str, *, conn: sqlite3.Connection | None = None) -> bool:
    if conn is not None:
        return conn.execute(
            "DELETE FROM workspace_state WHERE namespace = ?", (namespace,)
        ).rowcount > 0
    with transaction() as owned:
        return delete_state(namespace, conn=owned)


def get_meta(key: str) -> str | None:
    with contextlib.closing(_connect()) as conn:
        row = conn.execute(
            "SELECT value FROM workspace_meta WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row["value"])


def set_meta(
    key: str,
    value: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    values = (key, value, _now().isoformat())
    if conn is not None:
        conn.execute(
            """
            INSERT INTO workspace_meta(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            values,
        )
        return
    with transaction() as owned:
        set_meta(key, value, conn=owned)


def state_backend_enabled() -> bool:
    return get_meta("state_backend") != "legacy"


def migration_completed(name: str) -> bool:
    with contextlib.closing(_connect()) as conn:
        return conn.execute(
            "SELECT 1 FROM migrations WHERE name = ?", (name,)
        ).fetchone() is not None


def delete_migration(name: str, *, conn: sqlite3.Connection | None = None) -> bool:
    if conn is not None:
        return conn.execute(
            "DELETE FROM migrations WHERE name = ?", (name,)
        ).rowcount > 0
    with transaction() as owned:
        return delete_migration(name, conn=owned)


def record_migration(
    name: str,
    *,
    source_hash: str | None,
    details: dict[str, object],
    conn: sqlite3.Connection | None = None,
) -> None:
    values = (name, source_hash, _json(details), _now().isoformat())
    if conn is not None:
        conn.execute(
            """
            INSERT OR REPLACE INTO migrations(name, source_hash, details_json, completed_at)
            VALUES (?, ?, ?, ?)
            """,
            values,
        )
        return
    with transaction() as owned:
        record_migration(name, source_hash=source_hash, details=details, conn=owned)

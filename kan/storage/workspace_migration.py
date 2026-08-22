"""旧 JSON 用户状态到 workspace SQLite 的可恢复迁移。"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kan.storage import paths, workspace_db

STATE_NAMESPACES = ("config", "watchlist", "positions")
MIGRATION_PREFIX = "legacy-json-to-sqlite-v1:"


@dataclass(frozen=True)
class WorkspaceMigrationReport:
    backend: str
    migrated: tuple[str, ...]
    exported: tuple[str, ...]
    backups: tuple[str, ...]


def should_use_sqlite(legacy_path: Path) -> bool:
    """只接管标准工作区路径；显式自定义路径继续保留 JSON 兼容。"""
    return legacy_path.parent == paths.BASE_DIR and workspace_db.state_backend_enabled()


def _backup_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.vnext-backup")


def _source_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adopt_state(
    namespace: str,
    legacy_path: Path,
    payload: dict[str, object],
    *,
    force: bool = False,
) -> None:
    """把已校验 payload 原子纳入 SQLite，并只保留一份不覆盖的原始备份。"""
    if namespace not in STATE_NAMESPACES:
        raise ValueError(f"未知状态命名空间: {namespace}")
    if not force and not should_use_sqlite(legacy_path):
        return
    backup = _backup_path(legacy_path)
    if legacy_path.exists() and not backup.exists():
        shutil.copy2(legacy_path, backup)
        with contextlib.suppress(OSError):
            os.chmod(backup, 0o600)
    source_hash = _source_hash(legacy_path)
    with workspace_db.transaction() as conn:
        workspace_db.put_state(
            namespace,
            payload,
            source_hash=source_hash,
            conn=conn,
        )
        workspace_db.record_migration(
            f"{MIGRATION_PREFIX}{namespace}",
            source_hash=source_hash,
            details={
                "namespace": namespace,
                "had_legacy_file": legacy_path.exists(),
                "backup_created": backup.exists(),
            },
            conn=conn,
        )
        workspace_db.set_meta("state_backend", "sqlite", conn=conn)


def load_state(namespace: str, legacy_path: Path) -> dict[str, object] | None:
    if not should_use_sqlite(legacy_path):
        return None
    return workspace_db.get_state(namespace)


def save_state(
    namespace: str,
    legacy_path: Path,
    payload: dict[str, object],
) -> None:
    if should_use_sqlite(legacy_path):
        workspace_db.put_state(
            namespace,
            payload,
            source_hash=_source_hash(legacy_path),
        )


def _watchlist_payload(grouped: Any) -> dict[str, object]:
    from kan.storage.watchlist_models import SCHEMA_VERSION

    return {
        "version": SCHEMA_VERSION,
        "default": grouped.default,
        "groups": {
            name: {"stocks": [stock.model_dump(mode="json") for stock in stocks]}
            for name, stocks in grouped.groups.items()
        },
    }


def _positions_payload(book: Any) -> dict[str, object]:
    from kan.storage.positions import SCHEMA_VERSION

    return {
        "version": SCHEMA_VERSION,
        "cash": round(book.cash, 2),
        "positions": [item.model_dump(mode="json") for item in book.positions],
    }


def migrate_workspace_state() -> WorkspaceMigrationReport:
    """显式迁移三类 JSON 状态；重复执行只会刷新同一 namespace。"""
    from kan.storage import config, positions, watchlist

    config_payload = config.load()
    watchlist_payload = _watchlist_payload(watchlist.load_grouped_watchlist())
    positions_payload = _positions_payload(positions.load_positions())
    sources: tuple[tuple[str, Path, dict[str, object]], ...] = (
        ("config", config.CONFIG_PATH, config_payload),
        ("watchlist", paths.WATCHLIST_PATH, watchlist_payload),
        ("positions", positions.POSITIONS_PATH, positions_payload),
    )
    for namespace, path, payload in sources:
        adopt_state(namespace, path, payload, force=True)
    return workspace_status()


def rollback_workspace_state() -> WorkspaceMigrationReport:
    """把 SQLite 当前值导出回 JSON 后切到 legacy backend，不丢迁移后修改。"""
    from kan.storage import config, positions

    targets = {
        "config": config.CONFIG_PATH,
        "watchlist": paths.WATCHLIST_PATH,
        "positions": positions.POSITIONS_PATH,
    }
    exported: list[str] = []
    for namespace, path in targets.items():
        payload = workspace_db.get_state(namespace)
        if payload is None:
            continue
        paths.atomic_write_json(path, payload, ensure_ascii=False, indent=2)
        exported.append(namespace)
    with workspace_db.transaction() as conn:
        for namespace in STATE_NAMESPACES:
            workspace_db.delete_state(namespace, conn=conn)
            workspace_db.delete_migration(
                f"{MIGRATION_PREFIX}{namespace}", conn=conn
            )
        workspace_db.set_meta("state_backend", "legacy", conn=conn)
    return workspace_status(exported=tuple(exported))


def workspace_status(
    *,
    exported: tuple[str, ...] = (),
) -> WorkspaceMigrationReport:
    from kan.storage import config, positions

    backend = "sqlite" if workspace_db.state_backend_enabled() else "legacy"
    migrated = tuple(
        namespace
        for namespace in STATE_NAMESPACES
        if workspace_db.get_state(namespace) is not None
    )
    source_paths = (
        config.CONFIG_PATH,
        paths.WATCHLIST_PATH,
        positions.POSITIONS_PATH,
    )
    backups = tuple(
        str(_backup_path(path))
        for path in source_paths
        if _backup_path(path).exists()
    )
    return WorkspaceMigrationReport(
        backend=backend,
        migrated=migrated,
        exported=exported,
        backups=backups,
    )

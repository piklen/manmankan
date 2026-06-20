"""Agent 显式快照 / delta 支持。

快照只在用户传 `--snapshot` 时写入；普通查询无副作用。delta 只比较结构化
结果行本身，不生成强弱判断或交易结论。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from kan.storage.paths import AGENT_SNAPSHOTS_DIR, atomic_write_json, ensure_dirs

_SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,80}$")


def attach_find_snapshot_metadata(
    payload: dict[str, Any],
    *,
    snapshot: bool = False,
    since: str | None = None,
) -> dict[str, Any]:
    """Attach optional local snapshot and delta metadata to a find JSON payload."""
    if since:
        payload["snapshot_delta"] = _delta_from_snapshot(payload, since)
        if payload.get("result_schema") != "agent_summary":
            payload["result_schema"] = "delta"
    if snapshot:
        payload["snapshot"] = _write_snapshot(payload)
    return payload


def _write_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    created_at = str(payload.get("query_time") or "")
    base = {
        "created_at": created_at,
        "command": payload.get("command"),
        "mode": payload.get("mode"),
        "result_schema": payload.get("result_schema"),
        "rule": payload.get("rule"),
        "stats": payload.get("stats"),
        "results": payload.get("results") or [],
    }
    snapshot_id = _snapshot_id(base)
    atomic_write_json(
        AGENT_SNAPSHOTS_DIR / f"{snapshot_id}.json",
        base,
        ensure_ascii=False,
        indent=2,
    )
    return {
        "id": snapshot_id,
        "created_at": created_at,
        "result_count": len(base["results"]),
        "storage": "local_agent_snapshot",
    }


def _delta_from_snapshot(payload: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    if not _SNAPSHOT_ID_RE.match(snapshot_id):
        return {
            "since": snapshot_id,
            "status": "invalid_snapshot_id",
            "added": [],
            "removed": [],
            "changed": [],
            "counts": {"added": 0, "removed": 0, "changed": 0},
        }
    previous = _load_snapshot(snapshot_id)
    if previous is None:
        return {
            "since": snapshot_id,
            "status": "missing_snapshot",
            "next_command": "kan find ... --format json --snapshot",
            "added": [],
            "removed": [],
            "changed": [],
            "counts": {"added": 0, "removed": 0, "changed": 0},
        }
    return _build_delta(previous.get("results") or [], payload.get("results") or [], snapshot_id)


def _load_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    path = AGENT_SNAPSHOTS_DIR / f"{snapshot_id}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _build_delta(
    previous_rows: list[Any],
    current_rows: list[Any],
    snapshot_id: str,
) -> dict[str, Any]:
    prev = _indexed_rows(previous_rows)
    curr = _indexed_rows(current_rows)
    prev_keys = set(prev)
    curr_keys = set(curr)
    added = [curr[key]["row"] for key in sorted(curr_keys - prev_keys)]
    removed = [prev[key]["row"] for key in sorted(prev_keys - curr_keys)]
    changed = [
        {"before": prev[key]["row"], "after": curr[key]["row"]}
        for key in sorted(prev_keys & curr_keys)
        if prev[key]["hash"] != curr[key]["hash"]
    ]
    return {
        "since": snapshot_id,
        "status": "ok",
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }


def _indexed_rows(rows: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            key = f"row:{idx}"
        else:
            key = str(row.get("code") or row.get("symbol") or f"row:{idx}")
        out[key] = {"row": row, "hash": _hash_json(row)}
    return out


def _snapshot_id(payload: dict[str, Any]) -> str:
    return _hash_json(payload)[:16]


def _hash_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["attach_find_snapshot_metadata"]

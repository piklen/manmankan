from __future__ import annotations

from kan.storage import agent_snapshots, paths


def test_attach_snapshot_and_delta(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "AGENT_SNAPSHOTS_DIR", tmp_path / "agent_snapshots")
    monkeypatch.setattr(agent_snapshots, "AGENT_SNAPSHOTS_DIR", tmp_path / "agent_snapshots")

    first = {
        "ok": True,
        "command": "find",
        "result_schema": "fields",
        "query_time": "2026-06-20T10:00:00+08:00",
        "rule": {"pools": ["codes:1"], "filters": []},
        "stats": {"shown": 1},
        "results": [{"code": "600519", "price": 100.0}],
    }
    agent_snapshots.attach_find_snapshot_metadata(first, snapshot=True)
    snapshot_id = first["snapshot"]["id"]

    second = {
        "ok": True,
        "command": "find",
        "result_schema": "fields",
        "query_time": "2026-06-20T10:05:00+08:00",
        "rule": {"pools": ["codes:2"], "filters": []},
        "stats": {"shown": 2},
        "results": [
            {"code": "600519", "price": 101.0},
            {"code": "000858", "price": 80.0},
        ],
    }
    agent_snapshots.attach_find_snapshot_metadata(second, since=snapshot_id)

    delta = second["snapshot_delta"]
    assert delta["status"] == "ok"
    assert delta["counts"] == {"added": 1, "removed": 0, "changed": 1}
    assert delta["added"][0]["code"] == "000858"
    assert delta["changed"][0]["before"]["price"] == 100.0
    assert delta["changed"][0]["after"]["price"] == 101.0
    assert second["result_schema"] == "delta"


def test_missing_snapshot_delta_is_structured(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "AGENT_SNAPSHOTS_DIR", tmp_path / "agent_snapshots")
    monkeypatch.setattr(agent_snapshots, "AGENT_SNAPSHOTS_DIR", tmp_path / "agent_snapshots")

    payload = {
        "ok": True,
        "command": "find",
        "result_schema": "fields",
        "results": [],
    }
    agent_snapshots.attach_find_snapshot_metadata(payload, since="missing123")

    assert payload["snapshot_delta"]["status"] == "missing_snapshot"
    assert payload["snapshot_delta"]["next_command"].startswith("kan find")

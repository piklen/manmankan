"""观察保存、冻结范围复看与个人想法的完整主路径。"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from kan.domain.discovery import DiscoveryQuery
from kan.domain.observation import ObservationEditRequest, ObservationSaveRequest
from kan.service import discovery, observation, trend_search
from kan.storage import paths, workspace_db
from kan.web.app import create_app


@pytest.fixture
def observation_market(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    days = pd.bdate_range("2026-01-05", periods=7).date.tolist()

    def bars(prices):
        return pd.DataFrame({"date": days, "open": prices, "high": prices, "low": prices,
                             "close": prices, "volume": 1000, "_source": "synthetic"})

    frames = {
        "000001": bars([100, 100, 110, 110, 121, 110, 99]),
        "000002": None,
        "000003": bars([100, 100, 100, 100, 100, 100, 100]),
        "000004": bars([100, 110, 120, 130, 140, 150, 160]),
    }
    members = [(code, code) for code in frames]
    industries = {code: "甲" if code != "000004" else "乙" for code in frames}
    monkeypatch.setattr(discovery, "resolve_market_calendar", lambda as_of=None: (days, as_of or days[-1]))
    monkeypatch.setattr(trend_search, "resolve_study_members", lambda universe, codes: [(code, code) for code in codes] if universe == "codes" else members)
    monkeypatch.setattr(trend_search, "_industries", lambda: industries)
    monkeypatch.setattr("kan.data.fetcher.get_cached", frames.get)
    request = ObservationSaveRequest(note="上涨是否扩散到更多成员？", query=DiscoveryQuery(as_of=days[4], window=2, industries=["甲"]))
    return request, days, frames, industries


def test_save_full_scope_and_read_edit_delete_without_market_reads(observation_market, monkeypatch):
    request, _days, _frames, _industries = observation_market
    workspace_db.put_state("existing:user-note", {"note": "原资料保持"})
    saved = observation.save_observation(request)
    assert saved.title == "甲 · 2日观察"
    assert [item.symbol for item in saved.snapshot.members] == ["000001", "000002", "000003"]
    assert saved.snapshot.group.current.available == 2
    assert saved.snapshot.members[1].return_pct is None

    def unexpected_query(*_args, **_kwargs):
        raise AssertionError("保存后的读取与笔记编辑不应读取行情")

    monkeypatch.setattr(observation, "discover_market", unexpected_query)
    assert observation.get_observation(saved.id) == saved
    assert observation.list_observations()[0].total == 3
    # 已有观察是用户资产：缺少新增指纹仍可读取，且读操作不改写其原始存档。
    legacy = saved.model_dump(mode="json")
    del legacy["snapshot"]["group"]["fingerprint"]
    workspace_db.put_state("observation:" + saved.id, legacy)
    archived = observation.get_observation(saved.id)
    assert archived.snapshot.group.fingerprint == ""
    assert workspace_db.get_state("observation:" + saved.id) == legacy
    edited = observation.edit_observation(saved.id, ObservationEditRequest(title="核对参与范围", note="补充想法"))
    assert edited.snapshot == archived.snapshot and edited.query == saved.query
    assert edited.created_at == saved.created_at and edited.note == "补充想法"
    assert observation.list_observations()[0].title == edited.title
    assert observation.delete_observation(saved.id)
    assert not observation.delete_observation(saved.id)
    assert observation.list_observations() == []
    assert workspace_db.get_state("existing:user-note") == {"note": "原资料保持"}


def test_save_rejects_changed_members_or_prices_without_writing(observation_market, monkeypatch):
    request, days, frames, industries = observation_market
    selected = ["000001", "000002", "000003"]
    names = {code: code for code in frames}
    monkeypatch.setattr(trend_search, "resolve_study_members", lambda _universe, _codes: [(code, names[code]) for code in selected])
    request = request.model_copy(update={"query": DiscoveryQuery(universe="personal", as_of=days[4], window=2)})
    shown = discovery.discover_market(request.query)
    request = request.model_copy(update={"expected_fingerprint": shown.market.fingerprint})
    saved = observation.save_observation(request)
    assert saved.snapshot.group.fingerprint == shown.market.fingerprint
    index = observation.list_observations()

    def unexpected_write():
        raise AssertionError("事实冲突时不应进入写事务")

    with monkeypatch.context() as no_writes:
        no_writes.setattr(workspace_db, "transaction", unexpected_write)
        client = TestClient(create_app(session_required=False, recover_jobs=False), base_url="http://127.0.0.1")
        selected.append("000004")
        response = client.post("/api/v1/observations", json=request.model_dump(mode="json"), headers={"X-Kan-Web": "1"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "observation_changed"
        selected.pop()
        # 恢复成员后，同一截止日期的日线修订也必须拒绝旧屏幕事实。
        original = frames["000001"].copy()
        frames["000001"].loc[4, ["open", "high", "low", "close"]] = 99
        with pytest.raises(observation.ObservationChangedError, match="没有写入"):
            observation.save_observation(request)
        frames["000001"] = original
        names["000001"] = "修订名称"
        with pytest.raises(observation.ObservationChangedError):
            observation.save_observation(request)
        names["000001"] = "000001"
        industries["000001"] = "乙"
        with pytest.raises(observation.ObservationChangedError):
            observation.save_observation(request)
    assert observation.list_observations() == index
    assert observation.get_observation(saved.id) == saved
    # 用户明确重看、核对后，提交新的事实指纹才可保存。
    refreshed = discovery.discover_market(request.query)
    current = observation.save_observation(request.model_copy(update={"expected_fingerprint": refreshed.market.fingerprint}))
    assert current.snapshot.group.fingerprint == refreshed.market.fingerprint
    assert current.note == saved.note


def test_review_freezes_members_and_keeps_unknown_and_original_note(observation_market):
    request, days, frames, industries = observation_market
    saved = observation.save_observation(request)
    # 行业转移和新成员不改变原范围；补齐原未知、丢失原有效都不能假装退出。
    industries["000001"] = "乙"
    industries["000004"] = "甲"
    frames["000002"] = frames["000004"].copy()
    frames["000003"] = None
    reviewed = observation.review_observation(saved.id)
    assert reviewed.current.as_of == days[-1]
    assert [item.symbol for item in reviewed.current.members] == ["000001", "000002", "000003"]
    assert (reviewed.comparison.available, reviewed.comparison.missing) == (1, 2)
    assert (reviewed.comparison.previous_positive_share, reviewed.comparison.current_positive_share) == (100, 0)
    counts = {item.key: item.count for item in reviewed.transitions}
    assert counts["up_down"] == 1 and counts["unknown"] == 2
    assert sum(counts.values()) == 3
    assert reviewed.observation == saved and observation.get_observation(saved.id) == saved
    # 同日显式复核允许观察数据修正，但仍不会改写已保存的事实或想法。
    assert observation.review_observation(saved.id, days[4]).observation == saved
    with pytest.raises(ValueError, match="不能早于"):
        observation.review_observation(saved.id, days[3])


def test_save_requires_fixed_date_and_some_observable_data(observation_market):
    request, _days, frames, _industries = observation_market
    with pytest.raises(ValidationError, match="明确当时"):
        ObservationSaveRequest(query=DiscoveryQuery())
    with pytest.raises(ValueError, match="没有可判断"):
        observation.save_observation(request.model_copy(update={"query": request.query.model_copy(update={"industries": ["不存在"]})}))
    for code in frames:
        frames[code] = None
    with pytest.raises(ValueError, match="没有可判断"):
        observation.save_observation(request)
    assert observation.list_observations() == []


def test_cli_save_and_mcp_review_share_the_original_record(observation_market):
    from kan.api import get_observation
    from kan.cli import app
    from kan.mcp.server import TOOLS

    request, days, _frames, _industries = observation_market
    runner = CliRunner()
    saved = runner.invoke(app, ["observe", "save", "-", "--format", "json"], input=request.model_dump_json())
    assert saved.exit_code == 0, saved.output
    record = json.loads(saved.stdout)
    assert record == get_observation(record["id"]).model_dump(mode="json")
    mcp = TOOLS["kan_observe"].handler
    assert json.loads(mcp({"action": "show", "id": record["id"]})["stdout"]) == record
    listed = json.loads(mcp({"action": "list"})["stdout"])["observations"]
    assert listed[0]["id"] == record["id"]
    reviewed = runner.invoke(app, ["observe", "review", record["id"], "--as-of", days[-1].isoformat(), "--format", "json"])
    assert reviewed.exit_code == 0, reviewed.output
    assert json.loads(mcp({"action": "review", "id": record["id"], "as_of": days[-1].isoformat()})["stdout"]) == json.loads(reviewed.stdout)
    assert get_observation(record["id"]).model_dump(mode="json") == record


def test_http_observation_flow_and_patch_uses_existing_write_guard(observation_market):
    request, days, _frames, _industries = observation_market
    client = TestClient(create_app(session_required=False, recover_jobs=False), base_url="http://127.0.0.1")
    write = {"X-Kan-Web": "1"}
    response = client.post("/api/v1/observations", json=request.model_dump(mode="json"), headers=write)
    assert response.status_code == 201
    record = response.json()
    path = f"/api/v1/observations/{record['id']}"
    assert client.get(path).json() == record
    assert client.get("/api/v1/observations").json()[0]["id"] == record["id"]
    assert client.patch(path, json={"note": "不应写入"}).status_code == 403
    assert client.patch(path, json={"snapshot": {}}, headers=write).status_code == 422
    edited = client.patch(path, json={"note": ""}, headers=write)
    assert edited.status_code == 200 and edited.json()["note"] == ""
    reviewed = client.post(path + "/review", json={"as_of": days[-1].isoformat()}, headers=write)
    assert reviewed.status_code == 200 and reviewed.json()["observation"]["note"] == ""
    assert client.delete(path, headers=write).json() == {"deleted": True}
    assert client.get(path).status_code == 404

"""当时的认识与事实存一次；复看明确读取同一批股票，不覆盖原笔记。"""

import sqlite3
from collections import Counter
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import uuid4

import numpy as np
from pydantic import TypeAdapter

from kan.domain.discovery import DiscoveryQuery, DiscoveryResult, DiscoveryTransition, TransitionKey
from kan.domain.observation import (
    ObservationEditRequest,
    ObservationRecord,
    ObservationReviewResult,
    ObservationSaveRequest,
    ObservationSnapshot,
    ObservationSummary,
)
from kan.service.discovery import compare_returns, discover_market, return_transition
from kan.storage import workspace_db

_INDEX = "observations:index"
_RECORD = "observation:"
_SUMMARIES = TypeAdapter(list[ObservationSummary])
_TRANSITIONS: tuple[tuple[TransitionKey, str], ...] = (
    ("up_up", "两次均上涨"), ("down_up", "原观察下跌 · 本次上涨"),
    ("up_down", "原观察上涨 · 本次下跌"), ("down_down", "两次均下跌"),
    ("flat", "至少一次持平"), ("unknown", "两次无法比较"),
)


class ObservationNotFoundError(ValueError):
    """记录不存在，可由入口映射为 404。"""


class ObservationChangedError(ValueError):
    """保存时事实已不同于已展示内容，可由入口映射为 409。"""


def _snapshot(result: DiscoveryResult) -> ObservationSnapshot:
    return ObservationSnapshot(
        as_of=result.as_of, current_start=result.current_start,
        previous_as_of=result.previous_as_of, previous_start=result.previous_start,
        group=result.market, members=result.members,
    )


def _summary(record: ObservationRecord) -> ObservationSummary:
    return ObservationSummary(
        id=record.id, title=record.title, note=record.note, created_at=record.created_at,
        as_of=record.snapshot.as_of, window=record.query.window,
        scope_label=record.scope_label, total=len(record.snapshot.members),
    )


def _summaries(conn: sqlite3.Connection | None = None) -> list[ObservationSummary]:
    payload = workspace_db.get_state(_INDEX, conn=conn)
    return _SUMMARIES.validate_python(payload["items"]) if payload else []


def _write_index(items: list[ObservationSummary], conn: sqlite3.Connection) -> None:
    workspace_db.put_state(_INDEX, {"items": [item.model_dump(mode="json") for item in items]}, conn=conn)


def _read_record(observation_id: str, conn: sqlite3.Connection | None = None) -> ObservationRecord:
    payload = workspace_db.get_state(_RECORD + observation_id, conn=conn)
    if payload is None:
        raise ObservationNotFoundError("观察记录不存在")
    # 历史笔记没有浏览指纹，仍保留其原事实；读取不重算行情，也不改写存档。
    snapshot = cast(dict[str, Any], payload["snapshot"])
    snapshot["group"].setdefault("fingerprint", "")
    return ObservationRecord.model_validate(payload)


def _default_title(scope_label: str, window: int) -> str:
    return f"{scope_label} · {window}日观察"[:120]


def save_observation(request: ObservationSaveRequest) -> ObservationRecord:
    """重算明确日期的完整范围；有浏览指纹时，核对一致才保存。"""
    result = discover_market(request.query)
    if request.expected_fingerprint is not None and request.expected_fingerprint != result.market.fingerprint:
        raise ObservationChangedError("成员范围或数据已变化，请刷新观察并核对事实后再保存；本次没有写入记录")
    if not result.members or not result.market.current.available:
        raise ValueError("当前范围没有可判断的成员，请先确认日期、范围与数据后再保存")
    scope_label = "、".join(request.query.industries) or {"all": "全市场", "personal": "个人池", "codes": "指定股票"}[request.query.universe]
    record = ObservationRecord(
        id=uuid4().hex, title=request.title.strip() or _default_title(scope_label, request.query.window),
        note=request.note, created_at=datetime.now(UTC), query=request.query,
        scope_label=scope_label, snapshot=_snapshot(result),
    )
    with workspace_db.transaction() as conn:
        workspace_db.put_state(_RECORD + record.id, record.model_dump(mode="json"), conn=conn)
        _write_index([_summary(record), *_summaries(conn)], conn)
    return record


def list_observations() -> list[ObservationSummary]:
    """列表只读取轻量索引，不读行情或完整成员快照。"""
    return _summaries()


def get_observation(observation_id: str) -> ObservationRecord:
    return _read_record(observation_id)


def edit_observation(observation_id: str, request: ObservationEditRequest) -> ObservationRecord:
    with workspace_db.transaction() as conn:
        record = _read_record(observation_id, conn)
        changes = request.model_dump(exclude_unset=True)
        if "title" in changes:
            changes["title"] = request.title.strip() or _default_title(record.scope_label, record.query.window)
        updated = record.model_copy(update=changes)
        workspace_db.put_state(_RECORD + record.id, updated.model_dump(mode="json"), conn=conn)
        _write_index([_summary(updated) if item.id == record.id else item for item in _summaries(conn)], conn)
    return updated


def delete_observation(observation_id: str) -> bool:
    with workspace_db.transaction() as conn:
        deleted = workspace_db.delete_state(_RECORD + observation_id, conn=conn)
        if deleted:
            _write_index([item for item in _summaries(conn) if item.id != observation_id], conn)
    return deleted


def review_observation(observation_id: str, as_of: date | None = None) -> ObservationReviewResult:
    record = get_observation(observation_id)
    if as_of is not None and as_of < record.snapshot.as_of:
        raise ValueError("复看日期不能早于原观察日期")
    # 冻结的是成员和窗口；行业归属、上市名单或个人池后续变化不能改动范围。
    query = DiscoveryQuery(
        universe="codes", codes=[item.symbol for item in record.snapshot.members],
        as_of=as_of, window=record.query.window,
    )
    result = discover_market(query)
    if result.as_of < record.snapshot.as_of:
        raise ValueError("复看日期不能早于原观察日期")
    current = {item.symbol: item.return_pct for item in result.members}
    previous_values = [item.return_pct for item in record.snapshot.members]
    current_values = [current[item.symbol] for item in record.snapshot.members]
    counts = Counter(return_transition(previous, now) for previous, now in zip(previous_values, current_values, strict=True))
    return ObservationReviewResult(
        observation=record, current=_snapshot(result),
        comparison=compare_returns(np.array(previous_values, dtype=float), np.array(current_values, dtype=float)),
        transitions=[DiscoveryTransition(key=key, label=label, count=counts[key]) for key, label in _TRANSITIONS],
    )

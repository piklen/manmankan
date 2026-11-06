"""个人股票池的成员与笔记；行情统一由趋势与市场观察服务处理。"""

from __future__ import annotations

from datetime import UTC, datetime

from kan.domain.focus import FocusRow, FocusSnapshot
from kan.domain.workspace import Candidate, CandidateStatus
from kan.storage import positions, watchlist, workspace_db


def _focus_members() -> dict[str, FocusRow]:
    """合并成员身份，不复制持仓成本、股数和现金。"""
    rows: dict[str, FocusRow] = {}

    def add(symbol: str, name: str, source: str) -> FocusRow:
        row = rows.setdefault(symbol, FocusRow(symbol=symbol, name=name, sources=[]))
        if source not in row.sources:
            row.sources.append(source)
        if row.name == symbol and name != symbol:
            row.name = name
        return row

    for stock in watchlist.load_watchlist().stocks:
        add(stock.symbol, stock.name, "watchlist")
    for position in positions.load_positions().positions:
        add(position.symbol, position.name, "holding")
    for candidate_list in workspace_db.list_candidate_lists():
        for candidate in candidate_list.candidates:
            if candidate.status is CandidateStatus.REJECTED:
                row = rows.get(candidate.symbol)
                if row is None:
                    continue
            else:
                row = add(candidate.symbol, candidate.name, "candidate")
            row.candidates.append(candidate)
    for row in rows.values():
        selected_candidate = _preferred_candidate(row.candidates)
        if selected_candidate:
            row.note = selected_candidate.note
            row.candidate_list_id = selected_candidate.list_id
            row.candidate_status = selected_candidate.status
    return rows


def focus_symbols() -> list[str]:
    """显式刷新与关注页使用同一成员集合。"""
    return list(_focus_members())


def build_focus_snapshot() -> FocusSnapshot:
    """读取成员身份与笔记，不为管理股票池重复扫描行情。"""
    rows = list(_focus_members().values())
    return FocusSnapshot(generated_at=datetime.now(UTC), total=len(rows), rows=rows)


def _existing_candidate(symbol: str, list_id: str | None = None) -> Candidate | None:
    items = [
        candidate
        for candidate_list in workspace_db.list_candidate_lists()
        for candidate in candidate_list.candidates
        if candidate.symbol == symbol and (list_id is None or candidate.list_id == list_id)
    ]
    return _preferred_candidate(items)


def _preferred_candidate(items: list[Candidate]) -> Candidate | None:
    active = [item for item in items if item.status is not CandidateStatus.REJECTED]
    choices = active or items
    return next((item for item in choices if item.list_id == "default"), choices[0] if choices else None)


def add_focus(symbol: str) -> Candidate:
    """手动加入关注候选；重复添加不会擦除观察笔记与状态。"""
    symbol = watchlist._normalize_symbol(symbol)
    existing = _existing_candidate(symbol)
    if existing is not None and existing.status is not CandidateStatus.REJECTED:
        return existing
    names = watchlist.load_stock_names_cache(allow_stale=True) or {}
    return workspace_db.upsert_candidate(
        list_id=existing.list_id if existing else "default",
        symbol=symbol,
        name=existing.name if existing else names.get(symbol, symbol),
        status=CandidateStatus.WATCH,
        note=existing.note if existing else "",
        source_run_id=existing.source_run_id if existing else None,
    )


def update_focus_note(symbol: str, note: str, *, list_id: str | None = None) -> Candidate:
    """仅修改选定列表的笔记；保留其他候选列表与来源运行。"""
    from kan.domain.focus import FocusNoteRequest

    payload = FocusNoteRequest(note=note, list_id=list_id)
    symbol = watchlist._normalize_symbol(symbol)
    existing = _existing_candidate(symbol, list_id)
    if existing is None:
        if list_id not in (None, "default"):
            raise ValueError("该列表中没有这只股票")
        if list_id == "default":
            names = watchlist.load_stock_names_cache(allow_stale=True) or {}
            existing = workspace_db.upsert_candidate(
                list_id="default", symbol=symbol, name=names.get(symbol, symbol),
                status=CandidateStatus.WATCH,
            )
        else:
            existing = add_focus(symbol)
    return workspace_db.upsert_candidate(
        list_id=existing.list_id,
        symbol=symbol,
        name=existing.name,
        status=existing.status,
        note=payload.note,
        source_run_id=existing.source_run_id,
    )

"""个人关注的共享入口：只读本地行情，显式保存笔记和复看。"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from kan.domain.focus import FocusPeriod, FocusReviewEntry, FocusRow, FocusSnapshot
from kan.domain.screen import Candidate, CandidateStatus
from kan.storage import positions, watchlist, workspace_db

_REVIEW_PREFIX = "focus_reviews.v1:"
_PERIODS = [30, 60, 180]
_HISTORY_ADAPTER = TypeAdapter(list[FocusReviewEntry])


def _shanghai_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


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


def _cached_expected_cutoff() -> date | None:
    """首屏不为了日历隐式联网；没有有效日历时明确标记时效未知。"""
    from kan.core import trading_calendar

    days = trading_calendar._trade_dates_memo or trading_calendar._read_cache()
    if not days:
        return None
    now = _shanghai_now()
    if max(days) < now.date():
        return None
    complete = [
        day for day in days
        if day < now.date()
        or (day == now.date() and now.time() >= trading_calendar.DATA_AVAILABLE_AFTER)
    ]
    return max(complete) if complete else None


def _finite(value: float) -> float | None:
    return round(value, 4) if math.isfinite(value) else None


def _fill_market(row: FocusRow, expected: date | None) -> None:
    import pandas as pd

    from kan.core.scanner import calc_trend, scan_stock
    from kan.data.fetcher import cache_age, get_cached

    frame = get_cached(row.symbol)
    if frame is None or frame.empty:
        row.message = "尚无本地行情，点击更新关注行情"
        return
    required = {"date", "open", "close", "high", "low"}
    if not required.issubset(frame.columns):
        row.message = "本地行情字段不完整，请重新更新"
        return
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    if frame["date"].isna().any():
        row.message = "本地行情缺少交易日期，请重新更新"
        return
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    # 即使日历不可用，未来和当天未收盘行也不能成为日度观察事实。
    from kan.core.trading_calendar import DATA_AVAILABLE_AFTER

    now = _shanghai_now()
    upper = now.date() if now.time() >= DATA_AVAILABLE_AFTER else now.date() - timedelta(days=1)
    while upper.weekday() >= 5:
        upper -= timedelta(days=1)
    cutoff = min(expected, upper) if expected is not None else upper
    frame = frame[frame["date"].dt.date <= cutoff]
    if frame.empty:
        row.message = "没有完整交易日行情"
        return
    values = frame[list(required - {"date"})]
    if not all(math.isfinite(float(value)) for value in values.to_numpy().flat):
        row.message = "本地行情包含缺失价格，请重新更新"
        return
    if (frame["close"] <= 0).any():
        row.message = "本地行情含无效收盘价，请重新更新"
        return
    current = scan_stock(frame, row.symbol, row.name, periods=_PERIODS)
    previous = (
        scan_stock(frame.iloc[:-1], row.symbol, row.name, periods=_PERIODS)
        if len(frame) > 1 else None
    )
    row.available = True
    row.price = _finite(current.current_price)
    row.data_cutoff = pd.Timestamp(frame["date"].iloc[-1]).date()
    row.previous_cutoff = pd.Timestamp(frame["date"].iloc[-2]).date() if previous else None
    row.stale = expected is None or row.data_cutoff < expected
    row.fetched_at = cache_age(row.symbol)
    source_values = frame.tail(max(_PERIODS))["_source"] if "_source" in frame else [None]
    sources = list(dict.fromkeys(
        value.strip() if isinstance(value, str) and value.strip() else "local_cache"
        for value in source_values
    ))
    row.source = " / ".join(sources)
    row.message = "行情日期已显示，数据时效待核对" if expected is None else None
    if previous:
        row.change_pct = _finite((current.current_price / previous.current_price - 1) * 100)
    row.streak = calc_trend(frame, row.symbol, row.name).streak
    old_periods = {period.period: period for period in previous.periods} if previous else {}
    for period in current.periods:
        old = old_periods.get(period.period)
        current_pct = None if period.insufficient else _finite(period.position_pct)
        old_pct = None if old is None or old.insufficient else _finite(old.position_pct)
        row.periods.append(FocusPeriod(
            period=period.period,
            position_pct=current_pct,
            previous_position_pct=old_pct,
            change_pp=(
                round(current_pct - old_pct, 4)
                if current_pct is not None and old_pct is not None else None
            ),
            low=None if period.insufficient else _finite(period.n_low),
            high=None if period.insufficient else _finite(period.n_high),
        ))
    row.data_hash = _market_hash(row)


def _market_hash(row: FocusRow) -> str:
    """只绑定屏幕上看到的行情；保存笔记不使同一行情版本失效。"""
    payload = row.model_dump(mode="json", include={
        "symbol", "source", "price", "change_pct", "data_cutoff", "previous_cutoff",
        "periods", "streak",
    })
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _review_history(symbol: str) -> list[FocusReviewEntry]:
    payload = workspace_db.get_state(f"{_REVIEW_PREFIX}{symbol}")
    return _HISTORY_ADAPTER.validate_python(payload["items"]) if payload else []


def build_focus_snapshot() -> FocusSnapshot:
    """一次读取个人关注池；既不取数也不自动覆盖复看记录。"""
    expected = _cached_expected_cutoff()
    rows = list(_focus_members().values())
    for row in rows:
        try:
            _fill_market(row, expected)
        except (OSError, ValueError) as exc:
            from kan.infra.log import debug_log

            debug_log(__name__, "focus cache read failed", exc)
            row.message = "本地行情无法读取，请重新更新"
        row.review_history = _review_history(row.symbol)[:5]
        if row.review_history:
            last = row.review_history[0]
            row.reviewed_at = last.reviewed_at
            row.reviewed_data_cutoff = last.data_cutoff
            row.reviewed = (
                row.available
                and row.data_cutoff == last.data_cutoff
                and row.price == last.price
                and row.note == last.note
                and row.candidate_list_id == last.candidate_list_id
                and (not last.data_hash or row.data_hash == last.data_hash)
                and {str(item.period): item.position_pct for item in row.periods} == last.positions
            )
    return FocusSnapshot(
        generated_at=datetime.now(UTC),
        expected_cutoff=expected,
        total=len(rows),
        available=sum(row.available for row in rows),
        stale=sum(row.available and row.stale for row in rows),
        rows=rows,
        warnings=["行情日期已显示，当前无法确认是否最新"] if expected is None and any(row.available for row in rows) else [],
    )


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


def mark_focus_reviewed(
    symbol: str,
    *,
    expected_data_hash: str | None = None,
    expected_note: str | None = None,
) -> FocusReviewEntry:
    """保存用户实际复看的行情日和笔记；同一内容重复点击幂等。"""
    symbol = watchlist._normalize_symbol(symbol)
    row = _focus_members().get(symbol)
    if row is None:
        raise ValueError("请先将这只股票加入关注")
    _fill_market(row, _cached_expected_cutoff())
    if not row.available or row.data_cutoff is None or row.price is None:
        raise ValueError("暂无完整行情，不能标记已复看")
    if expected_data_hash is not None and row.data_hash != expected_data_hash:
        raise ValueError("行情已变化，请重新读取后再标记复看")
    if expected_note is not None and row.note != expected_note:
        raise ValueError("笔记已在其他窗口修改，请重新读取后再标记复看")
    entry = FocusReviewEntry(
        reviewed_at=datetime.now(UTC),
        data_cutoff=row.data_cutoff,
        note=row.note,
        price=row.price,
        positions={str(item.period): item.position_pct for item in row.periods},
        data_hash=row.data_hash,
        candidate_list_id=row.candidate_list_id,
    )
    namespace = f"{_REVIEW_PREFIX}{symbol}"
    with workspace_db.transaction() as conn:
        payload = workspace_db.get_state(namespace, conn=conn)
        history = _HISTORY_ADAPTER.validate_python(payload["items"]) if payload else []
        if history and history[0].model_dump(exclude={"reviewed_at"}) == entry.model_dump(exclude={"reviewed_at"}):
            return history[0]
        workspace_db.put_state(
            namespace,
            {"items": [item.model_dump(mode="json") for item in [entry, *history]]},
            conn=conn,
        )
    return entry

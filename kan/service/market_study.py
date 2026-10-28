"""日线研究：同一条件计算当前匹配、历史事件和未来实际分布。

研究定义与摘要放 SQLite；完整事件及本次行情放 Parquet。页面分页读事件，
点击图证读取当次封存数据，不把更新后的行情冒充旧研究。
"""

from __future__ import annotations

import math
import operator
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from kan.domain.market_study import (
    StudyBar,
    StudyBin,
    StudyCheck,
    StudyCondition,
    StudyCoverage,
    StudyDiff,
    StudyDistribution,
    StudyEvent,
    StudyEventPage,
    StudyEvidence,
    StudyField,
    StudyMatch,
    StudyQuery,
    StudyResult,
    StudySummary,
)
from kan.storage import paths, workspace_db

_INDEX = "market_studies:index"
_STUDY = "market_studies:study:"
_RUN = "market_studies:run:"
_OPS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le, "eq": operator.eq}
_STREAKS = {"up_days", "down_days", "bull_days", "bear_days", "joint_up_days"}
_PRICE_COLUMNS = ["open", "high", "low", "close"]

FIELD_CATALOG = [
    {"field": field, "label": label, "unit": unit, "window": window, "definition": definition}
    for field, label, unit, window, definition in [
        ("change_pct", "收盘涨跌", "%", False, "当日收盘相对前一市场交易日收盘的变化"),
        ("gap_pct", "开盘涨跌", "%", False, "当日开盘相对前一市场交易日收盘的变化"),
        ("body_pct", "日内实体涨跌", "%", False, "当日收盘相对当日开盘的变化"),
        ("return_pct", "区间涨跌", "%", True, "当前收盘相对 N 个市场交易日前收盘的变化"),
        ("position", "区间位置", "%", True, "收盘在最近 N 日最低价到最高价之间的位置"),
        ("low_age", "低点距今", "交易日", True, "最近 N 日最低价最后一次出现距今的交易日数"),
        ("up_days", "连续收盘上涨", "天", False, "严格 close > previous close；平盘与缺行中断"),
        ("down_days", "连续收盘下跌", "天", False, "严格 close < previous close；平盘与缺行中断"),
        ("bull_days", "连续阳线", "天", False, "严格 close > open；十字与缺行中断"),
        ("bear_days", "连续阴线", "天", False, "严格 close < open；十字与缺行中断"),
        ("joint_up_days", "连续收阳且上涨", "天", False, "每天同时 close > open 且 close > previous close"),
        ("volume_ratio", "成交量相对前期", "倍", True, "当日成交量 / 此前 N 日平均成交量，不含当日"),
        ("shape_distance", "与参照形态的距离", "百分点", True, "两段 N 日收盘按各自首日归一为100后，逐日差的均方根；事后形态距离，不是推荐评分"),
    ]
]


def resolve_study_members(universe: str, codes: list[str]) -> list[tuple[str, str]]:
    from kan.storage.watchlist import load_stock_names_cache

    if universe == "all":
        from kan.data.universe import fetch_all_stocks

        members = fetch_all_stocks()
        if not members:
            raise ValueError("无法取得完整上市股票名单；请在数据连接中配置可用来源后重试，未改用缓存股票子集")
        return list(dict(members).items())
    if universe == "personal":
        from kan.storage.positions import load_positions
        from kan.storage.watchlist import load_watchlist

        pairs = [(item.symbol, item.name) for item in load_watchlist().stocks]
        pairs.extend((item.symbol, item.name) for item in load_positions().positions)
        pairs.extend((item.symbol, item.name) for group in workspace_db.list_candidate_lists() for item in group.candidates if item.status.value != "rejected")
        return list(dict(pairs).items())
    names = load_stock_names_cache(allow_stale=True) or {}
    return [(code, names.get(code, code)) for code in codes]


def resolve_market_calendar(as_of: date | None = None) -> tuple[list[date], date]:
    from kan.core.trading_calendar import get_trade_dates, latest_trade_date

    sessions = sorted(get_trade_dates())
    if not sessions:
        raise ValueError("无法取得交易日历；请检查数据连接后重试，研究不会用自然日替代交易日")
    latest = latest_trade_date(datetime.now(ZoneInfo("Asia/Shanghai")))
    as_of = as_of or latest
    if as_of > latest or as_of not in sessions:
        raise ValueError("截止日必须是已完成收盘的市场交易日")
    return sessions, as_of


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def prepare_history(frame: pd.DataFrame, sessions: list[date]) -> pd.DataFrame:
    frame = frame.copy()
    if "date" not in frame:
        raise ValueError("本地日线缺少日期列，请更新对应股票行情后重试")
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    if frame["date"].duplicated().any():
        raise ValueError("本地日线存在重复交易日，请更新对应股票行情后重试")
    frame = frame.set_index("date").reindex(sessions)
    for column in [*_PRICE_COLUMNS, "volume"]:
        if column not in frame:
            frame[column] = np.nan
        elif not pd.api.types.is_numeric_dtype(frame[column].dtype):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    # 同一外部数据边界校验一次，避免每只股票重复构造多组临时 Series。
    prices = frame[_PRICE_COLUMNS].to_numpy(dtype=float, na_value=np.nan)
    valid = (
        np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
        & (prices[:, 1] >= prices[:, [0, 2, 3]].max(axis=1))
        & (prices[:, 2] <= prices[:, [0, 1, 3]].min(axis=1))
    )
    frame.loc[~valid, _PRICE_COLUMNS] = np.nan
    frame["valid"] = valid
    volume = frame.volume.to_numpy(dtype=float, na_value=np.nan)
    frame["volume"] = np.where(valid & (volume >= 0) & np.isfinite(volume), volume, np.nan)
    frame["_source"] = frame["_source"].fillna("local_cache").astype(str) if "_source" in frame else "local_cache"
    return frame


def _streak(flags: pd.Series, known: pd.Series) -> tuple[pd.Series, pd.Series]:
    """缺行后的连续段只知道下界，不能据此断言恰好 N 天。"""
    counts: list[float] = []
    exact_flags: list[bool] = []
    count, exact = 0, False
    for flag, valid in zip(flags.to_numpy(), known.to_numpy(), strict=True):
        if not valid:
            count, exact = 0, False
            counts.append(float("nan"))
        elif flag:
            count += 1
            counts.append(float(count))
        else:
            count, exact = 0, True
            counts.append(0.0)
        exact_flags.append(exact)
    return pd.Series(counts, index=flags.index), pd.Series(exact_flags, index=flags.index)


def calculate_metrics(frame: pd.DataFrame, fields: list[tuple[StudyField, int | None]], reference_prices: np.ndarray | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    close, valid = frame.close, frame.valid
    paired = valid & valid.shift(1, fill_value=False)
    metrics: dict[str, Any] = {}
    exact: dict[str, Any] = {}
    metrics["change_pct"] = (close / close.shift(1) - 1) * 100
    for field, window in fields:
        key = f"{field}.{window}" if window else field
        if key in exact:
            continue
        exact[key] = True
        if field == "change_pct":
            continue
        if field == "gap_pct":
            metrics[key] = (frame.open / close.shift(1) - 1) * 100
        elif field == "body_pct":
            metrics[key] = (close / frame.open - 1) * 100
        elif field in _STREAKS:
            flags, known = {
                "up_days": (close.gt(close.shift(1)), paired),
                "down_days": (close.lt(close.shift(1)), paired),
                "bull_days": (close.gt(frame.open), valid),
                "bear_days": (close.lt(frame.open), valid),
                "joint_up_days": (close.gt(frame.open) & close.gt(close.shift(1)), paired),
            }[field]
            metrics[key], exact[key] = _streak(flags, known)
        elif window is not None:
            if field == "return_pct":
                complete = valid.rolling(window + 1).sum().eq(window + 1)
                metrics[key] = ((close / close.shift(window) - 1) * 100).where(complete)
            elif field == "volume_ratio":
                average = frame.volume.shift(1).rolling(window).mean()
                metrics[key] = (frame.volume / average).where(average.gt(0))
            elif field == "position":
                low = frame.low.rolling(window).min()
                span = frame.high.rolling(window).max() - low
                metrics[key] = ((close - low) / span * 100).where(span.gt(0))
            elif field == "low_age":
                metrics[key] = frame.low.rolling(window).apply(lambda values: float(np.argmin(values[::-1])), raw=True)
            elif field == "shape_distance":
                if reference_prices is None or len(reference_prices) < window:
                    raise ValueError("形态比较缺少完整参照窗口")
                reference = reference_prices[-window:]
                if not np.isfinite(reference).all() or (reference <= 0).any():
                    raise ValueError("形态参照包含缺失或无效价格")
                distances = np.full(len(close), np.nan)
                if len(close) >= window:
                    windows = np.lib.stride_tricks.sliding_window_view(close.to_numpy(), window)
                    normalized = windows / windows[:, :1] * 100
                    distances[window - 1:] = np.sqrt(np.mean((normalized - reference / reference[0] * 100) ** 2, axis=1))
                metrics[key] = distances
    return (
        pd.DataFrame(metrics, index=frame.index).replace([np.inf, -np.inf], np.nan),
        pd.DataFrame(exact, index=frame.index),
    )


def _condition_mask(condition: StudyCondition, metrics: pd.DataFrame, exact: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    values = metrics[condition.key]
    matched = _OPS[condition.operator](values, condition.value)
    known = values.notna()
    uncertain = ~exact[condition.key]
    if condition.operator in {"gte", "gt"}:
        known &= ~uncertain | matched
    elif condition.operator in {"lte", "lt"}:
        known &= ~uncertain | ~matched
    else:
        known &= ~uncertain | values.gt(condition.value)
    return matched & known, known


def _evaluate(frame: pd.DataFrame, query: StudyQuery, reference_prices: np.ndarray | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    metrics, exact = calculate_metrics(frame, [(condition.field, condition.window) for condition in query.conditions], reference_prices)
    matched = pd.Series(True, index=frame.index)
    evaluated = pd.Series(True, index=frame.index)
    for condition in query.conditions:
        hits, known = _condition_mask(condition, metrics, exact)
        matched &= hits
        evaluated &= known
    return metrics, exact, matched, evaluated


def _values(metrics: pd.DataFrame, exact: pd.DataFrame, index: int, query: StudyQuery) -> tuple[dict[str, float | None], list[str]]:
    keys = list(dict.fromkeys(item.key for item in query.conditions))
    return (
        {key: _number(metrics[key].iloc[index]) for key in keys},
        [key for key in keys if not exact[key].iloc[index]],
    )


def _selected_indices(hits: pd.Series, evaluated: pd.Series, start: int, query: StudyQuery, *, excluded_index: int | None = None) -> list[int]:
    candidates = [index for index in np.flatnonzero(hits.to_numpy()).tolist() if index != excluded_index]
    if query.sample_policy == "first":
        return [index for index in candidates if index >= start and index > 0 and evaluated.iloc[index - 1] and not hits.iloc[index - 1]]
    candidates = [index for index in candidates if index >= start]
    if query.sample_policy == "every":
        return candidates
    selected: list[int] = []
    for index in candidates:
        if not selected or index > selected[-1] + query.forward_days:
            selected.append(index)
    return selected


def _distribution(events: pd.DataFrame) -> StudyDistribution:
    values = events.loc[events.status.eq("complete"), "return_pct"] if not events.empty else pd.Series(dtype=float)
    if values.empty:
        return StudyDistribution()
    edges = [-np.inf, -10, -5, -2, 0, 2, 5, 10, np.inf]
    labels = ["低于 -10%", "-10% 至 -5%", "-5% 至 -2%", "-2% 至 0%", "0% 至 2%", "2% 至 5%", "5% 至 10%", "10% 及以上"]
    counts = pd.cut(values, edges, right=False, labels=labels).value_counts(sort=False)
    return StudyDistribution(
        count=len(values), positive=int(values.gt(0).sum()), negative=int(values.lt(0).sum()), flat=int(values.eq(0).sum()),
        positive_ratio_pct=float(values.gt(0).mean() * 100), mean_pct=float(values.mean()), median_pct=float(values.median()),
        p10_pct=float(values.quantile(.1)), p90_pct=float(values.quantile(.9)), min_pct=float(values.min()), max_pct=float(values.max()),
        bins=[StudyBin(label=label, count=int(counts[label])) for label in labels],
    )


def _event_records(frame: pd.DataFrame, indices: list[int], metrics: pd.DataFrame, exact: pd.DataFrame, query: StudyQuery, symbol: str, name: str, all_sessions: list[date], session_positions: dict[date, int]) -> list[dict]:
    records = []
    for index in indices:
        day = frame.index[index]
        end = index + query.forward_days
        target_index = session_positions[day] + query.forward_days
        target = all_sessions[target_index] if target_index < len(all_sessions) else None
        if end >= len(frame):
            status = "pending"
        elif not frame.valid.iloc[index + 1:end + 1].all():
            status = "missing"
        else:
            status = "complete"
        price = float(frame.close.iloc[index])
        values, lower_bounds = _values(metrics, exact, index, query)
        record = {
            "event_id": f"{symbol}-{day.isoformat()}", "symbol": symbol, "name": name,
            "event_date": day, "event_close": price, "forward_date": target, "status": status,
            "return_pct": float(frame.close.iloc[end] / price - 1) * 100 if status == "complete" else None,
            "max_return_pct": float(frame.high.iloc[index + 1:end + 1].max() / price - 1) * 100 if status == "complete" else None,
            "min_return_pct": float(frame.low.iloc[index + 1:end + 1].min() / price - 1) * 100 if status == "complete" else None,
            "values": values, "lower_bounds": lower_bounds,
        }
        records.append(record)
    return records


def _event_model(record: dict) -> StudyEvent:
    for key in ("return_pct", "max_return_pct", "min_return_pct"):
        record[key] = _number(record.get(key))
    if pd.isna(record.get("forward_date")):
        record["forward_date"] = None
    record["lower_bounds"] = list(record.get("lower_bounds", []))
    return StudyEvent.model_validate(record)


def evaluate_study(query: StudyQuery, histories: Iterable[tuple[str, str, pd.DataFrame | None]], sessions: list[date], as_of: date, *, study_id: str = "study", run_id: str = "run", reference_history: pd.DataFrame | None = None) -> tuple[StudyResult, pd.DataFrame, pd.DataFrame]:
    """无取数、无写入的研究计算；历史条件只读取当日及之前的数据。"""
    complete_sessions = [day for day in sessions if day <= as_of]
    session_positions = {day: index for index, day in enumerate(sessions)}
    if not complete_sessions or complete_sessions[-1] != as_of:
        raise ValueError("交易日历不包含研究截止日")
    window = max((condition.window or 1 for condition in query.conditions), default=1)
    streak_history = [math.ceil(max(0, condition.value)) + 2 for condition in query.conditions if condition.field in _STREAKS]
    # 连续条件按阈值取得足以判定的前置记录；超过已知段时仍保留 lower_bound。
    warmup = max(31, window + 1, *streak_history)
    calendar = complete_sessions[-(query.lookback_days + warmup):]
    start = max(0, len(calendar) - query.lookback_days)
    coverage = StudyCoverage(calendar_days=len(calendar) - start)
    matches: list[StudyMatch] = []
    events: list[dict] = []
    frozen: list[pd.DataFrame] = []
    unavailable: list[str] = []
    warnings = [
        "股票池是本次选择的成员，用它研究历史不等于历史时点全市场；已退市或未在当前池内的股票不在样本中。",
        "使用本地缓存的日线复权序列；结果是历史报价分布，不是成交收益或未来概率。",
    ]
    reference_prices = None
    reference_bars: list[StudyBar] = []
    reference_source = None
    if query.reference is not None:
        reference = query.reference
        if reference.as_of > as_of or reference.as_of not in sessions:
            raise ValueError("形态参照日必须是不晚于研究截止日的完整市场交易日")
        reference_window = max(item.window or 0 for item in query.conditions if item.field == "shape_distance")
        reference_dates = [day for day in sessions if day <= reference.as_of][-reference_window:]
        if reference_history is None or len(reference_dates) < reference_window:
            raise ValueError("参照股票缺少完整窗口，请先更新参照股票行情")
        reference_frame = prepare_history(reference_history, reference_dates)
        if not reference_frame.valid.all():
            raise ValueError("参照股票窗口有行情缺口，请选择完整窗口或更新行情")
        reference_prices = reference_frame.close.to_numpy()
        reference_source = " / ".join(dict.fromkeys(reference_frame["_source"].astype(str)))
        reference_bars = [StudyBar(date=day, **{column: _number(row[column]) for column in [*_PRICE_COLUMNS, "volume"]}) for day, row in reference_frame.iterrows()]
        warnings.append("这是事后形态检索：参照形态可能包含历史事件当时尚未知的信息，不能解释为可事前执行的策略回测；同股票同参照日期的自匹配已排除。")
    for symbol, name, raw in histories:
        coverage.total_symbols += 1
        if raw is None or raw.empty:
            coverage.missing_symbols += 1
            unavailable.append(symbol)
            continue
        frame = prepare_history(raw, calendar)
        coverage.cached_symbols += 1
        metrics, exact, hits, evaluated = _evaluate(frame, query, reference_prices)
        coverage.valid_stock_days += int(frame.valid.iloc[start:].sum())
        coverage.evaluated_stock_days += int(evaluated.iloc[start:].sum())
        self_index = calendar.index(query.reference.as_of) if query.reference is not None and query.reference.symbol == symbol and query.reference.as_of in calendar else None
        self_hit = self_index is not None and self_index >= start and bool(hits.iloc[self_index])
        coverage.self_matches_excluded += int(self_hit)
        coverage.matched_stock_days += int(hits.iloc[start:].sum()) - int(self_hit)
        coverage.current_evaluated += int(evaluated.iloc[-1])
        if not evaluated.iloc[-1]:
            unavailable.append(symbol)
        if hits.iloc[-1] and self_index != len(frame) - 1:
            values, bounds = _values(metrics, exact, len(frame) - 1, query)
            matches.append(StudyMatch(symbol=symbol, name=name, date=as_of, close=float(frame.close.iloc[-1]), change_pct=_number(metrics.change_pct.iloc[-1]), values=values, lower_bounds=bounds))
        indices = _selected_indices(hits, evaluated, start, query, excluded_index=self_index)
        events.extend(_event_records(frame, indices, metrics, exact, query, symbol, name, sessions, session_positions))
        if indices or hits.iloc[-1]:
            saved = frame.reset_index(names="date")
            saved["symbol"], saved["name"] = symbol, name
            frozen.append(saved[["symbol", "name", "date", *_PRICE_COLUMNS, "volume", "_source"]])
    coverage.historical_stock_days = coverage.total_symbols * coverage.calendar_days
    coverage.current_matches = len(matches)
    coverage.current_missing = coverage.total_symbols - coverage.current_evaluated
    event_frame = pd.DataFrame(events)
    if not event_frame.empty:
        event_frame = event_frame.sort_values(["event_date", "symbol"], ascending=[False, True]).reset_index(drop=True)
        counts = event_frame.status.value_counts()
        coverage.complete_events = int(counts.get("complete", 0))
        coverage.pending_events = int(counts.get("pending", 0))
        coverage.missing_events = int(counts.get("missing", 0))
    coverage.selected_events = len(events)
    if coverage.current_missing:
        warnings.append(f"截至 {as_of}，{coverage.current_missing} 只股票缺少完整条件所需行情；未把它们当作不符合。")
    if query.sample_policy == "first":
        warnings.append("首次满足只在上一交易日可评估且不满足时计入；数据边界不冒充新事件。")
    if query.sample_policy == "every":
        warnings.append("逐日样本可能重叠，同一行情过程不能当作独立重复实验。")
    result = StudyResult(
        study_id=study_id, run_id=run_id, query=query, created_at=datetime.now(UTC), as_of=as_of,
        start_date=calendar[start], universe_note="当前选择的股票池历史；非历史时点全市场",
        coverage=coverage, distribution=_distribution(event_frame), current_matches=sorted(matches, key=lambda item: item.symbol),
        events=[_event_model(item) for item in event_frame.head(50).to_dict("records")],
        events_total=len(events), unavailable_symbols=unavailable, reference_bars=reference_bars, reference_source=reference_source, warnings=warnings,
    )
    return result, event_frame, pd.concat(frozen, ignore_index=True) if frozen else pd.DataFrame()


def _run_dir(run_id: str) -> Path:
    if not run_id or any(character not in "0123456789abcdef" for character in run_id) or len(run_id) != 32:
        raise ValueError("研究运行 ID 无效")
    return paths.BASE_DIR / "market_studies" / run_id


def _load_run(run_id: str) -> StudyResult:
    _run_dir(run_id)
    payload = workspace_db.get_state(f"{_RUN}{run_id}")
    if payload is None:
        raise ValueError("这份研究结果不存在")
    return StudyResult.model_validate(payload)


def run_study(query: StudyQuery, *, study_id: str | None = None) -> StudyResult:
    from kan.data.fetcher import get_cached

    sessions, as_of = resolve_market_calendar(query.as_of)
    members = resolve_study_members(query.universe, query.codes)
    if not members:
        raise ValueError("当前研究股票池为空，请填写明确代码或先添加个人研究对象")
    old_payload = workspace_db.get_state(f"{_STUDY}{study_id}") if study_id else None
    if study_id is not None and old_payload is None:
        raise ValueError("研究不存在")
    previous = _load_run(str(old_payload["last_run_id"])) if old_payload else None
    if previous is not None and previous.query.model_dump(exclude={"as_of"}) != query.model_dump(exclude={"as_of"}):
        raise ValueError("修改条件请创建一份新研究，同条件重跑不会改写原研究问题")
    actual_study_id, run_id = study_id or uuid4().hex, uuid4().hex
    reference_history = None
    if query.reference:
        if previous is not None:
            reference_history = pd.DataFrame([bar.model_dump() for bar in previous.reference_bars])
            reference_history["_source"] = previous.reference_source or "local_cache"
        else:
            reference_history = get_cached(query.reference.symbol)
    result, events, bars = evaluate_study(query, ((symbol, name, get_cached(symbol)) for symbol, name in members), sessions, as_of, study_id=actual_study_id, run_id=run_id, reference_history=reference_history)
    if previous:
        old = {item.symbol for item in previous.current_matches}
        new = {item.symbol for item in result.current_matches}
        outside_scope = old - {symbol for symbol, _name in members}
        unknown = set(result.unavailable_symbols) | outside_scope
        result.diff = StudyDiff(previous_run_id=previous.run_id, previous_as_of=previous.as_of, added=sorted(new - old), removed=sorted(old - new - unknown), unavailable=sorted((old - new) & unknown))
        if outside_scope:
            result.warnings.append(f"旧匹配对象 {', '.join(sorted(outside_scope))} 已不在本次股票池，列为无法核对，未判作条件不满足。")
    directory = _run_dir(run_id)
    directory.mkdir(parents=True, mode=0o700)
    if not events.empty:
        events.to_parquet(directory / "events.parquet", index=False)
    if not bars.empty:
        bars.to_parquet(directory / "bars.parquet", index=False)
    summary = StudySummary(
        study_id=actual_study_id, title=query.title, query=query,
        created_at=datetime.fromisoformat(str(old_payload["created_at"])) if old_payload else result.created_at,
        last_run_at=result.created_at, last_run_id=run_id, as_of=as_of,
        current_count=len(result.current_matches), event_count=result.events_total,
    )
    with workspace_db.transaction() as conn:
        index = workspace_db.get_state(_INDEX, conn=conn) or {"ids": []}
        ids = cast(list[str], index["ids"])
        workspace_db.put_state(_RUN + run_id, result.model_dump(mode="json"), conn=conn)
        workspace_db.put_state(_STUDY + actual_study_id, summary.model_dump(mode="json"), conn=conn)
        workspace_db.put_state(_INDEX, {"ids": [actual_study_id, *(item for item in ids if item != actual_study_id)]}, conn=conn)
    return result


def list_studies() -> list[StudySummary]:
    index = workspace_db.get_state(_INDEX) or {"ids": []}
    return [StudySummary.model_validate(workspace_db.get_state(_STUDY + item)) for item in cast(list[str], index["ids"])]


def get_study(study_id: str) -> StudyResult:
    payload = workspace_db.get_state(_STUDY + study_id)
    if payload is None:
        raise ValueError("研究不存在")
    return _load_run(str(payload["last_run_id"]))


def rerun_study(study_id: str, *, latest: bool = False) -> StudyResult:
    previous = get_study(study_id)
    query = previous.query.model_copy(update={"as_of": None if latest else previous.as_of})
    return run_study(query, study_id=study_id)


def study_events(run_id: str, *, offset: int = 0, limit: int = 50) -> StudyEventPage:
    import pyarrow.parquet as pq

    run = _load_run(run_id)
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("事件分页需要 offset >= 0、1 <= limit <= 200")
    items: list[StudyEvent] = []
    path = _run_dir(run_id) / "events.parquet"
    if path.exists():
        seen = 0
        for batch in pq.ParquetFile(path).iter_batches(batch_size=1_024):
            if seen + len(batch) > offset:
                start = max(0, offset - seen)
                records = batch.slice(start, min(limit - len(items), len(batch) - start)).to_pylist()
                items.extend(_event_model(item) for item in records)
            seen += len(batch)
            if len(items) >= limit:
                break
    return StudyEventPage(run_id=run_id, total=run.events_total, offset=offset, limit=limit, items=items)


def study_evidence(run_id: str, symbol: str, event_date: date) -> StudyEvidence:
    run = _load_run(run_id)
    if run.query.reference and run.query.reference.symbol == symbol and run.query.reference.as_of == event_date:
        raise ValueError("参照股票自身的同日窗口已排除，不属于匹配结果")
    path = _run_dir(run_id) / "bars.parquet"
    if not path.exists():
        raise ValueError("该结果没有可查看的行情证据")
    raw = pd.read_parquet(path, filters=[("symbol", "=", symbol)])
    if raw.empty:
        raise ValueError("该股票不在本次结果的图证中")
    sessions = [pd.Timestamp(item).date() for item in raw.date]
    if event_date not in sessions:
        raise ValueError("该日期不在本次研究图证中")
    frame = prepare_history(raw, sessions)
    reference_prices = np.array([bar.close for bar in run.reference_bars], dtype=float) if run.reference_bars else None
    metrics, exact, hits, _evaluated = _evaluate(frame, run.query, reference_prices)
    index = sessions.index(event_date)
    if not hits.iloc[index]:
        raise ValueError("该股票在指定日期未满足本次研究条件")
    checks = []
    for condition in run.query.conditions:
        matched, known = _condition_mask(condition, metrics, exact)
        checks.append(StudyCheck(condition=condition, actual=_number(metrics[condition.key].iloc[index]), bound="exact" if exact[condition.key].iloc[index] else "at_least", matched=bool(matched.iloc[index]) if known.iloc[index] else None))
    events_path = _run_dir(run_id) / "events.parquet"
    outcome = None
    if events_path.exists():
        found = pd.read_parquet(events_path, filters=[("symbol", "=", symbol), ("event_date", "=", event_date)])
        if not found.empty:
            outcome = _event_model(found.iloc[0].to_dict())
    before = max(30, max((item.window or 1 for item in run.query.conditions), default=1) + 1)
    shown = frame.iloc[max(0, index - before):index + run.query.forward_days + 1]
    source = " / ".join(dict.fromkeys(shown.loc[shown.valid, "_source"].astype(str)))
    return StudyEvidence(
        run_id=run_id, symbol=symbol, name=str(raw.name.iloc[0]), event_date=event_date, source=source,
        bars=[StudyBar(date=day, **{column: _number(row[column]) for column in [*_PRICE_COLUMNS, "volume"]}) for day, row in shown.iterrows()],
        reference_bars=run.reference_bars, reference_source=run.reference_source,
        conditions=checks, outcome=outcome,
        warnings=["图中空缺表示当次保存的数据缺口；所有价格为当次缓存复权口径。"],
    )

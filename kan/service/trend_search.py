"""当前趋势筛选：只读缓存、共用指标，不创建历史研究。"""

from __future__ import annotations

import datetime
import math
from collections import Counter
from typing import Any, Literal, cast
from uuid import uuid4

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from kan.domain.market_study import (
    StudyBar,
    StudyCheck,
    StudyCondition,
    StudyField,
    StudyModel,
    StudyReference,
    SwingEvidence,
)
from kan.service.market_study import (
    FIELD_CATALOG,
    calculate_metrics,
    evaluate_condition,
    normalize_history_dates,
    prepare_history,
    prepare_reference,
    resolve_market_calendar,
    resolve_study_members,
    swing_evidence,
)


class TrendSearchQuery(StudyModel):
    universe: Literal["all", "personal", "codes"] = "all"
    codes: list[str] = Field(default_factory=list, max_length=10_000)
    industries: list[str] = Field(default_factory=list, max_length=100)
    as_of: datetime.date | None = None
    compare_to: Literal["previous_session"] | datetime.date | None = None
    conditions: list[StudyCondition] = Field(default_factory=list, max_length=12)
    reference: StudyReference | None = None
    swing_reversal_pct: float = Field(default=5, gt=0, lt=100)

    @model_validator(mode="after")
    def validate_scope(self) -> TrendSearchQuery:
        from kan.storage.watchlist_models import _normalize_symbol

        if self.universe == "codes":
            if not self.codes:
                raise ValueError("请至少填写一个股票代码")
            self.codes = list(dict.fromkeys(_normalize_symbol(code) for code in self.codes))
        elif self.codes:
            raise ValueError("仅代码池接受代码列表")
        self.industries = list(dict.fromkeys(item.strip() for item in self.industries if item.strip()))
        if any(item.field == "shape_distance" for item in self.conditions) != (self.reference is not None):
            raise ValueError("形态距离必须选择参照股票及日期；其他筛选不使用形态参照")
        return self


class TrendSegment(StudyModel):
    direction: Literal["up", "down", "flat"]
    days: int
    bound: Literal["exact", "at_least"]
    start_date: datetime.date
    base_date: datetime.date
    return_pct: float


class TrendPricePoint(StudyModel):
    date: datetime.date
    close: float | None


class TrendSearchRow(StudyModel):
    symbol: str
    name: str
    industry: str | None = None
    date: datetime.date
    close: float
    change_pct: float | None
    values: dict[str, float | None]
    lower_bounds: list[str]
    positions: dict[str, float | None]
    returns: dict[str, float | None]
    current_segment: TrendSegment | None = None
    source: str
    gap_dates: list[datetime.date]
    sparkline: list[TrendPricePoint]


class TrendSearchMissing(StudyModel):
    symbol: str
    name: str
    reason: str


class TrendSearchCoverage(StudyModel):
    total: int
    evaluated: int
    matched: int
    missing: int
    self_matches_excluded: int = 0


class TrendSearchIndustry(StudyModel):
    name: str
    total: int


class TrendComparisonSnapshot(StudyModel):
    matched: bool | None
    close: float | None = None
    conditions: list[StudyCheck] = Field(default_factory=list)
    reason: str | None = None


class TrendComparisonRow(StudyModel):
    symbol: str
    name: str
    industry: str | None = None
    status: Literal["entered", "continued", "exited", "uncertain"]
    previous: TrendComparisonSnapshot
    current: TrendComparisonSnapshot


class TrendComparisonCoverage(StudyModel):
    comparable: int = 0
    entered: int = 0
    continued: int = 0
    exited: int = 0
    unchanged: int = 0
    uncertain: int = 0
    excluded: int = 0


class TrendSearchComparison(StudyModel):
    as_of: datetime.date
    coverage: TrendComparisonCoverage = Field(default_factory=TrendComparisonCoverage)
    rows: list[TrendComparisonRow] = Field(default_factory=list)
    excluded_rows: list[TrendSearchMissing] = Field(default_factory=list)


class TrendSearchResult(StudyModel):
    query: TrendSearchQuery
    as_of: datetime.date
    coverage: TrendSearchCoverage
    common_data_date: datetime.date | None = None
    common_data_count: int = 0
    rows: list[TrendSearchRow]
    missing_rows: list[TrendSearchMissing]
    scope_codes: list[str]
    industries: list[TrendSearchIndustry]
    warnings: list[str]
    comparison: TrendSearchComparison | None = None


class TrendEvidenceBar(StudyBar):
    change_pct: float | None = None
    body_pct: float | None = None


class TrendSearchEvidenceRequest(StudyModel):
    query: TrendSearchQuery
    symbol: str
    at: datetime.date | None = None


class TrendSearchEvidence(StudyModel):
    query: TrendSearchQuery
    as_of: datetime.date
    row: TrendSearchRow
    bars: list[TrendEvidenceBar]
    reference_bars: list[StudyBar] = Field(default_factory=list)
    reference_source: str | None = None
    conditions: list[StudyCheck]
    swings: list[SwingEvidence] = Field(default_factory=list)
    warnings: list[str]


_BASE_FIELDS: list[tuple[StudyField, int | None]] = [
    ("change_pct", None), ("body_pct", None),
    ("up_days", None), ("down_days", None), ("bull_days", None), ("bear_days", None),
    ("joint_up_days", None), ("previous_up_days", None), ("previous_down_days", None),
    *(("position", window) for window in (30, 60, 180)),
    *(("return_pct", window) for window in (5, 20, 60)),
]


def _number(value: Any) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _industries() -> dict[str, str]:
    from kan.data.industry_map import fetch_sw_l1_map

    return fetch_sw_l1_map()


def _scope(query: TrendSearchQuery) -> tuple[list[tuple[str, str]], dict[str, str], list[TrendSearchIndustry]]:
    members = resolve_study_members(query.universe, query.codes)
    industries = _industries()
    counts: dict[str, int] = {}
    for symbol, _name in members:
        industry = industries.get(symbol, "未分类")
        counts[industry] = counts.get(industry, 0) + 1
    choices = [TrendSearchIndustry(name=name, total=count) for name, count in sorted(counts.items())]
    if query.industries:
        if not industries and any(item != "未分类" for item in query.industries):
            raise ValueError("行业归属不可用，请更新行业数据或移除行业条件")
        members = [(symbol, name) for symbol, name in members if industries.get(symbol, "未分类") in query.industries]
    return members, industries, choices


def prepare_cached_history(symbol: str, sessions: list[datetime.date]) -> pd.DataFrame:
    from kan.data.fetcher import cache_unavailable_reason, get_cached

    try:
        raw = get_cached(symbol)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("本地行情文件无法读取，请重新获取该股票数据") from exc
    if raw is None:
        raise ValueError(cache_unavailable_reason(symbol))
    if raw.empty:
        raise ValueError("本地日线文件为空，请更新该股票数据")
    if "date" not in raw:
        raise ValueError("本地日线缺少日期列，请更新对应股票行情后重试")
    dates = normalize_history_dates(raw["date"])
    included = dates <= sessions[-1]
    raw = raw.loc[included].copy(deep=False)
    if raw.empty:
        raise ValueError("截止日前没有本地行情")
    dates = dates.loc[included]
    raw["date"] = dates
    # 保留缓存中完整的连续段；不把固定 180 日边界冒充真实段首。
    first_date = dates.min()
    calendar = [day for day in sessions if day >= first_date]
    return prepare_history(raw, calendar)


def _checks_at(query: TrendSearchQuery, metrics: pd.DataFrame, exact: pd.DataFrame, days: list[datetime.date]) -> dict[datetime.date, list[StudyCheck]]:
    """条件只判断一次完整序列，再摘取需要对照的日期。"""
    checks: dict[datetime.date, list[StudyCheck]] = {day: [] for day in days}
    for condition in query.conditions:
        hits, known = evaluate_condition(condition, metrics, exact)
        for day in days:
            checks[day].append(StudyCheck(
                condition=condition, actual=_number(metrics.at[day, condition.key]),
                bound="exact" if exact.at[day, condition.key] else "at_least",
                matched=bool(hits.at[day]) if known.at[day] else None,
            ))
    return checks


def _comparison_date(query: TrendSearchQuery, sessions: list[datetime.date], as_of: datetime.date) -> datetime.date | None:
    if query.compare_to is None:
        return None
    if query.compare_to == "previous_session":
        if len(sessions) < 2:
            raise ValueError("交易日历没有可用的上一交易日")
        return sessions[-2]
    if query.compare_to >= as_of or query.compare_to not in sessions:
        raise ValueError("对照日必须是早于截止日的已完成市场交易日")
    return query.compare_to


_DEFINITIONS = {item["field"]: item for item in FIELD_CATALOG}
_COMPARISONS = {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<", "eq": "="}


def _snapshot(frame: pd.DataFrame, day: datetime.date, checks: list[StudyCheck]) -> TrendComparisonSnapshot:
    if day not in frame.index or not frame.at[day, "valid"]:
        return TrendComparisonSnapshot(matched=None, reason="截止日缺少有效行情")
    unknown, failed = [], []
    for check in checks:
        definition = _DEFINITIONS[check.condition.field]
        label = f"{check.condition.window}日{definition['label']}" if check.condition.window else str(definition["label"])
        if check.matched is None:
            detail = (f"仅能确认至少 {check.actual:g}{definition['unit']}，无法核对当前条件"
                      if check.actual is not None and check.bound == "at_least" else "缺少所需行情")
            if check.condition.field == "swing_structure":
                sample = frame.loc[:day].tail(check.condition.window)
                if len(sample) == check.condition.window and sample.valid.all():
                    detail = "尚不足两组已确认波峰与波谷，无法判断结构"
            unknown.append(f"{label}：{detail}")
        elif not check.matched:
            bound = "至少 " if check.bound == "at_least" else ""
            failed.append(f"{label} {bound}{check.actual:g}{definition['unit']}，要求 {_COMPARISONS[check.condition.operator]} {check.condition.value:g}{definition['unit']}")
    return TrendComparisonSnapshot(
        matched=None if unknown else not failed, close=float(frame.at[day, "close"]),
        conditions=checks, reason="；".join(unknown or failed) or None,
    )


def _record_comparison(comparison: TrendSearchComparison, query: TrendSearchQuery, as_of: datetime.date, symbol: str, name: str, industry: str | None, previous: TrendComparisonSnapshot, current: TrendComparisonSnapshot) -> None:
    coverage = comparison.coverage
    if query.reference and query.reference.symbol == symbol and query.reference.as_of in {comparison.as_of, as_of}:
        coverage.excluded += 1
        comparison.excluded_rows.append(TrendSearchMissing(symbol=symbol, name=name, reason=f"参照自身 {query.reference.as_of} 窗口不参与两日变化判断"))
        return
    status: Literal["entered", "continued", "exited", "uncertain"]
    if previous.matched is None or current.matched is None:
        status = "uncertain"
        coverage.uncertain += 1
    else:
        coverage.comparable += 1
        if not previous.matched and not current.matched:
            coverage.unchanged += 1
            return
        status = "continued" if previous.matched and current.matched else "entered" if current.matched else "exited"
        setattr(coverage, status, getattr(coverage, status) + 1)
    comparison.rows.append(TrendComparisonRow(symbol=symbol, name=name, industry=industry, status=status, previous=previous, current=current))


def _segment(frame: pd.DataFrame, metrics: pd.DataFrame, exact: pd.DataFrame) -> TrendSegment | None:
    change = _number(metrics.change_pct.iloc[-1])
    if change is None:
        return None
    direction: Literal["up", "down", "flat"] = "up" if change > 0 else "down" if change < 0 else "flat"
    key = "up_days" if change > 0 else "down_days"
    count = int(metrics[key].iloc[-1]) if change else 0
    base = len(frame) - max(count, 1) - 1
    return TrendSegment(
        direction=direction, days=count,
        bound="exact" if not change or exact[key].iloc[-1] else "at_least",
        start_date=frame.index[base + 1], base_date=frame.index[base],
        return_pct=float((frame.close.iloc[-1] / frame.close.iloc[base] - 1) * 100),
    )


def _row(symbol: str, name: str, industry: str | None, frame: pd.DataFrame, metrics: pd.DataFrame, exact: pd.DataFrame) -> TrendSearchRow:
    latest = metrics.iloc[-1]
    return TrendSearchRow(
        symbol=symbol, name=name, industry=industry, date=frame.index[-1], close=float(frame.close.iloc[-1]),
        change_pct=_number(latest.change_pct),
        values={key: _number(value) for key, value in latest.items()},
        lower_bounds=[key for key in exact.columns if pd.notna(latest[key]) and not exact[key].iloc[-1]],
        positions={str(window): _number(latest[f"position.{window}"]) for window in (30, 60, 180)},
        returns={str(window): _number(latest[f"return_pct.{window}"]) for window in (5, 20, 60)},
        current_segment=_segment(frame, metrics, exact),
        source=" / ".join(dict.fromkeys(frame.loc[frame.valid, "_source"].astype(str))) or "local_cache",
        gap_dates=list(frame.index[~frame.valid]),
        sparkline=[TrendPricePoint(date=day, close=_number(value)) for day, value in frame.close.tail(20).items()],
    )


def _reference(query: TrendSearchQuery, sessions: list[datetime.date], as_of: datetime.date) -> tuple[np.ndarray | None, list[StudyBar], str | None]:
    if query.reference is None:
        return None, [], None
    from kan.data.fetcher import get_cached

    return prepare_reference(query.reference, query.conditions, sessions, as_of, get_cached(query.reference.symbol))


def _swing_display_fields(query: TrendSearchQuery) -> list[tuple[StudyField, int | None]]:
    fields: tuple[StudyField, ...] = ("swing_structure", "swing_direction", "swing_count")
    windows = sorted({item.window for item in query.conditions if item.field in fields and item.window is not None})
    return [(field, window) for window in windows for field in fields]


def search_trends(query: TrendSearchQuery) -> TrendSearchResult:
    """同一当前成员范围、同一复权缓存；一次读取同时核对两个日期。"""
    sessions, as_of = resolve_market_calendar(query.as_of)
    sessions = [day for day in sessions if day <= as_of]
    compared_at = _comparison_date(query, sessions, as_of)
    comparison = TrendSearchComparison(as_of=compared_at) if compared_at else None
    members, industries, choices = _scope(query)
    reference_prices, _reference_bars, _reference_source = _reference(query, sessions, as_of)
    cutoffs: Counter[datetime.date] = Counter()
    self_matches = 0
    rows: list[TrendSearchRow] = []
    missing: list[TrendSearchMissing] = []
    points = [as_of, compared_at] if compared_at else [as_of]
    swing_fields = _swing_display_fields(query)
    fields = [*((item.field, item.window) for item in query.conditions), *swing_fields] if query.conditions else _BASE_FIELDS
    for symbol, name in members:
        try:
            frame = prepare_cached_history(symbol, sessions)
            valid_dates = frame.index[frame.valid]
            if len(valid_dates):
                cutoffs[valid_dates[-1]] += 1
            available_points = [day for day in points if day in frame.index and frame.at[day, "valid"]]
            point_checks: dict[datetime.date, list[StudyCheck]] = {}
            if available_points:
                metrics, exact = calculate_metrics(frame, fields, reference_prices, swing_reversal_pct=query.swing_reversal_pct, swing_points=available_points)
                point_checks = _checks_at(query, metrics, exact, available_points)
            current = _snapshot(frame, as_of, point_checks.get(as_of, []))
            previous = _snapshot(frame, compared_at, point_checks.get(compared_at, [])) if compared_at else current
            if current.matched:
                if query.reference and query.reference.symbol == symbol and query.reference.as_of == as_of:
                    self_matches += 1
                else:
                    if query.conditions:
                        # 只给当前匹配补展示指标；变化列表复用两日条件值，不重复完整行情结果。
                        remaining = [(field, window) for field, window in _BASE_FIELDS if (f"{field}.{window}" if window else field) not in exact]
                        if remaining:
                            more_metrics, more_exact = calculate_metrics(frame, remaining, reference_prices)
                            metrics = metrics.join(more_metrics[[key for key in more_metrics if key not in metrics]])
                            exact = exact.join(more_exact[[key for key in more_exact if key not in exact]])
                        display_fields = [*_BASE_FIELDS, *((item.field, item.window) for item in query.conditions), *swing_fields]
                        keys = list(dict.fromkeys(f"{field}.{window}" if window else field for field, window in display_fields))
                        metrics, exact = metrics[keys], exact[keys]
                    rows.append(_row(symbol, name, industries.get(symbol), frame, metrics, exact))
        except (ValueError, OSError) as exc:
            current = previous = TrendComparisonSnapshot(matched=None, reason=str(exc))
        if current.matched is None:
            missing.append(TrendSearchMissing(symbol=symbol, name=name, reason=current.reason or "资料不足"))
        if comparison:
            _record_comparison(comparison, query, as_of, symbol, name, industries.get(symbol), previous, current)
    warnings = ["使用当前上市范围与当前行业归属；仅匹配明确条件，不代表推荐。"]
    if comparison:
        warnings.append("两日使用本次同一股票范围与当前缓存的统一复权基准；不是与上次运行存档比较。资料不足不计为新出现或已退出。")
    if query.reference:
        warnings.append("形态距离使用明确参照窗口；参照自身同日窗口已排除，不是推荐评分。")
        if compared_at and query.reference.as_of > compared_at:
            warnings.append("固定形态参照晚于对照日；两日对照是事后形态检索，不是当时可执行的筛选或回测。")
    if missing:
        warnings.append(f"{len(missing)} 只资料或条件证据不足，未将其视为不符合条件；具体原因见无法判断列表。")
    return TrendSearchResult(
        query=query, as_of=as_of,
        coverage=TrendSearchCoverage(total=len(members), evaluated=len(members) - len(missing), matched=len(rows), missing=len(missing), self_matches_excluded=self_matches),
        common_data_date=max(cutoffs, key=lambda day: (cutoffs[day], day)) if cutoffs else None,
        common_data_count=max(cutoffs.values(), default=0),
        rows=rows, missing_rows=missing, scope_codes=[symbol for symbol, _ in members], industries=choices, warnings=warnings, comparison=comparison,
    )


def trend_search_evidence(query: TrendSearchQuery, symbol: str, at: datetime.date | None = None) -> TrendSearchEvidence:
    """保留本次固定参照，核对当前日或对照日；图证不包含选中日期之后的行情。"""
    from kan.storage.watchlist_models import _normalize_symbol

    symbol = _normalize_symbol(symbol)
    sessions, as_of = resolve_market_calendar(query.as_of)
    sessions = [day for day in sessions if day <= as_of]
    compared_at = _comparison_date(query, sessions, as_of)
    point = at or as_of
    if point not in {as_of, compared_at}:
        raise ValueError("图证日期必须是本次截止日或对照日")
    names = dict(resolve_study_members("codes", [symbol]))
    reference_prices, reference_bars, reference_source = _reference(query, sessions, as_of)
    frame = prepare_cached_history(symbol, sessions).loc[:point]
    if frame.empty or frame.index[-1] != point or not frame.valid.iloc[-1]:
        raise ValueError("所选日期缺少有效行情，请先更新数据")
    fields = [*_BASE_FIELDS, *((item.field, item.window) for item in query.conditions), *_swing_display_fields(query)]
    metrics, exact = calculate_metrics(frame, fields, reference_prices, swing_reversal_pct=query.swing_reversal_pct, swing_points=[point])
    row = _row(symbol, names[symbol], _industries().get(symbol), frame, metrics, exact)
    bars = [TrendEvidenceBar(
        date=day, **{key: _number(value[key]) for key in ("open", "high", "low", "close", "volume")},
        change_pct=_number(metrics.at[day, "change_pct"]), body_pct=_number(metrics.at[day, "body_pct"]),
    ) for day, value in frame.iterrows()]
    warnings = ["图证读取当前本地缓存；如需保留当次证据，请显式创建历史研究。"]
    if query.reference and query.reference.as_of > point:
        warnings.append("固定形态参照晚于所选日期；此图仅用于事后形态核对。")
    return TrendSearchEvidence(
        query=query, as_of=point, row=row, bars=bars, reference_bars=reference_bars, reference_source=reference_source,
        conditions=_checks_at(query, metrics, exact, [point])[point], warnings=warnings,
        swings=swing_evidence(frame, query.conditions, query.swing_reversal_pct),
    )


class SaveTrendSearchRequest(StudyModel):
    title: str = Field(min_length=1, max_length=120)
    query: TrendSearchQuery

    @model_validator(mode="after")
    def validate_title(self) -> SaveTrendSearchRequest:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("筛选名称不能为空")
        return self


class SavedTrendSearch(SaveTrendSearchRequest):
    id: str


def list_saved_trends() -> list[SavedTrendSearch]:
    from kan.storage import workspace_db

    payload = workspace_db.get_state("trend_search:saved") or {"items": []}
    return [SavedTrendSearch.model_validate(item) for item in cast(list[dict], payload["items"])]


def save_trend_search(title: str, query: TrendSearchQuery) -> SavedTrendSearch:
    """仅保存命名条件，不读取行情、不运行或创建研究。"""
    from kan.storage import workspace_db

    saved = SavedTrendSearch(id=uuid4().hex, title=title, query=query)
    with workspace_db.transaction() as conn:
        payload = workspace_db.get_state("trend_search:saved", conn=conn) or {"items": []}
        workspace_db.put_state("trend_search:saved", {"items": [saved.model_dump(mode="json"), *cast(list[dict], payload["items"])]}, conn=conn)
    return saved


def delete_saved_trend(saved_id: str) -> bool:
    from kan.storage import workspace_db

    with workspace_db.transaction() as conn:
        payload = workspace_db.get_state("trend_search:saved", conn=conn) or {"items": []}
        remaining = [item for item in cast(list[dict], payload["items"]) if item["id"] != saved_id]
        if len(remaining) == len(cast(list[dict], payload["items"])):
            return False
        workspace_db.put_state("trend_search:saved", {"items": remaining}, conn=conn)
    return True

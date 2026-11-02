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
)


class TrendSearchQuery(StudyModel):
    universe: Literal["all", "personal", "codes"] = "all"
    codes: list[str] = Field(default_factory=list, max_length=10_000)
    industries: list[str] = Field(default_factory=list, max_length=100)
    as_of: datetime.date | None = None
    conditions: list[StudyCondition] = Field(default_factory=list, max_length=12)
    reference: StudyReference | None = None

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


class TrendEvidenceBar(StudyBar):
    change_pct: float | None = None
    body_pct: float | None = None


class TrendSearchEvidenceRequest(StudyModel):
    query: TrendSearchQuery
    symbol: str


class TrendSearchEvidence(StudyModel):
    query: TrendSearchQuery
    as_of: datetime.date
    row: TrendSearchRow
    bars: list[TrendEvidenceBar]
    reference_bars: list[StudyBar] = Field(default_factory=list)
    reference_source: str | None = None
    conditions: list[StudyCheck]
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


def _prepare_cached(symbol: str, sessions: list[datetime.date]) -> pd.DataFrame:
    from kan.data.fetcher import get_cached

    raw = get_cached(symbol)
    if raw is None or raw.empty:
        raise ValueError("缺少可用本地日线，请更新该股票数据")
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


def _checks(query: TrendSearchQuery, metrics: pd.DataFrame, exact: pd.DataFrame) -> list[StudyCheck]:
    checks = []
    for condition in query.conditions:
        hits, known = evaluate_condition(condition, metrics, exact)
        checks.append(StudyCheck(
            condition=condition, actual=_number(metrics[condition.key].iloc[-1]),
            bound="exact" if exact[condition.key].iloc[-1] else "at_least",
            matched=bool(hits.iloc[-1]) if known.iloc[-1] else None,
        ))
    return checks


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


def search_trends(query: TrendSearchQuery) -> TrendSearchResult:
    """全部成员按同一日判断；缺行情计入缺口，无条件时明确浏览当前池。"""
    sessions, as_of = resolve_market_calendar(query.as_of)
    sessions = [day for day in sessions if day <= as_of]
    members, industries, choices = _scope(query)
    reference_prices, _reference_bars, _reference_source = _reference(query, sessions, as_of)
    cutoffs: Counter[datetime.date] = Counter()
    self_matches = 0
    rows: list[TrendSearchRow] = []
    missing: list[TrendSearchMissing] = []
    definitions = {item["field"]: item for item in FIELD_CATALOG}
    for symbol, name in members:
        try:
            frame = _prepare_cached(symbol, sessions)
            valid_dates = frame.index[frame.valid]
            if len(valid_dates):
                cutoffs[valid_dates[-1]] += 1
            if not frame.valid.iloc[-1]:
                raise ValueError("截止日缺少有效行情")
            fields = [(item.field, item.window) for item in query.conditions] if query.conditions else _BASE_FIELDS
            metrics, exact = calculate_metrics(frame, fields, reference_prices)
            checks = _checks(query, metrics, exact)
            unknown = []
            for check in checks:
                if check.matched is not None:
                    continue
                definition = definitions[check.condition.field]
                label = f"{check.condition.window}日{definition['label']}" if check.condition.window else str(definition["label"])
                detail = (f"仅能确认至少 {check.actual:g}{definition['unit']}，无法核对当前条件"
                          if check.actual is not None and check.bound == "at_least" else "缺少所需行情")
                unknown.append(f"{label}：{detail}")
            if unknown:
                raise ValueError("；".join(unknown))
            if all(item.matched for item in checks):
                if query.reference and query.reference.symbol == symbol and query.reference.as_of == as_of:
                    self_matches += 1
                    continue
                if query.conditions:
                    # 仅命中后补展示指标；复用当前行情与已计算条件，不再读取缓存。
                    remaining = [(field, window) for field, window in _BASE_FIELDS if (f"{field}.{window}" if window else field) not in exact]
                    if remaining:
                        more_metrics, more_exact = calculate_metrics(frame, remaining, reference_prices)
                        metrics = metrics.join(more_metrics[[key for key in more_metrics if key not in metrics]])
                        exact = exact.join(more_exact[[key for key in more_exact if key not in exact]])
                    # 保持所有入口的字段与下界顺序一致，条件顺序不改变展示结果。
                    fields = [*_BASE_FIELDS, *((item.field, item.window) for item in query.conditions)]
                    keys = list(dict.fromkeys(f"{field}.{window}" if window else field for field, window in fields))
                    metrics, exact = metrics[keys], exact[keys]
                rows.append(_row(symbol, name, industries.get(symbol), frame, metrics, exact))
        except (ValueError, OSError) as exc:
            missing.append(TrendSearchMissing(symbol=symbol, name=name, reason=str(exc)))
    warnings = ["使用当前上市范围与当前行业归属；仅匹配明确条件，不代表推荐。"]
    if query.reference:
        warnings.append("形态距离使用明确参照窗口；参照自身同日窗口已排除，不是推荐评分。")
    if missing:
        warnings.append(f"{len(missing)} 只资料不足，未将其视为不符合条件；更新数据后可重新筛选。")
    return TrendSearchResult(
        query=query, as_of=as_of,
        coverage=TrendSearchCoverage(total=len(members), evaluated=len(members) - len(missing), matched=len(rows), missing=len(missing), self_matches_excluded=self_matches),
        common_data_date=max(cutoffs, key=lambda day: (cutoffs[day], day)) if cutoffs else None,
        common_data_count=max(cutoffs.values(), default=0),
        rows=rows, missing_rows=missing, scope_codes=[symbol for symbol, _ in members], industries=choices, warnings=warnings,
    )


def trend_search_evidence(query: TrendSearchQuery, symbol: str) -> TrendSearchEvidence:
    """按同一截止日读取当前图证；需要封存结果时显式创建历史研究。"""
    from kan.storage.watchlist_models import _normalize_symbol

    symbol = _normalize_symbol(symbol)
    sessions, as_of = resolve_market_calendar(query.as_of)
    sessions = [day for day in sessions if day <= as_of]
    names = dict(resolve_study_members("codes", [symbol]))
    reference_prices, reference_bars, reference_source = _reference(query, sessions, as_of)
    frame = _prepare_cached(symbol, sessions)
    if not frame.valid.iloc[-1]:
        raise ValueError("截止日缺少有效行情，请先更新数据")
    fields = [*_BASE_FIELDS, *((item.field, item.window) for item in query.conditions)]
    metrics, exact = calculate_metrics(frame, fields, reference_prices)
    row = _row(symbol, names[symbol], _industries().get(symbol), frame, metrics, exact)
    bars = [TrendEvidenceBar(
        date=day, **{key: _number(value[key]) for key in ("open", "high", "low", "close", "volume")},
        change_pct=_number(metrics.at[day, "change_pct"]), body_pct=_number(metrics.at[day, "body_pct"]),
    ) for day, value in frame.iterrows()]
    return TrendSearchEvidence(
        query=query, as_of=as_of, row=row, bars=bars, reference_bars=reference_bars, reference_source=reference_source, conditions=_checks(query, metrics, exact),
        warnings=["图证读取当前本地缓存；如需保留当次证据，请显式创建历史研究。"],
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

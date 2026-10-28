"""趋势坐标与多周期位置；与历史研究使用同一指标计算。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kan.domain.market_study import StudyBar, StudyField
from kan.service.market_study import (
    calculate_metrics,
    prepare_history,
    resolve_market_calendar,
    resolve_study_members,
)


class TrendMapQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    universe: Literal["all", "personal", "codes"] = "all"
    codes: list[str] = Field(default_factory=list, max_length=10_000)
    as_of: date | None = None
    position_window: int = Field(default=180, ge=2, le=360)
    momentum_window: int = Field(default=20, ge=2, le=120)
    trail_days: int = Field(default=5, ge=0, le=20)

    @model_validator(mode="after")
    def validate_codes(self) -> TrendMapQuery:
        from kan.storage.watchlist_models import _normalize_symbol

        if self.universe == "codes":
            if not self.codes:
                raise ValueError("请填写要观察的股票代码")
            self.codes = list(dict.fromkeys(_normalize_symbol(code) for code in self.codes))
        elif self.codes:
            raise ValueError("仅代码池接受代码列表")
        return self


class TrendPoint(BaseModel):
    date: date
    x: float | None
    y: float | None
    positions: dict[str, float | None]
    returns: dict[str, float | None]


class TrendMapRow(BaseModel):
    symbol: str
    name: str
    industry: str | None = None
    available: bool = False
    reason: str | None = None
    data_cutoff: date | None = None
    close: float | None = None
    change_pct: float | None = None
    x: float | None = None
    y: float | None = None
    positions: dict[str, float | None] = Field(default_factory=dict)
    returns: dict[str, float | None] = Field(default_factory=dict)
    trail: list[TrendPoint] = Field(default_factory=list)
    source: str = "local_cache"


class TrendIndustry(BaseModel):
    name: str
    total: int
    available: int
    up: int
    down: int
    flat: int
    median_return: float | None
    median_position: float | None


class TrendMapView(BaseModel):
    position_window: int
    momentum_window: int
    plotted: int
    missing: int
    industries: list[TrendIndustry]


class TrendMapSnapshot(BaseModel):
    query: TrendMapQuery
    as_of: date
    total: int
    plotted: int
    missing: int
    rows: list[TrendMapRow]
    industries: list[TrendIndustry]
    views: list[TrendMapView]
    warnings: list[str] = Field(default_factory=list)


class TrendStockQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    as_of: date | None = None
    days: int = Field(default=120, ge=20, le=360)


class TrendStockSnapshot(BaseModel):
    symbol: str
    name: str
    as_of: date
    source: str
    industry: str | None
    bars: list[StudyBar]
    positions: dict[str, float | None]
    returns: dict[str, float | None]


def _number(value: Any) -> float | None:
    return None if pd.isna(value) else float(value)


def _fields(query: TrendMapQuery) -> list[tuple[StudyField, int | None]]:
    return [
        *(("position", window) for window in sorted({30, 60, 180, query.position_window})),
        *(("return_pct", window) for window in sorted({5, 20, 60, query.momentum_window})),
    ]


def _industry_map() -> dict[str, str]:
    from kan.data.industry_map import fetch_sw_l1_map

    return fetch_sw_l1_map()


def _row(
    symbol: str, name: str, industry: str | None,
    query: TrendMapQuery, sessions: list[date], as_of: date,
) -> TrendMapRow:
    from kan.data.fetcher import get_cached

    row = TrendMapRow(symbol=symbol, name=name, industry=industry)
    raw = get_cached(symbol)
    if raw is None or raw.empty:
        row.reason = "缺少本地日线"
        return row
    raw = raw[pd.to_datetime(raw["date"]).dt.date <= as_of]
    if raw.empty:
        row.reason = "截止日前无行情"
        return row
    row.data_cutoff = pd.to_datetime(raw["date"]).max().date()
    frame = prepare_history(raw, sessions)
    metrics, _ = calculate_metrics(frame, _fields(query))
    latest = metrics.iloc[-1]
    row.positions = {str(n): _number(latest[f"position.{n}"]) for n in (30, 60, 180)}
    row.returns = {str(n): _number(latest[f"return_pct.{n}"]) for n in (5, 20, 60)}
    row.close = _number(frame.close.iloc[-1])
    row.change_pct = _number(latest["change_pct"])
    row.x = _number(latest[f"position.{query.position_window}"])
    row.y = _number(latest[f"return_pct.{query.momentum_window}"])
    row.source = ", ".join(sorted(set(frame.loc[frame.valid, "_source"].astype(str)))) or "local_cache"
    row.available = row.x is not None and row.y is not None
    if not row.available:
        row.reason = "截止日缺行情" if row.close is None else "观察窗口行情不完整"
    for day, item in metrics.tail(query.trail_days + 1).iterrows():
        row.trail.append(TrendPoint(
            date=day,
            x=_number(item[f"position.{query.position_window}"]),
            y=_number(item[f"return_pct.{query.momentum_window}"]),
            positions={str(n): _number(item[f"position.{n}"]) for n in (30, 60, 180)},
            returns={str(n): _number(item[f"return_pct.{n}"]) for n in (5, 20, 60)},
        ))
    return row


def _summarize(rows: list[TrendMapRow], position_window: int, momentum_window: int) -> TrendMapView:
    groups: dict[str, list[TrendMapRow]] = defaultdict(list)
    for row in rows:
        groups[row.industry or "未分类"].append(row)
    summaries = []
    for name, group in sorted(groups.items()):
        pairs = [(row.positions.get(str(position_window)), row.returns.get(str(momentum_window))) for row in group]
        complete = [(x, y) for x, y in pairs if x is not None and y is not None]
        moves = [y for _, y in complete]
        positions = [x for x, _ in complete]
        summaries.append(TrendIndustry(
            name=name, total=len(group), available=len(complete),
            up=sum(value > 0 for value in moves), down=sum(value < 0 for value in moves),
            flat=sum(value == 0 for value in moves),
            median_return=median(moves) if moves else None,
            median_position=median(positions) if positions else None,
        ))
    plotted = sum(item.available for item in summaries)
    return TrendMapView(
        position_window=position_window, momentum_window=momentum_window,
        plotted=plotted, missing=len(rows) - plotted, industries=summaries,
    )


def build_trend_map(query: TrendMapQuery) -> TrendMapSnapshot:
    """全部点使用同一截止日；缺失对象计入分母，不用旧日期混入当前图。"""
    sessions, as_of = resolve_market_calendar(query.as_of)
    sessions = [day for day in sessions if day <= as_of]
    needed = max(180, query.position_window, query.momentum_window) + query.trail_days + 2
    sessions = sessions[-needed:]
    members = resolve_study_members(query.universe, query.codes)
    industries = _industry_map()
    rows = []
    for symbol, name in members:
        try:
            rows.append(_row(symbol, name, industries.get(symbol), query, sessions, as_of))
        except (ValueError, OSError) as exc:
            rows.append(TrendMapRow(
                symbol=symbol, name=name, industry=industries.get(symbol),
                reason=f"行情无法用于定位：{exc}",
            ))
    views = [_summarize(rows, x, y) for x in (30, 60, 180) for y in (5, 20, 60)]
    # 自定义坐标窗口也使用同一份已计算指标；常用周期可在界面即时切换。
    for row in rows:
        row.positions[str(query.position_window)] = row.x
        row.returns[str(query.momentum_window)] = row.y
    current_view = _summarize(rows, query.position_window, query.momentum_window)
    plotted = sum(row.available for row in rows)
    warnings = ["当前上市股票池与当前行业归属，仅描述指定日期的可用行情分布。"]
    if plotted < len(rows):
        warnings.append(f"{len(rows) - plotted} 只缺少同日或完整窗口行情，未绘制为零值；可更新数据后重试。")
    if not industries:
        warnings.append("行业归属暂不可用，股票仍可按位置与涨跌观察。")
    return TrendMapSnapshot(
        query=query, as_of=as_of, total=len(rows), plotted=plotted,
        missing=len(rows) - plotted, rows=rows, industries=current_view.industries,
        views=views, warnings=warnings,
    )


def get_trend_stock(query: TrendStockQuery) -> TrendStockSnapshot:
    """按需取单股图形；不为每个散点携带全部 K 线。"""
    from kan.data.fetcher import get_cached
    from kan.storage.watchlist_models import _normalize_symbol

    symbol = _normalize_symbol(query.symbol)
    sessions, as_of = resolve_market_calendar(query.as_of)
    sessions = [day for day in sessions if day <= as_of][-max(query.days, 181):]
    raw = get_cached(symbol)
    if raw is None or raw.empty:
        raise ValueError("该股票尚无本地日线，请先更新数据")
    frame = prepare_history(raw, sessions)
    metric_fields: list[tuple[StudyField, int | None]] = [
        ("position", 30), ("position", 60), ("position", 180),
        ("return_pct", 5), ("return_pct", 20), ("return_pct", 60),
    ]
    metrics, _ = calculate_metrics(frame, metric_fields)
    latest = metrics.iloc[-1]
    names = dict(resolve_study_members("codes", [symbol]))
    bars = [StudyBar(
        date=day, open=_number(row.open), high=_number(row.high), low=_number(row.low),
        close=_number(row.close), volume=_number(row.volume),
    ) for day, row in frame.tail(query.days).iterrows()]
    return TrendStockSnapshot(
        symbol=symbol, name=names.get(symbol, symbol), as_of=as_of,
        industry=_industry_map().get(symbol),
        source=", ".join(sorted(set(frame.loc[frame.valid, "_source"].astype(str)))) or "local_cache",
        bars=bars,
        positions={str(n): _number(latest[f"position.{n}"]) for n in (30, 60, 180)},
        returns={str(n): _number(latest[f"return_pct.{n}"]) for n in (5, 20, 60)},
    )

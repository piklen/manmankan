"""板块指数历史事件复核 application service。"""

from __future__ import annotations

from datetime import timedelta
from math import ceil, floor, isfinite
from statistics import mean, median
from typing import TYPE_CHECKING

from kan.core.streaks import streak_counts
from kan.domain.board import BoardKind, BoardTrendMode
from kan.domain.board_history import (
    BoardHistoryCoverage,
    BoardHistoryEvent,
    BoardHistoryStudy,
    BoardHistoryStudyQuery,
    BoardStudyDirection,
    BoardStudySamplePolicy,
    PointInTimeAudit,
    ReturnDistribution,
)

if TYPE_CHECKING:
    import pandas as pd


class BoardHistoryServiceError(RuntimeError):
    """历史复核稳定失败，由 HTTP/Python 入口映射。"""

    def __init__(self, code: str, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _resolve_theme_reference(value: str):
    from kan.data import boards

    try:
        return boards.search_theme(value)
    except boards.ThemeNotFoundError as original_error:
        trend_code = value.strip().removesuffix(".TI")
        if not trend_code.isdigit():
            raise original_error
        from kan.data.tushare_themes import tushare_load_theme_catalog

        catalog, _error = tushare_load_theme_catalog()
        matched = next(
            (theme for theme in catalog or [] if theme.code == trend_code),
            None,
        )
        if matched is None:
            raise original_error
        return boards.search_theme(matched.name)


def _resolve_tushare_theme(value: str):
    """只做精确代码 / 精确规范名匹配，避免把模糊题材静默映射到另一指数。"""

    from kan.data import boards
    from kan.data.tushare_themes import tushare_load_theme_catalog

    catalog, _error = tushare_load_theme_catalog()
    if not catalog:
        return None
    code = value.strip().removesuffix(".TI")
    normalized = boards.normalize_theme_name(value)
    return next(
        (
            theme
            for theme in catalog
            if theme.code == code
            or boards.normalize_theme_name(theme.name) == normalized
        ),
        None,
    )


def _load_board_history(
    query: BoardHistoryStudyQuery,
) -> tuple[str, str, str, pd.DataFrame]:
    from kan.data import boards

    try:
        if query.kind is BoardKind.INDUSTRY:
            board = boards.search_industry(query.value)
            if board.level != query.level:
                raise boards.BoardNotFoundError(query.value)
            frame = boards.fetch_industry_kline(board, force=query.force)
            return board.code, board.name, "sw_index_history", frame
        tushare_theme = _resolve_tushare_theme(query.value)
        if tushare_theme is not None:
            from kan.data.tushare_themes import tushare_load_theme_history

            tushare_frame, _error = tushare_load_theme_history(
                tushare_theme,
                lookback_years=query.lookback_years,
                force=query.force,
            )
            if tushare_frame is not None and not tushare_frame.empty:
                return (
                    tushare_theme.code,
                    tushare_theme.name,
                    "tushare_ths_index_history",
                    tushare_frame,
                )
        theme = _resolve_theme_reference(query.value)
        frame = boards.fetch_theme_kline(theme, force=query.force)
        return theme.code, theme.name, "em_concept_history", frame
    except (boards.BoardNotFoundError, boards.ThemeNotFoundError) as exc:
        raise BoardHistoryServiceError(
            "board_not_found",
            f"没有找到板块: {query.value}",
            hint="从趋势页重新选择行业或题材",
        ) from exc
    except (boards.BoardDataUnavailableError, boards.ThemeDataUnavailableError) as exc:
        raise BoardHistoryServiceError(
            "data_unavailable",
            f"板块指数历史暂不可用: {exc}",
            hint="检查网络、数据源配置或本地板块缓存后重试",
        ) from exc


def _normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    import pandas as pd

    required = {"date", "open", "close"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        raise BoardHistoryServiceError(
            "invalid_data",
            "板块指数历史缺少 date/open/close",
        )
    normalized = frame[["date", "open", "close"]].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.date
    normalized["open"] = pd.to_numeric(normalized["open"], errors="coerce")
    normalized["close"] = pd.to_numeric(normalized["close"], errors="coerce")
    normalized = (
        normalized.dropna(subset=["date"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    for column in ("open", "close"):
        valid = normalized[column].map(lambda value: isfinite(float(value)) and float(value) > 0)
        normalized[column] = normalized[column].where(valid)
    if len(normalized) < 2 or normalized["close"].notna().sum() < 2:
        raise BoardHistoryServiceError(
            "insufficient_history",
            "板块指数历史不足两个有效交易日",
        )
    return normalized


def _historical_streaks(
    frame: pd.DataFrame,
    *,
    mode: BoardTrendMode,
) -> tuple[list[int], list[bool]]:
    """原值判方向；平盘结束连续段，缺口后的段长保留下界。"""
    import numpy as np

    close = frame["close"]
    base = frame["open"] if mode is BoardTrendMode.CANDLE else close.shift(1)
    known = np.isfinite(close) & np.isfinite(base) & close.gt(0) & base.gt(0)
    up, up_exact = streak_counts(close.gt(base), known)
    down, down_exact = streak_counts(close.lt(base), known)
    streaks = (up.fillna(0) - down.fillna(0)).astype(int)
    exact = (streaks.ge(0) & up_exact) | (streaks.lt(0) & down_exact)
    return streaks.tolist(), exact.tolist()


def _first_hit_indices(
    streaks: list[int],
    exact: list[bool],
    *,
    direction: BoardStudyDirection,
    min_streak: int,
) -> list[int]:
    expected_sign = 1 if direction is BoardStudyDirection.UP else -1
    hits: list[int] = []
    for index, streak in enumerate(streaks):
        if not exact[index] or streak * expected_sign < min_streak:
            continue
        previous = streaks[index - 1] if index else 0
        previous_same_direction = previous * expected_sign > 0
        if not previous_same_direction or abs(previous) < min_streak:
            hits.append(index)
    return hits


def _select_indices(
    first_hits: list[int],
    *,
    forward_days: int,
    policy: BoardStudySamplePolicy,
) -> list[int]:
    if policy is BoardStudySamplePolicy.FIRST_HIT:
        return list(first_hits)
    selected: list[int] = []
    last_forward_index = -1
    for index in first_hits:
        if index <= last_forward_index:
            continue
        selected.append(index)
        last_forward_index = index + forward_days
    return selected


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = floor(position)
    high = ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _distribution(values: list[float]) -> ReturnDistribution:
    if not values:
        return ReturnDistribution(count=0, positive=0, negative=0, flat=0)
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    flat = len(values) - positive - negative
    return ReturnDistribution(
        count=len(values),
        positive=positive,
        negative=negative,
        flat=flat,
        positive_ratio_pct=round(positive / len(values) * 100, 2),
        mean_pct=round(mean(values), 4),
        median_pct=round(median(values), 4),
        p25_pct=round(_percentile(values, 0.25), 4),
        p75_pct=round(_percentile(values, 0.75), 4),
        min_pct=round(min(values), 4),
        max_pct=round(max(values), 4),
    )


def _benchmark_history(
    query: BoardHistoryStudyQuery,
) -> tuple[str | None, str | None, dict[object, float], list[str]]:
    if query.benchmark_code is None:
        return None, None, {}, []
    from kan.data.index import fetch_index_daily, index_name, normalize_index_code

    try:
        code = normalize_index_code(query.benchmark_code)
    except ValueError as exc:
        raise BoardHistoryServiceError("invalid_benchmark", str(exc)) from exc
    days = query.lookback_years * 260 + query.forward_days + 90
    frame = fetch_index_daily(code, days=days)
    if frame is None or frame.empty:
        return index_name(code), None, {}, ["基准指数历史不可用，相对收益留空"]
    normalized = _normalize_history(frame)
    values = {
        row.date: float(row.close)
        for row in normalized.itertuples(index=False)
        if isfinite(float(row.close)) and row.close > 0
    }
    return index_name(code), "tushare_or_akshare_index_daily", values, []


def study_board_history(query: BoardHistoryStudyQuery) -> BoardHistoryStudy:
    """按用户显式条件复核板块指数历史事件，不读取当前成分股。"""

    board_code, board_name, source, raw_frame = _load_board_history(query)
    frame = _normalize_history(raw_frame)
    cutoff = frame.iloc[-1]["date"]
    start_boundary = cutoff - timedelta(days=query.lookback_years * 366)
    event_start_index = next(
        (index for index, value in enumerate(frame["date"]) if value >= start_boundary),
        len(frame) - 1,
    )
    streaks, exact = _historical_streaks(frame, mode=query.mode)
    first_hits = [
        index
        for index in _first_hit_indices(
            streaks, exact,
            direction=query.direction,
            min_streak=query.min_streak,
        )
        if index >= event_start_index
    ]
    selected = _select_indices(
        first_hits,
        forward_days=query.forward_days,
        policy=query.sample_policy,
    )
    benchmark_name, benchmark_source, benchmark, warnings = _benchmark_history(query)

    expected_sign = 1 if query.direction is BoardStudyDirection.UP else -1
    unknown_starts = sum(
        index >= event_start_index and not exact[index] and streak == expected_sign * query.min_streak
        for index, streak in enumerate(streaks)
    )
    if unknown_starts:
        warnings.append(f"{unknown_starts} 段缺少可确认段首，未计入首次命中事件")
    events: list[BoardHistoryEvent] = []
    censored = 0
    unavailable_windows = 0
    benchmark_aligned = 0
    for index in selected:
        forward_index = index + query.forward_days
        if forward_index >= len(frame):
            censored += 1
            continue
        event_row = frame.iloc[index]
        forward_row = frame.iloc[forward_index]
        event_close = float(event_row["close"])
        forward_close = float(forward_row["close"])
        if not isfinite(forward_close) or forward_close <= 0:
            unavailable_windows += 1
            continue
        return_pct = round((forward_close - event_close) / event_close * 100, 4)
        benchmark_return: float | None = None
        relative_return: float | None = None
        benchmark_start = benchmark.get(event_row["date"])
        benchmark_end = benchmark.get(forward_row["date"])
        if benchmark_start is not None and benchmark_end is not None and benchmark_start > 0:
            benchmark_return = round(
                (benchmark_end - benchmark_start) / benchmark_start * 100,
                4,
            )
            relative_return = round(return_pct - benchmark_return, 4)
            benchmark_aligned += 1
        events.append(
            BoardHistoryEvent(
                event_date=event_row["date"].isoformat(),
                forward_date=forward_row["date"].isoformat(),
                streak=streaks[index],
                event_close=round(event_close, 4),
                forward_close=round(forward_close, 4),
                return_pct=return_pct,
                benchmark_return_pct=benchmark_return,
                relative_return_pct=relative_return,
            )
        )

    raw_values = [event.return_pct for event in events]
    benchmark_values = [
        event.benchmark_return_pct
        for event in events
        if event.benchmark_return_pct is not None
    ]
    relative_values = [
        event.relative_return_pct
        for event in events
        if event.relative_return_pct is not None
    ]
    if unavailable_windows:
        warnings.append(f"{unavailable_windows} 个事件后续终点收盘缺失，已从可用样本中剔除")
    if benchmark and benchmark_aligned < len(events):
        warnings.append(f"{len(events) - benchmark_aligned} 个事件缺少精确同日基准")

    return BoardHistoryStudy(
        query=query,
        board_code=board_code,
        board_name=board_name,
        source=source,
        benchmark_name=benchmark_name,
        benchmark_source=benchmark_source,
        data_start=frame.iloc[event_start_index]["date"].isoformat(),
        data_cutoff=cutoff.isoformat(),
        coverage=BoardHistoryCoverage(
            observations=len(frame) - event_start_index,
            first_hits=len(first_hits),
            selected=len(selected) - unavailable_windows,
            completed=len(events),
            censored=censored,
            benchmark_aligned=benchmark_aligned,
        ),
        events=list(reversed(events)),
        raw_distribution=_distribution(raw_values),
        benchmark_distribution=_distribution(benchmark_values),
        relative_distribution=_distribution(relative_values),
        audit=PointInTimeAudit(
            notes=[
                "只使用数据源发布的板块指数历史，没有读取或回填当前成分股",
                "事件条件在当日收盘后才成立，收益从事件日收盘计算到未来交易日收盘",
                "连续段按价格原值判断，平盘与缺值中断，不设 30 天上限",
                "数据起点或缺口后无法确认段首的连续段，不伪装成首次命中事件",
                "后续窗口按原日期行计数，缺失终点价的事件不列入可用样本",
                "数据源可能修订历史序列；本工具没有保存逐日 vintage 版本",
                "从当前趋势榜选择板块带有事后选择，本结果不代表样本外表现",
            ]
        ),
        warnings=warnings,
    )


__all__ = [
    "BoardHistoryServiceError",
    "study_board_history",
]

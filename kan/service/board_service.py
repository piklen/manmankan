"""行业 / 题材趋势的入口无关应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import TYPE_CHECKING

from kan.domain.board import (
    BoardDailyChange,
    BoardKind,
    BoardPulseCoverage,
    BoardPulseMember,
    BoardPulseQuery,
    BoardPulseSnapshot,
    BoardTrendCoverage,
    BoardTrendFailure,
    BoardTrendMode,
    BoardTrendQuery,
    BoardTrendRow,
    BoardTrendSnapshot,
    BoardTrendSort,
)

if TYPE_CHECKING:
    import pandas as pd

    from kan.core.models import Theme
    from kan.core.scanner import TrendResult
    from kan.data.theme_leaderboard import LeaderboardDiagnosis
    from kan.infra.lifecycle import OperationLifecycle


class BoardServiceError(RuntimeError):
    """可由 CLI/HTTP 稳定映射的板块业务失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        diagnosis: LeaderboardDiagnosis | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.diagnosis = diagnosis


class BoardTrendServiceError(BoardServiceError):
    """板块趋势查询失败。"""


class BoardPulseServiceError(BoardServiceError):
    """板块成员变化查询失败。"""


@dataclass(frozen=True)
class BoardTrendExecution:
    """应用结果加入口层可能需要的原始降级诊断。"""

    snapshot: BoardTrendSnapshot
    results: list[TrendResult]
    diagnosis: LeaderboardDiagnosis | None = None


def _row_from_result(result, *, rank: int, kind) -> BoardTrendRow:
    changes = [
        BoardDailyChange(date=date_value, change_pct=change)
        for date_value, change in result.daily_changes
    ]
    return BoardTrendRow(
        rank=rank,
        kind=kind,
        code=result.symbol,
        name=result.name,
        current_price=result.current_price,
        streak=result.streak,
        streak_pct=result.streak_pct,
        direction=result.direction,
        latest_change_pct=changes[0].change_pct if changes else None,
        moneyflow_net=getattr(result, "moneyflow_net", None),
        daily_changes=changes,
    )


def execute_board_trends(
    query: BoardTrendQuery,
    *,
    lifecycle: OperationLifecycle | None = None,
) -> BoardTrendExecution:
    """执行一次板块趋势查询，并保留 partial 与数据源边界。"""
    from kan.data import boards
    from kan.data.board_trend import (
        board_trend_moneyflow_map,
        load_board_trends,
        sort_board_trends,
    )

    try:
        all_results, errors, source, diagnosis = load_board_trends(
            kind=query.kind.value,
            level=query.level,
            candle=query.mode is BoardTrendMode.CANDLE,
            force=query.force,
            lifecycle=lifecycle,
        )
    except (boards.BoardDataUnavailableError, boards.ThemeDataUnavailableError) as exc:
        raise BoardTrendServiceError(
            "data_unavailable",
            f"板块趋势不可用: {exc}",
            hint="检查网络、数据源配置或本地缓存后重试",
        ) from exc

    if not all_results:
        raise BoardTrendServiceError(
            "data_unavailable",
            "板块趋势无可用指数 K 线",
            hint="检查网络、数据源配置或本地缓存后重试",
            diagnosis=diagnosis,
        )

    moneyflow = None
    if query.sort is BoardTrendSort.MONEYFLOW:
        if lifecycle is not None:
            lifecycle.phase("聚合板块资金")
        moneyflow = board_trend_moneyflow_map(
            query.kind.value,
            all_results,
            force=query.force,
            lifecycle=lifecycle,
        )

    if lifecycle is not None:
        lifecycle.phase("过滤与排序板块趋势")
    sorted_results = sort_board_trends(
        all_results,
        up_filter=query.up,
        down_filter=query.down,
        min_streak=query.min_streak,
        sort_by=query.sort.value,
        moneyflow=moneyflow,
    )
    shown = sorted_results if query.limit is None else sorted_results[: query.limit]
    data_dates = [
        result.daily_changes[0][0]
        for result in all_results
        if result.daily_changes
    ]
    failures = [
        BoardTrendFailure(
            code=item.code,
            name=item.name,
            message=str(error) or type(error).__name__,
        )
        for item, error in errors[:20]
    ]
    warnings: list[str] = []
    if errors:
        warnings.append(f"{len(errors)} 个板块指数数据不可用")

    snapshot = BoardTrendSnapshot(
        query=query,
        source=source,
        data_cutoff=max(data_dates) if data_dates else None,
        partial=bool(errors),
        coverage=BoardTrendCoverage(
            total=len(all_results) + len(errors),
            evaluated=len(all_results),
            matched=len(sorted_results),
            returned=len(shown),
            errors=len(errors),
        ),
        rows=[
            _row_from_result(result, rank=index, kind=query.kind)
            for index, result in enumerate(shown, start=1)
        ],
        failures=failures,
        warnings=warnings,
    )
    return BoardTrendExecution(
        snapshot=snapshot,
        results=shown,
        diagnosis=diagnosis,
    )


def query_board_trends(
    query: BoardTrendQuery,
    *,
    lifecycle: OperationLifecycle | None = None,
) -> BoardTrendSnapshot:
    """给 Python/HTTP 消费者返回严格 typed 的板块趋势快照。"""

    return execute_board_trends(query, lifecycle=lifecycle).snapshot


def _resolve_pulse_constituents(
    query: BoardPulseQuery,
) -> tuple[str, str, list[tuple[str, str]]]:
    from kan.data import boards

    def resolve_theme() -> Theme:
        """把趋势榜的 TuShare 指数代码桥接到成分股目录的同名题材。"""
        try:
            return boards.search_theme(query.value)
        except boards.ThemeNotFoundError as original_error:
            trend_code = query.value.strip().removesuffix(".TI")
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

    try:
        if query.kind is BoardKind.INDUSTRY:
            industry = boards.search_industry(query.value)
            if industry.level != query.level:
                raise boards.BoardNotFoundError(query.value)
            constituents = boards.get_industry_constituents(
                industry,
                force=query.force,
            )
            board_code, board_name = industry.code, industry.name
        else:
            theme = resolve_theme()
            constituents = boards.get_theme_constituents(theme, force=query.force)
            board_code, board_name = theme.code, theme.name
    except (boards.BoardNotFoundError, boards.ThemeNotFoundError) as exc:
        raise BoardPulseServiceError(
            "board_not_found",
            f"没有找到板块: {query.value}",
            hint="检查板块名称或从趋势榜重新选择",
        ) from exc
    except (boards.BoardDataUnavailableError, boards.ThemeDataUnavailableError) as exc:
        raise BoardPulseServiceError(
            "data_unavailable",
            "板块成分股暂不可用",
            hint="检查网络、数据源配置或本地缓存后重试",
        ) from exc

    constituents = list({
        str(code).strip(): (str(code).strip(), str(name).strip())
        for code, name in constituents
        if str(code).strip()
    }.values())
    if not constituents:
        raise BoardPulseServiceError(
            "data_unavailable",
            f"{board_name}没有可用成分股",
            hint="刷新板块成分股数据后重试",
        )
    return board_code, board_name, constituents


def _cached_member_panel(
    constituents: list[tuple[str, str]],
) -> pd.DataFrame:
    import pandas as pd

    from kan.data.fetcher import get_cached

    frames: list[pd.DataFrame] = []
    for code, _name in constituents:
        frame = get_cached(code)
        if frame is None or frame.empty or "date" not in frame or "close" not in frame:
            continue
        selected = frame[["date", "close"]].copy()
        selected["date"] = pd.to_datetime(selected["date"], errors="coerce").dt.date
        selected = selected.dropna(subset=["date", "close"]).sort_values("date").tail(2)
        if selected.empty:
            continue
        selected["symbol"] = code
        frames.append(selected[["symbol", "date", "close"]])
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "close"])
    return pd.concat(frames, ignore_index=True)


def _load_pulse_panel(
    query: BoardPulseQuery,
    constituents: list[tuple[str, str]],
    *,
    lifecycle: OperationLifecycle | None,
) -> tuple[pd.DataFrame, str, list[str]]:
    from kan.data.kline_snapshot import fetch_recent_daily_bars
    from kan.infra.log import debug_log

    codes = [code for code, _ in constituents]
    warnings: list[str] = []
    try:
        panel = fetch_recent_daily_bars(
            2,
            symbols=codes,
            force=query.force,
            lifecycle=lifecycle,
        )
        if panel is None or panel.empty:
            raise ValueError("全市场日线截面为空")
        return panel, "tushare_daily_bars", warnings
    except Exception as exc:
        debug_log(__name__, "board pulse daily bars unavailable", exc)
        panel = _cached_member_panel(constituents)
        if panel.empty:
            raise BoardPulseServiceError(
                "data_unavailable",
                "板块成分股缺少可比较的两日行情",
                hint="先到“市场与数据”更新全市场行情，再返回趋势页重试",
            ) from exc
        warnings.append("全市场日线截面不可用，已降级读取本地个股缓存")
        return panel, "individual_cache", warnings


def _pulse_member_rows(
    panel: pd.DataFrame,
    constituents: list[tuple[str, str]],
) -> tuple[str, str, list[tuple[str, str, float, float]]]:
    import pandas as pd

    required = {"symbol", "date", "close"}
    if not required.issubset(panel.columns):
        raise BoardPulseServiceError(
            "invalid_data",
            "成分股行情字段不完整",
            hint="更新全市场行情后重试",
        )
    normalized = panel[["symbol", "date", "close"]].copy()
    normalized["symbol"] = normalized["symbol"].astype(str).str.strip()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.date
    normalized["close"] = pd.to_numeric(normalized["close"], errors="coerce")
    normalized = normalized.dropna(subset=["symbol", "date", "close"])
    dates = sorted(normalized["date"].unique())
    if len(dates) < 2:
        raise BoardPulseServiceError(
            "data_unavailable",
            "成分股行情不足两个完整交易日",
            hint="先到“市场与数据”更新全市场行情，再返回趋势页重试",
        )
    previous_date, data_cutoff = dates[-2], dates[-1]
    by_key = {
        (str(row.symbol), row.date): float(row.close)
        for row in normalized.itertuples(index=False)
    }
    rows: list[tuple[str, str, float, float]] = []
    for code, name in constituents:
        previous_close = by_key.get((code, previous_date))
        current_close = by_key.get((code, data_cutoff))
        if (
            previous_close is None
            or current_close is None
            or previous_close <= 0
            or not isfinite(previous_close)
            or not isfinite(current_close)
        ):
            continue
        change_pct = round((current_close - previous_close) / previous_close * 100, 2)
        if change_pct == -0.0:
            change_pct = 0.0
        rows.append((code, name, round(current_close, 2), change_pct))
    return data_cutoff.isoformat(), previous_date.isoformat(), rows


def query_board_pulse(
    query: BoardPulseQuery,
    *,
    lifecycle: OperationLifecycle | None = None,
) -> BoardPulseSnapshot:
    """计算板块最新完整交易日的成员涨跌结构。"""

    if lifecycle is not None:
        lifecycle.phase("解析板块成分股")
    board_code, board_name, constituents = _resolve_pulse_constituents(query)
    if lifecycle is not None:
        lifecycle.phase("读取成分股两日行情", total=len(constituents))
    panel, source, warnings = _load_pulse_panel(
        query,
        constituents,
        lifecycle=lifecycle,
    )
    data_cutoff, previous_date, rows = _pulse_member_rows(panel, constituents)
    if not rows:
        raise BoardPulseServiceError(
            "data_unavailable",
            "板块成分股没有可比较的两日行情",
            hint="先到“市场与数据”更新全市场行情，再返回趋势页重试",
        )

    changes = [row[3] for row in rows]
    up_count = sum(change > 0 for change in changes)
    down_count = sum(change < 0 for change in changes)
    flat_count = len(rows) - up_count - down_count
    missing = len(constituents) - len(rows)
    if missing:
        warnings.append(f"{missing} 个成分股在同一截止日缺少两日行情")

    top_up_rows = sorted(
        (row for row in rows if row[3] > 0),
        key=lambda row: (-row[3], row[0]),
    )[: query.limit]
    top_down_rows = sorted(
        (row for row in rows if row[3] < 0),
        key=lambda row: (row[3], row[0]),
    )[: query.limit]

    def members(values: list[tuple[str, str, float, float]]) -> list[BoardPulseMember]:
        return [
            BoardPulseMember(
                rank=index,
                code=code,
                name=name,
                close=close,
                change_pct=change,
            )
            for index, (code, name, close, change) in enumerate(values, start=1)
        ]

    if lifecycle is not None:
        lifecycle.phase("汇总板块内部结构", result_count=len(rows))
    return BoardPulseSnapshot(
        query=query,
        board_code=board_code,
        board_name=board_name,
        source=source,
        data_cutoff=data_cutoff,
        previous_date=previous_date,
        partial=missing > 0,
        coverage=BoardPulseCoverage(
            total=len(constituents),
            evaluated=len(rows),
            up=up_count,
            down=down_count,
            flat=flat_count,
            missing=missing,
        ),
        up_ratio_pct=round(up_count / len(rows) * 100, 1),
        down_ratio_pct=round(down_count / len(rows) * 100, 1),
        median_change_pct=round(float(median(changes)), 2),
        top_up=members(top_up_rows),
        top_down=members(top_down_rows),
        warnings=warnings,
    )


__all__ = [
    "BoardPulseServiceError",
    "BoardServiceError",
    "BoardTrendExecution",
    "BoardTrendServiceError",
    "execute_board_trends",
    "query_board_pulse",
    "query_board_trends",
]

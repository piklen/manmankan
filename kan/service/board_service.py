"""行业 / 题材趋势的入口无关应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kan.domain.board import (
    BoardDailyChange,
    BoardTrendCoverage,
    BoardTrendFailure,
    BoardTrendMode,
    BoardTrendQuery,
    BoardTrendRow,
    BoardTrendSnapshot,
    BoardTrendSort,
)

if TYPE_CHECKING:
    from kan.core.scanner import TrendResult
    from kan.data.theme_leaderboard import LeaderboardDiagnosis
    from kan.infra.lifecycle import OperationLifecycle


class BoardTrendServiceError(RuntimeError):
    """可由 CLI/HTTP 稳定映射的板块趋势业务失败。"""

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


__all__ = [
    "BoardTrendExecution",
    "BoardTrendServiceError",
    "execute_board_trends",
    "query_board_trends",
]

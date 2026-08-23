"""行业 / 题材指数连续涨跌编排层。

`kan board trend` 把板块指数当作与股票相同的 OHLC 标的，复用
``calc_trend`` 的收盘价 / 阳线阴线口径。行业使用申万指数，题材使用
TuShare THS 概念指数并在不可用时回退 AkShare EM 概念指数。
"""
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Literal

from kan.core.models import Board, Theme
from kan.core.scanner import TrendResult, calc_trend
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderFetchResult,
)

if TYPE_CHECKING:
    import pandas as pd

    from kan.data.theme_leaderboard import LeaderboardDiagnosis
    from kan.infra.lifecycle import OperationLifecycle

BoardTrendKind = Literal["industry", "theme"]
BoardTrendSort = Literal["streak", "latest", "moneyflow"]


def _fetch_industry_kline_job(
    board: Board,
    *,
    force: bool,
) -> ProviderFetchResult[pd.DataFrame]:
    """把申万行业 K 线异常转换为 provider-aware result。"""
    from kan.data import boards

    try:
        frame = boards.fetch_industry_kline(board, force=force)
    except boards.BoardDataUnavailableError as exc:
        message = str(exc)
        if "为空" in message:
            return ProviderFetchResult.failed(FetchFailure(
                FetchFailureKind.EMPTY,
                message=message,
            ))
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.TRANSPORT,
            message=message,
            retryable=True,
            affects_circuit=True,
        ))
    except Exception as exc:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.TRANSPORT,
            message=type(exc).__name__,
            retryable=True,
            affects_circuit=True,
        ))
    if frame is None or frame.empty:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.EMPTY,
            message="K 线为空",
        ))
    return ProviderFetchResult.succeeded(frame)


def load_industry_trends(
    *,
    level: int = 1,
    candle: bool = False,
    force: bool = False,
    parallel: int | None = None,
    lifecycle: OperationLifecycle | None = None,
) -> tuple[list[TrendResult], list[tuple[Board, Exception]]]:
    """拉取指定层级的全部申万行业指数并计算连续涨跌。"""
    from kan.data import boards
    from kan.data.board_leaderboard import (
        BOARD_INDEX_CAPABILITIES,
        resolve_board_parallel,
    )
    from kan.data.provider_batch import ProviderJob, run_provider_jobs

    catalog = [
        board
        for board in boards.load_industry_catalog(force=force)
        if board.level == level
    ]
    if not catalog:
        raise boards.BoardDataUnavailableError(f"申万 {level} 级行业清单为空")

    results: list[TrendResult] = []
    errors: list[tuple[Board, Exception]] = []
    boards_by_code = {board.code: board for board in catalog}

    if lifecycle is not None:
        lifecycle.phase(
            "拉取申万行业指数 K 线",
            total=len(catalog),
            level=level,
        )

    def on_result(job_result, completed: int, total: int) -> None:
        board = boards_by_code[job_result.key]
        frame = job_result.result.data
        failure = job_result.result.failure
        if frame is None:
            message = failure.message if failure is not None else "K 线为空"
            errors.append((board, boards.BoardDataUnavailableError(message)))
        else:
            try:
                results.append(calc_trend(
                    frame,
                    board.code,
                    board.name,
                    candle=candle,
                ))
            except Exception as exc:
                errors.append((board, exc))
        if lifecycle is not None:
            lifecycle.progress(
                completed,
                total,
                "拉取并计算行业趋势",
                provider=job_result.provider,
                failure_count=len(errors),
            )

    def on_wait(provider: str, failure: FetchFailure, attempt: int) -> None:
        if lifecycle is not None:
            lifecycle.wait(
                "行业指数 provider 退避重试",
                provider=provider,
                reason=failure.kind.value,
                attempt=attempt,
                retry_after=failure.retry_after or 0.0,
            )

    def report_heartbeat(active: int, queued: int) -> None:
        if lifecycle is not None:
            lifecycle.heartbeat(active_calls=active, queued=queued)

    jobs = [
        ProviderJob(
            key=board.code,
            provider="sw_index_hist",
            call=partial(_fetch_industry_kline_job, board, force=force),
            capabilities=BOARD_INDEX_CAPABILITIES,
        )
        for board in catalog
    ]
    run_provider_jobs(
        jobs,
        max_workers=resolve_board_parallel(parallel),
        on_result=on_result,
        on_wait=on_wait,
        heartbeat=report_heartbeat if lifecycle is not None else None,
    )

    if errors and lifecycle is not None:
        lifecycle.degraded(
            "部分申万行业指数 K 线不可用",
            failure_count=len(errors),
            total=len(catalog),
        )
    return results, errors


def load_board_trends(
    *,
    kind: BoardTrendKind,
    level: int = 1,
    candle: bool = False,
    force: bool = False,
    parallel: int | None = None,
    lifecycle: OperationLifecycle | None = None,
) -> tuple[
    list[TrendResult],
    list[tuple[Board | Theme, Exception]],
    str,
    LeaderboardDiagnosis | None,
]:
    """加载行业或题材趋势，统一返回结果、失败项、来源和诊断。"""
    if kind == "theme":
        from kan.data.theme_leaderboard import load_theme_leaderboard

        results, theme_errors, source, diagnosis = load_theme_leaderboard(
            candle=candle,
            force=force,
            parallel=parallel,
            lifecycle=lifecycle,
        )
        return results, list(theme_errors), source, diagnosis

    results, industry_errors = load_industry_trends(
        level=level,
        candle=candle,
        force=force,
        parallel=parallel,
        lifecycle=lifecycle,
    )
    return results, list(industry_errors), "sw", None


def board_trend_moneyflow_map(
    kind: BoardTrendKind,
    results: list[TrendResult],
    *,
    force: bool = False,
    lifecycle: OperationLifecycle | None = None,
) -> dict[str, float]:
    """为板块趋势结果补充同代码口径的主力净额。"""
    from kan.data.board_leaderboard import (
        industry_moneyflow_map,
        theme_moneyflow_map,
    )

    if kind == "industry":
        by_name = industry_moneyflow_map()
        return {
            result.symbol: by_name[result.name]
            for result in results
            if result.name in by_name
        }

    themes = [
        Theme(code=result.symbol, name=result.name, source="ths")
        for result in results
    ]
    return theme_moneyflow_map(
        themes,
        force=force,
        lifecycle=lifecycle,
    )


def sort_board_trends(
    results: list[TrendResult],
    *,
    up_filter: int | None = None,
    down_filter: int | None = None,
    min_streak: int | None = None,
    sort_by: BoardTrendSort = "streak",
    moneyflow: dict[str, float] | None = None,
) -> list[TrendResult]:
    """复用既有题材榜过滤排序，保持所有板块同一 streak 口径。"""
    from kan.data.theme_leaderboard import sort_leaderboard

    return sort_leaderboard(
        results,
        up_filter=up_filter,
        down_filter=down_filter,
        min_streak=min_streak,
        sort_by=sort_by,
        moneyflow=moneyflow,
    )


__all__ = [
    "BoardTrendKind",
    "BoardTrendSort",
    "board_trend_moneyflow_map",
    "load_board_trends",
    "load_industry_trends",
    "sort_board_trends",
]

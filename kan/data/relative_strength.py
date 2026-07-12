"""相对强度对照数据 · 个股区间涨幅的对照基准 (大盘指数 / 申万一级行业)。

只产出对照侧 N 日涨幅 (客观区间涨幅 dict) · 个股侧涨幅由 scan 已算
(StockScanResult.periods[N].gain_pct) · 差值由 enrich.attach_relative_strength 计算。

数据复用 (不引入新数据源):
- 大盘:kan.data.index.fetch_index_daily (TuShare index_daily) → scan_stock 算区间涨幅
- 行业:kan.data.boards 申万一级 catalog + 行业指数 K 线 → scan_stock 算区间涨幅

合规 (compliance §6/§7):本层只算客观区间涨幅 · 不判断 · 不排序 · 不输出强弱结论。
"""
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from kan.data.index import index_name, normalize_index_code
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.infra.log import debug_log

if TYPE_CHECKING:
    import pandas as pd

    from kan.core.models import Board

DEFAULT_RS_INDEX = "000300.SH"
"""默认大盘对照指数 · 沪深300 (标准 market beta 基准 · 可 --rs-index-code 改)。"""

_RS_INDUSTRY_CAPABILITIES = ProviderCapabilities(
    max_concurrency=16,
    initial_concurrency=4,
    max_attempts=1,
    timeout_seconds=30.0,
    backoff_base_seconds=0.5,
    backoff_cap_seconds=2.0,
)


def _gains_from_kline(
    df: pd.DataFrame | None,
    code: str,
    name: str,
    periods: set[int],
) -> dict[int, float]:
    """单标的 K 线 → {period: N 日涨幅%} · insufficient / gain None → 不入 dict (缺数据不当 0)。"""
    from kan.core.scanner import scan_stock

    out: dict[int, float] = {}
    if df is None or df.empty or not periods:
        return out
    try:
        scan = scan_stock(df, code, name, periods=sorted(periods))
    except Exception as e:
        debug_log(__name__, f"rs scan {code} 失败", e)
        return out
    for pr in scan.periods:
        if pr.insufficient or pr.gain_pct is None:
            continue
        out[pr.period] = pr.gain_pct
    return out


def _rs_industry_job(
    board: Board,
    periods: set[int],
    *,
    force: bool,
) -> ProviderFetchResult[dict[int, float]]:
    """把 _one 的行业 K 线拉取封装为 provider-aware job。"""
    from kan.data import boards

    try:
        df = boards.fetch_industry_kline(board, force=force)
    except Exception as e:
        debug_log(__name__, f"rs industry kline {board.name} 失败", e)
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.TRANSPORT,
            message=type(e).__name__,
            retryable=True,
            affects_circuit=True,
        ))
    gains = _gains_from_kline(df, board.code, board.name, periods)
    if not gains:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.EMPTY,
            message="K 线不足或扫描无 gain",
        ))
    return ProviderFetchResult.succeeded(gains)


def index_gains(
    periods: set[int],
    *,
    index_code: str = DEFAULT_RS_INDEX,
) -> tuple[dict[int, float], str, str]:
    """大盘指数 N 日涨幅 · 返回 ({period: gain%}, 规范化 ts_code, 指数名)。

    无 token / 拉取失败 / 根数不足 → 对应 period 不入 dict (优雅降级)。
    """
    from kan.data.index import fetch_index_daily

    code = normalize_index_code(index_code)
    name = index_name(index_code)
    if not periods:
        return {}, code, name
    # gain 需 p+1 根 · +30 给假期 / p+1 缓冲;下限 60 根避免极小周期拉太少。
    df = fetch_index_daily(code, days=max(max(periods) + 30, 60))
    return _gains_from_kline(df, code, name, periods), code, name


def industry_gains(
    periods: set[int],
    *,
    force: bool = False,
    parallel: int = 16,
) -> dict[str, dict[int, float]]:
    """各申万一级行业 N 日涨幅 · {行业名: {period: gain%}}。

    复用 industry catalog + 行业指数 K 线 · 受控并发 · 只算 gain 不碰 moneyflow
    (比 load_board_leaderboard 省一次全市场 moneyflow)。行业名口径 = Board.name
    (与 fetch_sw_l1_map 的 l1_name 同源申万 · attach 用行业名对齐个股)。
    无 catalog / 全失败 → 空 dict (调用方按空降级 · board 对照标 not_available)。
    """
    if not periods:
        return {}

    from kan.data import boards
    from kan.data.provider_batch import ProviderJob, run_provider_jobs

    catalog = [b for b in boards.load_industry_catalog(force=force) if b.level == 1]
    if not catalog:
        return {}

    workers = max(1, min(parallel, len(catalog)))
    if workers <= 1:
        out: dict[str, dict[int, float]] = {}
        for b in catalog:
            result = _rs_industry_job(b, periods, force=force)
            if result.data is not None:
                out[b.name] = result.data
        return out

    jobs = [
        ProviderJob(
            key=board.name,
            provider="rs_industry",
            call=partial(_rs_industry_job, board, periods, force=force),
            capabilities=_RS_INDUSTRY_CAPABILITIES,
        )
        for board in catalog
    ]
    results = run_provider_jobs(jobs, max_workers=workers)
    return {
        key: job_result.result.data
        for key, job_result in results.items()
        if job_result.result.data is not None
    }


__all__ = ["DEFAULT_RS_INDEX", "index_gains", "industry_gains"]

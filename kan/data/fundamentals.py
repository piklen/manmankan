"""逐股财务指标 (ROE / 增速) 拉取编排 · 逐股缓存 + 公开 API (估值/质量/资金维度)。

仿 metrics.fetch_valuation_history 的逐股缓存 (每股一 parquet · 存全报告期) +
industry_map 单源降级。fina_indicator 按 ts_code 逐股 (全市场逐股代价高) ·
只在 K 线池 / 小池按需拉 (find --roe · 全市场 --all 不支持)。

每股缓存全历史报告期，保留公告日；24小时内复用，读时取最新报告期的最新披露。
原始指标值 (compliance §6/§7 · 命名中性)。
"""
from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR, atomic_write_parquet, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

    from kan.infra.lifecycle import OperationLifecycle

_FUNDAMENTALS_COLUMNS = ["end_date", "ann_date", "roe", "netprofit_yoy", "or_yoy"]
_FUNDAMENTALS_NUMERIC = ["roe", "netprofit_yoy", "or_yoy"]
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_FUNDAMENTALS_TTL = 24 * 3600
"""按需每日检查新披露；用户可显式强制刷新。"""

_TUSHARE_FUNDAMENTALS_FIELDS = "end_date,ann_date,roe,netprofit_yoy,or_yoy"
"""fina_indicator 拉取字段 · 净资产收益率 ROE + 净利同比 + 营收同比增速 (%)."""

_TUSHARE_FINA_CAPABILITIES = ProviderCapabilities(
    max_concurrency=12,
    initial_concurrency=4,
    max_attempts=3,
    timeout_seconds=30.0,
    backoff_base_seconds=0.5,
    backoff_cap_seconds=5.0,
    supports_retry_after=True,
)


def _cache_path(symbol: str) -> Path:
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"非法股票代码: {symbol!r}")
    return DATA_DIR / f"fundamentals_{symbol}.parquet"


def _empty_df() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=_FUNDAMENTALS_COLUMNS)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """归一化单股财务时序:补缺列 + end_date → date + 数值清洗 + 去无效行。"""
    import pandas as pd

    for col in _FUNDAMENTALS_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_FUNDAMENTALS_COLUMNS].copy()
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce").dt.date
    df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce").dt.date
    for col in _FUNDAMENTALS_NUMERIC:
        df[col], _bad = to_numeric_checked(df[col])
    return df.dropna(subset=["end_date"]).reset_index(drop=True)


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd
    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_cache({path.name})", e)
        return None


def _fetch_tushare_fundamentals_detailed(
    symbol: str,
) -> ProviderFetchResult[pd.DataFrame]:
    """TuShare fina_indicator 单次调用；重试由 provider scheduler 统一负责。"""
    from kan.data.tushare import (
        _api_error_to_failure,
        _normalize_symbol_to_ts,
        _post_tushare_api,
        _resolve_config,
    )
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.UNAVAILABLE,
            message="tushare token is not configured",
        ))
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_fina"):
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.CIRCUIT_OPEN,
            message="tushare_fina circuit is open",
        ))
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError as exc:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.INVALID,
            message=str(exc),
        ))
    data, err = _post_tushare_api(
        endpoint=endpoint,
        token=token,
        api_name="fina_indicator",
        params={"ts_code": ts_code},
        fields=_TUSHARE_FUNDAMENTALS_FIELDS,
        allow_transport_retries=False,
    )
    if data is None:
        failure = _api_error_to_failure(err)
        if failure.affects_circuit:
            cb.record("tushare_fina", ok=False)
        return ProviderFetchResult.failed(
            failure,
            breaker_recorded=failure.affects_circuit,
        )
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.EMPTY,
            message="fina_indicator returned no data",
        ))
    cb.record("tushare_fina", ok=True)
    import pandas as pd
    return ProviderFetchResult.succeeded(
        pd.DataFrame(items, columns=fields),
        breaker_recorded=True,
    )


def _fetch_tushare_fundamentals(symbol: str) -> pd.DataFrame | None:
    """兼容旧单股 adapter。"""
    return _fetch_tushare_fundamentals_detailed(symbol).data


_ORIGINAL_FETCH_TUSHARE_FUNDAMENTALS = _fetch_tushare_fundamentals


def _fetch_fundamentals_job(symbol: str) -> ProviderFetchResult[pd.DataFrame]:
    """生产走结构化 adapter；测试/兼容 monkeypatch 仍可替换旧 seam。"""
    if _fetch_tushare_fundamentals is _ORIGINAL_FETCH_TUSHARE_FUNDAMENTALS:
        return _fetch_tushare_fundamentals_detailed(symbol)
    data = _fetch_tushare_fundamentals(symbol)
    if data is None or data.empty:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.EMPTY,
            message="fina_indicator returned no data",
        ))
    return ProviderFetchResult.succeeded(data)


def _fresh_cache(symbol: str, *, force: bool) -> pd.DataFrame | None:
    """读取仍在 TTL 内的缓存；未命中返回 None。"""
    if force:
        return None
    cache = _cache_path(symbol)
    if not cache.exists() or (time.time() - cache.stat().st_mtime) >= _FUNDAMENTALS_TTL:
        return None
    loaded = _load_cache(cache)
    # 旧缓存没有公告日字段，首次使用时补取一次。
    return loaded if loaded is not None and "ann_date" in loaded else None


def _fetch_one(symbol: str, force: bool = False) -> pd.DataFrame:
    """单股财务时序 (全报告期) · 逐股 parquet 缓存 · 无 token/失败 → 空 df。"""
    if not _SYMBOL_PATTERN.match(symbol):
        return _empty_df()
    ensure_dirs()
    cache = _cache_path(symbol)
    loaded = _fresh_cache(symbol, force=force)
    if loaded is not None:
        return loaded

    raw = _fetch_tushare_fundamentals(symbol)
    if raw is None or raw.empty:
        return _empty_df()
    df = _normalize(raw)
    if df.empty:
        return _empty_df()
    atomic_write_parquet(df, cache)
    return df


def _latest_row(df: pd.DataFrame) -> pd.Series | None:
    """先取最新报告期，同报告期按公告日取最新披露。"""
    if df is None or df.empty:
        return None
    order = ["end_date", "ann_date"] if "ann_date" in df else ["end_date"]
    return df.sort_values(order, na_position="first").iloc[-1].copy()


def _fetched_at(symbol: str) -> str:
    return datetime.fromtimestamp(_cache_path(symbol).stat().st_mtime, UTC).isoformat()


def fetch_fundamentals(
    symbols: list[str],
    force: bool = False,
    *,
    max_workers: int | None = None,
    lifecycle: OperationLifecycle | None = None,
) -> dict[str, pd.Series]:
    """逐股拉财务指标 · 返回 {symbol: 最新一期 Series} (估值/质量/资金维度 · ROE/增速)。

    逐股 HTTP (全市场代价高 · 只在小池 / K 线池按需调) · 每股24小时 parquet 缓存。
    无 token / 失败 → 该股不入 dict (caller .get(symbol) → None · 优雅降级)。

    Args:
        symbols: 6 位代码列表
        force: 跳缓存强制重拉

    Returns:
        {symbol: pd.Series (end_date / ann_date / fetched_at / roe / netprofit_yoy / or_yoy)}。
        仅含有数据的股，fetched_at 是本地缓存成功写入时间 (UTC)。
        空 symbols → 空 dict (不触网)。
    """
    from kan.data.provider_batch import ProviderJob, run_provider_jobs

    unique = list(dict.fromkeys(str(symbol) for symbol in symbols))
    valid = [symbol for symbol in unique if _SYMBOL_PATTERN.match(symbol)]
    if not valid:
        return {}
    ensure_dirs()

    out: dict[str, pd.Series] = {}
    pending: list[str] = []
    for symbol in valid:
        cached = _fresh_cache(symbol, force=force)
        row = _latest_row(cached) if cached is not None else None
        if row is not None:
            row["fetched_at"] = _fetched_at(symbol)
            out[symbol] = row
        else:
            pending.append(symbol)
    if not pending:
        return out

    if lifecycle is not None:
        lifecycle.phase("拉取候选股财务指标", total=len(pending))

    failures = 0

    def on_result(result, completed: int, total: int) -> None:
        nonlocal failures
        if result.result.failure is not None:
            failures += 1
        if lifecycle is not None:
            lifecycle.progress(
                completed,
                total,
                "拉取候选股财务指标",
                provider=result.provider,
                failure_count=failures,
            )

    def on_wait(provider: str, failure: FetchFailure, attempt: int) -> None:
        if lifecycle is not None:
            lifecycle.wait(
                "财务指标 provider 退避重试",
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
            key=symbol,
            provider="tushare_fina",
            call=partial(_fetch_fundamentals_job, symbol),
            capabilities=_TUSHARE_FINA_CAPABILITIES,
        )
        for symbol in pending
    ]
    results = run_provider_jobs(
        jobs,
        max_workers=max_workers,
        on_result=on_result,
        on_wait=on_wait,
        heartbeat=report_heartbeat if lifecycle is not None else None,
    )
    for symbol, job_result in results.items():
        raw = job_result.result.data
        if raw is None or raw.empty:
            continue
        df = _normalize(raw)
        row = _latest_row(df)
        if row is None:
            continue
        atomic_write_parquet(df, _cache_path(symbol))
        row["fetched_at"] = _fetched_at(symbol)
        out[symbol] = row
    if failures and lifecycle is not None:
        lifecycle.degraded(
            "部分候选股财务指标不可用",
            failure_count=failures,
            total=len(pending),
        )
    return out


__all__ = ["fetch_fundamentals"]

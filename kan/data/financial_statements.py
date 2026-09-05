"""按需读取财报三表的关键科目，逐股逐表复用24小时缓存。"""

from __future__ import annotations

import contextlib
import time
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, cast

from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.domain.research import STATEMENT_FIELDS, ResearchDimension
from kan.storage.paths import DATA_DIR, atomic_write_parquet

if TYPE_CHECKING:
    import pandas as pd

_CACHE_TTL = 24 * 3600
_METADATA = ("ts_code", "end_date", "ann_date", "f_ann_date", "report_type", "update_flag")
_CAPABILITIES = ProviderCapabilities(
    max_concurrency=4, initial_concurrency=2, max_attempts=2,
    timeout_seconds=30, supports_retry_after=True,
)


def _fetch_statement(symbol: str, dimension: ResearchDimension) -> ProviderFetchResult[pd.DataFrame]:
    """沿用 TuShare 协议和调度器，单次只取一只股票的一张合并报表。"""
    import pandas as pd

    from kan.data.tushare import (
        _api_error_to_failure,
        _normalize_symbol_to_ts,
        _post_tushare_api,
        _resolve_config,
    )
    from kan.infra.numeric import to_numeric_checked

    token, endpoint = _resolve_config()
    if not token:
        return ProviderFetchResult.failed(FetchFailure(FetchFailureKind.UNAVAILABLE))
    ts_code = _normalize_symbol_to_ts(symbol)
    columns = [*_METADATA, *(field for field, _ in STATEMENT_FIELDS[dimension])]
    data, error = _post_tushare_api(
        endpoint=endpoint, token=token, api_name=dimension.value,
        params={"ts_code": ts_code, "report_type": "1"}, fields=",".join(columns),
        allow_transport_retries=False,
    )
    if data is None:
        return ProviderFetchResult.failed(_api_error_to_failure(error))
    frame = pd.DataFrame(data.get("items") or [], columns=data.get("fields") or [])
    if frame.empty:
        return ProviderFetchResult.failed(FetchFailure(FetchFailureKind.EMPTY))
    frame = frame.reindex(columns=columns)
    # 合并/母公司、累计/单季不能混用；同时核对上游是否遵守股票筛选条件。
    frame = frame.loc[(frame["ts_code"] == ts_code) & (frame["report_type"] == "1")].copy()
    for field in ("end_date", "ann_date", "f_ann_date"):
        frame[field] = pd.to_datetime(frame[field], format="%Y%m%d", errors="coerce").dt.date
    for field, _ in STATEMENT_FIELDS[dimension]:
        frame[field], _ = to_numeric_checked(frame[field])
    frame = frame.dropna(subset=["end_date"])
    if frame.empty:
        return ProviderFetchResult.failed(FetchFailure(FetchFailureKind.INVALID_SCHEMA))
    # 先选报告期，再看实际披露时间；同日重复行按来源的最新版本标记取舍。
    frame["_disclosed_on"] = frame["f_ann_date"].fillna(frame["ann_date"])
    frame["update_flag"] = frame["update_flag"].fillna("0").astype(str)
    frame = frame.sort_values(["end_date", "_disclosed_on", "update_flag"], na_position="first")
    return ProviderFetchResult.succeeded(frame.drop(columns="_disclosed_on").reset_index(drop=True))


def fetch_financial_statements(
    symbols: list[str], *, dimensions: set[ResearchDimension], force: bool = False,
) -> tuple[dict[tuple[str, ResearchDimension], pd.Series], dict[tuple[str, ResearchDimension], FetchFailure]]:
    """返回最新一期科目及逐股逐表失败，某一张表失败不丢弃其他表。"""
    import pandas as pd

    from kan.data.provider_batch import ProviderJob, run_provider_jobs

    rows: dict[tuple[str, ResearchDimension], pd.Series] = {}
    failures: dict[tuple[str, ResearchDimension], FetchFailure] = {}
    jobs: list[ProviderJob[pd.DataFrame]] = []
    keys: dict[str, tuple[str, ResearchDimension]] = {}
    for symbol in symbols:
        for dimension in sorted(dimensions):
            key = (symbol, dimension)
            path = DATA_DIR / f"statement_{dimension.value}_{symbol}.parquet"
            frame = None
            if not force and path.exists() and time.time() - path.stat().st_mtime < _CACHE_TTL:
                # 可重建缓存读取失败时，继续按原请求取数。
                with contextlib.suppress(OSError, ValueError):
                    frame = pd.read_parquet(path)
            if frame is not None and not frame.empty:
                row = frame.iloc[-1].copy()
                row["fetched_at"] = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
                rows[key] = row
                continue
            job_key = f"{symbol}:{dimension.value}"
            keys[job_key] = key
            jobs.append(ProviderJob(
                key=job_key, provider=f"tushare_{dimension.value}",
                call=partial(_fetch_statement, symbol, dimension), capabilities=_CAPABILITIES,
            ))
    for job_key, result in run_provider_jobs(jobs, max_workers=4).items():
        symbol, dimension = key = keys[job_key]
        if result.result.failure is not None:
            failures[key] = result.result.failure
            continue
        frame = cast(pd.DataFrame, result.result.data)
        path = DATA_DIR / f"statement_{dimension.value}_{symbol}.parquet"
        atomic_write_parquet(frame, path)
        row = frame.iloc[-1].copy()
        row["fetched_at"] = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        rows[key] = row
    return rows, failures

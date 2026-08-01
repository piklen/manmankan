"""全市场 K 线裸值快照 · `kan find --all` 时序类 filter 的批量缓存。

目标:避免 `--all` 为了位置 / 涨幅 / 连阳逐只触发 `fetch_kline`。本模块按交易日
缓存全市场 daily OHLC,再派生出一份每日快照:

- pos_N / low_N / high_N: N 日位置百分位及区间上下沿
- gain_N: 近 N 日涨幅
- low_resonance / high_resonance: 位置共振计数
- up_days: 连续阳线数

历史 daily 截面永鲜,最新交易日用 TTL 兜底。派生快照按 end_date + max_period
缓存,让多个 `kan find --all --pos/--gain/--up-days` 调用复用同一份结果。
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from hashlib import sha1
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING

from kan.core.scanner import PERIODS, scan_stock
from kan.data.tushare import TushareDataContractError
from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR, atomic_write_parquet, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

    from kan.core.pipeline import Freshness
    from kan.infra.lifecycle import LifecycleReporter, OperationLifecycle

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")
_DAILY_TTL = 6 * 3600
_SNAPSHOT_TTL = 6 * 3600
_CACHE_SCHEMA_VERSION = 2
"""v2 在落盘前校验全市场截面完整性；隔离旧版可能截断的缓存。"""
_MIN_COMPLETE_DAILY_BARS = 3000
"""近期待扫描 A 股单日截面的保守完整性下界。"""
_MIN_DAILY_UNIVERSE_COVERAGE = 0.9
"""已知全市场池存在时，单日截面至少覆盖其中 90%，为停牌 / 新股保留余量。"""

DAILY_BAR_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]


def _validate_trade_date(trade_date: str) -> str:
    if not isinstance(trade_date, str) or not _TRADE_DATE_PATTERN.match(trade_date):
        raise ValueError(f"非法交易日: {trade_date!r} · 应为 8 位 YYYYMMDD")
    return trade_date


def _date_from_trade_date(trade_date: str) -> date:
    return datetime.strptime(_validate_trade_date(trade_date), "%Y%m%d").date()


def _latest_trade_date_str() -> str:
    from kan.core.trading_calendar import latest_trade_date

    return latest_trade_date().strftime("%Y%m%d")


def _cache_fresh(path: Path, trade_date: str, ttl: float) -> bool:
    if not path.exists():
        return False
    td = _date_from_trade_date(trade_date)
    from kan.core.trading_calendar import latest_trade_date

    if td < latest_trade_date():
        return True
    return (time.time() - path.stat().st_mtime) < ttl


def _daily_cache_path(trade_date: str) -> Path:
    return DATA_DIR / (
        f"daily_bars_v{_CACHE_SCHEMA_VERSION}_{_validate_trade_date(trade_date)}.parquet"
    )


def _snapshot_cache_path(trade_date: str, periods: list[int]) -> Path:
    raw = "-".join(map(str, sorted(set(periods))))
    key = raw if len(raw) <= 80 else sha1(raw.encode("ascii")).hexdigest()[:16]
    return DATA_DIR / (
        f"kline_snapshot_v{_CACHE_SCHEMA_VERSION}_"
        f"{_validate_trade_date(trade_date)}_{key}.parquet"
    )


@contextmanager
def _lifecycle_scope(
    lifecycle: OperationLifecycle | None,
    reporter: LifecycleReporter | None,
) -> Iterator[OperationLifecycle | None]:
    if lifecycle is not None:
        yield lifecycle
        return
    if reporter is None:
        yield None
        return
    from kan.infra.lifecycle import operation

    with operation("获取全市场日线截面", reporter=reporter) as owned:
        yield owned


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd

    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"读取缓存失败: {path.name}", e)
        return None


def _empty_daily_df() -> pd.DataFrame:
    import pandas as pd

    return pd.DataFrame(columns=DAILY_BAR_COLUMNS)


def _normalize_daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """daily 截面归一化 · symbol/date/数值列清洗 + 去重。"""
    import pandas as pd

    if "symbol" not in df.columns:
        raise ValueError("daily bars 缺少 symbol 列")
    for col in DAILY_BAR_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    out = df[DAILY_BAR_COLUMNS].copy()
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
    for col in ("open", "high", "low", "close", "volume", "amount"):
        out[col], _bad = to_numeric_checked(out[col])
    out = out[out["symbol"].str.match(_SYMBOL_PATTERN, na=False)]
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    return out.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)


def _filter_symbols(df: pd.DataFrame, symbols: list[str] | None) -> pd.DataFrame:
    if symbols is None:
        return df
    wanted = {str(s) for s in symbols}
    return df[df["symbol"].isin(wanted)].reset_index(drop=True)


def _minimum_daily_rows(symbols: list[str] | None) -> int:
    universe_size = len(set(map(str, symbols or [])))
    return max(
        _MIN_COMPLETE_DAILY_BARS,
        ceil(universe_size * _MIN_DAILY_UNIVERSE_COVERAGE),
    )


def _validate_daily_cross_section(
    df: pd.DataFrame,
    trade_date: str,
    *,
    minimum_rows: int | None = None,
) -> None:
    """在缓存边界验证近期全市场截面，拒绝把部分响应持久化。"""
    row_count = df["symbol"].nunique() if "symbol" in df.columns else 0
    required_rows = max(_MIN_COMPLETE_DAILY_BARS, minimum_rows or 0)
    if row_count < required_rows:
        raise TushareDataContractError(
            "stk_factor_pro",
            f"trade_date={trade_date} 仅返回 {row_count} 只，"
            f"低于全市场截面校验下界 {required_rows}",
        )
    returned_dates = {
        value.strftime("%Y%m%d")
        for value in df["date"].dropna()
        if isinstance(value, date)
    }
    if returned_dates != {trade_date}:
        raise TushareDataContractError(
            "stk_factor_pro",
            f"请求 trade_date={trade_date}，归一化响应日期为 {sorted(returned_dates)!r}",
        )


def daily_panel_freshness(
    panel: pd.DataFrame,
    *,
    symbols: list[str],
    expected_cutoff: date | None = None,
    required_rows: int | None = None,
) -> Freshness:
    """从 daily_bars_YYYYMMDD.parquet 截面缓存聚合 freshness。"""
    from kan.core.pipeline import Freshness
    from kan.core.trading_calendar import latest_trade_date, market_phase

    expected = expected_cutoff or latest_trade_date()
    symbol_list = list(dict.fromkeys(str(symbol) for symbol in symbols))
    symbol_cutoffs: dict[str, date] = {}
    cache_mtimes: list[float] = []

    if not panel.empty and "date" in panel.columns:
        relevant = panel.copy()
        if "symbol" in relevant.columns:
            relevant["symbol"] = relevant["symbol"].astype(str)
            relevant = relevant[relevant["symbol"].isin(symbol_list)]
            for symbol, group in relevant.groupby("symbol", sort=False):
                dates = [value for value in group["date"].dropna() if isinstance(value, date)]
                if dates:
                    symbol_cutoffs[str(symbol)] = max(dates)
        panel_dates = {
            value for value in relevant["date"].dropna() if isinstance(value, date)
        }
        for panel_date in panel_dates:
            cache = _daily_cache_path(panel_date.strftime("%Y%m%d"))
            if cache.exists():
                cache_mtimes.append(cache.stat().st_mtime)

    cutoffs = list(symbol_cutoffs.values())
    data_cutoff = max(cutoffs, default=None)
    fetched_at = None
    if cache_mtimes:
        fetched_at = datetime.fromtimestamp(max(cache_mtimes)).strftime("%Y-%m-%d %H:%M")

    current_count = sum(symbol_cutoffs.get(symbol) == expected for symbol in symbol_list)
    missing_count = sum(symbol not in symbol_cutoffs for symbol in symbol_list)

    minimum = required_rows if required_rows is not None and required_rows > 0 else None
    incomplete_count = 0
    if minimum is not None and not panel.empty:
        row_counts = panel.groupby(panel["symbol"].astype(str))["date"].nunique()
        incomplete_count = sum(int(row_counts.get(symbol, 0)) < minimum for symbol in symbol_list)

    return Freshness(
        data_cutoff=data_cutoff,
        fetched_at=fetched_at,
        expected_cutoff=expected,
        # 单日截面本身已通过完整响应契约落盘；停牌、未交易和新股没有当日 K 线
        # 不等于数据源滞后。历史不足单独通过 history_incomplete_count 呈现。
        is_stale=data_cutoff != expected or missing_count > 0,
        phase=market_phase(),
        min_cutoff=data_cutoff,
        missing_count=missing_count,
        current_count=current_count,
        target_count=len(symbol_list),
        history_incomplete_count=incomplete_count,
        required_rows=minimum,
    )


def fetch_daily_bars(
    trade_date: str | None = None,
    *,
    symbols: list[str] | None = None,
    force: bool = False,
    minimum_rows: int | None = None,
) -> pd.DataFrame:
    """按交易日拉全市场 daily OHLC 截面 · parquet 缓存后按 symbols 过滤。"""
    from kan.data.tushare import (
        _fetch_tushare_daily_bars,
        _fetch_tushare_raw_daily_bars,
    )

    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    ensure_dirs()
    cache = _daily_cache_path(td)
    if not force and _cache_fresh(cache, td, _DAILY_TTL):
        cached = _load_cache(cache)
        if cached is not None:
            try:
                _validate_daily_cross_section(
                    cached,
                    td,
                    minimum_rows=minimum_rows,
                )
            except TushareDataContractError as exc:
                debug_log(__name__, f"忽略不完整截面缓存: {cache.name}", exc)
            else:
                return _filter_symbols(cached, symbols)

    raw = _fetch_tushare_daily_bars(td)
    if raw is None or raw.empty:
        if td != _latest_trade_date_str():
            return _empty_daily_df()
        raw = _fetch_tushare_raw_daily_bars(td)
        if raw is None or raw.empty:
            return _empty_daily_df()
    df = _normalize_daily_bars(raw)
    try:
        _validate_daily_cross_section(df, td, minimum_rows=minimum_rows)
    except TushareDataContractError as primary_error:
        # PanShu 的 stk_factor_pro 当日 generation 可能晚于基础 daily。最新交易日
        # 的 qfq 价与原始价相同，可用完整 daily 截面安全补齐；历史日绝不这样做。
        if td != _latest_trade_date_str():
            raise
        fallback = _fetch_tushare_raw_daily_bars(td)
        if fallback is None or fallback.empty:
            raise primary_error
        candidate = _normalize_daily_bars(fallback)
        try:
            _validate_daily_cross_section(
                candidate,
                td,
                minimum_rows=minimum_rows,
            )
        except TushareDataContractError:
            raise primary_error from None
        debug_log(
            __name__,
            f"最新交易日复权截面不完整，已用 daily 完整截面补齐: {td}",
            primary_error,
        )
        df = candidate
    atomic_write_parquet(df, cache)
    return _filter_symbols(df, symbols)


def _recent_trade_dates(end_date: date, count: int) -> list[date]:
    """取 <= end_date 的最近 count 个交易日 · calendar 不可用时退化 weekday。"""
    try:
        from kan.core.trading_calendar import get_trade_dates

        dates = sorted(d for d in get_trade_dates() if d <= end_date)
    except Exception:
        dates = []
    if len(dates) >= count:
        return dates[-count:]

    out: list[date] = []
    cursor = end_date
    while len(out) < count:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(out)


def fetch_recent_daily_bars(
    days: int,
    *,
    end_date: str | None = None,
    symbols: list[str] | None = None,
    force: bool = False,
    lifecycle: OperationLifecycle | None = None,
    reporter: LifecycleReporter | None = None,
    on_progress: Callable[[int, int, date, int], None] | None = None,
    max_workers: int | None = None,
    sort_by_symbol: bool = True,
) -> pd.DataFrame:
    """拉近 `days` 个交易日的全市场 daily OHLC panel · trend --all 截面路径专用。

    相比逐股 `fetch_kline` 的 N×HTTP,这里按交易日循环调 `fetch_daily_bars`,
    每日一次 `stk_factor_pro(trade_date=)` 拉全市场截面 · concat 成 (symbol,date,OHLC) panel。

    - days: 需要的交易日数(含 end_date)· trend 算 30 天 streak → 拉 31 天(含起点前置日用于算第一日 change)
    - end_date: 截止交易日(YYYYMMDD)· None 用 latest_trade_date()
    - symbols: 可选 symbol 过滤 · None 返回全市场
    - force: 强刷每日截面缓存
    - lifecycle/reporter: 复用外部 operation，或独立创建一个 operation
    - on_progress: 保留旧回调；仅在单日截面真实完成后调用
    - max_workers: 交易日之间的并发上限；默认从 8 起跑、最高 12
    - sort_by_symbol: 默认保持公开函数原有 symbol/date 顺序；仅写逐股缓存的调用方
      可关闭全表排序，因为每个交易日本来已按日期有序，分组后仍保持日期顺序
    """
    import pandas as pd

    with _lifecycle_scope(lifecycle, reporter) as active:
        if days < 1:
            return _empty_daily_df()
        td = _validate_trade_date(end_date or _latest_trade_date_str())
        end = _date_from_trade_date(td)
        if active is not None:
            active.phase("解析交易日历", days=days, end_date=td)
        dates = _recent_trade_dates(end, days)
        if active is not None:
            active.phase("交易日历就绪", total_days=len(dates))
        if not dates:
            raise RuntimeError("交易日历未返回可用交易日")

        frames_by_date: dict[str, pd.DataFrame] = {}
        total = len(dates)
        minimum_rows = _minimum_daily_rows(symbols)
        from kan.data.provider_batch import (
            ProviderJob,
            ProviderJobResult,
            resolve_provider_workers,
            run_provider_jobs,
        )
        from kan.data.provider_contracts import (
            FetchFailure,
            FetchFailureKind,
            ProviderCapabilities,
            ProviderFetchResult,
        )

        requested_workers = resolve_provider_workers(max_workers)
        worker_cap = min(12, requested_workers, total)
        # 小批保持原有确定顺序；全市场历史窗口才启用并发扇出。
        if max_workers is None and total < 8:
            worker_cap = 1
        capabilities = ProviderCapabilities(
            max_concurrency=max(1, worker_cap),
            initial_concurrency=min(8, max(1, worker_cap)),
            max_attempts=2,
            timeout_seconds=45,
            backoff_base_seconds=0.5,
            backoff_cap_seconds=2.0,
            rate_limit_cooldown_seconds=2.0,
        )

        def fetch_one(trade_day: date) -> ProviderFetchResult[pd.DataFrame]:
            try:
                daily = fetch_daily_bars(
                    trade_day.strftime("%Y%m%d"),
                    force=force,
                    minimum_rows=minimum_rows,
                )
            except TushareDataContractError as exc:
                return ProviderFetchResult.failed(
                    FetchFailure(
                        FetchFailureKind.INVALID_SCHEMA,
                        message=str(exc),
                    )
                )
            except Exception as exc:
                return ProviderFetchResult.failed(
                    FetchFailure(
                        FetchFailureKind.TRANSPORT,
                        message=f"{type(exc).__name__}: {exc}",
                        retryable=True,
                        affects_circuit=True,
                    )
                )
            if daily.empty:
                return ProviderFetchResult.failed(
                    FetchFailure(
                        FetchFailureKind.EMPTY,
                        message=f"交易日 {trade_day:%Y-%m-%d} 的日线截面为空",
                    )
                )
            # fetch_daily_bars 内部已经完成 provider 熔断记账，避免重复累计。
            return ProviderFetchResult.succeeded(daily, breaker_recorded=True)

        from functools import partial

        jobs: list[ProviderJob[pd.DataFrame]] = [
            ProviderJob(
                trade_day.strftime("%Y%m%d"),
                "tushare_daily_bars",
                partial(fetch_one, trade_day),
                capabilities,
            )
            for trade_day in dates
        ]

        if active is not None and worker_cap > 1:
            active.phase(
                "并发获取每日截面",
                total_days=total,
                workers=worker_cap,
            )

        def report_daily(
            result: ProviderJobResult[pd.DataFrame],
            completed: int,
            _total: int,
        ) -> None:
            trade_day = _date_from_trade_date(result.key)
            frame = result.result.data
            rows = 0 if frame is None else len(frame)
            if frame is not None:
                frames_by_date[result.key] = frame
            if active is not None:
                active.progress(
                    completed,
                    total,
                    "每日截面完成" if frame is not None else "每日截面失败",
                    trade_date=trade_day.isoformat(),
                    rows=rows,
                    workers=worker_cap,
                )
            if frame is not None and on_progress is not None:
                on_progress(completed, total, trade_day, rows)

        if worker_cap == 1:
            # 保留小批量逐日等待提示和确定回调顺序。
            for idx, job in enumerate(jobs, start=1):
                trade_day = _date_from_trade_date(job.key)
                if active is not None:
                    active.progress(
                        idx - 1,
                        total,
                        "获取每日截面",
                        trade_date=trade_day.isoformat(),
                    )
                def report_serial(
                    result: ProviderJobResult[pd.DataFrame],
                    _done: int,
                    _count: int,
                    *,
                    completed: int = idx,
                ) -> None:
                    report_daily(result, completed, total)

                batch = run_provider_jobs(
                    [job],
                    max_workers=1,
                    on_result=report_serial,
                )
                result = batch[job.key]
                if result.result.data is None:
                    failure = result.result.failure
                    if active is not None:
                        active.degraded(
                            "每日截面失败",
                            trade_date=trade_day.isoformat(),
                            error_type=(failure.kind.value if failure else "unknown"),
                        )
                    raise RuntimeError(
                        failure.message if failure else f"交易日 {trade_day:%Y-%m-%d} 拉取失败"
                    )
        else:
            def report_heartbeat(running: int, waiting: int) -> None:
                if active is not None:
                    active.heartbeat(
                        active_calls=running,
                        waiting=waiting,
                        workers=worker_cap,
                    )

            batch = run_provider_jobs(
                jobs,
                max_workers=worker_cap,
                on_result=report_daily,
                heartbeat=None if active is None else report_heartbeat,
            )
            failures = [result for result in batch.values() if result.result.data is None]
            if failures:
                first = failures[0]
                failure = first.result.failure
                if active is not None:
                    active.degraded(
                        "每日截面失败",
                        failure_count=len(failures),
                        trade_date=_date_from_trade_date(first.key).isoformat(),
                        error_type=(failure.kind.value if failure else "unknown"),
                    )
                raise RuntimeError(
                    failure.message if failure else f"交易日 {first.key} 拉取失败"
                )

        frames = [frames_by_date[d.strftime("%Y%m%d")] for d in dates]

        if active is not None:
            active.phase("合并每日截面", frame_count=len(frames))
        panel = pd.concat(frames, ignore_index=True)
        # `run_provider_jobs` 结果、按日字典和 frames 列表都持有 360 份原始
        # DataFrame。concat 完成后立即断开这些引用，避免排序 200 万行面板时
        # 同时保留一整份日截面副本。
        frames.clear()
        frames_by_date.clear()
        batch.clear()
        if active is not None:
            active.phase("每日截面合并完成", rows=len(panel))
        if sort_by_symbol:
            if active is not None:
                active.phase("排序日线面板", rows=len(panel))
            panel.sort_values(["symbol", "date"], inplace=True, ignore_index=True)
            if active is not None:
                active.phase("日线面板排序完成", rows=len(panel))
        elif active is not None:
            active.phase("保留交易日顺序", rows=len(panel))
        if active is not None:
            active.phase("过滤目标股票", target_count=len(symbols or []))
        # 正常路径的每个 fetch_daily_bars 调用已经按 symbols 过滤。仅在自定义
        # provider / 测试替身没有遵守该约定时再复制，兼顾公开函数语义与内存。
        if symbols is not None and not panel["symbol"].isin(set(symbols)).all():
            filtered = _filter_symbols(panel, symbols)
        else:
            filtered = panel
        if active is not None:
            active.phase("目标股票过滤完成", rows=len(filtered))
        return filtered


def _snapshot_columns(periods: list[int]) -> list[str]:
    cols = ["symbol", "trade_date", "close", "up_days", "low_resonance", "high_resonance"]
    for p in periods:
        cols += [
            f"pos_{p}",
            f"gain_{p}",
            f"ma_bias_{p}",
            f"low_{p}",
            f"high_{p}",
            f"insufficient_{p}",
        ]
    return cols


def _empty_snapshot_df(periods: list[int]) -> pd.DataFrame:
    import pandas as pd

    return pd.DataFrame(columns=_snapshot_columns(periods))


def _build_snapshot(
    bars: pd.DataFrame,
    *,
    periods: list[int],
    end_date: date,
    lifecycle: OperationLifecycle | None = None,
) -> pd.DataFrame:
    import pandas as pd

    if bars.empty:
        return _empty_snapshot_df(periods)
    rows: list[dict] = []
    bars = bars.sort_values(["symbol", "date"])
    groups = bars.groupby("symbol", sort=False)
    total = groups.ngroups
    report_every = max(1, (total + 99) // 100)
    failures: list[str] = []
    for completed, (symbol, group) in enumerate(groups, start=1):
        if group.empty:
            if lifecycle is not None and (
                completed % report_every == 0 or completed == total
            ):
                lifecycle.progress(completed, total, "计算 K 线快照")
            continue
        try:
            result = scan_stock(
                group,
                str(symbol),
                str(symbol),
                periods=periods,
                ma_bias_periods=periods,
            )
        except Exception as e:
            debug_log(__name__, f"kline snapshot scan failed · symbol={symbol}", e)
            failures.append(str(symbol))
            if lifecycle is not None and (
                completed % report_every == 0 or completed == total
            ):
                lifecycle.progress(
                    completed,
                    total,
                    "计算 K 线快照",
                    failure_count=len(failures),
                )
            continue
        row = {
            "symbol": str(symbol),
            "trade_date": end_date,
            "close": result.current_price,
            "up_days": result.up_days,
            "low_resonance": result.low_resonance,
            "high_resonance": result.high_resonance,
        }
        for pr in result.periods:
            row[f"pos_{pr.period}"] = None if pr.insufficient else pr.position_pct
            row[f"gain_{pr.period}"] = pr.gain_pct
            row[f"ma_bias_{pr.period}"] = result.ma_biases.get(pr.period)
            row[f"low_{pr.period}"] = None if pr.insufficient else pr.n_low
            row[f"high_{pr.period}"] = None if pr.insufficient else pr.n_high
            row[f"insufficient_{pr.period}"] = pr.insufficient
        rows.append(row)
        if lifecycle is not None and (
            completed % report_every == 0 or completed == total
        ):
            lifecycle.progress(
                completed,
                total,
                "计算 K 线快照",
                failure_count=len(failures),
            )
    if failures and lifecycle is not None:
        lifecycle.degraded(
            "部分股票 K 线快照计算失败",
            failure_count=len(failures),
            samples=failures[:5],
        )
    if not rows:
        return _empty_snapshot_df(periods)
    return pd.DataFrame(rows, columns=_snapshot_columns(periods))


def _fetch_kline_snapshot_impl(
    trade_date: str | None = None,
    *,
    symbols: list[str] | None = None,
    periods: list[int] | None = None,
    force: bool = False,
    lifecycle: OperationLifecycle | None = None,
) -> pd.DataFrame:
    """取每日 K 线裸值快照 · 支持全市场 `--all` 的 pos/gain/up-days/resonance filter。"""
    import pandas as pd

    periods = sorted(set(periods or PERIODS))
    max_period = max(periods)
    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    end = _date_from_trade_date(td)
    ensure_dirs()
    cache = _snapshot_cache_path(td, periods)
    if lifecycle is not None:
        lifecycle.phase("检查 K 线快照缓存", trade_date=td)
    if not force and _cache_fresh(cache, td, _SNAPSHOT_TTL):
        cached = _load_cache(cache)
        if cached is not None:
            if lifecycle is not None:
                lifecycle.phase("命中 K 线快照缓存", rows=len(cached))
            return _filter_symbols(cached, symbols)

    dates = _recent_trade_dates(end, max_period + 1)
    frames: list[pd.DataFrame] = []
    total = len(dates)
    minimum_rows = _minimum_daily_rows(symbols)
    if lifecycle is not None:
        lifecycle.phase("获取 K 线每日截面", total_days=total)
    for completed, d in enumerate(dates, start=1):
        daily = fetch_daily_bars(
            d.strftime("%Y%m%d"),
            force=force,
            minimum_rows=minimum_rows,
        )
        if not daily.empty:
            frames.append(daily)
        if lifecycle is not None:
            lifecycle.progress(
                completed, total, "获取 K 线每日截面", rows=len(daily)
            )
    if not frames:
        return _empty_snapshot_df(periods)

    if lifecycle is not None:
        lifecycle.phase("合并 K 线每日截面", frame_count=len(frames))
    bars = pd.concat(frames, ignore_index=True)
    if lifecycle is not None:
        lifecycle.phase("计算 K 线快照", symbol_count=bars["symbol"].nunique())
    snapshot = _build_snapshot(
        bars, periods=periods, end_date=end, lifecycle=lifecycle
    )
    if not snapshot.empty:
        if lifecycle is not None:
            lifecycle.phase("写入 K 线快照缓存", rows=len(snapshot))
        atomic_write_parquet(snapshot, cache)
    if lifecycle is not None:
        lifecycle.phase("过滤目标股票", target_count=len(symbols or []))
    return _filter_symbols(snapshot, symbols)


def fetch_kline_snapshot(
    trade_date: str | None = None,
    *,
    symbols: list[str] | None = None,
    periods: list[int] | None = None,
    force: bool = False,
    lifecycle: OperationLifecycle | None = None,
    reporter: LifecycleReporter | None = None,
) -> pd.DataFrame:
    """取每日 K 线裸值快照，并复用调用方的 operation 生命周期。"""
    with _lifecycle_scope(lifecycle, reporter) as active:
        return _fetch_kline_snapshot_impl(
            trade_date,
            symbols=symbols,
            periods=periods,
            force=force,
            lifecycle=active,
        )


__all__ = [
    "DAILY_BAR_COLUMNS",
    "daily_panel_freshness",
    "fetch_daily_bars",
    "fetch_kline_snapshot",
    "fetch_recent_daily_bars",
]

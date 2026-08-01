"""K 线数据拉取编排 · cache + chain (责任链) + 公开 API。

架构分层:
- `kan.data.protocols.KlineSource`     · Protocol (adapter 契约)
- `kan.data.sources` / `kan.data.tushare` · 5 个内置 KlineSource 实现
- `kan.data.source_chain.KlineSourceChain` · 责任链 (priority sort + race + 熔断)
- `kan.data._builtin_sources`         · 内置源工厂 + 用户注册表 (internal)
- `kan.data.fetcher` (本文件)         · cache + chain 编排 + 公开 API (fetch_kline / fetch_batch)
- `kan.api`                            · 用户 facing (register_kline_source / kline_chain)

用户自定义源: `from kan.api import register_kline_source` · 详见 `kan.api` docstring。
"""

from __future__ import annotations

import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from kan.data.scheduler import KlineFetchResult, KlineScheduler
from kan.data.source_chain import default_kline_chain
from kan.infra.log import debug_log, redact_text
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandas as pd

    from kan.data.protocols import KlineSource
    from kan.infra.lifecycle import OperationLifecycle

# ── K 线标准 schema ──────────────────────────────────────────────────
# 所有数据源的出口必须经过 _normalize_kline() 归一化到此格式。
# 新增列只需追加到 KLINE_OPTIONAL · 下游按列名读取 · 不受影响。

KLINE_REQUIRED = ["date", "open", "high", "low", "close"]
KLINE_OPTIONAL = ["volume", "amount", "_source"]
KLINE_COLUMNS = KLINE_REQUIRED + KLINE_OPTIONAL

# 6 位纯数字股票代码 · 防止 path traversal
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
DEFAULT_KLINE_DAYS = 360
DEFAULT_ADAPTIVE_MAX_WORKERS = 32
_ADAPTIVE_WINDOW_SIZE = 20
_BACKPRESSURE_KEYWORDS = (
    "40203",
    "429",
    "rate limit",
    "retry-after",
    "too many requests",
    "timeout",
    "timed out",
    "backpressure",
    "限流",
    "频率",
    "排队",
    "超时",
)


@dataclass(frozen=True)
class FetchProgress:
    """批量 K 线拉取进度快照 · 给终端显示当前自适应并发用。"""

    symbol: str
    ok: bool
    error: str | None
    elapsed_seconds: float
    concurrency: int
    max_concurrency: int
    inflight: int
    completed: int
    total: int


class _AdaptiveConcurrency:
    """轻量 AIMD 控制器 · 用请求延迟和错误反馈调节提交窗口。"""

    def __init__(self, *, initial: int, maximum: int, minimum: int = 1) -> None:
        self.minimum = max(1, minimum)
        self.maximum = max(self.minimum, maximum)
        self.limit = min(max(initial, self.minimum), self.maximum)
        self._latencies: deque[float] = deque(maxlen=_ADAPTIVE_WINDOW_SIZE)
        self._baseline: float | None = None
        self._success_since_adjust = 0

    def record(self, *, ok: bool, error: str | None, elapsed_seconds: float) -> None:
        elapsed = max(elapsed_seconds, 0.001)
        self._latencies.append(elapsed)
        if ok and (self._baseline is None or elapsed < self._baseline):
            self._baseline = elapsed

        if not ok:
            self._success_since_adjust = 0
            self._decrease(aggressive=_is_backpressure_error(error))
            return

        self._success_since_adjust += 1
        if len(self._latencies) < min(8, _ADAPTIVE_WINDOW_SIZE):
            return

        sample = _percentile(list(self._latencies), 0.90)
        baseline = self._baseline or min(self._latencies)
        if sample > baseline * 3.0:
            self._success_since_adjust = 0
            self._decrease(aggressive=False)
            return

        if self._success_since_adjust >= _ADAPTIVE_WINDOW_SIZE and self.limit < self.maximum:
            self.limit += 1
            self._success_since_adjust = 0

    def _decrease(self, *, aggressive: bool) -> None:
        if self.limit <= self.minimum:
            return
        next_limit = self.limit // 2 if aggressive else self.limit - 1
        self.limit = max(self.minimum, next_limit)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[idx]


def _is_backpressure_error(error: str | None) -> bool:
    if not error:
        return False
    text = error.lower()
    return any(keyword in text for keyword in _BACKPRESSURE_KEYWORDS)


def _normalize_kline(
    df: pd.DataFrame, source: str = "unknown", symbol: str | None = None,
) -> pd.DataFrame:
    """统一归一化：类型转换 + 补缺失列 + 排序 + 去 NaN。所有数据源的出口。

    source: 数据来源标记 (baostock / sina / eastmoney / tencent / unknown).
            写入 `_source` 列 · 支持跨源单位差异回查 · 缓存来源可追溯。
    symbol: 当前归一化的股票代码 · 仅用于 warning 文案 · 调试时定位脏数据源头。
    """
    import pandas as pd

    for col in KLINE_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")

    for col in KLINE_OPTIONAL:
        if col not in df.columns:
            df[col] = source if col == "_source" else float("nan")

    df = df[KLINE_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    # _source 是 str 列 · 不进数值转换
    bad_cols: list[tuple[str, int]] = []
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col], bad_count = to_numeric_checked(df[col])
        if bad_count:
            bad_cols.append((col, bad_count))
    if bad_cols:
        detail = ", ".join(f"{c}×{n}" for c, n in bad_cols)
        sym_tag = f" [{symbol}]" if symbol else ""
        logging.getLogger(__name__).warning(
            "数据源 %s K线含无法解析的数值 · 已置 NaN: %s%s", source, detail, sym_tag
        )
    df["_source"] = source

    df = df.sort_values("date").reset_index(drop=True)
    df = df.dropna(subset=["date", "close"])
    return df


# ── 通用工具 ─────────────────────────────────────────────────────────

def _validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"非法股票代码: {symbol!r} · 应为 6 位纯数字")
    return symbol


def _ensure_data_dir() -> None:
    from kan.storage.paths import ensure_dirs
    ensure_dirs()


def _cache_path(symbol: str) -> Path:
    symbol = _validate_symbol(symbol)
    return DATA_DIR / f"{symbol}.parquet"


def _read_cutoff_from_parquet(path: Path) -> date | None:
    """从 parquet 缓存读 K 线最后一行 date（数据真实截止日）· 失败返回 None。

    只读 date 列降低 IO（pyarrow 列式存储天然友好）。

    异常路径加 debug logging · 默认不输出 (用户开 KAN_DEBUG=1 才显示) ·
    诊断时不再"吞 None 后调用方无信息"。
    """
    try:
        import pandas as pd
        df = pd.read_parquet(path, columns=["date"])
        if df.empty:
            return None
        last = df["date"].iloc[-1]
        if isinstance(last, date) and not isinstance(last, datetime):
            return last
        return pd.Timestamp(last).date()
    except Exception as e:
        # normalize 到 log.debug_log helper (KAN_DEBUG=1 可见)
        debug_log(__name__, f"_read_cutoff_from_parquet({path.name})", e)
        return None


def _cache_has_min_rows(path: Path, min_rows: int | None) -> bool:
    """缓存是否已按所需周期完整请求过。

    新股上市历史可能天然少于所需行数；只要缓存由不少于 min_rows 的请求生成，
    就视为已完整刷新，计算层仍会把不足周期标成 insufficient。
    """
    if min_rows is None or min_rows <= 0:
        return True
    try:
        import pandas as pd

        cached_dates = pd.read_parquet(path, columns=["date"])
        if len(cached_dates) >= min_rows:
            return True
        import pyarrow.parquet as pq

        raw_requested = (pq.read_metadata(path).metadata or {}).get(
            b"kan.requested_days"
        )
        requested_days = int(raw_requested.decode("utf-8")) if raw_requested else 0
        return requested_days >= min_rows
    except Exception as e:
        debug_log(__name__, f"_cache_has_min_rows({path.name}, {min_rows})", e)
        return False


def _is_cache_fresh(path: Path, *, min_rows: int | None = None) -> bool:
    """缓存是否已包含"应有最近交易日"数据。

    当前判据：K 线最后一行 date == latest_trade_date()。
    旧实现 mtime_date == today 已废 · 凌晨 02:55 拉到昨日数据后会被
    误判为"今日数据齐了"整天不刷新 · scan 显示昨日涨停名单。
    """
    if not path.exists():
        return False
    if not _cache_has_min_rows(path, min_rows):
        debug_log(
            __name__,
            f"_is_cache_fresh({path.name})",
            f"cache rows < required {min_rows} → stale",
        )
        return False
    last_date = _read_cutoff_from_parquet(path)
    if last_date is None:
        return False
    from kan.core.trading_calendar import latest_trade_date
    return last_date == latest_trade_date()


# ── 网络代理隔离 ─────────────────────────────────────────────────────

# 数据源 apex 域名 · 用 apex 而非具体 host · 抗 akshare 端点漂移
_DATA_SOURCE_DOMAINS = (
    "eastmoney.com",
    "sina.com.cn",
    "sinajs.cn",
    "gtimg.cn",
    "baostock.com",
)

_no_proxy_configured = False


def _ensure_no_proxy() -> None:
    """把数据源域名并入 no_proxy · 使其绕过用户配置的（可能失效的）代理。

    场景：用户设了 HTTP(S)_PROXY / ALL_PROXY，代理却挂了、或会劫持/封禁本工具
    流量——数据请求被带偏。把数据源域名加进 no_proxy 让这些请求直连。

    幂等（模块 flag 守一次性）· 不 clobber 用户已设的 no_proxy（取并集）·
    KAN_KEEP_PROXY 置位时整体跳过——给"必须走代理才能出网"的用户的逃生口。
    """
    global _no_proxy_configured
    if _no_proxy_configured:
        return
    import os

    if os.environ.get("KAN_KEEP_PROXY"):
        _no_proxy_configured = True
        return

    # requests / akshare 同时认 no_proxy 与 NO_PROXY · 合并已有值取并集
    existing = os.environ.get("no_proxy", "") or os.environ.get("NO_PROXY", "")
    entries = [e.strip() for e in existing.split(",") if e.strip()]
    for domain in _DATA_SOURCE_DOMAINS:
        if domain not in entries:
            entries.append(domain)
    merged = ",".join(entries)
    os.environ["no_proxy"] = merged
    os.environ["NO_PROXY"] = merged
    _no_proxy_configured = True


# ── 公开 API ─────────────────────────────────────────────────────────


def _kline_source_snapshot() -> list[KlineSource]:
    """每次 operation 取一次当前 chain snapshot，并兼容旧注册留下的重名源。"""
    unique: dict[str, KlineSource] = {}
    for source in default_kline_chain().sources:
        unique.setdefault(source.name, source)
    return list(unique.values())


def _finalize_kline_result(
    result: KlineFetchResult,
    *,
    days: int,
) -> pd.DataFrame:
    """把 scheduler raw result 归一化并原子落盘，保留旧失败文案。"""
    if not result.succeeded or result.data is None or result.source is None:
        raise ValueError(f"无效股票代码或无数据: {result.symbol}")
    cache = _cache_path(result.symbol)
    df = _normalize_kline(result.data, source=result.source, symbol=result.symbol)
    from kan.storage.paths import atomic_write_parquet

    atomic_write_parquet(
        df,
        cache,
        metadata={"kan.requested_days": str(int(days))},
    )
    return df


def fetch_kline(
    symbol: str,
    days: int = DEFAULT_KLINE_DAYS,
    force: bool = False,
) -> pd.DataFrame:
    """拉取单只股票前复权日 K 线 · 走 default KlineSourceChain (按 priority sort + race)。

    返回 DataFrame · 标准列：date, open, high, low, close, volume, amount, _source

    内置 priority (chain 内自动排序 · 见 protocols.py priority 约定):
    - 10  TushareKlineSource    · 配 token 时顶档 · 付费源
    - 20  BaostockKlineSource   · 独立服务器最稳 · 数值精度全板块对齐
    - 30  EastmoneyKlineSource  · akshare 主路径
    - 30  SinaKlineSource       · 与 eastmoney 并发 race · 任一慢/挂不拖累另一个
                                  (东财 push2his 对部分 IP 段封禁时新浪兜底)
    - 40  TencentKlineSource    · 兜底 · 仅价格可信 · volume 已 drop

    用户可通过 `kan.api.register_kline_source` 插队自定义源 (priority ∈ [50, 89] 推荐)。
    """
    symbol = _validate_symbol(symbol)
    _ensure_data_dir()
    cache = _cache_path(symbol)

    if not force and _is_cache_fresh(cache, min_rows=days):
        import pandas as pd
        return pd.read_parquet(cache)

    _ensure_no_proxy()
    start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime("%Y%m%d")

    with KlineScheduler(
        _kline_source_snapshot(),
        supervisor_workers=2,
    ) as scheduler:
        result = scheduler.fetch(symbol, start)
    return _finalize_kline_result(result, days=days)


def resolve_max_workers() -> int:
    """启发式 max_workers · 不再硬编码 5.

    akshare 是 I/O bound (HTTP 拉取 · 不是 CPU 计算) · cpu_count*2 比 cpu-1 更合理.
    默认上限 16；TuShare/PanShu lane 健康时仍可继续自适应探到 32。
    公开源各自还有 provider lane 上限，不会因为全局窗口变大而失控。

    Examples:
    - 4 核 Mac mini: cpu_count=4 → workers=8
    - 8 核 MacBook: cpu_count=8 → workers=16
    - 16 核 Mac Studio: cpu_count=16 → workers=16 (默认起跑 cap)
    - Docker / cgroup 返宿主机核数: 默认起跑 cap 16

    KAN_WORKERS env var 可显式 override (整数 · 1-32 范围 · 越界回退默认).
    """
    override = _worker_override_from_env()
    if override is not None:
        return override
    return min((os.cpu_count() or 4) * 2, 16)


def resolve_batch_worker_bounds(max_workers: int | None = None) -> tuple[int, int]:
    """返回批量 fetch 的 (起跑并发, 自适应上限)。

    - 显式 `max_workers` 或 `KAN_WORKERS` 代表用户手动控速,不越过该上限。
    - 默认从 I/O 启发式起跑,健康时最多探到 32；失败/限流时控制器会回落。
    """
    if max_workers is not None and max_workers >= 1:
        workers = min(max_workers, DEFAULT_ADAPTIVE_MAX_WORKERS)
        return workers, workers

    initial = resolve_max_workers()
    if _worker_override_from_env() is not None:
        return initial, initial
    return initial, max(initial, DEFAULT_ADAPTIVE_MAX_WORKERS)


def _worker_override_from_env() -> int | None:
    import os

    raw = os.environ.get("KAN_WORKERS")
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    # 32 是 PanShu 逐股接口在真实全板块样本上的吞吐甜点上界；公开源仍受
    # 自己的 provider lane (1/4/4/2) 限制，不会直接收到 32 路请求。
    return n if 1 <= n <= DEFAULT_ADAPTIVE_MAX_WORKERS else None


def _fetch_market_batch(
    symbols: list[str],
    *,
    days: int,
    force: bool,
    max_workers: int | None,
    on_progress: Callable | None,
    on_progress_state: Callable[[FetchProgress], None] | None,
    lifecycle: OperationLifecycle | None,
    retain_frames: bool,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """全市场高速路径：按交易日批量拉取，再并发物化逐股 parquet。

    这是 `kan fetch --all` 的主路径。把约 5500 次逐股 HTTP 改为 `days` 次
    全市场截面请求；批量源整体不可用时明确失败，不再静默退化到 5500 次
    串行 Baostock。
    """
    import time
    from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

    import pandas as pd

    from kan.data.kline_snapshot import fetch_recent_daily_bars

    results: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    success_marker = pd.DataFrame()
    unique_symbols = list(dict.fromkeys(symbols))
    completed = 0
    started_at = time.monotonic()
    worker_limit = min(
        max_workers or resolve_max_workers(),
        DEFAULT_ADAPTIVE_MAX_WORKERS,
        max(1, len(unique_symbols)),
    )

    def safe_callback(callback: Callable | None, *args: object) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as exc:
            debug_log(__name__, "fetch_market_batch progress callback", exc)

    def finish(symbol: str, frame: pd.DataFrame | None, error: str | None) -> None:
        nonlocal completed
        completed += 1
        ok = frame is not None and error is None
        if ok and frame is not None:
            # CLI 全市场刷新只需要成功集合；不为 5534 只股票同时保留约 200 万
            # 行 DataFrame。库调用默认仍返回完整结果，保持公开 API 兼容。
            results[symbol] = frame if retain_frames else success_marker
        else:
            errors[symbol] = error or "unknown error"
        state = FetchProgress(
            symbol=symbol,
            ok=ok,
            error=error,
            elapsed_seconds=max(0.0, time.monotonic() - started_at),
            concurrency=worker_limit,
            max_concurrency=worker_limit,
            inflight=0,
            completed=completed,
            total=len(unique_symbols),
        )
        safe_callback(on_progress_state, state)
        safe_callback(on_progress, symbol, ok, error)

    pending_symbols: list[str] = []
    for symbol in unique_symbols:
        try:
            _validate_symbol(symbol)
            cache = _cache_path(symbol)
            if not force and _is_cache_fresh(cache, min_rows=days):
                finish(symbol, pd.read_parquet(cache), None)
                continue
        except Exception as exc:
            finish(symbol, None, str(exc))
            continue
        pending_symbols.append(symbol)

    if not pending_symbols:
        return results, errors

    if lifecycle is not None:
        lifecycle.phase(
            "全市场批量拉取",
            symbols=len(pending_symbols),
            days=days,
            workers=min(max_workers or 12, 12),
        )
    try:
        panel = fetch_recent_daily_bars(
            days,
            symbols=pending_symbols,
            force=force,
            lifecycle=lifecycle,
            max_workers=max_workers,
            sort_by_symbol=False,
        )
    except Exception as exc:
        safe_detail = redact_text(str(exc))
        message = (
            "全市场批量源不可用，已停止耗时的串行降级："
            f"{type(exc).__name__}: {safe_detail}"
        )
        if lifecycle is not None:
            lifecycle.degraded(
                "全市场批量拉取失败",
                error_type=type(exc).__name__,
                fallback="serial_disabled",
            )
        for symbol in pending_symbols:
            finish(symbol, None, message)
        return results, errors

    if lifecycle is not None:
        lifecycle.phase(
            "并发写入逐股缓存",
            symbols=len(pending_symbols),
            rows=len(panel),
            workers=worker_limit,
        )

    from kan.storage.paths import atomic_write_parquet

    wanted = set(pending_symbols)
    seen: set[str] = set()

    def write_one(symbol: str, group: pd.DataFrame) -> tuple[str, pd.DataFrame | None, str | None]:
        try:
            frame = _normalize_kline(
                group,
                source="tushare_market_batch",
                symbol=symbol,
            )
            if frame.empty:
                raise ValueError(f"无效股票代码或无数据: {symbol}")
            atomic_write_parquet(
                frame,
                _cache_path(symbol),
                metadata={"kan.requested_days": str(int(days))},
            )
            return symbol, frame, None
        except Exception as exc:
            return symbol, None, str(exc)

    def consume(done: set[Future]) -> None:
        for future in done:
            symbol, frame, error = future.result()
            finish(symbol, frame, error)

    outstanding: set[Future] = set()
    with ThreadPoolExecutor(
        max_workers=worker_limit,
        thread_name_prefix="kan-market-cache",
    ) as executor:
        for raw_symbol, group in panel.groupby("symbol", sort=False):
            symbol = str(raw_symbol)
            if symbol not in wanted:
                continue
            seen.add(symbol)
            outstanding.add(executor.submit(write_one, symbol, group))
            if len(outstanding) >= worker_limit * 2:
                done, outstanding = wait(outstanding, return_when=FIRST_COMPLETED)
                consume(done)
        while outstanding:
            done, outstanding = wait(outstanding, return_when=FIRST_COMPLETED)
            consume(done)

    for symbol in pending_symbols:
        if symbol not in seen:
            finish(symbol, None, f"无效股票代码或无数据: {symbol}")

    return results, errors


def fetch_batch(
    symbols: list[str],
    days: int = DEFAULT_KLINE_DAYS,
    force: bool = False,
    max_workers: int | None = None,
    on_progress: Callable | None = None,
    on_progress_state: Callable[[FetchProgress], None] | None = None,
    lifecycle: OperationLifecycle | None = None,
    market_wide: bool = False,
    retain_frames: bool = True,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """批量拉取 · 自适应提交窗口 + 可选 progress callback.

    max_workers=None → resolve_max_workers() 启发式 (cpu_count*2 cap 16).
    未显式设置上限时,控制器可在健康窗口内继续升到 32；遇到限流/超时/失败回落。
    market_wide=True → 按交易日批量获取全市场，再并发物化逐股缓存。
    retain_frames=False → 成功结果只保留代码键，值为空 DataFrame；适合只需刷新
    缓存和成功计数的 CLI 全市场任务，可显著降低 360 日窗口峰值内存。
    """
    import time
    from collections import defaultdict

    import pandas as pd

    if not symbols:
        return {}, {}

    if market_wide:
        return _fetch_market_batch(
            symbols,
            days=days,
            force=force,
            max_workers=max_workers,
            on_progress=on_progress,
            on_progress_state=on_progress_state,
            lifecycle=lifecycle,
            retain_frames=retain_frames,
        )

    initial_workers, worker_cap = resolve_batch_worker_bounds(max_workers)
    worker_cap = min(worker_cap, len(symbols))
    initial_workers = min(initial_workers, worker_cap)
    results: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    completed = 0
    network_symbols: list[str] = []
    network_started: dict[str, deque[float]] = defaultdict(deque)
    scheduler_ref: list[KlineScheduler] = []

    def _safe_callback(callback: Callable | None, *args: object) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as exc:
            debug_log(__name__, "fetch_batch progress callback", exc)

    def _finish(
        symbol: str,
        *,
        frame: pd.DataFrame | None,
        error: str | None,
        started_at: float,
    ) -> None:
        nonlocal completed
        completed += 1
        ok = frame is not None and error is None
        if ok:
            results[symbol] = frame
            errors.pop(symbol, None)
        else:
            errors[symbol] = error or "unknown error"
            results.pop(symbol, None)
        scheduler = scheduler_ref[0] if scheduler_ref else None
        state = FetchProgress(
            symbol=symbol,
            ok=ok,
            error=error,
            elapsed_seconds=max(0.0, time.monotonic() - started_at),
            concurrency=scheduler.concurrency if scheduler else initial_workers,
            max_concurrency=worker_cap,
            inflight=scheduler.active_calls if scheduler else 0,
            completed=completed,
            total=len(symbols),
        )
        _safe_callback(on_progress_state, state)
        _safe_callback(on_progress, symbol, ok, error)

    for symbol in symbols:
        started_at = time.monotonic()
        try:
            _validate_symbol(symbol)
            cache = _cache_path(symbol)
            if not force and _is_cache_fresh(cache, min_rows=days):
                frame = pd.read_parquet(cache)
                _finish(symbol, frame=frame, error=None, started_at=started_at)
                continue
        except Exception as exc:
            _finish(symbol, frame=None, error=str(exc), started_at=started_at)
            continue
        network_symbols.append(symbol)
        network_started[symbol].append(started_at)

    if not network_symbols:
        return results, errors

    _ensure_data_dir()
    _ensure_no_proxy()
    start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime("%Y%m%d")

    def _on_result(result: KlineFetchResult) -> None:
        started_at = network_started[result.symbol].popleft()
        try:
            frame = _finalize_kline_result(result, days=days)
        except Exception as exc:
            _finish(result.symbol, frame=None, error=str(exc), started_at=started_at)
            return
        _finish(result.symbol, frame=frame, error=None, started_at=started_at)

    with KlineScheduler(
        _kline_source_snapshot(),
        supervisor_workers=worker_cap,
        worker_cap=worker_cap,
        initial_concurrency=initial_workers,
        on_result=_on_result,
        lifecycle=lifecycle,
    ) as scheduler:
        scheduler_ref.append(scheduler)
        scheduler.fetch_many(network_symbols, start)

    return results, errors


def is_fresh(symbol: str, *, min_rows: int | None = None) -> bool:
    return _is_cache_fresh(_cache_path(symbol), min_rows=min_rows)


def cache_has_min_rows(symbol: str, min_rows: int) -> bool:
    """缓存是否已有足够行数，或已按指定周期完成过全量请求。"""
    return _cache_has_min_rows(_cache_path(symbol), min_rows)


def has_cache(symbol: str) -> bool:
    return _cache_path(symbol).exists()


def get_cached(symbol: str) -> pd.DataFrame | None:
    cache = _cache_path(symbol)
    if not cache.exists():
        return None
    import pandas as pd

    df = pd.read_parquet(cache)
    # 兜底:用户自定义源 / 手工写入的 parquet 可能缺 volume/amount · 补 NaN 防下游 KeyError
    for col in ["volume", "amount"]:
        if col not in df.columns:
            df[col] = float("nan")
    return df


def cache_age(symbol: str) -> str | None:
    """缓存文件 mtime · 语义 = "上次拉取时间"（现在不再当作"数据日期"使用）。

    历史教训：早期实现把 mtime 当作"数据日期"显示在 scan 标题（"X 更新"），
    凌晨 02:55 拉数据后 mtime 日期 = 今天，但 K 线最后一行还是昨日，
    用户看到"今天更新"以为是今日数据，实际还是昨日（涨停标签错位）。
    现在 scan 标题分离展示"数据截止 X 收盘 · Y 拉取"（见 data_cutoff_date）。
    """
    cache = _cache_path(symbol)
    if not cache.exists():
        return None
    mtime = datetime.fromtimestamp(cache.stat().st_mtime)
    return mtime.strftime("%Y-%m-%d %H:%M")


def data_cutoff_date(symbol: str) -> date | None:
    """缓存 K 线最后一行的真实 date（数据截止日期 · 而非文件 mtime）。

    用于 scan / info / low / high 标题展示"数据截止 YYYY-MM-DD 收盘"。
    与 cache_age() 严格分离：
    - data_cutoff_date = "数据涵盖到哪一天"（K 线 date 列 · 真相）
    - cache_age        = "文件何时被写入"（文件 mtime · 仅供"上次拉取"显示）
    """
    cache = _cache_path(symbol)
    if not cache.exists():
        return None
    return _read_cutoff_from_parquet(cache)

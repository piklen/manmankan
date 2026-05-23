"""K 线数据拉取编排 · cache + fallback 链 + 公开 API。

v0.0.5.0 起架构拆为两层:
- `kan.data.sources` 单点数据源 fetcher(eastmoney/baostock/sina/tencent + akshare race)
- `kan.data.fetcher`(本文件) cache + fallback 编排 + `fetch_kline` / `fetch_batch` 公开 API

fallback 链:tushare → baostock → akshare 双源并发 → tencent · 见 `fetch_kline`。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from kan.data.sources import (
    _fetch_baostock,
    _fetch_tencent,
    _fetch_via_akshare,
)
from kan.data.tushare import _fetch_tushare
from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandas as pd

# ── K 线标准 schema ──────────────────────────────────────────────────
# 所有数据源的出口必须经过 _normalize_kline() 归一化到此格式。
# 新增列只需追加到 KLINE_OPTIONAL · 下游按列名读取 · 不受影响。

KLINE_REQUIRED = ["date", "open", "high", "low", "close"]
KLINE_OPTIONAL = ["volume", "amount", "_source"]
KLINE_COLUMNS = KLINE_REQUIRED + KLINE_OPTIONAL

# 6 位纯数字股票代码 · 防止 path traversal
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")


def _normalize_kline(df: pd.DataFrame, source: str = "unknown") -> pd.DataFrame:
    """统一归一化：类型转换 + 补缺失列 + 排序 + 去 NaN。所有数据源的出口。

    source: 数据来源标记 (baostock / sina / eastmoney / tencent / unknown).
            写入 `_source` 列 · 支持跨源单位差异回查 · 缓存来源可追溯。
    """
    import pandas as pd

    for col in KLINE_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")

    for col in KLINE_OPTIONAL:
        if col not in df.columns:
            df[col] = float("nan") if col != "_source" else source

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
        logging.getLogger(__name__).warning(
            "数据源 %s K线含无法解析的数值 · 已置 NaN: %s", source, detail
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


def _load_with_migration(path: Path) -> pd.DataFrame:
    """读 parquet · 旧 schema 缺 `_source` 列自动加 'unknown' · atomic write back.

    集中 migration 入口 · fetch_kline cache 命中 + get_cached 两处调用 ·
    防散布式 migration 漂移。`_read_cutoff_from_parquet` 不调 (只读 date 列 ·
    与 _source 无关 · 也不触发 atomic write back 防止 mtime 漂移)。
    """
    import pandas as pd

    from kan.storage.paths import atomic_write_parquet

    df = pd.read_parquet(path)
    if "_source" not in df.columns:
        df["_source"] = "unknown"
        atomic_write_parquet(df, path)
        debug_log(__name__, f"_load_with_migration({path.name})", "legacy → _source=unknown")
    return df


def _is_cache_fresh(path: Path) -> bool:
    """缓存是否已包含"应有最近交易日"数据。

    v0.0.4.5 起判据：K 线最后一行 date ≥ latest_trade_date()。
    旧实现 mtime_date == today 已废 · 凌晨 02:55 拉到昨日数据后会被
    误判为"今日数据齐了"整天不刷新 · scan 显示昨日涨停名单。
    """
    if not path.exists():
        return False
    last_date = _read_cutoff_from_parquet(path)
    if last_date is None:
        return False
    from kan.core.trading_calendar import latest_trade_date
    return last_date >= latest_trade_date()


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

def fetch_kline(symbol: str, days: int = 180, force: bool = False) -> pd.DataFrame:
    """拉取单只股票前复权日 K 线（tushare 配 token 时优先 → baostock → 东财/新浪并发 → 腾讯）。

    返回 DataFrame · 标准列：date, open, high, low, close, volume, amount

    fallback 设计：
    0. TuShare Pro（仅当 tushare_token 配置时）· 顶优先 · 付费源 / 自部署镜像
    1. baostock 独立服务器最稳 · 数值精度全 A 股板块对齐 · 主路径
    2. 东财 + 新浪 两个 akshare 源并发 race（_fetch_via_akshare）· 谁先成功用谁 ·
       任一源慢/挂不拖累另一个 · 东财 push2his 对部分 IP 段持续封禁时新浪兜底
       （akshare GitHub Issue #6092/#6148/#7011/#6214）
    3. 腾讯（akshare stock_zh_a_hist_tx）· 仅价格可信 · amount 字段板块语义不一致已 drop
    """
    symbol = _validate_symbol(symbol)
    _ensure_data_dir()
    cache = _cache_path(symbol)

    if not force and _is_cache_fresh(cache):
        return _load_with_migration(cache)

    _ensure_no_proxy()
    start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime("%Y%m%d")

    # v0.0.5: TuShare Pro 优先（配 token 时）→ baostock → akshare 并发 → 腾讯
    raw = _fetch_tushare(symbol, start)
    source = "tushare"
    if raw is None:
        raw = _fetch_baostock(symbol, start)
        source = "baostock"
    if raw is None:
        akshare_result = _fetch_via_akshare(symbol, start)
        if akshare_result is not None:
            raw, source = akshare_result
    if raw is None:
        raw = _fetch_tencent(symbol, start)
        source = "tencent"

    if raw is None or raw.empty:
        raise ValueError(f"无效股票代码或无数据: {symbol}")

    from kan.storage.paths import atomic_write_parquet

    df = _normalize_kline(raw, source=source)
    atomic_write_parquet(df, cache)
    return df


def resolve_max_workers() -> int:
    """启发式 max_workers · 不再硬编码 5.

    akshare 是 I/O bound (HTTP 拉取 · 不是 CPU 计算) · cpu_count*2 比 cpu-1 更合理.
    上限 cap 12 防 akshare 限流 (弱网下 ≥ 12 反而变慢).

    Examples:
    - 4 核 Mac mini: cpu_count=4 → workers=8 (5 → 8 提升 60%)
    - 8 核 MacBook: cpu_count=8 → workers=12 (cap)
    - 16 核 Mac Studio: cpu_count=16 → workers=12 (cap · 防限流)
    - Docker / cgroup 返宿主机核数: cap 12 天然缓解

    KAN_WORKERS env var 可显式 override (整数 · 1-50 范围 · 越界回退默认).
    """
    import os
    raw = os.environ.get("KAN_WORKERS")
    if raw:
        try:
            n = int(raw)
            # 上限从 50 收紧到 20 · 防 KAN_WORKERS=50 反射 DoS akshare
            # akshare 限流阈值实测约 10-15 req/s · 20 并发已超 · 50 必触发限流
            if 1 <= n <= 20:
                return n
        except ValueError:
            pass
    return min((os.cpu_count() or 4) * 2, 12)


def fetch_batch(
    symbols: list[str],
    days: int = 180,
    force: bool = False,
    max_workers: int | None = None,
    on_progress: Callable | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """批量拉取 · ThreadPoolExecutor 并发 + 可选 progress callback.

    max_workers=None → resolve_max_workers() 启发式 (cpu_count*2 cap 12).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # max_workers None / 0 / 负数 都退化到 resolve_max_workers
    # 防御 ThreadPoolExecutor(max_workers=0) 抛 ValueError 的边界
    if max_workers is None or max_workers < 1:
        max_workers = resolve_max_workers()

    results: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}

    def _safe_one(symbol: str) -> tuple[str, pd.DataFrame | None, str | None]:
        import time

        for attempt in range(2):
            try:
                df = fetch_kline(symbol, days=days, force=force)
                return symbol, df, None
            except Exception as e:
                # fetch_batch retry path · 加 debug log
                debug_log(__name__, f"fetch_batch retry {attempt}", e)
                if attempt == 0:
                    time.sleep(1)
                    continue
                return symbol, None, str(e)
        return symbol, None, "unknown error"

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_safe_one, s) for s in symbols]
        try:
            for future in as_completed(futures):
                symbol, df, err = future.result()
                if err is None and df is not None:
                    results[symbol] = df
                    if on_progress:
                        on_progress(symbol, True, None)
                else:
                    errors[symbol] = err or "unknown error"
                    if on_progress:
                        on_progress(symbol, False, err)
        except KeyboardInterrupt:
            for f in futures:
                f.cancel()
            raise

    return results, errors


def is_fresh(symbol: str) -> bool:
    return _is_cache_fresh(_cache_path(symbol))


def has_cache(symbol: str) -> bool:
    return _cache_path(symbol).exists()


def get_cached(symbol: str) -> pd.DataFrame | None:
    cache = _cache_path(symbol)
    if not cache.exists():
        return None
    df = _load_with_migration(cache)
    # 兜底：手工写入的 parquet 可能缺 volume/amount (非 _source · migration 已处理)
    for col in ["volume", "amount"]:
        if col not in df.columns:
            df[col] = float("nan")
    return df


def cache_age(symbol: str) -> str | None:
    """缓存文件 mtime · 语义 = "上次拉取时间"（v0.0.4.5 起不再当作"数据日期"使用）。

    历史教训：v0.0.4.4 及之前把 mtime 当作"数据日期"显示在 scan 标题（"X 更新"），
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

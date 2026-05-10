"""K 线数据拉取层 · 多源 fallback（东方财富 → baostock → 腾讯）"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import akshare as ak
import pandas as pd

from kan.paths import DATA_DIR

if TYPE_CHECKING:
    from collections.abc import Callable

# ── K 线标准 schema ──────────────────────────────────────────────────
# 所有数据源的出口必须经过 _normalize_kline() 归一化到此格式。
# 新增列只需追加到 KLINE_OPTIONAL · 下游按列名读取 · 不受影响。

KLINE_REQUIRED = ["date", "open", "high", "low", "close"]
KLINE_OPTIONAL = ["volume", "amount"]
KLINE_COLUMNS = KLINE_REQUIRED + KLINE_OPTIONAL

# 东方财富中文列名 → 标准列名
_EM_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}

# 6 位纯数字股票代码 · 防止 path traversal
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")


def _normalize_kline(df: pd.DataFrame) -> pd.DataFrame:
    """统一归一化：类型转换 + 补缺失列 + 排序 + 去 NaN。所有数据源的出口。"""
    for col in KLINE_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")

    for col in KLINE_OPTIONAL:
        if col not in df.columns:
            df[col] = float("nan")

    df = df[KLINE_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in KLINE_COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("date").reset_index(drop=True)
    df = df.dropna(subset=["date", "close"])
    return df


# ── 通用工具 ─────────────────────────────────────────────────────────

def _validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"非法股票代码: {symbol!r} · 应为 6 位纯数字")
    return symbol


def _ensure_data_dir() -> None:
    from kan.paths import ensure_dirs
    ensure_dirs()


def _cache_path(symbol: str) -> Path:
    symbol = _validate_symbol(symbol)
    return DATA_DIR / f"{symbol}.parquet"


def _is_cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    mtime_date = datetime.fromtimestamp(path.stat().st_mtime).date()
    return mtime_date == date.today()


def _market_prefix(symbol: str, sep: str = "") -> str:
    """6 位代码 → 带市场前缀（sh600519 / sz.000001）"""
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    return f"{prefix}{sep}{symbol}"


# ── 数据源 1: 东方财富（最快 · 单次 HTTP · 带熔断） ──────────────────

_eastmoney_ok: bool | None = None


def _fetch_eastmoney(symbol: str, start: str) -> pd.DataFrame | None:
    global _eastmoney_ok
    if _eastmoney_ok is False:
        return None
    try:
        raw = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", adjust="qfq",
            start_date=start, timeout=5,
        )
        if raw is None or raw.empty or "日期" not in raw.columns:
            return None
        _eastmoney_ok = True
        return raw.rename(columns=_EM_COLUMN_MAP)
    except Exception:
        _eastmoney_ok = False
        return None


# ── 数据源 2: baostock（独立服务器 · 最稳 · 线程安全锁） ─────────────

_bs_lock = threading.Lock()
_bs_logged_in = False


def _ensure_bs_login() -> None:
    global _bs_logged_in
    if _bs_logged_in:
        return
    import io
    import sys

    import baostock as bs

    _stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        bs.login()
    finally:
        sys.stdout = _stdout
    _bs_logged_in = True


def _fetch_baostock(symbol: str, start: str) -> pd.DataFrame | None:
    try:
        import baostock as bs
    except ImportError:
        return None

    start_fmt = f"{start[:4]}-{start[4:6]}-{start[6:8]}"

    with _bs_lock:
        try:
            _ensure_bs_login()
            rs = bs.query_history_k_data_plus(
                _market_prefix(symbol, sep="."),
                "date,open,high,low,close,volume,amount",
                start_date=start_fmt,
                frequency="d",
                adjustflag="2",
            )
            if rs.error_code != "0":
                return None
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
        except Exception:
            return None

    if not rows:
        return None

    return pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "volume", "amount"],
    )


# ── 数据源 3: 新浪财经（akshare stock_zh_a_daily · 免登录 · 数值精度高） ──

def _fetch_sina(symbol: str, start: str) -> pd.DataFrame | None:
    """新浪财经历史日 K · akshare 官方 fallback。

    返回 schema: date/open/high/low/close/volume/amount/outstanding_share/turnover
    其中 volume 单位「股」、amount 单位「元」，跟 baostock 完全对齐（实测）。
    免登录、不熔断；东财 push2his 被 ban 时最稳的路径之一。
    """
    import io
    import sys

    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    end = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")

    _real_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        raw = ak.stock_zh_a_daily(
            symbol=f"{prefix}{symbol}",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    except Exception:
        return None
    finally:
        sys.stderr = _real_stderr

    if raw is None or raw.empty:
        return None
    return raw


# ── 数据源 4: 腾讯证券（备用 · 按年分片 · 价格可信 · 量额不可信） ────

def _fetch_tencent(symbol: str, start: str) -> pd.DataFrame | None:
    """腾讯 K 线 fallback。

    akshare.stock_zh_a_hist_tx 返回 6 列：date/open/close/high/low/amount。
    其中 "amount" 字段语义在不同板块不一致（实测 2026-05-08）：
      - 主板/创业板：amount 实际是「成交手数」(volume / 100)
      - 科创板（688/689）：amount 实际是「成交股数」(等于 volume)
    既然语义不可移植，我们**保守只取价格列**（date/open/high/low/close），
    丢弃 amount，让 _normalize_kline 把 volume/amount 都填 NaN。
    下游看到 NaN 会跳过相关计算（成交量异动相关），比错值安全。
    """
    import io
    import sys

    _real_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        raw = ak.stock_zh_a_hist_tx(
            symbol=_market_prefix(symbol),
            start_date=start,
            adjust="qfq",
            timeout=15,
        )
    except Exception:
        return None
    finally:
        sys.stderr = _real_stderr

    if raw is None or raw.empty:
        return None

    if "amount" in raw.columns:
        raw = raw.drop(columns=["amount"])
    return raw


# ── 公开 API ─────────────────────────────────────────────────────────

def fetch_kline(symbol: str, days: int = 180, force: bool = False) -> pd.DataFrame:
    """拉取单只股票前复权日 K 线（baostock → 新浪 → 东财 → 腾讯）。

    返回 DataFrame · 标准列：date, open, high, low, close, volume, amount

    fallback 顺序设计依据（2026-05-10 实测）：
    1. baostock 独立服务器最稳 · 免熔断 · 数值精度全 A 股板块对齐
    2. 新浪源（akshare stock_zh_a_daily）· 免登录 · 精度跟 baostock 一致 · akshare 官方推荐 fallback
    3. 东财（akshare stock_zh_a_hist）· push2his.eastmoney.com 对部分 IP 段持续封禁
       （akshare GitHub Issue #6092/#6148/#7011/#6214）· 偶尔可用降到第三
    4. 腾讯（akshare stock_zh_a_hist_tx）· 仅价格可信 · amount 字段板块语义不一致已 drop
    """
    symbol = _validate_symbol(symbol)
    _ensure_data_dir()
    cache = _cache_path(symbol)

    if not force and _is_cache_fresh(cache):
        return pd.read_parquet(cache)

    start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime("%Y%m%d")

    raw = _fetch_baostock(symbol, start)
    if raw is None:
        raw = _fetch_sina(symbol, start)
    if raw is None:
        raw = _fetch_eastmoney(symbol, start)
    if raw is None:
        raw = _fetch_tencent(symbol, start)

    if raw is None or raw.empty:
        raise ValueError(f"无效股票代码或无数据: {symbol}")

    df = _normalize_kline(raw)
    df.to_parquet(cache, index=False)
    return df


def fetch_batch(
    symbols: list[str],
    days: int = 180,
    force: bool = False,
    max_workers: int = 5,
    on_progress: Callable | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """批量拉取 · ThreadPoolExecutor 并发 + 可选 progress callback。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}

    def _safe_one(symbol: str) -> tuple[str, pd.DataFrame | None, str | None]:
        import time

        for attempt in range(2):
            try:
                df = fetch_kline(symbol, days=days, force=force)
                return symbol, df, None
            except Exception as e:
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
    df = pd.read_parquet(cache)
    for col in KLINE_OPTIONAL:
        if col not in df.columns:
            df[col] = float("nan")
    return df


def cache_age(symbol: str) -> str | None:
    cache = _cache_path(symbol)
    if not cache.exists():
        return None
    mtime = datetime.fromtimestamp(cache.stat().st_mtime)
    return mtime.strftime("%Y-%m-%d %H:%M")

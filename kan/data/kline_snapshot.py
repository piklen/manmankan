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
from datetime import date, datetime, timedelta
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING

from kan.core.scanner import PERIODS, scan_stock
from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR, atomic_write_parquet, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")
_DAILY_TTL = 6 * 3600
_SNAPSHOT_TTL = 6 * 3600

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
    return DATA_DIR / f"daily_bars_{_validate_trade_date(trade_date)}.parquet"


def _snapshot_cache_path(trade_date: str, periods: list[int]) -> Path:
    raw = "-".join(map(str, sorted(set(periods))))
    key = raw if len(raw) <= 80 else sha1(raw.encode("ascii")).hexdigest()[:16]
    return DATA_DIR / f"kline_snapshot_{_validate_trade_date(trade_date)}_{key}.parquet"


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


def fetch_daily_bars(
    trade_date: str | None = None,
    *,
    symbols: list[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """按交易日拉全市场 daily OHLC 截面 · parquet 缓存后按 symbols 过滤。"""
    from kan.data.tushare import _fetch_tushare_daily_bars

    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    ensure_dirs()
    cache = _daily_cache_path(td)
    if not force and _cache_fresh(cache, td, _DAILY_TTL):
        cached = _load_cache(cache)
        if cached is not None:
            return _filter_symbols(cached, symbols)

    raw = _fetch_tushare_daily_bars(td)
    if raw is None or raw.empty:
        return _empty_daily_df()
    df = _normalize_daily_bars(raw)
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
) -> pd.DataFrame:
    import pandas as pd

    if bars.empty:
        return _empty_snapshot_df(periods)
    rows: list[dict] = []
    bars = bars.sort_values(["symbol", "date"])
    for symbol, group in bars.groupby("symbol", sort=False):
        if group.empty:
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
    if not rows:
        return _empty_snapshot_df(periods)
    return pd.DataFrame(rows, columns=_snapshot_columns(periods))


def fetch_kline_snapshot(
    trade_date: str | None = None,
    *,
    symbols: list[str] | None = None,
    periods: list[int] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """取每日 K 线裸值快照 · 支持全市场 `--all` 的 pos/gain/up-days/resonance filter。"""
    import pandas as pd

    periods = sorted(set(periods or PERIODS))
    max_period = max(periods)
    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    end = _date_from_trade_date(td)
    ensure_dirs()
    cache = _snapshot_cache_path(td, periods)
    if not force and _cache_fresh(cache, td, _SNAPSHOT_TTL):
        cached = _load_cache(cache)
        if cached is not None:
            return _filter_symbols(cached, symbols)

    dates = _recent_trade_dates(end, max_period + 1)
    frames: list[pd.DataFrame] = []
    for d in dates:
        daily = fetch_daily_bars(d.strftime("%Y%m%d"), force=force)
        if not daily.empty:
            frames.append(daily)
    if not frames:
        return _empty_snapshot_df(periods)

    bars = pd.concat(frames, ignore_index=True)
    snapshot = _build_snapshot(bars, periods=periods, end_date=end)
    if not snapshot.empty:
        atomic_write_parquet(snapshot, cache)
    return _filter_symbols(snapshot, symbols)


__all__ = ["DAILY_BAR_COLUMNS", "fetch_daily_bars", "fetch_kline_snapshot"]

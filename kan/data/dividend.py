"""分红送股 / 除权除息事件缓存 · scan 行标记用。

本模块只提供客观事件数据:除权除息日、股权登记日、每股现金分红、每股送转。
K 线复权由数据源层保证;这里的事件标记用于提醒 scan 消费方该区间存在价格口径事件。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR, atomic_write_parquet, ensure_dirs

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

DIVIDEND_COLUMNS = [
    "symbol",
    "record_date",
    "ex_date",
    "cash_div_tax",
    "cash_div",
    "stk_div",
    "div_proc",
    "_source",
]

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_DIVIDEND_TTL = 7 * 24 * 3600
_SOURCE = "tushare_dividend"
_TUSHARE_DIVIDEND_FIELDS = "ts_code,record_date,ex_date,cash_div_tax,cash_div,stk_div,div_proc"


def _cache_path(symbol: str) -> Path:
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"非法股票代码: {symbol!r}")
    return DATA_DIR / f"dividend_{symbol}.parquet"


def _empty_df() -> pd.DataFrame:
    import pandas as pd

    return pd.DataFrame(columns=DIVIDEND_COLUMNS)


def _normalize_dividend(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """dividend 原始表 → 标准列 · 日期/数值清洗 · 仅保留有 ex_date 的事件。"""
    import pandas as pd

    for col in DIVIDEND_COLUMNS:
        if col not in df.columns:
            df[col] = _SOURCE if col == "_source" else None
    out = df[DIVIDEND_COLUMNS].copy()
    out["symbol"] = out["symbol"].fillna(symbol).astype(str).str.strip()
    out = out[out["symbol"] == symbol]
    out["record_date"] = pd.to_datetime(out["record_date"], errors="coerce").dt.date
    out["ex_date"] = pd.to_datetime(out["ex_date"], errors="coerce").dt.date
    for col in ("cash_div_tax", "cash_div", "stk_div"):
        out[col], _bad = to_numeric_checked(out[col])
    out["_source"] = _SOURCE
    out = out.dropna(subset=["ex_date"])
    return out.sort_values("ex_date").drop_duplicates(
        subset=["symbol", "ex_date"], keep="last",
    ).reset_index(drop=True)


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd

    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"读取分红缓存失败: {path.name}", e)
        return None


def _to_tushare_dividend_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare dividend data block -> raw dividend DataFrame with `symbol`."""
    import pandas as pd

    from kan.data.tushare import _strip_ts_suffix

    if not data:
        return None
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return None
    df = pd.DataFrame(items, columns=fields)
    if "ts_code" not in df.columns:
        return None
    df["symbol"] = df["ts_code"].map(_strip_ts_suffix)
    return df.drop(columns=["ts_code"])


def _fetch_tushare_dividend(symbol: str) -> pd.DataFrame | None:
    """TuShare dividend 单股事件 adapter · 独立熔断 key `tushare_dividend`."""
    from kan.data.tushare import _normalize_symbol_to_ts, _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_dividend"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="dividend",
            params={"ts_code": ts_code},
            fields=_TUSHARE_DIVIDEND_FIELDS,
        )
        if data is None:
            cb.record("tushare_dividend", ok=False)
            return None
        df = _to_tushare_dividend_df(data)
        if df is None:
            cb.record("tushare_dividend", ok=False)
            return None
        cb.record("tushare_dividend", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare dividend 失败", e)
        cb.record("tushare_dividend", ok=False)
        return None


def fetch_dividends(symbol: str, *, force: bool = False) -> pd.DataFrame:
    """取单股分红送股事件 · 无 token/无数据返回空表,不抛业务异常。"""
    if not _SYMBOL_PATTERN.match(symbol):
        return _empty_df()
    ensure_dirs()
    cache = _cache_path(symbol)
    if not force and cache.exists() and (time.time() - cache.stat().st_mtime) < _DIVIDEND_TTL:
        cached = _load_cache(cache)
        if cached is not None:
            return cached

    raw = _fetch_tushare_dividend(symbol)
    if raw is None or raw.empty:
        return _empty_df()
    df = _normalize_dividend(raw, symbol)
    atomic_write_parquet(df, cache)
    return df


def latest_event_between(symbol: str, start: date, end: date) -> dict | None:
    """返回 [start,end] 内最新除权除息事件 dict · 无则 None。"""
    df = fetch_dividends(symbol)
    if df.empty:
        return None
    sub = df[(df["ex_date"] >= start) & (df["ex_date"] <= end)]
    if sub.empty:
        return None
    row = sub.sort_values("ex_date").iloc[-1]
    return row.to_dict()


__all__ = ["DIVIDEND_COLUMNS", "fetch_dividends", "latest_event_between"]

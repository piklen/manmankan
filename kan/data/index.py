"""A 股指数日线 · TuShare index_daily 接入。

指数行情只作为市场参照数据输出,不参与自选股扫描排序。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from kan.infra.log import debug_log

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class IndexSpec:
    code: str
    name: str


DEFAULT_INDEXES = (
    IndexSpec("000001.SH", "上证指数"),
    IndexSpec("399001.SZ", "深证成指"),
    IndexSpec("399006.SZ", "创业板指"),
    IndexSpec("000300.SH", "沪深300"),
)

_ALIASES = {
    "sh": "000001.SH",
    "sz": "399001.SZ",
    "cyb": "399006.SZ",
    "hs300": "000300.SH",
    "上证": "000001.SH",
    "深成": "399001.SZ",
    "创业板": "399006.SZ",
    "沪深300": "000300.SH",
}

_INDEX_FIELDS = (
    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
)


def normalize_index_code(raw: str) -> str:
    """Normalize user input to TuShare index ts_code."""
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("指数代码不能为空")
    alias = _ALIASES.get(cleaned.lower()) or _ALIASES.get(cleaned)
    if alias:
        return alias
    upper = cleaned.upper()
    if "." in upper:
        return upper
    if len(upper) == 6 and upper.isdigit():
        if upper.startswith(("000", "880")):
            return f"{upper}.SH"
        return f"{upper}.SZ"
    raise ValueError(f"不支持的指数代码: {raw!r}")


def index_name(code: str) -> str:
    """Known index display name; unknown code falls back to code itself."""
    normalized = normalize_index_code(code)
    for spec in DEFAULT_INDEXES:
        if spec.code == normalized:
            return spec.name
    return normalized


def _to_index_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare index_daily data 块 → scanner 可直接读取的 K 线 schema."""
    import pandas as pd

    if not data:
        return None
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return None
    df = pd.DataFrame(items, columns=fields)
    if "trade_date" not in df.columns:
        return None
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "volume", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    if df.empty:
        return None
    return df.sort_values("date").reset_index(drop=True)


def fetch_index_daily(
    code: str,
    *,
    days: int = 420,
    end_date: date | None = None,
) -> pd.DataFrame | None:
    """Fetch index_daily for one index.

    Returns None when TuShare is unavailable, token is missing, or the interface
    returns no rows. Callers display null/empty data instead of failing loudly.
    """
    from kan.data.tushare import _post_tushare_api, _resolve_config

    token, endpoint = _resolve_config()
    if not token:
        return None
    ts_code = normalize_index_code(code)
    if end_date is None:
        from kan.core.trading_calendar import latest_trade_date

        end_date = latest_trade_date()
    # Calendar days rather than trading days; 2x leaves enough room for holidays.
    start_date = end_date - timedelta(days=max(days * 2, 30))
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="index_daily",
            params={
                "ts_code": ts_code,
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d"),
            },
            fields=_INDEX_FIELDS,
        )
    except Exception as e:
        debug_log(__name__, "fetch index_daily failed", e)
        return None
    df = _to_index_df(data)
    if df is None or df.empty:
        return None
    return df.tail(days).reset_index(drop=True)


__all__ = ["DEFAULT_INDEXES", "IndexSpec", "fetch_index_daily", "index_name", "normalize_index_code"]

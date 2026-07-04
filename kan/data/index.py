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
    """Fetch daily kline for one index.

    主路径 TuShare index_daily;无 token、接口未覆盖或返回空时 fallback 到
    akshare 新浪指数源,让指数参照对零 token 用户也可用。两路都失败返回
    None,调用方按 data_available=False 呈现,不硬报错。
    """
    ts_code = normalize_index_code(code)
    df = _fetch_index_tushare(ts_code, days=days, end_date=end_date)
    if df is not None:
        return df
    return _fetch_index_akshare(ts_code, days=days, end_date=end_date)


def _fetch_index_tushare(
    ts_code: str,
    *,
    days: int,
    end_date: date | None,
) -> pd.DataFrame | None:
    """TuShare index_daily 主路径;token 缺失或无数据返回 None。"""
    from kan.data.tushare import _post_tushare_api, _resolve_config

    token, endpoint = _resolve_config()
    if not token:
        return None
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


def _akshare_index_symbol(ts_code: str) -> str:
    """TuShare ts_code → akshare 新浪指数 symbol(如 000001.SH → sh000001)。"""
    code, _, exchange = ts_code.partition(".")
    return f"{exchange.lower()}{code}"


def _fetch_index_akshare(
    ts_code: str,
    *,
    days: int,
    end_date: date | None,
) -> pd.DataFrame | None:
    """akshare 新浪指数日线 fallback;失败静默返回 None,细节进 debug log。"""
    import pandas as pd

    try:
        import akshare as ak

        from kan.infra.finalizer_guard import defuse_mini_racer_finalizer

        defuse_mini_racer_finalizer()
        raw = ak.stock_zh_index_daily(symbol=_akshare_index_symbol(ts_code))
    except Exception as e:
        debug_log(__name__, "akshare index fallback failed", e)
        return None
    if raw is None or raw.empty or "date" not in raw.columns:
        return None
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    if end_date is not None:
        df = df[df["date"] <= end_date]
    if df.empty:
        return None
    return df.sort_values("date").tail(days).reset_index(drop=True)


__all__ = ["DEFAULT_INDEXES", "IndexSpec", "fetch_index_daily", "index_name", "normalize_index_code"]

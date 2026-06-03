"""技术面因子截面拉取编排 · cache + 公开 API (整合-2)。

仿 moneyflow.py 的截面缓存机制 (cache key = trade_date · parquet · 历史日永鲜 /
最新日 TTL) · 单源直调 _fetch_tushare_technical (不走责任链:stk_factor_pro 仅
tushare 一源 · 同 moneyflow "单源暂不抽 chain" 约定 · 避免过度抽象)。

前复权 (_qfq) 技术指标 (adapter 已 rename 去后缀)。客观指标值 · 不含信号判断词
(compliance §3/§7 · 裸值可出 · filter 阈值用户主导)。
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR, atomic_write_parquet, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

# ── 技术面因子截面标准 schema ────────────────────────────────────────
# 出口必须经 _normalize_technical 归一化 · 新增列追加到 TECHNICAL_OPTIONAL。
TECHNICAL_REQUIRED = ["symbol"]
TECHNICAL_OPTIONAL = [
    "trade_date",
    "close",
    "atr",
    "macd_dif",
    "macd_dea",
    "macd",
    "kdj_k",
    "kdj_d",
    "kdj_j",
    "rsi_6",
    "rsi_12",
    "rsi_24",
    "ma_5",
    "ma_10",
    "ma_20",
    "ma_60",
    "boll_upper",
    "boll_mid",
    "boll_lower",
    "_source",
]
TECHNICAL_COLUMNS = TECHNICAL_REQUIRED + TECHNICAL_OPTIONAL
_TECHNICAL_NUMERIC = [c for c in TECHNICAL_OPTIONAL if c not in ("trade_date", "_source")]

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")

_TECHNICAL_TTL = 6 * 3600
"""最新交易日截面 mtime TTL (同 moneyflow) · 历史交易日截面固定 · 永鲜。"""
_TECHNICAL_SOURCE = "tushare_factor"
_TUSHARE_TECHNICAL_FIELDS = (
    "ts_code,trade_date,close_qfq,atr_qfq,"
    "macd_dif_qfq,macd_dea_qfq,macd_qfq,"
    "kdj_k_qfq,kdj_d_qfq,kdj_qfq,"
    "rsi_qfq_6,rsi_qfq_12,rsi_qfq_24,"
    "ma_qfq_5,ma_qfq_10,ma_qfq_20,ma_qfq_60,"
    "boll_upper_qfq,boll_mid_qfq,boll_lower_qfq"
)
_TUSHARE_TECHNICAL_RENAME = {
    "close_qfq": "close",
    "atr_qfq": "atr",
    "macd_dif_qfq": "macd_dif",
    "macd_dea_qfq": "macd_dea",
    "macd_qfq": "macd",
    "kdj_k_qfq": "kdj_k",
    "kdj_d_qfq": "kdj_d",
    "kdj_qfq": "kdj_j",
    "rsi_qfq_6": "rsi_6",
    "rsi_qfq_12": "rsi_12",
    "rsi_qfq_24": "rsi_24",
    "ma_qfq_5": "ma_5",
    "ma_qfq_10": "ma_10",
    "ma_qfq_20": "ma_20",
    "ma_qfq_60": "ma_60",
    "boll_upper_qfq": "boll_upper",
    "boll_mid_qfq": "boll_mid",
    "boll_lower_qfq": "boll_lower",
}


# ── 归一化 ───────────────────────────────────────────────────────────

def _normalize_technical(df: pd.DataFrame, source: str = _TECHNICAL_SOURCE) -> pd.DataFrame:
    """补缺列 + symbol 规范 + 数值清洗 + _source 标注 (仿 moneyflow._normalize_moneyflow)。

    截面无时序 · 不排序 · 按 symbol 去重 · 过滤非 6 位代码 (脏数据防御)。
    """
    import pandas as pd

    for col in TECHNICAL_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")
    for col in TECHNICAL_OPTIONAL:
        if col not in df.columns:
            df[col] = source if col == "_source" else float("nan")

    df = df[TECHNICAL_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for col in _TECHNICAL_NUMERIC:
        df[col], _bad = to_numeric_checked(df[col])
    df["_source"] = source

    df = df[df["symbol"].str.match(_SYMBOL_PATTERN, na=False)]
    df = df.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
    return df


# ── 通用工具 (仿 moneyflow) ──────────────────────────────────────────

def _validate_trade_date(trade_date: str) -> str:
    if not isinstance(trade_date, str) or not _TRADE_DATE_PATTERN.match(trade_date):
        raise ValueError(f"非法交易日: {trade_date!r} · 应为 8 位 YYYYMMDD")
    return trade_date


def _latest_trade_date_str() -> str:
    from kan.core.trading_calendar import latest_trade_date
    return latest_trade_date().strftime("%Y%m%d")


def _cache_path(trade_date: str) -> Path:
    trade_date = _validate_trade_date(trade_date)
    return DATA_DIR / f"technical_{trade_date}.parquet"


def _cache_fresh(path: Path, trade_date: str) -> bool:
    """截面缓存判鲜:历史交易日永鲜 · 最新交易日 mtime TTL (同 moneyflow)。"""
    if not path.exists():
        return False
    try:
        td = datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError:
        return False
    from kan.core.trading_calendar import latest_trade_date
    if td < latest_trade_date():
        return True
    return (time.time() - path.stat().st_mtime) < _TECHNICAL_TTL


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd
    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_cache({path.name})", e)
        return None


def _empty_df() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=TECHNICAL_COLUMNS)


def _filter_symbols(df: pd.DataFrame, symbols: list[str] | None) -> pd.DataFrame:
    if symbols is None:
        return df
    wanted = {str(s) for s in symbols}
    return df[df["symbol"].isin(wanted)].reset_index(drop=True)


def _to_tushare_technical_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare stk_factor_pro data block -> raw technical DataFrame with `symbol`."""
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
    df = df.drop(columns=["ts_code"])
    return df.rename(columns=_TUSHARE_TECHNICAL_RENAME)


def _fetch_tushare_technical(trade_date: str) -> pd.DataFrame | None:
    """TuShare stk_factor_pro 单日截面 adapter · 独立熔断 key `tushare_factor`."""
    from kan.data.tushare import _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_factor"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="stk_factor_pro",
            params={"trade_date": trade_date},
            fields=_TUSHARE_TECHNICAL_FIELDS,
        )
        if data is None:
            cb.record("tushare_factor", ok=False)
            return None
        df = _to_tushare_technical_df(data)
        if df is None or df.empty:
            cb.record("tushare_factor", ok=False)
            return None
        cb.record("tushare_factor", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare technical 失败", e)
        cb.record("tushare_factor", ok=False)
        return None


# ── 公开 API ─────────────────────────────────────────────────────────

def fetch_technical(
    trade_date: str | None = None,
    symbols: list[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """拉单日技术面因子截面 · 单源直调 + 全市场缓存 + symbols 编排层过滤。

    截面优势:stk_factor_pro 按 trade_date 一次拉全市场 (一次 HTTP) · parquet 缓存 ·
    symbols 过滤读缓存后切子集 (仿 moneyflow.fetch_moneyflow)。

    Args:
        trade_date: YYYYMMDD · None → 最近交易日
        symbols: 限定 6 位代码子集 · None = 全市场 · 过滤在编排层
        force: 跳缓存强制重拉

    Returns:
        DataFrame · 标准列 TECHNICAL_COLUMNS。无 token / 失败 → 空 DataFrame
        (列齐 · 0 行 · 不抛 · 调用方按行数判断)。
    """
    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    ensure_dirs()
    cache = _cache_path(td)
    if not force and _cache_fresh(cache, td):
        cached = _load_cache(cache)
        if cached is not None:
            return _filter_symbols(cached, symbols)

    raw = _fetch_tushare_technical(td)
    if raw is None or raw.empty:
        return _empty_df()
    df = _normalize_technical(raw)
    atomic_write_parquet(df, cache)
    return _filter_symbols(df, symbols)


__all__ = ["TECHNICAL_COLUMNS", "fetch_technical"]

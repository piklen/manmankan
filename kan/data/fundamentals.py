"""逐股财务指标 (ROE / 增速) 拉取编排 · 逐股缓存 + 公开 API (整合-1)。

仿 metrics.fetch_valuation_history 的逐股缓存 (每股一 parquet · 存全报告期) +
industry_map 单源降级。fina_indicator 按 ts_code 逐股 (全市场逐股代价高 ·
PRD §3.2) · 只在 K 线池 / 小池按需拉 (find --roe · 全市场 --all 不支持)。

每股缓存全历史报告期 · 读时取最新一期 (max end_date)。TTL 90d (季报季度更新)。
原始指标值 (compliance §6/§7 · 命名中性)。
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
    import pandas as pd

_FUNDAMENTALS_COLUMNS = ["end_date", "roe", "netprofit_yoy", "or_yoy"]
_FUNDAMENTALS_NUMERIC = ["roe", "netprofit_yoy", "or_yoy"]
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_FUNDAMENTALS_TTL = 90 * 24 * 3600
"""季报季度更新 · 90d 长缓存 (逐股 HTTP 贵 · 长缓存复用)。"""


def _cache_path(symbol: str) -> Path:
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"非法股票代码: {symbol!r}")
    return DATA_DIR / f"fundamentals_{symbol}.parquet"


def _empty_df() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=_FUNDAMENTALS_COLUMNS)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """归一化单股财务时序:补缺列 + end_date → date + 数值清洗 + 去无效行。"""
    import pandas as pd

    for col in _FUNDAMENTALS_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_FUNDAMENTALS_COLUMNS].copy()
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce").dt.date
    for col in _FUNDAMENTALS_NUMERIC:
        df[col], _bad = to_numeric_checked(df[col])
    return df.dropna(subset=["end_date"]).reset_index(drop=True)


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd
    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_cache({path.name})", e)
        return None


def _fetch_one(symbol: str, force: bool = False) -> pd.DataFrame:
    """单股财务时序 (全报告期) · 逐股 parquet 缓存 · 无 token/失败 → 空 df。"""
    from kan.data.tushare import _fetch_tushare_fundamentals

    if not _SYMBOL_PATTERN.match(symbol):
        return _empty_df()
    ensure_dirs()
    cache = _cache_path(symbol)
    if (
        not force
        and cache.exists()
        and (time.time() - cache.stat().st_mtime) < _FUNDAMENTALS_TTL
    ):
        loaded = _load_cache(cache)
        if loaded is not None:
            return loaded

    raw = _fetch_tushare_fundamentals(symbol)
    if raw is None or raw.empty:
        return _empty_df()
    df = _normalize(raw)
    if df.empty:
        return _empty_df()
    atomic_write_parquet(df, cache)
    return df


def _latest_row(df: pd.DataFrame) -> pd.Series | None:
    """取最新一期报告 (max end_date) · 空 df → None。"""
    if df is None or df.empty:
        return None
    idx = df["end_date"].idxmax()
    return df.loc[idx]


def fetch_fundamentals(
    symbols: list[str], force: bool = False,
) -> dict[str, pd.Series]:
    """逐股拉财务指标 · 返回 {symbol: 最新一期 Series} (整合-1 · ROE/增速)。

    逐股 HTTP (全市场代价高 · 只在小池 / K 线池按需调) · 每股 90d parquet 缓存。
    无 token / 失败 → 该股不入 dict (caller .get(symbol) → None · 优雅降级)。

    Args:
        symbols: 6 位代码列表
        force: 跳缓存强制重拉

    Returns:
        {symbol: pd.Series (end_date / roe / netprofit_yoy / or_yoy)} · 仅含有数据的股。
        空 symbols → 空 dict (不触网)。
    """
    out: dict[str, pd.Series] = {}
    for symbol in symbols:
        row = _latest_row(_fetch_one(symbol, force=force))
        if row is not None:
            out[str(symbol)] = row
    return out


__all__ = ["fetch_fundamentals"]

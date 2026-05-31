"""情绪面 (涨跌停/连板) 截面拉取编排 · cache + 公开 API (整合-2)。

仿 moneyflow.py 的截面缓存机制 · 单源直调 _fetch_tushare_sentiment (limit_list_d 仅
tushare 一源)。

稀疏事件型:limit_list_d 只返回当日有涨跌停/炸板的票 (不在榜 = 该股当日未涨跌停 ·
SentimentMetrics 为 None · 非数据缺失) · 不含 ST (接口不统计) · 数据从 2020 起。
连板天数 / 炸板次数是客观市场事实 (compliance §2/§3 · 裸值可出 · filter 用户主导)。

与 moneyflow 差异:limit / up_stat 是字符串列 (不进数值清洗)。
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

# ── 情绪面截面标准 schema ────────────────────────────────────────────
# 出口必须经 _normalize_sentiment 归一化。limit / up_stat 是字符串列 (不数值清洗)。
SENTIMENT_REQUIRED = ["symbol"]
SENTIMENT_OPTIONAL = [
    "trade_date",
    "limit_times",   # 连板天数
    "open_times",    # 炸板/开板次数
    "limit",         # 涨跌停类型 U/D/Z (str)
    "up_stat",       # 涨停统计 "3/3" (str)
    "_source",
]
SENTIMENT_COLUMNS = SENTIMENT_REQUIRED + SENTIMENT_OPTIONAL
_SENTIMENT_NUMERIC = ["limit_times", "open_times"]
_SENTIMENT_STR = ["limit", "up_stat"]

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")

_SENTIMENT_TTL = 6 * 3600
"""最新交易日截面 mtime TTL (同 moneyflow) · 历史交易日截面固定 · 永鲜。"""
_SENTIMENT_SOURCE = "tushare_limit"


# ── 归一化 ───────────────────────────────────────────────────────────

def _normalize_sentiment(df: pd.DataFrame, source: str = _SENTIMENT_SOURCE) -> pd.DataFrame:
    """补缺列 + symbol 规范 + 数值清洗 + _source 标注 (仿 moneyflow · 含 str 列分流)。

    与 moneyflow 差异:limit / up_stat 是字符串列 · 不进数值清洗 (缺列填 None)。
    截面无时序 · 不排序 · 按 symbol 去重 · 过滤非 6 位代码 (脏数据防御)。
    """
    import pandas as pd

    for col in SENTIMENT_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")
    for col in SENTIMENT_OPTIONAL:
        if col not in df.columns:
            if col == "_source":
                df[col] = source
            elif col in _SENTIMENT_STR:
                df[col] = None
            else:
                df[col] = float("nan")

    df = df[SENTIMENT_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for col in _SENTIMENT_NUMERIC:
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
    return DATA_DIR / f"sentiment_{trade_date}.parquet"


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
    return (time.time() - path.stat().st_mtime) < _SENTIMENT_TTL


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd
    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_cache({path.name})", e)
        return None


def _empty_df() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=SENTIMENT_COLUMNS)


def _filter_symbols(df: pd.DataFrame, symbols: list[str] | None) -> pd.DataFrame:
    if symbols is None:
        return df
    wanted = {str(s) for s in symbols}
    return df[df["symbol"].isin(wanted)].reset_index(drop=True)


# ── 公开 API ─────────────────────────────────────────────────────────

def fetch_sentiment(
    trade_date: str | None = None,
    symbols: list[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """拉单日涨跌停/连板情绪截面 · 单源直调 + 全市场缓存 + symbols 编排层过滤。

    稀疏事件型:limit_list_d 按 trade_date 一次拉当日涨跌停榜 (只有涨跌停票有行) ·
    parquet 缓存 · symbols 过滤读缓存后切子集 (不在榜的 symbol 切不到 → enrich None)。

    Args:
        trade_date: YYYYMMDD · None → 最近交易日
        symbols: 限定 6 位代码子集 · None = 全市场 · 过滤在编排层
        force: 跳缓存强制重拉

    Returns:
        DataFrame · 标准列 SENTIMENT_COLUMNS。无 token / 失败 / 当日无涨跌停 →
        空 DataFrame (列齐 · 0 行 · 不抛 · 调用方按行数判断)。
    """
    from kan.data.tushare import _fetch_tushare_sentiment

    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    ensure_dirs()
    cache = _cache_path(td)
    if not force and _cache_fresh(cache, td):
        cached = _load_cache(cache)
        if cached is not None:
            return _filter_symbols(cached, symbols)

    raw = _fetch_tushare_sentiment(td)
    if raw is None or raw.empty:
        return _empty_df()
    df = _normalize_sentiment(raw)
    atomic_write_parquet(df, cache)
    return _filter_symbols(df, symbols)


__all__ = ["SENTIMENT_COLUMNS", "fetch_sentiment"]

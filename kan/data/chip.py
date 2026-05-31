"""筹码 (获利盘/成本分布) 截面拉取编排 · cache + 公开 API (整合-2)。

仿 moneyflow.py 的截面缓存机制 (cache key = trade_date · parquet · 历史日永鲜 /
最新日 TTL) · 单源直调 _fetch_tushare_cyq (cyq_perf 仅 tushare 一源)。

截面 (trade_date) 维度 · 官方支持 trade_date 全市场拉 (单次上限 5000 条 · A股 ~5500
可能截断少数票 → 该票 None 降级)。若实测 cyq_perf 不支持截面 (需 ts_code) → 改逐股
(仿 fundamentals.py)· 见 PRD 整合-2。获利盘是客观计算值 (compliance §2/§7 · 裸值可出)。
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

# ── 筹码截面标准 schema ──────────────────────────────────────────────
# 出口必须经 _normalize_chip 归一化 · 新增列追加到 CHIP_OPTIONAL。
CHIP_REQUIRED = ["symbol"]
CHIP_OPTIONAL = [
    "trade_date",
    "winner_rate",   # 获利盘比例 (%)
    "cost_5pct",     # 5 分位成本 (低位筹码)
    "cost_50pct",    # 50 分位成本 (中位筹码)
    "cost_95pct",    # 95 分位成本 (高位筹码)
    "weight_avg",    # 加权平均成本
    "_source",
]
CHIP_COLUMNS = CHIP_REQUIRED + CHIP_OPTIONAL
_CHIP_NUMERIC = ["winner_rate", "cost_5pct", "cost_50pct", "cost_95pct", "weight_avg"]

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")

_CHIP_TTL = 6 * 3600
"""最新交易日截面 mtime TTL (同 moneyflow) · 历史交易日截面固定 · 永鲜。"""
_CHIP_SOURCE = "tushare_cyq"


# ── 归一化 ───────────────────────────────────────────────────────────

def _normalize_chip(df: pd.DataFrame, source: str = _CHIP_SOURCE) -> pd.DataFrame:
    """补缺列 + symbol 规范 + 数值清洗 + _source 标注 (仿 moneyflow._normalize_moneyflow)。

    截面无时序 · 不排序 · 按 symbol 去重 · 过滤非 6 位代码 (脏数据防御)。
    """
    import pandas as pd

    for col in CHIP_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")
    for col in CHIP_OPTIONAL:
        if col not in df.columns:
            df[col] = source if col == "_source" else float("nan")

    df = df[CHIP_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for col in _CHIP_NUMERIC:
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
    return DATA_DIR / f"chip_{trade_date}.parquet"


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
    return (time.time() - path.stat().st_mtime) < _CHIP_TTL


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd
    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_cache({path.name})", e)
        return None


def _empty_df() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=CHIP_COLUMNS)


def _filter_symbols(df: pd.DataFrame, symbols: list[str] | None) -> pd.DataFrame:
    if symbols is None:
        return df
    wanted = {str(s) for s in symbols}
    return df[df["symbol"].isin(wanted)].reset_index(drop=True)


# ── 公开 API ─────────────────────────────────────────────────────────

def fetch_chip(
    trade_date: str | None = None,
    symbols: list[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """拉单日筹码获利盘/成本分布截面 · 单源直调 + 全市场缓存 + symbols 编排层过滤。

    截面优势:cyq_perf 按 trade_date 一次拉全市场 (一次 HTTP) · parquet 缓存 ·
    symbols 过滤读缓存后切子集 (仿 moneyflow.fetch_moneyflow)。单次上限 5000 条 ·
    A股 ~5500 可能截断少数票 (该票切不到 → enrich None 降级)。

    Args:
        trade_date: YYYYMMDD · None → 最近交易日
        symbols: 限定 6 位代码子集 · None = 全市场 · 过滤在编排层
        force: 跳缓存强制重拉

    Returns:
        DataFrame · 标准列 CHIP_COLUMNS。无 token / 失败 → 空 DataFrame
        (列齐 · 0 行 · 不抛 · 调用方按行数判断)。
    """
    from kan.data.tushare import _fetch_tushare_cyq

    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    ensure_dirs()
    cache = _cache_path(td)
    if not force and _cache_fresh(cache, td):
        cached = _load_cache(cache)
        if cached is not None:
            return _filter_symbols(cached, symbols)

    raw = _fetch_tushare_cyq(td)
    if raw is None or raw.empty:
        return _empty_df()
    df = _normalize_chip(raw)
    atomic_write_parquet(df, cache)
    return _filter_symbols(df, symbols)


__all__ = ["CHIP_COLUMNS", "fetch_chip"]

"""截面市场指标拉取编排 · cache + chain (责任链) + 公开 API。

架构分层 (地基-1 起 · 类比 fetcher.py 之于 K 线):
- `kan.data.protocols.MetricsSource`         · Protocol (截面 adapter 契约)
- `kan.data.metrics.TushareMetricsSource`    · 内置截面源 (daily_basic)
- `kan.data.source_chain.MetricsSourceChain` · 责任链 (priority sort + race + 熔断)
- `kan.data._builtin_sources`                · 内置源工厂 + 用户注册表 (internal)
- `kan.data.metrics` (本文件)                · adapter + cache + chain 编排 + 公开 API

与 K 线 fetcher 的本质区别 (截面 vs 时序 · 代价不对称):
- K 线: 逐只拉历史 · cache key = symbol · 判鲜 = 最后一行 date ≥ latest_trade_date
- 截面: 按 trade_date 一次拉全市场 · cache key = trade_date · 判鲜 = 历史日永鲜 / 最新日 TTL

合规 (compliance §6/§7 · PRD §6):本层只承载原始指标值 (pe_ttm / pb / dv_ttm ...) ·
分位 / 行业中位对照在输出层 (地基-2/3 有全市场池后) 呈现 · 数据层不算不输出。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from kan.data.source_chain import default_metrics_chain
from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR, atomic_write_parquet, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

# ── 截面指标标准 schema ──────────────────────────────────────────────
# 所有指标源的出口必须经过 _normalize_metrics() 归一化到此格式。
# 新增指标列只需追加到 METRICS_OPTIONAL · 下游按列名读取 · 不受影响。

METRICS_REQUIRED = ["symbol"]
METRICS_OPTIONAL = [
    "trade_date", "close",
    "pe_ttm", "pb", "ps_ttm", "dv_ttm",          # 估值
    "turnover_rate", "volume_ratio",             # 量价
    "total_mv", "circ_mv",                       # 市值
    "_source",
]
METRICS_COLUMNS = METRICS_REQUIRED + METRICS_OPTIONAL

# 需数值清洗的列 (symbol / trade_date / _source 不进数值转换)
_METRICS_NUMERIC = [
    "close", "pe_ttm", "pb", "ps_ttm", "dv_ttm",
    "turnover_rate", "volume_ratio", "total_mv", "circ_mv",
]

# 6 位纯数字代码 · 8 位 YYYYMMDD · 防 path traversal / 脏数据
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")

_METRICS_TTL = 6 * 3600
"""最新交易日截面 mtime TTL · 盘后工具一天拉一次足够 · 跨收盘边界能刷新。

历史交易日截面固定 · 永鲜 · 不受此 TTL 约束 (见 _metrics_cache_fresh)。
"""

_TUSHARE_METRICS_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,volume_ratio,"
    "pe_ttm,pb,ps_ttm,dv_ttm,total_mv,circ_mv"
)
_TUSHARE_HISTORY_FIELDS = "trade_date,pe_ttm,pb,ps_ttm,dv_ttm"


# ── 归一化 ───────────────────────────────────────────────────────────

def _normalize_metrics(df: pd.DataFrame, source: str = "unknown") -> pd.DataFrame:
    """统一归一化:补缺失列 + symbol 规范 + 数值清洗 + _source 标注。所有指标源的出口。

    截面无时序 · 不排序 · 按 symbol 去重 (源偶发重复行取首条) ·
    过滤非 6 位代码 (截面接口偶发非标代码 · 脏数据防御)。

    source: 数据来源标记 (tushare_metrics / ...) · 写入 `_source` 列 · 来源可追溯。
    """
    import pandas as pd

    for col in METRICS_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")

    for col in METRICS_OPTIONAL:
        if col not in df.columns:
            df[col] = source if col == "_source" else float("nan")

    df = df[METRICS_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    # trade_date 统一为 date (tushare YYYYMMDD 字符串 → date · 无法解析置 NaT)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date

    bad_cols: list[tuple[str, int]] = []
    for col in _METRICS_NUMERIC:
        df[col], bad_count = to_numeric_checked(df[col])
        if bad_count:
            bad_cols.append((col, bad_count))
    if bad_cols:
        detail = ", ".join(f"{c}×{n}" for c, n in bad_cols)
        logging.getLogger(__name__).warning(
            "数据源 %s 截面指标含无法解析的数值 · 已置 NaN: %s", source, detail
        )
    df["_source"] = source

    df = df[df["symbol"].str.match(_SYMBOL_PATTERN, na=False)]
    df = df.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
    return df


# ── 通用工具 ─────────────────────────────────────────────────────────

def _validate_trade_date(trade_date: str) -> str:
    if not isinstance(trade_date, str) or not _TRADE_DATE_PATTERN.match(trade_date):
        raise ValueError(f"非法交易日: {trade_date!r} · 应为 8 位 YYYYMMDD")
    return trade_date


def _latest_trade_date_str() -> str:
    """最近交易日 → YYYYMMDD 字符串 (trade_date=None 时的默认截面日)。"""
    from kan.core.trading_calendar import latest_trade_date
    return latest_trade_date().strftime("%Y%m%d")


def _metrics_cache_path(trade_date: str) -> Path:
    trade_date = _validate_trade_date(trade_date)
    return DATA_DIR / f"metrics_{trade_date}.parquet"


def _metrics_cache_fresh(path: Path, trade_date: str) -> bool:
    """截面缓存判鲜 (按交易日语义)。

    历史交易日截面固定 → 文件存在即永鲜 · 不重复拉。
    最新交易日盘中会变 → mtime TTL 兜底 (_METRICS_TTL) · 跨收盘刷新。
    """
    if not path.exists():
        return False
    try:
        td = datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError:
        return False
    from kan.core.trading_calendar import latest_trade_date
    if td < latest_trade_date():
        return True  # 历史交易日截面不变 · 永鲜
    return (time.time() - path.stat().st_mtime) < _METRICS_TTL


def _load_metrics_cache(path: Path) -> pd.DataFrame | None:
    """读截面 parquet · 失败 (损坏 / schema 漂移) 返 None · caller 走重拉。"""
    import pandas as pd
    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_metrics_cache({path.name})", e)
        return None


def _empty_metrics_df() -> pd.DataFrame:
    """空截面 DataFrame (列齐 · 0 行) · 无 token / 全源失败时返回 · 不抛。"""
    import pandas as pd
    return pd.DataFrame(columns=METRICS_COLUMNS)


def _filter_symbols(df: pd.DataFrame, symbols: list[str] | None) -> pd.DataFrame:
    """symbols=None → 全市场;否则切子集 (编排层过滤 · 截面源拉全市场后在此筛)。"""
    if symbols is None:
        return df
    wanted = {str(s) for s in symbols}
    return df[df["symbol"].isin(wanted)].reset_index(drop=True)


def _to_tushare_metrics_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare daily_basic data block -> raw metrics DataFrame with `symbol`."""
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


def _fetch_tushare_metrics(
    trade_date: str, symbols: list[str] | None = None,
) -> pd.DataFrame | None:
    """TuShare daily_basic 单日截面 adapter · 独立熔断 key `tushare_metrics`."""
    del symbols  # daily_basic 截面一次拉全市场，过滤交给编排层。

    from kan.data.tushare import _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_metrics"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="daily_basic",
            params={"trade_date": trade_date},
            fields=_TUSHARE_METRICS_FIELDS,
        )
        if data is None:
            cb.record("tushare_metrics", ok=False)
            return None
        df = _to_tushare_metrics_df(data)
        if df is None or df.empty:
            cb.record("tushare_metrics", ok=False)
            return None
        cb.record("tushare_metrics", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare metrics 失败", e)
        cb.record("tushare_metrics", ok=False)
        return None


class TushareMetricsSource:
    """TuShare Pro 截面指标源 · priority=10 · 配 token 时顶档优先 · daily_basic."""

    name = "tushare_metrics"
    priority = 10

    def is_available(self) -> bool:
        from kan.data.tushare import _resolve_config
        from kan.infra import circuit_breaker

        token, _ = _resolve_config()
        if not token:
            return False
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(
        self, trade_date: str, symbols: list[str] | None = None,
    ) -> pd.DataFrame | None:
        return _fetch_tushare_metrics(trade_date, symbols)


# ── 公开 API ─────────────────────────────────────────────────────────

def fetch_metrics(
    trade_date: str | None = None,
    symbols: list[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """拉单日截面市场指标 · 走 default MetricsSourceChain · 全市场缓存 + symbols 编排层过滤。

    截面优势:daily_basic 按 trade_date 一次拉全市场 (一次 HTTP) · 全市场 parquet
    缓存 · symbols 过滤读缓存后切子集 · 一次拉全多次复用 (区别于 K 线逐只)。

    Args:
        trade_date: YYYYMMDD · None → 最近交易日 latest_trade_date()
        symbols: 限定 6 位代码子集 · None = 全市场 · 过滤在编排层 (源总拉全市场)
        force: 跳过缓存强制重拉

    Returns:
        DataFrame · 标准列 METRICS_COLUMNS (symbol + 各指标 + _source)。
        无 token / 全源失败 → 空 DataFrame (列齐 · 0 行) · 不抛
        (对齐"数据层不抛业务异常 · 无数据非异常" · 调用方按行数判断)。

    内置 priority (chain 内自动排序 · 见 protocols.py priority 约定):
    - 10  TushareMetricsSource · 配 token 时顶档 · daily_basic
    (地基-1 仅此一源 · PublicMetricsSource 降级源留后续阶段)
    """
    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    ensure_dirs()
    cache = _metrics_cache_path(td)

    if not force and _metrics_cache_fresh(cache, td):
        cached = _load_metrics_cache(cache)
        if cached is not None:
            return _filter_symbols(cached, symbols)

    result = default_metrics_chain().fetch(td)
    if result is None:
        # 无 token / 全源失败 · 返回空 schema DataFrame (不抛 · 截面"无数据非异常")
        return _empty_metrics_df()
    raw, source = result

    df = _normalize_metrics(raw, source=source)
    atomic_write_parquet(df, cache)
    return _filter_symbols(df, symbols)


# ── 估值历史时序 (地基-3) · 历史分位原料 (单股多日 · 与截面正交) ──────────

_HISTORY_COLUMNS = ["trade_date", "pe_ttm", "pb", "ps_ttm", "dv_ttm"]
_HISTORY_TTL = 20 * 3600
"""估值历史 cache TTL · ~每日刷新 (历史段固定 · 仅追加最新交易日)。"""
_DEFAULT_LOOKBACK_DAYS = 730  # 估值分位回看 ~2 年


def _history_cache_path(symbol: str) -> Path:
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"非法股票代码: {symbol!r}")
    return DATA_DIR / f"metrics_hist_{symbol}.parquet"


def _empty_history_df() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=_HISTORY_COLUMNS)


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    """归一化估值时序:补缺列 + trade_date → date + 数值清洗 + 去无效行。"""
    import pandas as pd

    for col in _HISTORY_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_HISTORY_COLUMNS].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for col in ("pe_ttm", "pb", "ps_ttm", "dv_ttm"):
        df[col], _bad = to_numeric_checked(df[col])
    return df.dropna(subset=["trade_date"]).reset_index(drop=True)


def _fetch_tushare_metrics_history(
    symbol: str,
    start_date: str,
) -> pd.DataFrame | None:
    """TuShare daily_basic 单股估值时序 adapter · 复用 `tushare_metrics` 熔断 key."""
    import pandas as pd

    from kan.data.tushare import _normalize_symbol_to_ts, _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_metrics"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="daily_basic",
            params={"ts_code": ts_code, "start_date": start_date},
            fields=_TUSHARE_HISTORY_FIELDS,
        )
        if data is None:
            cb.record("tushare_metrics", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_metrics", ok=False)
            return None
        cb.record("tushare_metrics", ok=True)
        return pd.DataFrame(items, columns=fields)
    except Exception as e:
        debug_log(__name__, "fetch tushare metrics history 失败", e)
        cb.record("tushare_metrics", ok=False)
        return None


def fetch_valuation_history(
    symbol: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    force: bool = False,
) -> pd.DataFrame:
    """单股估值时序 (pe_ttm/pb/ps_ttm/dv_ttm) · 估值历史分位原料 (地基-3)。

    走 tushare daily_basic (ts_code + start_date · 单股多日) · 单股 parquet 缓存。
    无 token / 失败 / 非法 symbol → 空 DataFrame (不抛 · 分位维度缺失即降级)。

    Args:
        symbol: 6 位代码
        lookback_days: 回看天数 (默认 ~2 年 · 分位样本)
        force: 跳缓存强制重拉
    """
    from datetime import timedelta

    from kan.core.trading_calendar import latest_trade_date
    if not _SYMBOL_PATTERN.match(symbol):
        return _empty_history_df()
    ensure_dirs()
    cache = _history_cache_path(symbol)
    if (
        not force
        and cache.exists()
        and (time.time() - cache.stat().st_mtime) < _HISTORY_TTL
    ):
        loaded = _load_metrics_cache(cache)
        if loaded is not None:
            return loaded

    start = (latest_trade_date() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    raw = _fetch_tushare_metrics_history(symbol, start)
    if raw is None or raw.empty:
        return _empty_history_df()
    df = _normalize_history(raw)
    atomic_write_parquet(df, cache)
    return df

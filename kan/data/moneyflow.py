"""主力资金截面拉取编排 · cache + 公开 API (估值/质量/资金维度)。

仿 metrics.py 的截面缓存机制 (cache key = trade_date · parquet · 历史日永鲜 /
最新日 TTL) · 但单源直调 _fetch_tushare_moneyflow (不走责任链:moneyflow 仅
tushare 一源 · 同 industry_map "单源暂不抽 chain" 约定 · 避免过度抽象)。

moneyflow 数据从 2010 起。主力净额是客观资金事实
(compliance §2 安全区 · 同 OHLCV · 裸值可出)。
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from kan.infra.log import debug_log
from kan.infra.numeric import to_numeric_checked
from kan.storage.paths import DATA_DIR, atomic_write_parquet, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

# ── 主力资金截面标准 schema ──────────────────────────────────────────
# 出口必须经 _normalize_moneyflow 归一化 · 新增列追加到 MONEYFLOW_OPTIONAL。
MONEYFLOW_REQUIRED = ["symbol"]
MONEYFLOW_OPTIONAL = [
    "trade_date",
    "net_amount",        # 主力净额 (单位万元)
    "buy_elg_amount",    # 超大单净额
    "buy_lg_amount",     # 大单净额
    "buy_md_amount",     # 中单净额
    "buy_sm_amount",     # 小单净额
    "inflow_days",       # 截至 trade_date 连续主力净流入天数
    "outflow_days",      # 截至 trade_date 连续主力净流出天数
    "net_amount_5d",     # 近 5 个交易日主力净额合计
    "_source",
]
MONEYFLOW_COLUMNS = MONEYFLOW_REQUIRED + MONEYFLOW_OPTIONAL
_MONEYFLOW_NUMERIC = [
    "net_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount",
    "inflow_days", "outflow_days", "net_amount_5d",
]

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")

_MONEYFLOW_TTL = 6 * 3600
"""最新交易日截面 mtime TTL (同 metrics) · 历史交易日截面固定 · 永鲜。"""
_MONEYFLOW_SOURCE = "tushare_moneyflow"
_TUSHARE_MONEYFLOW_FIELDS = (
    "ts_code,trade_date,"
    "buy_elg_amount,sell_elg_amount,"
    "buy_lg_amount,sell_lg_amount,"
    "buy_md_amount,sell_md_amount,"
    "buy_sm_amount,sell_sm_amount,"
    "net_mf_amount"
)
_MONEYFLOW_STREAK_LOOKBACK = 20


# ── 归一化 ───────────────────────────────────────────────────────────

def _normalize_moneyflow(df: pd.DataFrame, source: str = _MONEYFLOW_SOURCE) -> pd.DataFrame:
    """补缺列 + symbol 规范 + 数值清洗 + _source 标注 (仿 metrics._normalize_metrics)。

    截面无时序 · 不排序 · 按 symbol 去重 · 过滤非 6 位代码 (脏数据防御)。
    """
    import pandas as pd

    for col in MONEYFLOW_REQUIRED:
        if col not in df.columns:
            raise ValueError(f"数据缺少必需列: {col}")
    for col in MONEYFLOW_OPTIONAL:
        if col not in df.columns:
            df[col] = source if col == "_source" else float("nan")

    df = df[MONEYFLOW_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for col in _MONEYFLOW_NUMERIC:
        df[col], _bad = to_numeric_checked(df[col])
    df["_source"] = source

    df = df[df["symbol"].str.match(_SYMBOL_PATTERN, na=False)]
    df = df.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
    return df


# ── 通用工具 (仿 metrics) ────────────────────────────────────────────

def _validate_trade_date(trade_date: str) -> str:
    if not isinstance(trade_date, str) or not _TRADE_DATE_PATTERN.match(trade_date):
        raise ValueError(f"非法交易日: {trade_date!r} · 应为 8 位 YYYYMMDD")
    return trade_date


def _latest_trade_date_str() -> str:
    from kan.core.trading_calendar import latest_trade_date
    return latest_trade_date().strftime("%Y%m%d")


def _cache_path(trade_date: str) -> Path:
    trade_date = _validate_trade_date(trade_date)
    return DATA_DIR / f"moneyflow_{trade_date}.parquet"


def _cache_fresh(path: Path, trade_date: str) -> bool:
    """截面缓存判鲜:历史交易日永鲜 · 最新交易日 mtime TTL (同 metrics)。"""
    if not path.exists():
        return False
    try:
        td = datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError:
        return False
    from kan.core.trading_calendar import latest_trade_date
    if td < latest_trade_date():
        return True
    return (time.time() - path.stat().st_mtime) < _MONEYFLOW_TTL


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd
    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_cache({path.name})", e)
        return None


def _load_latest_available_moneyflow(before_td: str) -> pd.DataFrame | None:
    """latest 截面拉空时 · 降级到 DATA_DIR 里早于 before_td 的最近资金流截面缓存。"""
    best_date: str | None = None
    best_path: Path | None = None
    for path in DATA_DIR.glob("moneyflow_*.parquet"):
        m = re.match(r"^moneyflow_(\d{8})\.parquet$", path.name)
        if not m:
            continue
        d = m.group(1)
        if d < before_td and (best_date is None or d > best_date):
            best_date, best_path = d, path
    if best_path is None:
        return None
    df = _load_cache(best_path)
    if df is None or df.empty:
        return None
    return _normalize_moneyflow(df)


def _empty_df() -> pd.DataFrame:
    import pandas as pd
    return pd.DataFrame(columns=MONEYFLOW_COLUMNS)


def _filter_symbols(df: pd.DataFrame, symbols: list[str] | None) -> pd.DataFrame:
    if symbols is None:
        return df
    wanted = {str(s) for s in symbols}
    return df[df["symbol"].isin(wanted)].reset_index(drop=True)


def _to_tushare_moneyflow_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare moneyflow data block -> raw DataFrame with `symbol` and normalized net columns."""
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
    if "net_mf_amount" in df.columns and "net_amount" not in df.columns:
        df["net_amount"] = df["net_mf_amount"]
    for prefix in ("elg", "lg", "md", "sm"):
        buy_col = f"buy_{prefix}_amount"
        sell_col = f"sell_{prefix}_amount"
        if buy_col in df.columns and sell_col in df.columns:
            buy = pd.to_numeric(df[buy_col], errors="coerce")
            sell = pd.to_numeric(df[sell_col], errors="coerce")
            df[buy_col] = buy - sell
    return df.drop(columns=["ts_code"])


def _fetch_tushare_moneyflow(trade_date: str) -> pd.DataFrame | None:
    """TuShare moneyflow 单日截面 adapter · 独立熔断 key `tushare_moneyflow`."""
    from kan.data.tushare import _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_moneyflow"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="moneyflow",
            params={"trade_date": trade_date},
            fields=_TUSHARE_MONEYFLOW_FIELDS,
        )
        if data is None:
            cb.record("tushare_moneyflow", ok=False)
            return None
        df = _to_tushare_moneyflow_df(data)
        if df is None or df.empty:
            # API 成功响应但 items 空 = 当日数据未出 / 瞬时空 · 不熔断健康源。
            return None
        cb.record("tushare_moneyflow", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare moneyflow 失败", e)
        cb.record("tushare_moneyflow", ok=False)
        return None


def _load_or_fetch_moneyflow_frame(
    trade_date: str,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """Load one exact trade_date frame from cache/API without historical fallback or rolling stats."""
    ensure_dirs()
    cache = _cache_path(trade_date)
    if not force and _cache_fresh(cache, trade_date):
        cached = _load_cache(cache)
        if cached is not None:
            return _normalize_moneyflow(cached)

    raw = _fetch_tushare_moneyflow(trade_date)
    if raw is None or raw.empty:
        return _empty_df()
    df = _normalize_moneyflow(raw)
    atomic_write_parquet(df, cache)
    return df


def _max_trade_date(df: pd.DataFrame, fallback_td: str) -> date:
    import pandas as pd

    vals = [d for d in df.get("trade_date", []) if d is not None and not pd.isna(d)]
    if vals:
        return max(vals)
    return datetime.strptime(fallback_td, "%Y%m%d").date()


def _recent_trade_dates(end_date: date, count: int) -> list[date]:
    """取 <= end_date 的最近 count 个交易日 · calendar 不可用时退化 weekday。"""
    from datetime import timedelta

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


def _attach_recent_flow_stats(
    df: pd.DataFrame,
    *,
    end_date: date,
    fetch_missing_history: bool,
) -> pd.DataFrame:
    """Attach net_amount_5d / inflow_days / outflow_days to the returned cross-section."""
    import pandas as pd

    if df.empty:
        return df
    symbols = set(df["symbol"].astype(str))
    frames: list[pd.DataFrame] = []
    for d in _recent_trade_dates(end_date, _MONEYFLOW_STREAK_LOOKBACK):
        if d == end_date:
            frame = df
        elif fetch_missing_history:
            frame = _load_or_fetch_moneyflow_frame(d.strftime("%Y%m%d"))
        else:
            cached = _load_cache(_cache_path(d.strftime("%Y%m%d")))
            frame = cached if cached is not None else _empty_df()
        if frame.empty:
            continue
        frame = frame[frame["symbol"].isin(symbols)]
        if not frame.empty:
            frames.append(frame[["symbol", "trade_date", "net_amount"]].copy())
    if not frames:
        return df

    hist = pd.concat(frames, ignore_index=True)
    hist = hist.dropna(subset=["trade_date"])
    hist["net_amount"], _bad = to_numeric_checked(hist["net_amount"])
    hist = hist.dropna(subset=["net_amount"])
    if hist.empty:
        return df

    stats: dict[str, dict[str, float | int]] = {}
    for symbol, group in hist.sort_values("trade_date").groupby("symbol", sort=False):
        nets = [float(x) for x in group["net_amount"].tolist()]
        dates = list(group["trade_date"])
        if not nets:
            continue
        last5 = [net for d, net in zip(dates, nets, strict=False) if d <= end_date][-5:]
        inflow = 0
        outflow = 0
        direction = 0
        for net in reversed(nets):
            if net == 0:
                break
            sign = 1 if net > 0 else -1
            if direction == 0:
                direction = sign
            if sign != direction:
                break
            if sign > 0:
                inflow += 1
            else:
                outflow += 1
        stats[str(symbol)] = {
            "net_amount_5d": round(sum(last5), 2) if last5 else 0.0,
            "inflow_days": inflow,
            "outflow_days": outflow,
        }

    out = df.copy()
    for col in ("net_amount_5d", "inflow_days", "outflow_days"):
        out[col] = out["symbol"].map(lambda s, c=col: stats.get(str(s), {}).get(c))
    return out


# ── 公开 API ─────────────────────────────────────────────────────────

def fetch_moneyflow(
    trade_date: str | None = None,
    symbols: list[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """拉单日主力资金截面 · 单源直调 + 全市场缓存 + symbols 编排层过滤。

    截面优势:moneyflow_dc 按 trade_date 一次拉全市场 (一次 HTTP) · parquet 缓存 ·
    symbols 过滤读缓存后切子集 (仿 metrics.fetch_metrics)。

    Args:
        trade_date: YYYYMMDD · None → 最近交易日
        symbols: 限定 6 位代码子集 · None = 全市场 · 过滤在编排层
        force: 跳缓存强制重拉

    Returns:
        DataFrame · 标准列 MONEYFLOW_COLUMNS。无 token / 失败 / 早期无数据
        (< 20230911) → 空 DataFrame (列齐 · 0 行 · 不抛 · 调用方按行数判断)。
    """
    td = _validate_trade_date(trade_date or _latest_trade_date_str())
    ensure_dirs()
    df = _load_or_fetch_moneyflow_frame(td, force=force)
    if df.empty:
        fallback = _load_latest_available_moneyflow(before_td=td)
        if fallback is None:
            return _empty_df()
        df = fallback
    end_date = _max_trade_date(df, td)
    df = _attach_recent_flow_stats(
        df,
        end_date=end_date,
        fetch_missing_history=symbols is not None,
    )
    return _filter_symbols(df, symbols)


__all__ = ["MONEYFLOW_COLUMNS", "fetch_moneyflow"]

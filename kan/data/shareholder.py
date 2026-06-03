"""股东·持股结构 (户数环比 / 十大流通集中度 / 北向中央结算代理) 逐股拉取编排 (整合-3)。

仿 fundamentals.py 的逐股缓存 (每股一 parquet · 存衍生单行 · TTL 90d) · 单源直调两个
tushare adapter (stk_holdernumber + top10_floatholders) 合成衍生指标 · 与整合-2 的截面
缓存 (chip/technical 按 trade_date 一次拉全市场) 本质不同。

逐股 (ts_code) 维度:stk_holdernumber 不定期季度披露 · top10_floatholders 必须 ts_code
(无截面全市场拉法 · 同 fundamentals · 全市场 --all 不支持 · PRD §3.2)。三维均季度级 ·
None = 该期无披露 / 未进前十 (非故障 · 仿 sentiment None 语义)。

北向:hk_hold 日频明细 2024-08 断供 (tushare 实测核实) → 用 top10_floatholders 里"香港
中央结算有限公司"季度名义持有人占流通比作代理 (复用 top10 一次拉取 · 零额外数据源) ·
未进前十大流通 → north_hold_ratio None。

衍生计算 (compliance §7 整合-3 守则):户数环比 / 前十大集中度 / 北向占比均为已披露客观
事实的算术衍生 · 裸值可出 · 不输出"主力建仓 / 洗盘 / 控盘 / 高度控盘"等判断词。
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

# ── 股东·持股结构衍生 schema (每股缓存单行) ──────────────────────────────
SHAREHOLDER_COLUMNS = [
    "symbol",
    "holder_end_date",    # 户数最近报告期 (季度披露)
    "holder_num",         # 最近期股东户数
    "holder_chg_pct",     # 户数环比 % (最近相邻两次披露 · 负=户数减少)
    "top10_end_date",     # 十大流通最近报告期
    "top10_float_ratio",  # 前十大流通股东持股合计占流通比 %
    "north_hold_ratio",   # 香港中央结算占流通比 % (北向季度代理 · 未进前十=NaN)
    "_source",
]
_SH_NUMERIC = ["holder_num", "holder_chg_pct", "top10_float_ratio", "north_hold_ratio"]
_SH_DATE = ["holder_end_date", "top10_end_date"]

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")

_NORTH_NOMINEE = "香港中央结算"
"""北向名义持有人 (子串匹配 · 防全称 / 空格差异 · 不误匹配"中国证券登记结算")。"""

_SH_TTL = 90 * 24 * 3600
"""季度披露 · 90d 长缓存 (逐股 HTTP 贵 · 同 fundamentals · 季报季度更新)。"""
_SH_SOURCE = "tushare_shareholder"
_HOLDERNUM_FIELDS = "ann_date,end_date,holder_num"
_TOP10FLOAT_FIELDS = "end_date,holder_name,hold_ratio"


def _cache_path(symbol: str) -> Path:
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"非法股票代码: {symbol!r}")
    return DATA_DIR / f"shareholder_{symbol}.parquet"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """补缺列 + 日期列 → date + 数值清洗 + _source 标注 (仿 fundamentals._normalize)。

    单行衍生 df 统一类型 (date32 + float) · 利于 parquet 往返与 enrich 层一致消费。
    """
    import pandas as pd

    for col in SHAREHOLDER_COLUMNS:
        if col not in df.columns:
            df[col] = _SH_SOURCE if col == "_source" else float("nan")
    df = df[SHAREHOLDER_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    for dcol in _SH_DATE:
        df[dcol] = pd.to_datetime(df[dcol], errors="coerce").dt.date
    for col in _SH_NUMERIC:
        df[col], _bad = to_numeric_checked(df[col])
    df["_source"] = _SH_SOURCE
    return df


def _load_cache(path: Path) -> pd.DataFrame | None:
    import pandas as pd

    try:
        return pd.read_parquet(path)
    except Exception as e:
        debug_log(__name__, f"_load_cache({path.name})", e)
        return None


def _fetch_tushare_holdernumber(symbol: str) -> pd.DataFrame | None:
    """TuShare stk_holdernumber 单股股东户数 adapter · 独立熔断 key `tushare_holdernum`."""
    from kan.data.tushare import _normalize_symbol_to_ts, _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_holdernum"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="stk_holdernumber",
            params={"ts_code": ts_code},
            fields=_HOLDERNUM_FIELDS,
        )
        if data is None:
            cb.record("tushare_holdernum", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_holdernum", ok=False)
            return None
        cb.record("tushare_holdernum", ok=True)
        import pandas as pd
        return pd.DataFrame(items, columns=fields)
    except Exception as e:
        debug_log(__name__, "fetch tushare holdernumber 失败", e)
        cb.record("tushare_holdernum", ok=False)
        return None


def _fetch_tushare_top10float(symbol: str) -> pd.DataFrame | None:
    """TuShare top10_floatholders 单股十大流通股东 adapter · 独立熔断 key."""
    from kan.data.tushare import _normalize_symbol_to_ts, _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_top10float"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="top10_floatholders",
            params={"ts_code": ts_code},
            fields=_TOP10FLOAT_FIELDS,
        )
        if data is None:
            cb.record("tushare_top10float", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_top10float", ok=False)
            return None
        cb.record("tushare_top10float", ok=True)
        import pandas as pd
        return pd.DataFrame(items, columns=fields)
    except Exception as e:
        debug_log(__name__, "fetch tushare top10float 失败", e)
        cb.record("tushare_top10float", ok=False)
        return None


# ── 衍生计算 (两源 → 单行指标) ────────────────────────────────────────────

def _derive_holders(
    raw: pd.DataFrame | None,
) -> tuple[object | None, float | None, float | None]:
    """stk_holdernumber 多期 → (最近报告期, 最近期户数, 户数环比%)。

    去重陷阱:同一 end_date 可能多 ann_date (预约 + 正式披露 · holder_num 相同) ·
    必须按 end_date 去重再取相邻两期 · 否则"最近两期"会撞同一报告期 (环比恒 0)。
    环比 = (最近期 - 上一期) / 上一期 × 100 · 不足两期 / 上期为 0 → None。
    """
    import pandas as pd

    if raw is None or raw.empty:
        return (None, None, None)
    df = raw.copy()
    if "end_date" not in df.columns or "holder_num" not in df.columns:
        return (None, None, None)
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    df["holder_num"], _bad = to_numeric_checked(df["holder_num"])
    df = df.dropna(subset=["end_date", "holder_num"])
    if df.empty:
        return (None, None, None)
    # 同 end_date 去重 (预约 + 正式值同) → 每报告期保留一行 → 报告期降序
    df = df.sort_values("end_date").drop_duplicates(subset=["end_date"], keep="last")
    df = df.sort_values("end_date", ascending=False).reset_index(drop=True)

    latest_end = df.loc[0, "end_date"].date()
    latest_num = float(df.loc[0, "holder_num"])
    chg_pct: float | None = None
    if len(df) >= 2:
        prev_num = float(df.loc[1, "holder_num"])
        if prev_num != 0:
            chg_pct = (latest_num - prev_num) / prev_num * 100.0
    return (latest_end, latest_num, chg_pct)


def _derive_top10(
    raw: pd.DataFrame | None,
) -> tuple[object | None, float | None, float | None]:
    """top10_floatholders 多期×10 → (最近报告期, 前十大集中度%, 北向中央结算占比%)。

    取最新 end_date 那组 (≤10 行) · 集中度 = 组内 hold_ratio 求和 (全 NaN → None) ·
    北向 = 组内"香港中央结算"行的 hold_ratio (未进前十 → None · 季度名义持有人代理)。
    """
    import pandas as pd

    if raw is None or raw.empty:
        return (None, None, None)
    df = raw.copy()
    if "end_date" not in df.columns or "hold_ratio" not in df.columns:
        return (None, None, None)
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    df["hold_ratio"], _bad = to_numeric_checked(df["hold_ratio"])
    df = df.dropna(subset=["end_date"])
    if df.empty:
        return (None, None, None)

    latest_end = df["end_date"].max()
    grp = df[df["end_date"] == latest_end]

    valid = grp["hold_ratio"].dropna()
    top10_ratio = float(valid.sum()) if not valid.empty else None

    north: float | None = None
    if "holder_name" in grp.columns:
        mask = grp["holder_name"].astype(str).str.contains(_NORTH_NOMINEE, na=False)
        nrows = grp[mask]
        if not nrows.empty:
            nv = nrows["hold_ratio"].iloc[0]
            north = float(nv) if pd.notna(nv) else None
    return (latest_end.date(), top10_ratio, north)


# ── 逐股拉取 + 缓存 ────────────────────────────────────────────────────────

def _fetch_one(symbol: str, force: bool = False) -> pd.Series | None:
    """单股股东·持股结构衍生 · 逐股 parquet 缓存 · 两源任一有数据即缓存 (优雅降级)。

    两源 (stk_holdernumber + top10_floatholders) 均失败 / 无披露 → None (不缓存 ·
    同 fundamentals 失败不落盘 · caller .get(symbol) → None)。
    """
    import pandas as pd

    if not _SYMBOL_PATTERN.match(symbol):
        return None
    ensure_dirs()
    cache = _cache_path(symbol)
    if (
        not force
        and cache.exists()
        and (time.time() - cache.stat().st_mtime) < _SH_TTL
    ):
        loaded = _load_cache(cache)
        if loaded is not None and not loaded.empty:
            return loaded.iloc[0]

    h_end, h_num, h_chg = _derive_holders(_fetch_tushare_holdernumber(symbol))
    t_end, t_ratio, north = _derive_top10(_fetch_tushare_top10float(symbol))

    # 两源都无 → 不缓存 (优雅降级 · 区别于"已拉取但该期无字段")
    if h_end is None and t_end is None:
        return None

    raw = pd.DataFrame(
        [{
            "symbol": symbol,
            "holder_end_date": h_end,
            "holder_num": h_num,
            "holder_chg_pct": h_chg,
            "top10_end_date": t_end,
            "top10_float_ratio": t_ratio,
            "north_hold_ratio": north,
            "_source": _SH_SOURCE,
        }],
        columns=SHAREHOLDER_COLUMNS,
    )
    df = _normalize(raw)
    atomic_write_parquet(df, cache)
    return df.iloc[0]


def fetch_shareholder(
    symbols: list[str], force: bool = False,
) -> dict[str, pd.Series]:
    """逐股拉股东·持股结构 · 返回 {symbol: 衍生单行 Series} (整合-3)。

    逐股 HTTP (全市场代价高 · 只在小池 / K 线池按需调 · find --holders/--top10/--north ·
    全市场 --all 不支持) · 每股 90d parquet 缓存。无 token / 失败 / 无披露 → 该股不入
    dict (caller .get(symbol) → None · 优雅降级)。

    Args:
        symbols: 6 位代码列表
        force: 跳缓存强制重拉

    Returns:
        {symbol: pd.Series (SHAREHOLDER_COLUMNS)} · 仅含有数据的股。
        空 symbols → 空 dict (不触网)。
    """
    out: dict[str, pd.Series] = {}
    for symbol in symbols:
        row = _fetch_one(str(symbol), force=force)
        if row is not None:
            out[str(symbol)] = row
    return out


__all__ = ["SHAREHOLDER_COLUMNS", "fetch_shareholder"]

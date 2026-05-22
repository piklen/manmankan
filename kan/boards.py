"""申万行业板块数据子系统 · catalog / 模糊搜索 / 成分股 / 板块指数 K 线。

数据源:申万(akshare)单源。同花顺无成分股接口、东财被反爬封 —— 不建假 fallback,
申万失败直接抛 BoardDataUnavailableError。
冷启动规则:akshare / pandas 一律函数内延迟 import。
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from kan.models import Board
from kan.paths import BOARDS_DIR, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

_CATALOG_TTL = 24 * 3600  # 24h
_CONS_TTL = 24 * 3600

_SW_LEVEL_FUNCS = {
    1: "sw_index_first_info",
    2: "sw_index_second_info",
    3: "sw_index_third_info",
}


class BoardNotFoundError(Exception):
    """search_industry 未命中任何行业。"""


class BoardDataUnavailableError(Exception):
    """申万数据源不可用(网络/接口失败/空数据)。"""


def _cache_fresh(path, ttl: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


# ── catalog + 搜索 ────────────────────────────────────────────────────

def load_industry_catalog(force: bool = False) -> list[Board]:
    """申万一(31)+二(131)+三(336)级合并清单 · JSON cache 24h TTL。"""
    ensure_dirs()
    cache = BOARDS_DIR / "catalog_sw.json"
    if not force and _cache_fresh(cache, _CATALOG_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Board(**b) for b in data]
        except Exception:
            pass  # cache 损坏 → 重新拉
    boards_list = _fetch_catalog()
    cache.write_text(
        json.dumps([b.model_dump() for b in boards_list], ensure_ascii=False),
        encoding="utf-8",
    )
    return boards_list


def _fetch_catalog() -> list[Board]:
    import akshare as ak

    boards_list: list[Board] = []
    for level, fn_name in _SW_LEVEL_FUNCS.items():
        try:
            df = getattr(ak, fn_name)()
        except Exception:
            continue  # 单级失败不致命 · 用其它级
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            raw_code = str(row["行业代码"])
            boards_list.append(Board(
                code=raw_code.split(".")[0],
                name=str(row["行业名称"]).strip(),
                level=level,
                size=int(row["成份个数"]),
            ))
    if not boards_list:
        raise BoardDataUnavailableError("申万行业 catalog 三级全部拉取失败")
    return boards_list


def search_industry(query: str) -> Board:
    """模糊匹配行业名或代码 → Board。未命中抛 BoardNotFoundError。

    优先级:精确代码 > 精确名 > 含匹配(二级 > 一级 > 三级)。
    """
    q = query.strip()
    catalog = load_industry_catalog()
    code_q = q.split(".")[0]
    for b in catalog:
        if b.code == code_q:
            return b
    for b in catalog:
        if b.name == q:
            return b
    for lvl in (2, 1, 3):
        for b in catalog:
            if b.level == lvl and q in b.name:
                return b
    raise BoardNotFoundError(query)


# ── 成分股 ────────────────────────────────────────────────────────────

def get_industry_constituents(
    board: Board, force: bool = False,
) -> list[tuple[str, str]]:
    """行业成分股 (代码, 名称) 列表 · JSON cache 24h TTL。

    akshare: index_component_sw(symbol=board.code) → 证券代码 / 证券名称。
    """
    ensure_dirs()
    cache = BOARDS_DIR / f"cons_{board.code}.json"
    if not force and _cache_fresh(cache, _CONS_TTL):
        try:
            return [
                (str(c), str(n))
                for c, n in json.loads(cache.read_text(encoding="utf-8"))
            ]
        except Exception:
            pass
    import akshare as ak

    try:
        df = ak.index_component_sw(symbol=board.code)
    except Exception as e:
        raise BoardDataUnavailableError(f"申万成分股拉取失败 {board.code}: {e}") from e
    if df is None or df.empty:
        raise BoardDataUnavailableError(f"申万成分股为空: {board.code}")
    pairs = [
        (str(row["证券代码"]).strip(), str(row["证券名称"]).strip())
        for _, row in df.iterrows()
    ]
    cache.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
    return pairs


# ── 板块指数 K 线 ─────────────────────────────────────────────────────

_SW_KLINE_RENAME = {
    "日期": "date", "开盘": "open", "最高": "high",
    "最低": "low", "收盘": "close", "成交量": "volume", "成交额": "amount",
}
_KLINE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _kline_cache_fresh(path) -> bool:
    """板块 K 线 cache 是否含最近交易日(复用个股的 freshness 判据)。"""
    if not path.exists():
        return False
    try:
        import pandas as pd

        last = pd.read_parquet(path, columns=["date"])["date"].iloc[-1]
        last_d = last if hasattr(last, "isoformat") else pd.Timestamp(last).date()
        from kan.trading_calendar import latest_trade_date

        return last_d >= latest_trade_date()
    except Exception:
        return False


def fetch_industry_kline(board: Board, force: bool = False) -> pd.DataFrame:
    """板块指数 K 线 · 归一化到与个股 K 线同 schema · parquet cache。

    akshare: index_hist_sw(symbol=board.code, period="day")。
    """
    import pandas as pd

    from kan.paths import atomic_write_parquet

    ensure_dirs()
    cache = BOARDS_DIR / f"kline_{board.code}.parquet"
    if not force and _kline_cache_fresh(cache):
        return pd.read_parquet(cache)
    import akshare as ak

    try:
        raw = ak.index_hist_sw(symbol=board.code, period="day")
    except Exception as e:
        raise BoardDataUnavailableError(f"申万指数K线拉取失败 {board.code}: {e}") from e
    if raw is None or raw.empty:
        raise BoardDataUnavailableError(f"申万指数K线为空: {board.code}")
    df = raw.rename(columns=_SW_KLINE_RENAME)
    for col in _KLINE_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_KLINE_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = (
        df.sort_values("date")
        .dropna(subset=["date", "close"])
        .reset_index(drop=True)
    )
    atomic_write_parquet(df, cache)
    return df

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

    from kan.models import Theme

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


class ThemeNotFoundError(Exception):
    """search_theme 未命中任何题材。"""


class ThemeDataUnavailableError(Exception):
    """adata THS+EM 题材数据全挂(双源都失败才抛)。"""


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

# ══════════════════════════════════════════════════════════════════
# 题材(theme)数据子系统 · ***REMOVED*** · 见 docs/design-f11-theme-scan.md §5
# ══════════════════════════════════════════════════════════════════

_THEME_CATALOG_TTL = 24 * 3600
_THEME_CONS_TTL = 24 * 3600
_STOCK_THEMES_TTL = 12 * 3600  # 个股反查 TTL 更短(公司频繁变题材归属)


def _load_themes_from_cache(cache) -> list[Theme] | None:
    """题材 catalog 陈旧 cache 退化读取 · 失败返回 None(由调用方决定 raise 还是 raise from)。"""
    from kan.models import Theme

    if not cache.exists():
        return None
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        return [Theme(**t) for t in data]
    except Exception:
        return None


def load_theme_catalog(force: bool = False) -> list[Theme]:
    """adata THS 题材 catalog · 24h JSON cache · 失败退化到陈旧 cache。

    返回 list[Theme] · 391 个题材左右(2026-05-23 spike 实测)。
    """
    from kan.models import Theme

    ensure_dirs()
    cache = BOARDS_DIR / "catalog_concept_ths.json"
    if not force and _cache_fresh(cache, _THEME_CATALOG_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Theme(**t) for t in data]
        except Exception:
            pass

    import adata

    try:
        df = adata.stock.info.all_concept_code_ths()
    except Exception as e:
        # 失败时退化到陈旧 cache(若存在),否则抛
        stale = _load_themes_from_cache(cache)
        if stale is not None:
            from kan._log import debug_log

            debug_log(__name__, "load adata THS catalog", e)
            return stale
        raise ThemeDataUnavailableError(f"题材清单首次拉取失败: {e}") from e

    if df is None or df.empty:
        stale = _load_themes_from_cache(cache)
        if stale is not None:
            return stale
        raise ThemeDataUnavailableError("adata THS catalog 返回空数据")

    themes = [
        Theme(
            code=str(row["index_code"]).strip(),
            name=str(row["name"]).strip(),
            source="ths",
            size=None,
        )
        for _, row in df.iterrows()
    ]
    cache.write_text(
        json.dumps([t.model_dump() for t in themes], ensure_ascii=False),
        encoding="utf-8",
    )
    return themes


def normalize_theme_name(name: str) -> str:
    """规范化题材名 · 去全角半角空格 · alias 表后续累积。

    THS 'AI应用' / 'AI 应用' / 'AI　应用' → 'AI应用'。
    EM 'AI应用' / THS 'AI应用' → 同字串(本期不做跨源 alias)。
    """
    return name.replace(" ", "").replace("　", "").strip()


def search_theme(query: str) -> Theme:
    """模糊匹配题材名或代码 → Theme · 未命中抛 ThemeNotFoundError。

    优先级:精确代码 > 精确名(normalize) > 含匹配(normalize)。
    """
    q = query.strip()
    q_norm = normalize_theme_name(q)
    catalog = load_theme_catalog()
    for t in catalog:
        if t.code == q:
            return t
    for t in catalog:
        if normalize_theme_name(t.name) == q_norm:
            return t
    for t in catalog:
        if q_norm in normalize_theme_name(t.name):
            return t
    raise ThemeNotFoundError(query)


def get_theme_constituents(theme, force: bool = False) -> list[tuple[str, str]]:
    """题材成分股 (代码, 名称) 列表 · THS 优先 → EM fallback(走 ***REMOVED***) · JSON cache 24h。

    THS adata.stock.info.concept_constituent_ths(index_code=) · 走 THS HTTP · 稳定。
    EM  adata.stock.info.concept_constituent_east(concept_code=) · 走 push2 · 反爬触发熔断。

    熔断器 source id `em_push2_concept` · 5min cooldown(沿 T6 LOCKED 默认 TTL)。
    """
    from kan._log import debug_log
    from kan.circuit_breaker import get_breaker

    ensure_dirs()
    src_prefix = "THS" if theme.source == "ths" else "EM"
    cache = BOARDS_DIR / f"cons_{src_prefix}{theme.code}.json"

    if not force and _cache_fresh(cache, _THEME_CONS_TTL):
        try:
            return [
                (str(c), str(n))
                for c, n in json.loads(cache.read_text(encoding="utf-8"))
            ]
        except Exception:
            pass

    import adata

    breaker = get_breaker()

    # 1. THS 优先
    try:
        df = adata.stock.info.concept_constituent_ths(index_code=theme.code)
        if df is not None and not df.empty:
            pairs = [
                (str(row["stock_code"]).strip(), str(row["short_name"]).strip())
                for _, row in df.iterrows()
            ]
            cache.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
            return pairs
    except Exception as e:
        debug_log(__name__, f"THS concept_constituent_ths({theme.code})", e)

    # 2. EM fallback · 先检查熔断
    if breaker.is_down("em_push2_concept"):
        raise ThemeDataUnavailableError(
            f"题材成分股 {theme.code} 不可用 · THS 失败 · EM push2 在 5min 熔断冷却中"
        )

    try:
        df = adata.stock.info.concept_constituent_east(concept_code=theme.code)
        if df is None or df.empty:
            breaker.record("em_push2_concept", ok=False)
            raise ThemeDataUnavailableError(
                f"题材成分股 {theme.code} 不可用 · EM 返回空"
            )
        pairs = [
            (str(row["stock_code"]).strip(), str(row["short_name"]).strip())
            for _, row in df.iterrows()
        ]
        cache.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
        breaker.record("em_push2_concept", ok=True)
        return pairs
    except ThemeDataUnavailableError:
        raise
    except Exception as e:
        breaker.record("em_push2_concept", ok=False)
        raise ThemeDataUnavailableError(
            f"题材成分股 {theme.code} 不可用 · THS+EM 双源失败: {e}"
        ) from e

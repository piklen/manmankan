"""全市场股票列表 (全市场截面层 · AllStocksSet 截面池原料)。

tushare stock_basic 一次拉全市场上市股 → [(symbol, name)] · 24h JSON cache。
保留主板 / 创业板 / 科创板 / 含 ST · **排北交所** · 含 ST 是有意:排不排交给
用户 `--exclude-st` 决定。

排北交所用 `market == "北交所"` 过滤 (不用代码段正则):北交所现主力 920xxx 段 ·
tushare 旧式 83/43/87/82 代码推断会漏 (代码段会变 · market 字段稳)。

无 token / 失败 → 退化陈旧 cache · 仍无则空 list (优雅降级 · caller 按空判断报错)。

单源领域 (tushare stock_basic) · 暂不抽 chain (复刻 industry_map 单源约定) ·
后续可加 akshare 降级源 (同形 metrics chain)。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from kan.infra.log import debug_log
from kan.storage.paths import DATA_DIR, atomic_write_json, ensure_dirs

_ALL_STOCKS_TTL = 24 * 3600
_ALL_STOCKS_CACHE = "all_stocks.json"
_BSE_MARKET = "北交所"
"""排除的 market 字段值 · tushare stock_basic 北交所统一此值 (920xxx 段 · 真数据已验)。"""


def _cache_fresh(path: Path, ttl: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


def _load_cache(path: Path) -> list[tuple[str, str]] | None:
    """读 cache · JSON [[code, name], ...] → [(code, name)] · 损坏返 None。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        out: list[tuple[str, str]] = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                out.append((str(item[0]), str(item[1])))
        return out
    except Exception as e:
        debug_log(__name__, f"all_stocks cache {path.name} 损坏", e)
        return None


def _fetch_tushare_stock_basic_all():
    """TuShare stock_basic 全市场上市股 adapter · 独立熔断 key `tushare_basic`."""
    import pandas as pd

    from kan.data.tushare import _post_tushare_api, _resolve_config
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_basic"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="stock_basic",
            params={"list_status": "L"},
            fields="ts_code,symbol,name,market,list_status",
        )
        if data is None:
            cb.record("tushare_basic", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_basic", ok=False)
            return None
        df = pd.DataFrame(items, columns=fields)
        if "symbol" not in df.columns or "market" not in df.columns:
            cb.record("tushare_basic", ok=False)
            return None
        cb.record("tushare_basic", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare stock_basic 失败", e)
        cb.record("tushare_basic", ok=False)
        return None


def fetch_all_stocks(force: bool = False) -> list[tuple[str, str]]:
    """全市场 [(symbol, name)] · 主板+创业板+科创板+含 ST · 排北交所 · 24h JSON cache。

    无 token / 全失败 → 退化陈旧 cache · 仍无返空 list (调用方按空判断降级)。
    """
    ensure_dirs()
    cache = DATA_DIR / _ALL_STOCKS_CACHE
    if not force and _cache_fresh(cache, _ALL_STOCKS_TTL):
        cached = _load_cache(cache)
        if cached is not None:
            return cached

    df = _fetch_tushare_stock_basic_all()
    if df is None or df.empty:
        # 退化陈旧 cache (若存在) · 否则空 (无 token / 全失败)
        stale = _load_cache(cache) if cache.exists() else None
        return stale or []

    pairs: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        name = str(row.get("name", "")).strip()
        market = str(row.get("market", "")).strip()
        if not symbol or market == _BSE_MARKET:  # 排北交所 + 跳空代码
            continue
        pairs.append((symbol, name))
    if pairs:
        atomic_write_json(cache, [[c, n] for c, n in pairs], ensure_ascii=False)
    return pairs


__all__ = ["fetch_all_stocks"]

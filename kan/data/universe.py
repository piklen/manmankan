"""全市场股票列表 (全市场截面层 · AllStocksSet 截面池原料)。

tushare stock_basic(list_status="L") 一次拉全部上市股 → [(symbol, name)] · 24h
JSON cache。保留主板 / 创业板 / 科创板 / 北交所 / 含 ST；`--all` 的含义就是
完整 A 股市场，需要排除某类股票时由命令自己的显式过滤项负责。

无 token / 网络失败 → 退化陈旧 cache · 仍无则空 list；响应契约不完整则明确报错，
不能用旧缓存掩盖数据源偏差。

单源领域 (tushare stock_basic) · 暂不抽 chain (复刻 industry_map 单源约定) ·
后续可加 akshare 降级源 (同形 metrics chain)。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from kan.data.tushare import TushareDataContractError
from kan.infra.log import debug_log
from kan.storage.paths import DATA_DIR, atomic_write_json, ensure_dirs

_ALL_STOCKS_TTL = 24 * 3600
_ALL_STOCKS_CACHE = "all_stocks.json"
_MIN_COMPLETE_STOCKS = 5000
"""当前 A 股全市场的保守完整性下界；用于拒绝明显不完整的响应和旧缓存。"""
_MIN_COMPLETE_BSE_STOCKS = 1
"""v2 全市场语义必须含北交所；用于淘汰旧版主动排除北交所的缓存。"""
_BSE_PREFIXES = ("92", "83", "43", "87", "82")


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


def _cache_complete(stocks: list[tuple[str, str]]) -> bool:
    bse_count = sum(code.startswith(_BSE_PREFIXES) for code, _name in stocks)
    return (
        len(stocks) >= _MIN_COMPLETE_STOCKS
        and bse_count >= _MIN_COMPLETE_BSE_STOCKS
    )


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
            # Tushare 官方说明该调用一次即可覆盖全市场，不注入中转服务的分页参数。
            params={"list_status": "L"},
            fields="ts_code,symbol,name,market,exchange,list_status",
        )
        if data is None:
            cb.record("tushare_basic", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            raise TushareDataContractError(
                "stock_basic",
                "list_status=L 返回 0 只，无法构成完整 A 股市场",
            )
        df = pd.DataFrame(items, columns=fields)
        missing_fields = {"symbol", "name", "market"} - set(df.columns)
        if missing_fields:
            raise TushareDataContractError(
                "stock_basic",
                f"响应缺少字段 {sorted(missing_fields)!r}",
            )
        stock_count = df["symbol"].astype(str).nunique()
        if stock_count < _MIN_COMPLETE_STOCKS:
            raise TushareDataContractError(
                "stock_basic",
                f"list_status=L 仅返回 {stock_count} 只，"
                f"低于完整 A 股市场校验下界 {_MIN_COMPLETE_STOCKS}",
            )
        cb.record("tushare_basic", ok=True)
        return df
    except TushareDataContractError:
        # 契约偏差必须暴露给调用方，不能静默回退后继续冒充“全市场”。
        raise
    except Exception as e:
        debug_log(__name__, "fetch tushare stock_basic 失败", e)
        cb.record("tushare_basic", ok=False)
        return None


def fetch_all_stocks(force: bool = False) -> list[tuple[str, str]]:
    """全市场 [(symbol, name)] · 含北交所 / ST · 24h JSON cache。

    无 token / 网络失败 → 退化陈旧 cache；响应契约错误直接抛出且不覆盖缓存。
    """
    ensure_dirs()
    cache = DATA_DIR / _ALL_STOCKS_CACHE
    if not force and _cache_fresh(cache, _ALL_STOCKS_TTL):
        cached = _load_cache(cache)
        if cached is not None and _cache_complete(cached):
            return cached

    df = _fetch_tushare_stock_basic_all()
    if df is None or df.empty:
        # 退化陈旧 cache (若存在) · 否则空 (无 token / 全失败)
        stale = _load_cache(cache) if cache.exists() else None
        return stale if stale is not None and _cache_complete(stale) else []

    pairs: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        name = str(row.get("name", "")).strip()
        if not symbol:
            continue
        pairs.append((symbol, name))
    if pairs:
        atomic_write_json(cache, [[c, n] for c, n in pairs], ensure_ascii=False)
    return pairs


__all__ = ["fetch_all_stocks"]

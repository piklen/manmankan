"""申万一级行业反查映射 (地基-3 · 行业中位对照原料)。

tushare index_member_all 一次拉全市场最新申万成分 → {symbol: 申万一级名} · 24h JSON cache。
无 token / 失败 → 退化到陈旧 cache · 仍无则空 dict (优雅降级 · 行业中位维度缺失)。

单源领域 (tushare index_member_all) · 暂不抽 chain (复刻 boards 单源约定)。
后续可加 akshare 申万降级源 (同形 metrics chain)。
"""
from __future__ import annotations

import json
import time

from kan.infra.log import debug_log
from kan.storage.paths import DATA_DIR, atomic_write_json, ensure_dirs

_SW_MAP_TTL = 24 * 3600
_SW_MAP_CACHE = "sw_l1_map.json"


def _cache_fresh(path, ttl: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


def _load_cache(path) -> dict[str, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else None
    except Exception as e:
        debug_log(__name__, f"sw_l1_map cache {path.name} 损坏", e)
        return None


def _fetch_tushare_sw_l1_members():
    """TuShare index_member_all 申万成分 adapter · 独立熔断 key `tushare_sw`."""
    import pandas as pd

    from kan.data.tushare import _post_tushare_api, _resolve_config, _strip_ts_suffix
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_sw"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="index_member_all",
            params={"is_new": "Y"},
            fields="l1_name,ts_code",
        )
        if data is None:
            cb.record("tushare_sw", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_sw", ok=False)
            return None
        df = pd.DataFrame(items, columns=fields)
        if "ts_code" not in df.columns or "l1_name" not in df.columns:
            cb.record("tushare_sw", ok=False)
            return None
        df["symbol"] = df["ts_code"].map(_strip_ts_suffix)
        cb.record("tushare_sw", ok=True)
        return df[["symbol", "l1_name"]]
    except Exception as e:
        debug_log(__name__, "fetch tushare sw members 失败", e)
        cb.record("tushare_sw", ok=False)
        return None


def fetch_sw_l1_map(force: bool = False) -> dict[str, str]:
    """全市场 {symbol: 申万一级行业名} · 24h JSON cache · 行业中位反查。

    无 token / 全失败 → 退化陈旧 cache · 仍无返空 dict (调用方按空判断降级)。
    """
    ensure_dirs()
    cache = DATA_DIR / _SW_MAP_CACHE
    if not force and _cache_fresh(cache, _SW_MAP_TTL):
        cached = _load_cache(cache)
        if cached is not None:
            return cached

    df = _fetch_tushare_sw_l1_members()
    if df is None or df.empty:
        # 退化陈旧 cache (若存在) · 否则空
        stale = _load_cache(cache) if cache.exists() else None
        return stale or {}

    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        l1 = str(row.get("l1_name", "")).strip()
        if symbol and l1:
            mapping[symbol] = l1
    if mapping:
        atomic_write_json(cache, mapping, ensure_ascii=False)
    return mapping


__all__ = ["fetch_sw_l1_map"]

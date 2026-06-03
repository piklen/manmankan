"""东方财富热榜数据子系统 · 人气榜 / 飙升榜拉取 + 缓存 + 代码归一化。

数据源:东方财富(akshare / 东财公开接口)单源。同花顺无人气热榜接口 —— 不建假 fallback。
实时源失败时只降级到同一东财接口或本地旧缓存,仍统一抛 HotListUnavailableError。
冷启动规则:akshare 一律函数内延迟 import。
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kan.infra.log import debug_log
from kan.storage.paths import HOT_DIR, STOCK_NAMES_CACHE, atomic_write_json, ensure_dirs

_CACHE_TTL = 3600  # 1h · 热榜实时榜 · 盘后工具 1h 内重复跑结果稳定 · 不反复打源
_HOT_TIMEOUT_SECONDS = 15  # 单次拉取硬超时 · 防 v0.0.4.3 同型"沉默 5 分钟卡死"
_EASTMONEY_TIMEOUT_SECONDS = 8
_SURGE_RANK_URL = "https://emappdata.eastmoney.com/stockrank/getAllHisRcList"
_EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://guba.eastmoney.com",
    "Referer": "https://guba.eastmoney.com/rank/",
}

_PREFIX_RE = re.compile(r"^[A-Za-z]{2}")
_CODE_RE = re.compile(r"\d{6}")


class HotList(StrEnum):
    """支持的东财热榜 · 同时作 typer 选项枚举(值 = CLI 输入)。"""

    RANK = "rank"     # 东财人气榜
    SURGE = "surge"   # 东财飙升榜


# 榜单元信息:akshare 函数名 + 展示名
_HOT_SPEC: dict[HotList, tuple[str, str]] = {
    HotList.RANK: ("stock_hot_rank_em", "东财人气榜"),
    HotList.SURGE: ("stock_hot_up_em", "东财飙升榜"),
}


@dataclass
class HotEntry:
    """热榜单条目。"""

    rank: int
    symbol: str   # 6 位裸代码
    name: str


class HotListUnavailableError(Exception):
    """东财热榜数据源不可用(网络 / 接口失败 / 空数据)。"""


def hot_list_name(which: HotList) -> str:
    """榜单展示名 · 如 '东财人气榜'。"""
    return _HOT_SPEC[which][1]


def _cache_fresh(path, ttl: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


def _load_hot_cache(path) -> list[HotEntry] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [HotEntry(**e) for e in data]
        return entries or None
    except Exception as e:
        debug_log(__name__, f"hot cache {path.name} 损坏", e)
        return None


def _load_stock_names_cache() -> dict[str, str]:
    """读本地代码表快照,不触发网络刷新。名称缺失时 fallback 到代码本身。"""
    if not STOCK_NAMES_CACHE.exists():
        return {}
    try:
        raw = json.loads(STOCK_NAMES_CACHE.read_text(encoding="utf-8"))
    except Exception as e:
        debug_log(__name__, "stock_names cache read failed for hot fallback", e)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(code): str(name).strip()
        for code, name in raw.items()
        if _CODE_RE.fullmatch(str(code)) and str(name).strip()
    }


def _normalize_code(raw: str) -> str | None:
    """东财代码(SZ000725 / SH603759)→ 6 位裸代码。无法归一化返回 None。"""
    cleaned = _PREFIX_RE.sub("", str(raw).strip())
    if _CODE_RE.fullmatch(cleaned):
        return cleaned
    return None


def _coerce_rank(raw: Any) -> int | None:
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _post_json(url: str, payload: dict[str, object]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers=_EASTMONEY_HEADERS,
        method="POST",
    )
    try:
        with urlopen(req, timeout=_EASTMONEY_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        raise HotListUnavailableError(f"东财飙升榜直连失败: {e}") from e
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        prefix = raw[:80].decode("utf-8", errors="replace")
        raise HotListUnavailableError(f"东财飙升榜直连非 JSON 响应: {prefix!r}") from e
    if not isinstance(parsed, dict):
        raise HotListUnavailableError("东财飙升榜直连响应结构异常")
    return parsed


def _entries_from_dataframe(df, fn_name: str, which: HotList) -> list[HotEntry]:
    if df is None or df.empty:
        raise HotListUnavailableError(f"东财热榜为空: {fn_name}")

    entries: list[HotEntry] = []
    skipped = 0
    for _, row in df.iterrows():
        code = _normalize_code(row["代码"])
        rank = _coerce_rank(row["当前排名"])
        if code is None or rank is None:
            skipped += 1
            continue
        entries.append(HotEntry(
            rank=rank,
            symbol=code,
            name=str(row["股票名称"]).strip(),
        ))
    if skipped:
        debug_log(
            __name__,
            f"hot list {which.value} skipped {skipped} non-A-share codes",
            ValueError("codes outside 6-digit A-share range"),
        )
    if not entries:
        raise HotListUnavailableError(f"东财热榜无有效条目: {fn_name}")
    return entries


def _fetch_akshare_entries(which: HotList, fn_name: str) -> list[HotEntry]:
    import akshare as ak

    # 硬超时拉取 · 防 akshare/requests 默认长重试导致用户感受"卡死"
    # ThreadPoolExecutor.result(timeout) 让 main thread 立即 return 报错
    # 真 thread 不能强制 kill(Python 限制)· 但用户看到错误 + 后台 thread 自然结束
    def _call():
        return getattr(ak, fn_name)()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call)
        try:
            df = future.result(timeout=_HOT_TIMEOUT_SECONDS)
        except FuturesTimeout as e:
            raise HotListUnavailableError(
                f"东财热榜拉取超时({_HOT_TIMEOUT_SECONDS}s) {fn_name} · 网络慢或接口限流"
            ) from e
        except Exception as e:
            raise HotListUnavailableError(f"东财热榜拉取失败 {fn_name}: {e}") from e
    return _entries_from_dataframe(df, fn_name, which)


def _fetch_surge_direct_entries() -> list[HotEntry]:
    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": 100,
    }
    data_json = _post_json(_SURGE_RANK_URL, payload)
    rows = data_json.get("data")
    if not isinstance(rows, list) or not rows:
        raise HotListUnavailableError("东财飙升榜直连为空")

    names = _load_stock_names_cache()
    entries: list[HotEntry] = []
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        code = _normalize_code(str(row.get("sc", "")))
        rank = _coerce_rank(row.get("rk"))
        if code is None or rank is None:
            skipped += 1
            continue
        entries.append(HotEntry(
            rank=rank,
            symbol=code,
            name=names.get(code, code),
        ))
    if skipped:
        debug_log(
            __name__,
            f"hot list surge direct skipped {skipped} invalid rows",
            ValueError("invalid surge rows"),
        )
    if not entries:
        raise HotListUnavailableError("东财飙升榜直连无有效条目")
    return entries


def fetch_hot_list(which: HotList, force: bool = False) -> list[HotEntry]:
    """拉取指定东财热榜 · (名次, 代码, 名称) 列表 · JSON cache 1h TTL。

    akshare: stock_hot_rank_em(人气榜) / stock_hot_up_em(飙升榜)。
    无法归一化的代码跳过 · 经 debug_log 记数。
    数据源失败 / 空 / 无有效条目 → 抛 HotListUnavailableError。
    """
    ensure_dirs()
    cache = HOT_DIR / f"hot_{which.value}.json"
    if not force and _cache_fresh(cache, _CACHE_TTL):
        cached = _load_hot_cache(cache)
        if cached is not None:
            return cached

    fn_name, _label = _HOT_SPEC[which]
    try:
        entries = _fetch_akshare_entries(which, fn_name)
    except HotListUnavailableError as source_error:
        if which is HotList.SURGE:
            try:
                entries = _fetch_surge_direct_entries()
            except HotListUnavailableError as direct_error:
                debug_log(__name__, "surge direct fallback failed", direct_error)
                cached = _load_hot_cache(cache)
                if cached is not None:
                    debug_log(__name__, f"hot list {which.value} using stale cache", source_error)
                    return cached
                raise HotListUnavailableError(
                    f"{source_error}; direct fallback: {direct_error}"
                ) from source_error
        else:
            cached = _load_hot_cache(cache)
            if cached is not None:
                debug_log(__name__, f"hot list {which.value} using stale cache", source_error)
                return cached
            raise

    atomic_write_json(cache, [asdict(e) for e in entries], ensure_ascii=False)
    return entries

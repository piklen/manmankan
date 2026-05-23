"""东方财富热榜数据子系统 · 人气榜 / 飙升榜拉取 + 缓存 + 代码归一化。

数据源:东方财富(akshare)单源。同花顺无人气热榜接口 —— 不建假 fallback,
东财失败直接抛 HotListUnavailableError(沿用 boards.py 单源原则)。
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

from kan._log import debug_log
from kan.paths import HOT_DIR, ensure_dirs

_CACHE_TTL = 3600  # 1h · 热榜实时榜 · 盘后工具 1h 内重复跑结果稳定 · 不反复打源
_HOT_TIMEOUT_SECONDS = 15  # 单次拉取硬超时 · 防 v0.0.4.3 同型"沉默 5 分钟卡死"

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


def _normalize_code(raw: str) -> str | None:
    """东财代码(SZ000725 / SH603759)→ 6 位裸代码。无法归一化返回 None。"""
    cleaned = _PREFIX_RE.sub("", str(raw).strip())
    if _CODE_RE.fullmatch(cleaned):
        return cleaned
    return None


def fetch_hot_list(which: HotList, force: bool = False) -> list[HotEntry]:
    """拉取指定东财热榜 · (名次, 代码, 名称) 列表 · JSON cache 1h TTL。

    akshare: stock_hot_rank_em(人气榜) / stock_hot_up_em(飙升榜)。
    无法归一化的代码跳过 · 经 debug_log 记数。
    数据源失败 / 空 / 无有效条目 → 抛 HotListUnavailableError。
    """
    ensure_dirs()
    cache = HOT_DIR / f"hot_{which.value}.json"
    if not force and _cache_fresh(cache, _CACHE_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [HotEntry(**e) for e in data]
        except Exception as e:
            debug_log(__name__, f"hot cache {cache.name} 损坏 · 重新拉", e)

    fn_name, _label = _HOT_SPEC[which]
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
    if df is None or df.empty:
        raise HotListUnavailableError(f"东财热榜为空: {fn_name}")

    entries: list[HotEntry] = []
    skipped = 0
    for _, row in df.iterrows():
        code = _normalize_code(row["代码"])
        if code is None:
            skipped += 1
            continue
        try:
            rank = int(row["当前排名"])
        except (ValueError, TypeError):
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

    cache.write_text(
        json.dumps([asdict(e) for e in entries], ensure_ascii=False),
        encoding="utf-8",
    )
    return entries

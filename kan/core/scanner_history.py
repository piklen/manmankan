"""历史 scan 快照的离线读取和共振标记。"""
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class SymbolHistoryEntry:
    """单只股票在某一快照日的位置记录。

    periods: {period: {"pct", "at_low", "at_high"}} · 只含当日非 insufficient 的周期
    (跟 save_snapshot 写入口径一致 · 缺的周期 = 那天历史不足)。
    """

    snapshot_date: date
    name: str
    periods: dict[int, dict]


@dataclass
class PoolHistoryEntry:
    """某一快照日的池级位置聚合(纯客观统计 · 不含判断词)。"""

    snapshot_date: date
    stock_count: int      # 当日有该周期有效位置的股票数
    median_pct: float     # 池内位置中位数 %
    low_count: int        # 位置 <= 20% 只数
    high_count: int       # 位置 >= 80% 只数


def _iter_snapshot_files() -> Iterator[tuple[date, list[dict[str, Any]]]]:
    """按文件名(= 快照日)升序遍历 snapshots/*.json · 文件名非法日期的跳过。

    yield (date, list[dict]) · 文件损坏 / 不可读的整份 skip(跟 save_snapshot
    的清理逻辑同样宽容 · 一份坏文件不该让整条历史不可用)。
    """
    from kan.storage.paths import SNAPSHOTS_DIR

    if not SNAPSHOTS_DIR.exists():
        return
    for f in sorted(SNAPSHOTS_DIR.glob("*.json"), key=lambda p: p.stem):
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            yield d, data


def load_symbol_history(symbol: str) -> list[SymbolHistoryEntry]:
    """读取单只股票跨快照日的位置历史 · 纯离线(只读 snapshots/)· 按日期降序(新→旧)。

    只有曾进过自选、且当天跑过 `kan scan`(全量 · 非 industry/theme)的股票才有记录。
    """
    entries: list[SymbolHistoryEntry] = []
    for d, data in _iter_snapshot_files():
        for item in data:
            if item.get("symbol") != symbol:
                continue
            raw = item.get("periods", {})
            periods: dict[int, dict] = {}
            for k, v in raw.items():
                try:
                    periods[int(k)] = v
                except (ValueError, TypeError):
                    continue
            entries.append(SymbolHistoryEntry(d, item.get("name", symbol), periods))
            break
    entries.sort(key=lambda e: e.snapshot_date, reverse=True)
    return entries


def load_pool_history(period: int, *, min_stocks: int = 5) -> list[PoolHistoryEntry]:
    """读取池级位置趋势 · 纯离线(只读 snapshots/)· 按日期降序(新→旧)。

    只聚合「当日有 period 周期有效位置」的股票;当日有效只数 < min_stocks
    的整页跳过(自定义周期/分组扫描遗留的残缺快照日不冒充池状态)。
    """
    entries: list[PoolHistoryEntry] = []
    for d, data in _iter_snapshot_files():
        pcts: list[float] = []
        for item in data:
            cell = (item.get("periods") or {}).get(str(period))
            if cell is None:
                continue
            try:
                pcts.append(float(cell["pct"]))
            except (KeyError, TypeError, ValueError):
                continue
        if len(pcts) < min_stocks:
            continue
        pcts.sort()
        entries.append(PoolHistoryEntry(
            snapshot_date=d,
            stock_count=len(pcts),
            median_pct=pcts[len(pcts) // 2],
            low_count=sum(1 for p in pcts if p <= 20),
            high_count=sum(1 for p in pcts if p >= 80),
        ))
    entries.sort(key=lambda e: e.snapshot_date, reverse=True)
    return entries


def snapshot_symbol_names() -> dict[str, str]:
    """所有快照里出现过的 {symbol: name} · 后出现(更新)的 name 覆盖旧的。

    供 `kan history` 离线解析「名称 → 代码」· 解析域 = 有历史的股票本身,
    天然不会解析到没历史的股(语义比全局代码-名称表更贴)。
    """
    out: dict[str, str] = {}
    for _d, data in _iter_snapshot_files():
        for item in data:
            sym = item.get("symbol")
            if sym:
                out[sym] = item.get("name", sym)
    return out


def history_resonance(periods: dict[int, dict]) -> tuple[int, int]:
    """某快照日的 (低点共振数, 高点共振数) · 跨该日所有已存周期统计。"""
    low = sum(1 for v in periods.values() if v.get("at_low"))
    high = sum(1 for v in periods.values() if v.get("at_high"))
    return low, high


def history_mark(periods: dict[int, dict]) -> tuple[int, str]:
    """某快照日的 (共振数, 方向) · 方向 ∈ {"", "low", "high"} · 平局取 low(跟 scan 同口径)。

    这是纯数据判定 · 终端 / md / json 各自映射到自己的字形 / 文案。
    """
    low, high = history_resonance(periods)
    res = max(low, high)
    if res == 0:
        return 0, ""
    return res, "low" if low >= high else "high"

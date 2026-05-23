"""kan.core.verbs · 统一 verb 入口 (OOP 视角)。

任何 StockSet 都可以被这一层的 verb 操作:

    >>> from kan.core import verbs
    >>> from kan.core.stock_set import WatchlistSet, ThemeSet, HotRankSet, IndustrySet
    >>> verbs.scan(WatchlistSet())                   # 自选股位置扫描 + 共振排序
    >>> verbs.low(ThemeSet("新能源"), periods=[60])  # 新能源题材筛 60 日低点
    >>> verbs.high(HotRankSet(mode="surge"))         # 飙升榜筛 [30,60,120] 高点
    >>> verbs.trend(WatchlistSet())                  # 自选股连续涨跌排序
    >>> verbs.fetch(IndustrySet("白酒"))             # 白酒行业 K 线拉到本地

设计选择:
- 不重写底层 scanner / fetcher 算法 (那些已经成熟 + 测试好)
- 只做 thin facade · 把 StockSet 翻译成 (code, name) pairs 喂给 underlying
- 返回 raw result · CLI 层负责渲染 · 用户调用时自由处理 (写脚本 / cron / 出 markdown)
- kwargs 透传 underlying · 不引入新参数概念

CLI 层 (kan/cli/*_cmds.py) 暂未迁移到这一层 (仍走 resolve_scan_targets +
run_data_pipeline 编排)。OOP 层是给 "Python API 脚本化使用 + 渐进迁移 CLI"
打地基。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.models import StockScanResult, TrendResult
    from kan.core.stock_set import StockSet


def scan(stock_set: StockSet, *, mode: str = "low") -> list[StockScanResult]:
    """全位置扫描 + 共振排序。

    Args:
        stock_set: 任何 StockSet 实例 (Watchlist / HotRank / Theme / Industry)
        mode: "low" (低位优先) | "high" (高位优先) · 影响 sort order

    Returns:
        list[StockScanResult] · 每只股票的多周期位置 + 共振得分。

    Note: 要求底层 K 线缓存已存在 (没缓存的股票静默跳过)。先跑 verbs.fetch() 拉数据。
    """
    from kan.core import scanner

    return scanner.scan_batch(stock_set.pairs(), mode=mode)


def low(
    stock_set: StockSet,
    *,
    periods: list[int] | None = None,
) -> dict[int, list]:
    """筛 stock_set 中触及各周期低点的股票。

    Args:
        stock_set: 任何 StockSet 实例
        periods: 检查周期 (默认 [30, 60, 120] · 跟 CLI `kan low` 默认对齐)

    Returns:
        dict[int, list[tuple[StockScanResult, PeriodResult]]] · 按周期分组的命中股票。
    """
    from kan.core import scanner

    if periods is None:
        periods = [30, 60, 120]
    return scanner.filter_extreme(stock_set.pairs(), periods=periods, mode="low")


def high(
    stock_set: StockSet,
    *,
    periods: list[int] | None = None,
) -> dict[int, list]:
    """筛 stock_set 中触及各周期高点的股票。

    跟 low() 对称 · 详见该函数 docstring。
    """
    from kan.core import scanner

    if periods is None:
        periods = [30, 60, 120]
    return scanner.filter_extreme(stock_set.pairs(), periods=periods, mode="high")


def trend(stock_set: StockSet, *, candle: bool = False) -> list[TrendResult]:
    """对 stock_set 算连续涨跌 · 按天数 / 累计幅度排序。

    Args:
        stock_set: 任何 StockSet 实例
        candle: 是否带 K 线形态附加信息 (吞没 / 锤子线之类) · 默认 False
    """
    from kan.core import scanner

    return scanner.trend_batch(stock_set.pairs(), candle=candle)


def fetch(
    stock_set: StockSet,
    *,
    days: int = 180,
    force: bool = False,
    max_workers: int | None = None,
) -> tuple[dict, dict]:
    """拉取 stock_set 中所有股票的 K 线数据到本地缓存。

    Returns:
        (results, errors) · results = {code: DataFrame} · errors = {code: msg}

    Note: 这是真正落网络的 verb · 其他 verb 都假设缓存已存在。
    """
    from kan.data import fetcher

    return fetcher.fetch_batch(
        stock_set.codes(),
        days=days,
        force=force,
        max_workers=max_workers,
    )


__all__ = ["fetch", "high", "low", "scan", "trend"]

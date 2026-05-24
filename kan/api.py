"""kan.api · 公开 Python API 入口 (稳定 surface · 用户脚本化使用首选)。

把 manmankan 的 OOP 框架收口成一个稳定 import 入口 · 用户脚本写:

    from kan.api import WatchlistSet, ThemeSet, HotRankSet, IndustrySet
    from kan.api import scan, low, high, trend, fetch

替代散布在多个内部模块的 import:

    # 不推荐(内部布局可能在小版本调整)
    from kan.core.stock_set import WatchlistSet, ThemeSet, HotRankSet, IndustrySet
    from kan.core.verbs import scan, low, high, trend, fetch

设计原则:
- 本模块是**公开 contract** · 一旦添加的符号在下个版本不应被 breaking 变更
- 内部模块布局可继续重构 · 用户脚本不受影响
- 不引入新概念 · 只是 re-export · 文档汇集于此

四类股票集合 (StockSet):
- WatchlistSet:   自选股 (本地 `kan add` 管理的列表)
- HotRankSet:     东方财富热榜 (mode="rank" 人气榜 / "surge" 飙升榜)
- ThemeSet:       题材股 (同花顺概念板块成分股 · 如 "新能源" / "AI")
- IndustrySet:    行业股 (申万行业分类 · 如 "白酒" / "半导体")

五个 verb (任何 StockSet 都可接受):
- scan(stock_set, mode="low"|"high"):  全位置扫描 + 共振排序
- low(stock_set, periods=[30,60,120]): 筛触及 N 日低点的股票
- high(stock_set, periods=[30,60,120]): 筛触及 N 日高点的股票
- trend(stock_set, candle=False):      连续涨跌排序
- fetch(stock_set, days=180):          拉 K 线数据到本地缓存

完整使用示例
─────────

`scan` 自选股的多周期位置:

    >>> from kan.api import WatchlistSet, scan
    >>> results = scan(WatchlistSet())
    >>> for r in results[:5]:
    ...     print(r.symbol, r.name, r.low_resonance, r.high_resonance)

`low` 题材股的 60 日低位:

    >>> from kan.api import ThemeSet, low
    >>> hits = low(ThemeSet("新能源"), periods=[60])
    >>> for period, stocks in hits.items():
    ...     for r, pr in stocks:
    ...         print(period, r.symbol, r.name, pr.position_pct)

`trend` 热榜飙升榜的连续涨跌:

    >>> from kan.api import HotRankSet, trend
    >>> trends = trend(HotRankSet(mode="surge"))
    >>> for t in trends[:5]:
    ...     print(t.symbol, t.name, t.streak)

`fetch` 行业全股票 K 线 (写本地 cache):

    >>> from kan.api import IndustrySet, fetch
    >>> results, errors = fetch(IndustrySet("白酒"), days=180)
    >>> print(f"成功 {len(results)} · 失败 {len(errors)}")

`from_flags` (用 CLI flags 风格构造 StockSet · 内部三者互斥校验):

    >>> from kan.api import from_flags, scan
    >>> stock_set = from_flags(theme="AI", watchlist_pairs=[("600519","贵州茅台")])
    >>> scan(stock_set)  # AI 题材全部成分股 · 自选 ⭐ 标记

`StockSet` Protocol (自定义集合):

    >>> from kan.api import StockSet, scan
    >>> class MyETFBasket:
    ...     name = "新能源车 ETF 篮"
    ...     def codes(self): return ["600519", "300750", "002230"]
    ...     def pairs(self): return [("600519","茅台"), ("300750","宁德"), ("002230","讯飞")]
    ...     def meta(self): return None
    >>> isinstance(MyETFBasket(), StockSet)  # True · 鸭子类型
    >>> scan(MyETFBasket())  # 直接喂给 verb

注意
────
- verb 不做 fetch · 假设本地缓存已存在 (没缓存的股票静默跳过)。先跑 `fetch()` 拉数据。
- meta 在 industry/hot/theme 模式才有 (WatchlistSet.meta() = None) · 含 highlight
  (集合 ∩ 自选)、rank_map (热榜名次)、index_kline (板块指数 K 线) 等。
- 数据源限流时各 Set 内部已做 5 分钟熔断 · 不会反复打挂上游。
"""
from __future__ import annotations

# Re-export · 集合抽象 + 4 实现 + factory
from kan.core.stock_set import (
    HotRankSet,
    IndustrySet,
    StockSet,
    ThemeSet,
    WatchlistSet,
    from_flags,
)

# Re-export · 5 个 verb
from kan.core.verbs import (
    fetch,
    high,
    low,
    scan,
    trend,
)

__all__ = [
    # StockSet
    "HotRankSet",
    "IndustrySet",
    "StockSet",
    "ThemeSet",
    "WatchlistSet",
    # verbs
    "fetch",
    "from_flags",
    "high",
    "low",
    "scan",
    "trend",
]

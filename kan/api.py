"""kan.api · 公开 Python API 入口 (稳定 surface · 用户脚本化使用首选)。

把 manmankan 的 OOP 框架收口成一个稳定 import 入口 · 用户脚本写:

    from kan.api import WatchlistSet, WatchlistHoldingsSet, ThemeSet, HotRankSet, IndustrySet
    from kan.api import scan, low, high, trend, fetch

替代散布在多个内部模块的 import:

    # 不推荐(内部布局可能在小版本调整)
    from kan.core.stock_set import WatchlistSet, WatchlistHoldingsSet, ThemeSet, HotRankSet, IndustrySet
    from kan.core.verbs import scan, low, high, trend, fetch

设计原则:
- 本模块是**公开 contract** · 一旦添加的符号在下个版本不应被 breaking 变更
- 内部模块布局可继续重构 · 用户脚本不受影响
- StockSet verb 与 vNext Screen application service 都只在这里暴露稳定入口

vNext 可复跑选股规则:

    >>> from kan.api import ScreenSpec, save_screen, run_screen
    >>> spec = ScreenSpec(name="排除 ST", exclude_st=True)
    >>> saved = save_screen(spec)
    >>> result = run_screen(saved.spec, screen_id=saved.screen_id,
    ...                     screen_version=saved.current_version)
    >>> result.spec_hash == saved.spec_hash
    True

四类股票集合 (StockSet):
- WatchlistSet:   自选股 (本地 `kan add` 管理的列表)
- HoldingsSet:    真实持仓 (本地 `kan hold` 管理的列表)
- WatchlistHoldingsSet: 默认池 (自选 ∪ 真实持仓)
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

数据源扩展
─────────────────────

manmankan 内置 K 线 5 源 (tushare/baostock/eastmoney/sina/tencent · 按稳定性排优先级)
+ 题材成分股 2 源 (THS / EM)。用户可通过 `register_*_source` 注入自定义源 ·
chain 自动按 priority 排序 + fallback · 你的源失败不影响其他源。

K 线数据源 (实现 `KlineSource` Protocol):

    >>> from kan.api import KlineSource, register_kline_source
    >>> import pandas as pd
    >>>
    >>> class MyWindKlineSource:
    ...     '''自接 Wind / 自建数据库 / 通达信本地缓存 / 任何源。'''
    ...     name = "user_wind"            # 唯一标识 (建议 user_ 前缀避免与内置撞名)
    ...     priority = 5                  # 顶档 (内置最高 tushare=10 · 你可压它)
    ...     def is_available(self) -> bool:
    ...         return True               # 软依赖 / token / 熔断检查 · cheap (不做网络)
    ...     def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
    ...         # 返回标准 schema · 必含 date/open/high/low/close · 可选 volume/amount
    ...         # 失败返 None · chain 自动 fallback 下一档 (异常吞掉 + debug_log)
    ...         return your_wind_query(symbol, start)
    ...
    >>> register_kline_source(MyWindKlineSource())
    >>> # 之后 fetch / scan / low / high / trend 自动走 chain · Wind 顶档优先

题材成分股数据源 (实现 `ThemeConstituentSource` Protocol):

    >>> from kan.api import ThemeConstituentSource, register_theme_constituent_source
    >>> from kan.core.models import Theme
    >>>
    >>> class MyTdxThemeSource:
    ...     '''通达信本地 .blk 板块文件 / 自建题材库 / 任何源。'''
    ...     name = "user_tdx"
    ...     priority = 5
    ...     def is_available(self) -> bool:
    ...         return Path("~/.tdx/blk").expanduser().exists()
    ...     def fetch(self, theme: Theme) -> list[tuple[str, str]] | None:
    ...         # 返 [(code, name), ...] · 失败 None
    ...         return read_tdx_blk(theme.code)
    ...
    >>> register_theme_constituent_source(MyTdxThemeSource())

priority 约定 (按稳定性 · 数字小优先):
- 0-9   极顶档 (未来 ToB 付费 + 自部署留)
- 10-19 内置付费 (tushare)
- 20-29 内置免费稳定 (baostock 独立服务器)
- 30-39 内置免费并发 race (eastmoney / sina · 同 priority 自动 ThreadPool race)
- 40-49 内置兜底 (tencent · 部分字段不可信)
- **50-89 留给用户自定义** (推荐区间 · 避开内置)
- 90-99 极兜底保留

熔断器 + chain skip 语义:
- TushareKlineSource.is_available() 未配 token 返 False · chain 跳过 (不浪费 fetch 调用)
- BaostockKlineSource.is_available() 未装 baostock 软依赖返 False · 跳过
- 任意源连续失败 → 熔断器 5min 冷却 · is_available 返 False · chain 跳过

inspect 当前 chain 注册的源 (调试 / 用户脚本检查):

    >>> from kan.api import kline_chain, theme_constituent_chain
    >>> for src in kline_chain().sources:
    ...     print(src.name, src.priority, src.is_available())
"""
from __future__ import annotations

# Re-export · 集合抽象 + 4 实现 + factory
from kan.core.stock_set import (
    HoldingsSet,
    HotRankSet,
    IndustrySet,
    StockSet,
    ThemeSet,
    WatchlistHoldingsSet,
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

# 背景 · 数据源扩展 API (KlineSource + ThemeConstituentSource Protocol + register/inspect)
from kan.data._builtin_sources import (
    clear_user_kline_sources,
    register_kline_source,
)
from kan.data.protocols import KlineSource
from kan.data.source_chain import default_kline_chain as kline_chain
from kan.data.theme_constituents import (
    ThemeConstituentSource,
    clear_user_theme_constituent_sources,
    register_theme_constituent_source,
)
from kan.data.theme_constituents import (
    default_theme_constituent_chain as theme_constituent_chain,
)
from kan.domain.board import (
    BoardDailyChange,
    BoardKind,
    BoardTrendCoverage,
    BoardTrendFailure,
    BoardTrendMode,
    BoardTrendQuery,
    BoardTrendRow,
    BoardTrendSnapshot,
    BoardTrendSort,
)
from kan.domain.screen import (
    CandidateList,
    CompareSet,
    SavedScreen,
    ScreenRun,
    ScreenSpec,
)
from kan.service.board_service import (
    BoardTrendServiceError,
    query_board_trends,
)
from kan.service.screen_ai import (
    ScreenExplainInput,
    ScreenParseInput,
    ScreenPlanInput,
    explain_run,
    parse_screen_text,
    plan_screen,
)
from kan.service.screen_service import (
    add_candidate,
    filter_catalog,
    get_run,
    get_screen,
    list_candidate_lists,
    list_compare_sets,
    list_runs,
    list_screens,
    remove_candidate,
    run_screen,
    save_compare_set,
    save_screen,
    screen_schema,
)

__all__ = [
    "BoardDailyChange",
    "BoardKind",
    "BoardTrendCoverage",
    "BoardTrendFailure",
    "BoardTrendMode",
    "BoardTrendQuery",
    "BoardTrendRow",
    "BoardTrendServiceError",
    "BoardTrendSnapshot",
    "BoardTrendSort",
    "CandidateList",
    "CompareSet",
    "HoldingsSet",
    "HotRankSet",
    "IndustrySet",
    "KlineSource",
    "SavedScreen",
    "ScreenExplainInput",
    "ScreenParseInput",
    "ScreenPlanInput",
    "ScreenRun",
    "ScreenSpec",
    "StockSet",
    "ThemeConstituentSource",
    "ThemeSet",
    "WatchlistHoldingsSet",
    "WatchlistSet",
    "add_candidate",
    "clear_user_kline_sources",
    "clear_user_theme_constituent_sources",
    "explain_run",
    "fetch",
    "filter_catalog",
    "from_flags",
    "get_run",
    "get_screen",
    "high",
    "kline_chain",
    "list_candidate_lists",
    "list_compare_sets",
    "list_runs",
    "list_screens",
    "low",
    "parse_screen_text",
    "plan_screen",
    "query_board_trends",
    "register_kline_source",
    "register_theme_constituent_source",
    "remove_candidate",
    "run_screen",
    "save_compare_set",
    "save_screen",
    "scan",
    "screen_schema",
    "theme_constituent_chain",
    "trend",
]

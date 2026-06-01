"""StockSet · 股票集合抽象 (OOP 视角的 manmankan)。

把"一组股票"抽象成对象 · 让 verb (scan / trend / low / high / ...) 接受
任何 StockSet 实例统一处理 · 而不是各命令 if industry / elif hot / elif theme /
else watchlist 分支分发。

四类基础实现:
- WatchlistSet:  自选股 (本地 storage · 无 meta)
- HotRankSet:    东方财富热榜 (人气榜 / 飙升榜 · meta = HotMeta)
- ThemeSet:      题材股 (同花顺概念板块成分股 · meta = ThemeMeta)
- IndustrySet:   行业股 (东财行业分类 · meta = BoardMeta)
- CodeListSet:   用户传入的代码列表 (CLI `kan find --codes` / stdin)

设计选择:
- Protocol-based · 任何带 name / codes() / pairs() / meta 的对象都可扮演 StockSet
- lazy resolution · 调 .pairs() / .codes() / .meta 时才真正拉数据
- meta 承载 highlight / rank_map / index_kline / 板块名 (取代 resolve_scan_targets 中的等价计算)
- watchlist_pairs + only_watchlist 是 Set 自身职责 · 解放 CLI 命令重复布线

v0.0.5.3 起 CLI 层 (kan/cli/*_cmds.py) 直接走 StockSet · 不再用 resolve_scan_targets。
老函数 resolve_scan_targets 仍存在作 thin wrapper (内部走本模块) · 给老测试用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.data.hot import HotList


@runtime_checkable
class StockSet(Protocol):
    """股票集合抽象 · 任何"一组股票"对象都可以扮演这个 role。

    必需:
    - `name` (property 或 attr): 集合显示名 (CLI 输出 / 日志 / 错误提示)
    - `codes()`: 6 位纯数字代码列表
    - `pairs()`: (代码, 名称) 元组列表 (名称缺失时可为空字符串)
    - `meta()`: 返回 BoardMeta / HotMeta / ThemeMeta / None (method · 不是 property)
      - WatchlistSet → None
      - HotRankSet → HotMeta
      - ThemeSet → ThemeMeta
      - IndustrySet → BoardMeta
      meta() 触发 lazy resolve · 调用前可先 .pairs() 触发 (两者共享 cache)
      用 method 不用 @property:让 `isinstance(x, StockSet)` 的 hasattr 探测不会
      触发 IO (lazy fetch 推迟到实际 .meta() 调用)

    可选:
    - `__len__`: 元素个数 (默认走 len(codes()))
    """

    name: str

    def codes(self) -> list[str]: ...
    def pairs(self) -> list[tuple[str, str]]: ...
    def meta(self) -> BoardMeta | HotMeta | ThemeMeta | None: ...


# ───────────────────── 4 个具体实现 ─────────────────────


@dataclass
class WatchlistSet:
    """自选股集合 · 从本地 storage 加载指定组 (kan add/remove --group 管理)。

    group=None → 走 default 组 (kan group default 切换) · 跟 v0.0.6 行为完全一致 ·
    group="持仓" → 走该具名组 · 触发 lazy resolve 时调 load_watchlist("持仓")。
    """

    name: str = "自选股"
    group: str | None = None
    _pairs: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        # group 指定时 name 自动加组名后缀 (CLI 输出 / 日志识别) · 默认不变
        if self.group and self.name == "自选股":
            self.name = f"自选股·{self.group}"

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.storage.watchlist import load_watchlist

            wl = load_watchlist(self.group)
            self._pairs = [(s.symbol, s.name) for s in wl.stocks]
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def meta(self) -> None:
        """自选股集合无 meta (highlight/index_kline/rank_map 仅对 industry/hot/theme 有意义)。"""
        return None

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class HotRankSet:
    """东方财富热榜 / 涨速榜集合。

    mode = "rank" (or HotList.RANK) → 人气榜
    mode = "surge" (or HotList.SURGE) → 飙升榜

    watchlist_pairs / only_watchlist:
    - watchlist_pairs:可选 · 用来算 meta.highlight (热榜 ∩ 自选 高亮)
    - only_watchlist=True:.pairs() 自动 filter 成 热榜 ∩ 自选 (需要 watchlist_pairs 非空)
    """

    mode: HotList | str = "rank"
    watchlist_pairs: list[tuple[str, str]] = field(default_factory=list, repr=False)
    only_watchlist: bool = False
    _pairs: list[tuple[str, str]] | None = field(default=None, repr=False)
    _meta: HotMeta | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return "东财人气榜" if str(self.mode) == "rank" else "东财飙升榜"

    def _hot_list(self) -> HotList:
        from kan.data.hot import HotList

        return self.mode if isinstance(self.mode, HotList) else HotList(self.mode)

    def _resolve_full(self) -> None:
        """触发完整 fetch · 同时填 _pairs + _meta。"""
        from kan.core.models import HotMeta
        from kan.data.hot import fetch_hot_list, hot_list_name

        which = self._hot_list()
        entries = fetch_hot_list(which)
        wl_codes = {c for c, _ in self.watchlist_pairs}
        highlight = {e.symbol for e in entries} & wl_codes
        pairs = [(e.symbol, e.name) for e in entries]
        if self.only_watchlist:
            pairs = [(c, n) for c, n in pairs if c in highlight]
        self._pairs = pairs
        self._meta = HotMeta(
            list_name=hot_list_name(which),
            rank_map={e.symbol: e.rank for e in entries},
            highlight=highlight,
        )

    def codes(self) -> list[str]:
        if self._pairs is None:
            self._resolve_full()
        return [c for c, _ in self._pairs or []]

    def pairs(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            self._resolve_full()
        return list(self._pairs or [])

    def meta(self) -> HotMeta:
        if self._meta is None:
            self._resolve_full()
        return self._meta  # type: ignore[return-value]

    def __len__(self) -> int:
        return len(self.pairs())


@dataclass
class ThemeSet:
    """题材股集合 · 同花顺概念板块成分股。

    构造时传题材名 (如 "AI" / "国产软件" / "新能源")。
    """

    theme: str = ""
    watchlist_pairs: list[tuple[str, str]] = field(default_factory=list, repr=False)
    only_watchlist: bool = False
    _pairs: list[tuple[str, str]] | None = field(default=None, repr=False)
    _meta: ThemeMeta | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return f"题材「{self.theme}」"

    def _resolve_full(self) -> None:
        """触发完整 fetch · 同时填 _pairs + _meta (含 index_kline)。"""
        import pandas as pd

        from kan.core.models import ThemeMeta
        from kan.data import boards
        from kan.data.boards import ThemeDataUnavailableError

        themed = boards.search_theme(self.theme)
        constituents = boards.get_theme_constituents(themed)
        # K 线失败降级为空 df · 不影响成分股扫描 (spec §11)
        try:
            index_kline = boards.fetch_theme_kline(themed)
        except ThemeDataUnavailableError as e:
            from kan.infra.log import debug_log

            debug_log(__name__, f"fetch theme kline · theme={themed.name}", e)
            index_kline = pd.DataFrame()

        wl_codes = {c for c, _ in self.watchlist_pairs}
        highlight = {code for code, _ in constituents} & wl_codes
        pairs = constituents if not self.only_watchlist else [
            (c, n) for c, n in constituents if c in highlight
        ]
        self._pairs = pairs
        self._meta = ThemeMeta(
            theme=themed,
            index_kline=index_kline,
            constituents=constituents,
            highlight=highlight,
        )

    def codes(self) -> list[str]:
        if self._pairs is None:
            self._resolve_full()
        return [c for c, _ in self._pairs or []]

    def pairs(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            self._resolve_full()
        return list(self._pairs or [])

    def meta(self) -> ThemeMeta:
        if self._meta is None:
            self._resolve_full()
        return self._meta  # type: ignore[return-value]

    def __len__(self) -> int:
        return len(self.pairs())


@dataclass
class IndustrySet:
    """行业股集合 · 东财行业分类 (申万 / 中信类似行业体系)。"""

    industry: str = ""
    watchlist_pairs: list[tuple[str, str]] = field(default_factory=list, repr=False)
    only_watchlist: bool = False
    _pairs: list[tuple[str, str]] | None = field(default=None, repr=False)
    _meta: BoardMeta | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return f"行业「{self.industry}」"

    def _resolve_full(self) -> None:
        """触发完整 fetch · 同时填 _pairs + _meta (含 index_kline)。"""
        from kan.core.models import BoardMeta
        from kan.data import boards

        board = boards.search_industry(self.industry)
        constituents = boards.get_industry_constituents(board)
        index_kline = boards.fetch_industry_kline(board)
        wl_codes = {c for c, _ in self.watchlist_pairs}
        highlight = {code for code, _ in constituents} & wl_codes
        pairs = constituents if not self.only_watchlist else [
            (c, n) for c, n in constituents if c in highlight
        ]
        self._pairs = pairs
        self._meta = BoardMeta(
            board=board,
            index_kline=index_kline,
            constituents=constituents,
            highlight=highlight,
        )

    def codes(self) -> list[str]:
        if self._pairs is None:
            self._resolve_full()
        return [c for c, _ in self._pairs or []]

    def pairs(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            self._resolve_full()
        return list(self._pairs or [])

    def meta(self) -> BoardMeta:
        if self._meta is None:
            self._resolve_full()
        return self._meta  # type: ignore[return-value]

    def __len__(self) -> int:
        return len(self.pairs())


@dataclass
class AllStocksSet:
    """A 股全市场集合 · tushare stock_basic 全部上市股 (排北交所 · 含 ST)。

    kan find --all 的截面池 · 走截面专用路径 (core.cross_section.run_cross_section) ·
    不走 K 线管线 (全市场逐股 auto-fetch K 线 = 灾难 · PRD §3.2)。lazy:.pairs() 才
    拉 universe。meta() → None (同 WatchlistSet · highlight/index_kline 对全市场无意义)。
    """

    name: str = "A股全市场"
    _pairs: list[tuple[str, str]] | None = None

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.data.universe import fetch_all_stocks

            self._pairs = fetch_all_stocks()
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def meta(self) -> None:
        """全市场集合无 meta (highlight/index_kline/rank_map 仅对 industry/hot/theme 有意义)。"""
        return None

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class CodeListSet:
    """用户显式传入的代码池 · 给 `kan find --codes` / stdin 管线复用。

    pairs 由 CLI 层完成解析、去重、名称补全后注入。这里保持纯容器职责:
    - 不读自选、不触外部 catalog
    - meta() 为 None (无高亮 / 板块指数 / 榜单名次)
    - name 带数量，便于终端和 JSON 审计识别池来源
    """

    pairs_input: list[tuple[str, str]]
    label: str = "自定义代码池"

    @property
    def name(self) -> str:
        return f"{self.label}({len(self.pairs_input)}只)"

    def codes(self) -> list[str]:
        return [c for c, _ in self.pairs_input]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self.pairs_input)

    def meta(self) -> None:
        return None

    def __len__(self) -> int:
        return len(self.pairs_input)


# ───────────────────── factory ─────────────────────


def from_flags(
    *,
    industry: str | None = None,
    hot: HotList | str | None = None,
    theme: str | None = None,
    watchlist_pairs: list[tuple[str, str]] | None = None,
    only_watchlist: bool = False,
    watchlist_group: str | None = None,
    all_stocks: bool = False,
) -> StockSet:
    """从 CLI flags 构造对应 StockSet (一类 factory)。

    - all_stocks=True → AllStocksSet (全市场截面池 · 与 industry/hot/theme 互斥)
    - 三者全 None → WatchlistSet · 走 watchlist_group 指定组 (不指定走 default)
    - 任一非 None → 对应 Set · 同时把 watchlist_pairs + only_watchlist 注入 (算 highlight + filter)
    - 任意两个或三个同时非 None → ValueError (互斥)

    Args:
        industry / hot / theme: 三选一(或都 None)的 source 标识
        watchlist_pairs: 自选股 pairs · 用来算 meta.highlight (industry/hot/theme 集合 ∩ 自选)
        only_watchlist: True 时 set.pairs() = source 集合 ∩ 自选 (要求 watchlist_pairs 非空)
        watchlist_group: 选 WatchlistSet 的具名组 (None 走 default · 等价 v0.0.6 行为)
        all_stocks: True → AllStocksSet (全市场 · 与 industry/hot/theme 互斥)
    """
    if all_stocks:
        if any(x is not None for x in (industry, hot, theme)):
            raise ValueError(
                "all_stocks 与 industry / hot / theme 互斥 · 同时只能指定一个池"
            )
        return AllStocksSet()
    given = sum(1 for x in (industry, hot, theme) if x is not None)
    if given > 1:
        raise ValueError(
            "industry / hot / theme 三者互斥 · 同时只能指定一个"
        )
    wl_pairs = watchlist_pairs or []
    if industry is not None:
        return IndustrySet(
            industry=industry,
            watchlist_pairs=wl_pairs,
            only_watchlist=only_watchlist,
        )
    if hot is not None:
        return HotRankSet(
            mode=hot,
            watchlist_pairs=wl_pairs,
            only_watchlist=only_watchlist,
        )
    if theme is not None:
        return ThemeSet(
            theme=theme,
            watchlist_pairs=wl_pairs,
            only_watchlist=only_watchlist,
        )
    return WatchlistSet(group=watchlist_group)


__all__ = [
    "AllStocksSet",
    "CodeListSet",
    "HotRankSet",
    "IndustrySet",
    "StockSet",
    "ThemeSet",
    "WatchlistSet",
    "from_flags",
]

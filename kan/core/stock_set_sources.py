"""外部来源股票集合实现。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.data.hot import HotList


@dataclass
class HotRankSet:
    """东方财富热榜 / 涨速榜集合。"""

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
    """题材股集合 · 同花顺概念板块成分股。"""

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
        # K 线失败降级为空 df · 不影响成分股扫描
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

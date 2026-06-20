"""StockSet factory。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.stock_set_local import (
    AllStocksSet,
    HoldingsSet,
    WatchlistHoldingsSet,
    WatchlistSet,
)
from kan.core.stock_set_protocol import StockSet
from kan.core.stock_set_sources import HotRankSet, IndustrySet, ThemeSet

if TYPE_CHECKING:
    from kan.data.hot import HotList


def from_flags(
    *,
    industry: str | None = None,
    hot: HotList | str | None = None,
    theme: str | None = None,
    watchlist_pairs: list[tuple[str, str]] | None = None,
    only_watchlist: bool = False,
    watchlist_group: str | None = None,
    all_stocks: bool = False,
    only_holdings: bool = False,
) -> StockSet:
    """从 CLI flags 构造对应 StockSet (一类 factory)。

    - all_stocks=True → AllStocksSet (全市场截面池 · 与 industry/hot/theme 互斥)
    - only_holdings=True → HoldingsSet
    - 三者全 None + only_watchlist=True → WatchlistSet · 只看自选
    - 三者全 None + 无 group → WatchlistHoldingsSet · 默认自选 ∪ 持仓
    - 三者全 None + 有 group → WatchlistSet · 走 watchlist_group 指定组
    - 任一非 None → 对应 Set · 同时把 watchlist_pairs + only_watchlist 注入
    - 任意两个或三个同时非 None → ValueError (互斥)
    """
    if all_stocks:
        if only_holdings or any(x is not None for x in (industry, hot, theme)):
            raise ValueError(
                "all_stocks 与 industry / hot / theme / only_holdings 互斥 · 同时只能指定一个池"
            )
        return AllStocksSet()
    if only_holdings:
        if watchlist_group is not None or any(x is not None for x in (industry, hot, theme)):
            raise ValueError(
                "only_holdings 与 industry / hot / theme / group 互斥 · 同时只能指定一个池"
            )
        return HoldingsSet()
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
    if only_watchlist:
        return WatchlistSet(group=watchlist_group)
    if watchlist_group is None:
        return WatchlistHoldingsSet()
    return WatchlistSet(group=watchlist_group)

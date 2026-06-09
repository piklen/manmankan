"""StockSet 公共兼容入口。

具体实现按职责拆到同包下的 stock_set_* 模块；对外继续保留
`from kan.core.stock_set import ...` 的历史导入路径。
"""
from __future__ import annotations

from kan.core.stock_set_factory import from_flags
from kan.core.stock_set_local import (
    AllStocksSet,
    CodeListSet,
    HoldingsSet,
    WatchlistHoldingsSet,
    WatchlistSet,
)
from kan.core.stock_set_protocol import StockSet
from kan.core.stock_set_sources import HotRankSet, IndustrySet, ThemeSet

__all__ = [
    "AllStocksSet",
    "CodeListSet",
    "HoldingsSet",
    "HotRankSet",
    "IndustrySet",
    "StockSet",
    "ThemeSet",
    "WatchlistHoldingsSet",
    "WatchlistSet",
    "from_flags",
]

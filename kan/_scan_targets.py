"""扫描目标解析 · scan/low/high/trend/fetch 共享。

industry 给定 → 拉行业成分股;hot 给定 → 拉东财热榜;否则用自选股。
三种来源的差异收敛进 resolve_scan_targets 一个函数,各命令只需"换数据来源
+ 多收一个 meta"。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kan.models import Board

if TYPE_CHECKING:
    import pandas as pd

    from kan.hot import HotList


@dataclass
class BoardMeta:
    """resolve_scan_targets 在 industry 模式下的附加产物。"""

    board: Board
    index_kline: pd.DataFrame          # 板块指数 K(已归一化)
    constituents: list[tuple[str, str]]  # 全成分股 (代码, 名称)
    highlight: set[str]                  # 成分股代码 ∩ 自选股代码


@dataclass
class HotMeta:
    """resolve_scan_targets 在 hot 模式下的附加产物。"""

    list_name: str                # "东财人气榜" / "东财飙升榜"
    rank_map: dict[str, int]      # {代码: 热榜名次}
    highlight: set[str]           # 热榜代码 ∩ 自选股代码


def resolve_scan_targets(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
    hot: HotList | None = None,
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | None]:
    """解析扫描目标。

    - industry / hot 都为 None → (watchlist_pairs, None) · 现有行为完全不变
    - industry 给定 → 拉成分股 + 板块指数 K,组 BoardMeta
    - hot 给定 → 拉东财热榜,组 HotMeta
        - only_watchlist=True → targets 取 (成分股 | 热榜) ∩ 自选
    - industry 与 hot 同时给定 → raise ValueError
    - 行业未找到 → 透传 boards.BoardNotFoundError
    - 行业数据源失败 → 透传 boards.BoardDataUnavailableError
    - 热榜数据源失败 → 透传 hot.HotListUnavailableError
    """
    if industry is not None and hot is not None:
        raise ValueError("industry 与 hot 不能同时指定")

    if industry is not None:
        from kan import boards

        board = boards.search_industry(industry)            # raises BoardNotFoundError
        constituents = boards.get_industry_constituents(board)
        index_kline = boards.fetch_industry_kline(board)
        watch_codes = {code for code, _ in watchlist_pairs}
        highlight = {code for code, _ in constituents} & watch_codes
        board_meta = BoardMeta(
            board=board,
            index_kline=index_kline,
            constituents=constituents,
            highlight=highlight,
        )
        targets = constituents
        if only_watchlist:
            targets = [(c, n) for c, n in constituents if c in highlight]
        return targets, board_meta

    if hot is not None:
        from kan import hot as hot_mod

        entries = hot_mod.fetch_hot_list(hot)               # raises HotListUnavailableError
        watch_codes = {code for code, _ in watchlist_pairs}
        highlight = {e.symbol for e in entries} & watch_codes
        hot_meta = HotMeta(
            list_name=hot_mod.hot_list_name(hot),
            rank_map={e.symbol: e.rank for e in entries},
            highlight=highlight,
        )
        targets = [(e.symbol, e.name) for e in entries]
        if only_watchlist:
            targets = [(c, n) for c, n in targets if c in highlight]
        return targets, hot_meta

    return watchlist_pairs, None

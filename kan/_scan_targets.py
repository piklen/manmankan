"""扫描目标解析 · 7 命令共享。

industry 给定 → 拉行业成分股;否则用自选股。把 `--industry` 与自选的差异
收敛进 resolve_scan_targets 一个函数,各命令只需"换数据来源 + 多收一个
board_meta"。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kan.models import Board

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class BoardMeta:
    """resolve_scan_targets 在 industry 模式下的附加产物。"""

    board: Board
    index_kline: pd.DataFrame          # 板块指数 K(已归一化)
    constituents: list[tuple[str, str]]  # 全成分股 (代码, 名称)
    highlight: set[str]                  # 成分股代码 ∩ 自选股代码


def resolve_scan_targets(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], BoardMeta | None]:
    """解析扫描目标。

    - industry is None → (watchlist_pairs, None) · 现有行为完全不变
    - industry 给定 → 拉成分股 + 板块指数 K,组 BoardMeta
        - only_watchlist=True → targets 取成分股 ∩ 自选
    - 行业未找到 → 透传 boards.BoardNotFoundError
    - 数据源失败 → 透传 boards.BoardDataUnavailableError
    """
    if industry is None:
        return watchlist_pairs, None

    from kan import boards

    board = boards.search_industry(industry)            # raises BoardNotFoundError
    constituents = boards.get_industry_constituents(board)
    index_kline = boards.fetch_industry_kline(board)
    watch_codes = {code for code, _ in watchlist_pairs}
    highlight = {code for code, _ in constituents} & watch_codes
    meta = BoardMeta(
        board=board,
        index_kline=index_kline,
        constituents=constituents,
        highlight=highlight,
    )
    targets = constituents
    if only_watchlist:
        targets = [(c, n) for c, n in constituents if c in highlight]
    return targets, meta

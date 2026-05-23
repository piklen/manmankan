"""扫描目标解析 · scan/low/high/trend/fetch 共享。

industry 给定 → 拉行业成分股;
hot 给定 → 拉东财热榜;
theme 给定 → 拉题材成分股(F11);
否则用自选股。

四种来源的差异收敛进 resolve_scan_targets 一个函数,各命令只需"换数据来源
+ 多收一个 meta"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kan.models import Board, Theme

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


@dataclass
class ThemeMeta:
    """resolve_scan_targets 在 theme 模式下的附加产物 · 跟 BoardMeta 对称。"""

    theme: Theme
    index_kline: pd.DataFrame              # EM 题材指数 K(已 rename)· K 线失败时为空 DataFrame
    constituents: list[tuple[str, str]]    # 全成分股(THS 拉)
    highlight: set[str]                    # 成分股 ∩ 自选
    source_dispatch: dict[str, str] = field(
        default_factory=lambda: {
            "catalog": "ths",
            "cons": "ths",
            "kline": "em",
            "reverse": "em",
        }
    )


def resolve_scan_targets(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
    hot: HotList | None = None,
    theme: str | None = None,
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | ThemeMeta | None]:
    """解析扫描目标。

    - industry / hot / theme 都为 None → (watchlist_pairs, None) · 现有行为完全不变
    - industry 给定 → 拉成分股 + 板块指数 K,组 BoardMeta
    - hot 给定 → 拉东财热榜,组 HotMeta
    - theme 给定 → 拉题材成分股(THS)+ 题材指数 K(EM),组 ThemeMeta
        - only_watchlist=True → targets = 成分股 ∩ 自选
    - 三者同时给定 → raise ValueError
    - 题材未找到 → 透传 boards.ThemeNotFoundError
    - 题材数据源失败 → 透传 boards.ThemeDataUnavailableError(K 线失败降级为空 df)
    """
    given = sum(1 for x in (industry, hot, theme) if x is not None)
    if given > 1:
        raise ValueError("--industry / --hot / --theme 三者互斥 · 同时只能用一个")

    if industry is not None:
        from kan import boards

        board = boards.search_industry(industry)
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

        entries = hot_mod.fetch_hot_list(hot)
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

    if theme is not None:
        import pandas as pd

        from kan import boards
        from kan.boards import ThemeDataUnavailableError

        themed = boards.search_theme(theme)
        constituents = boards.get_theme_constituents(themed)

        # K 线失败降级为空 df · 不影响成分股扫描(spec §11)
        try:
            index_kline = boards.fetch_theme_kline(themed)
        except ThemeDataUnavailableError as e:
            from kan._log import debug_log

            debug_log(__name__, f"fetch theme kline · theme={themed.name}", e)
            index_kline = pd.DataFrame()

        watch_codes = {code for code, _ in watchlist_pairs}
        highlight = {code for code, _ in constituents} & watch_codes
        theme_meta = ThemeMeta(
            theme=themed,
            index_kline=index_kline,
            constituents=constituents,
            highlight=highlight,
        )
        targets = constituents
        if only_watchlist:
            targets = [(c, n) for c, n in constituents if c in highlight]
        return targets, theme_meta

    return watchlist_pairs, None

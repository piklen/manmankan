"""扫描目标解析 · 历史 API + meta 类型 re-export 入口 (deprecated layer)。

历史背景本模块沉降为兼容层:
- `BoardMeta / HotMeta / ThemeMeta` 三个 dataclass 已迁到 `kan.core.models`
  (跟 Board / Theme 同地存放)。本文件 re-export 保留旧 import path 不破坏老 caller。
- `resolve_scan_targets()` 改为 thin wrapper · 内部走 `kan.core.stock_set.from_flags()` ·
  CLI 层不再直接调用本函数 (改用 StockSet)。本函数仍保留供 test_scan_targets 等老
  测试 + 第三方脚本使用 (行为完全等价)。

新代码请用:
    from kan.core.stock_set import from_flags
    stock_set = from_flags(industry=..., hot=..., theme=...,
                            watchlist_pairs=..., only_watchlist=...)
    pairs = stock_set.pairs()
    meta = stock_set.meta
"""
from __future__ import annotations

from typing import TYPE_CHECKING

# Re-export · 旧路径 `from kan.core.scan_targets import BoardMeta` 仍 work
from kan.core.models import BoardMeta, HotMeta, ThemeMeta

if TYPE_CHECKING:
    from kan.data.hot import HotList

__all__ = ["BoardMeta", "HotMeta", "ThemeMeta", "resolve_scan_targets"]


def resolve_scan_targets(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
    hot: HotList | None = None,
    theme: str | None = None,
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | ThemeMeta | None]:
    """[deprecated] 解析扫描目标 · 已改为 stock_set.from_flags 的 thin wrapper。

    行为契约不变 (现有测试覆盖):
    - industry / hot / theme 都为 None → (watchlist_pairs, None) · 不触发任何 IO
    - industry / hot / theme 任一给定 → 拉对应 source · 组 meta · 应用 only_watchlist 过滤
    - 三者同时给定 → ValueError("--industry / --hot / --theme 三者互斥 ...")
    - 上游异常 (BoardNotFound / ThemeNotFound / HotListUnavailable /
      ThemeDataUnavailable) 直接 propagate (caller 负责转 typer.Exit)
    """
    given = sum(1 for x in (industry, hot, theme) if x is not None)
    if given > 1:
        raise ValueError("--industry / --hot / --theme 三者互斥 · 同时只能用一个")

    # 三源都 None · 早返 · 不构造 StockSet (跟旧版语义对齐:零 IO)
    if industry is None and hot is None and theme is None:
        return watchlist_pairs, None

    from kan.core.stock_set import from_flags

    stock_set = from_flags(
        industry=industry,
        hot=hot,
        theme=theme,
        watchlist_pairs=watchlist_pairs,
        only_watchlist=only_watchlist,
    )
    return stock_set.pairs(), stock_set.meta()

"""CLI 数据命令的脊椎与共享 helper · scan/low/high/trend/info/fetch 共用。

行为保持型 helper:把 resolve_scan_targets 的 5 类 source 错误统一收成
typer.Exit;后续会在此基础上扩成完整数据流水线 orchestrator(聚合新鲜度、
统一格式分发、注入 compute 等)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from kan._scan_targets import resolve_scan_targets
from kan.boards import (
    BoardDataUnavailableError,
    BoardNotFoundError,
    ThemeDataUnavailableError,
    ThemeNotFoundError,
)
from kan.cli_helpers import _print_err
from kan.hot import HotListUnavailableError

if TYPE_CHECKING:
    from kan._scan_targets import BoardMeta, HotMeta, ThemeMeta
    from kan.hot import HotList


def resolve_targets_or_exit(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
    *,
    hot: HotList | None = None,
    theme: str | None = None,
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | ThemeMeta | None]:
    """resolve_scan_targets 的 CLI 友好包装 · 5 类 source 错误 → _print_err + typer.Exit。

    退出码沿用现有命令(行为保持):
      - BoardNotFound / BoardDataUnavailable / HotListUnavailable
        / ThemeDataUnavailable → Exit(1)
      - ThemeNotFound → Exit(2)(theme 名 typo 视为用户输入错,与命令现状一致)

    错误文案取最完整版本(带场景提示和后续动作引导)。各命令调本 helper 后
    可从 ~12 行 try/except 块塌成 1 行 `targets, meta = resolve_targets_or_exit(...)`。
    """
    try:
        return resolve_scan_targets(
            industry, only_watchlist, watchlist_pairs,
            hot=hot, theme=theme,
        )
    except BoardNotFoundError:
        _print_err(
            f"❌ 未找到行业「{industry}」· 可试更短关键词(如「半导体」「白酒」)"
        )
        raise typer.Exit(1) from None
    except BoardDataUnavailableError:
        _print_err("❌ 行业数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    except HotListUnavailableError:
        _print_err("❌ 热榜数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    except ThemeNotFoundError:
        _print_err(
            f"❌ 未找到题材「{theme}」· 试更短关键词(如「AI」「华为」) · "
            "或跑 kan theme search 看候选"
        )
        raise typer.Exit(2) from None
    except ThemeDataUnavailableError:
        _print_err(
            "❌ 题材数据源暂时不可用 · 稍后再试 · 行业扫描可用(--industry)"
        )
        raise typer.Exit(1) from None

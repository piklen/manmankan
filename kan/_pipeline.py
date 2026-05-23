"""CLI 数据命令的脊椎与共享 helper · scan/low/high/trend/info/fetch 共用。

行为保持型 helper:
  - resolve_targets_or_exit:把 resolve_scan_targets 的 5 类 source 错误统一收成
    typer.Exit。
  - Freshness + freshness_of:跨 symbols 聚合 max data_cutoff 与 max cache_age,
    一并推导 is_stale / phase。
  - render_freshness_warning:在终端打 stale / 盘中 互斥警告(各命令复用同一份
    措辞,告别 3 处逐字 markup 复制)。

后续会在此基础上扩成完整数据流水线 orchestrator(注入 compute、统一格式分发等)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
    from collections.abc import Iterable
    from datetime import date

    from kan._scan_targets import BoardMeta, HotMeta, ThemeMeta
    from kan.hot import HotList


# ── 目标源错误统一处理 ────────────────────────────────────────────────


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


# ── 数据新鲜度聚合 ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Freshness:
    """跨 symbols 的数据新鲜度聚合 + 推导状态。

    data_cutoff     = max(data_cutoff_date(sym) for sym in symbols) · None 若全 None
    fetched_at      = max(cache_age(sym) for sym in symbols)(ISO datetime string)
    expected_cutoff = latest_trade_date() (helper 调用时的快照)
    is_stale        = data_cutoff is None or data_cutoff < expected_cutoff
    phase           = market_phase() snapshot

    frozen=True · helper 返回不可变快照 · 命令侧只读不改。
    """

    data_cutoff: date | None
    fetched_at: str | None
    expected_cutoff: date
    is_stale: bool
    phase: str


def freshness_of(symbols: Iterable[str]) -> Freshness:
    """聚合 symbols 列表的 max data_cutoff 与 max cache_age · 推导 is_stale / phase。

    用法:
        freshness = freshness_of(r.symbol for r in results)
        if freshness.data_cutoff:
            title += f" · 数据截止 {format_date_compact(freshness.data_cutoff)} 收盘"
        if freshness.is_stale: ...

    空 symbols / 所有 symbols 都无 cutoff → data_cutoff = None · is_stale = True
    (与 v0.0.4.5+ 各命令的现状一致:无缓存视为 stale)。
    """
    from kan.fetcher import cache_age, data_cutoff_date
    from kan.trading_calendar import latest_trade_date, market_phase

    data_cutoff: date | None = None
    fetched_at: str | None = None
    for sym in symbols:
        d = data_cutoff_date(sym)
        if d is not None and (data_cutoff is None or d > data_cutoff):
            data_cutoff = d
        t = cache_age(sym)
        if t and (fetched_at is None or t > fetched_at):
            fetched_at = t
    expected = latest_trade_date()
    is_stale = data_cutoff is None or data_cutoff < expected
    return Freshness(
        data_cutoff=data_cutoff,
        fetched_at=fetched_at,
        expected_cutoff=expected,
        is_stale=is_stale,
        phase=market_phase(),
    )


# ── 新鲜度警告渲染 ───────────────────────────────────────────────────


def render_freshness_warning(freshness: Freshness, console: Any) -> None:
    """在终端打 stale / 盘中 互斥警告 · 跟 v0.0.4.7 ***REMOVED*** 行为完全一致。

    优先级互斥:if is_stale → 缓存滞后警告 · elif 盘中 → 实时状态警告 · else 静默。
    理由(v0.0.4.7 ***REMOVED***):stale 状态下用户首动作是 fetch · fetch 后会重 scan · 再判 intraday。

    无 cutoff 时显「无缓存」+ days_behind 显「?」(罕见但需兜底)。

    console 参数 duck-typed · 任何有 .print(str) 方法的对象都接受(rich.Console / Mock 等)。
    """
    from kan.cli_helpers import format_date_compact
    from kan.trading_calendar import PHASE_INTRADAY

    if freshness.is_stale:
        cutoff_str = (
            format_date_compact(freshness.data_cutoff)
            if freshness.data_cutoff else "无缓存"
        )
        expected_str = format_date_compact(freshness.expected_cutoff)
        days_behind = (
            (freshness.expected_cutoff - freshness.data_cutoff).days
            if freshness.data_cutoff else "?"
        )
        console.print(
            f"\n  [bold yellow]⚠️ 当前缓存到 {cutoff_str} 收盘 · "
            f"最近交易日是 {expected_str} · 数据滞后 {days_behind} 天\n"
            "   运行 `kan fetch --force` 拉取最新数据[/bold yellow]"
        )
    elif freshness.phase == PHASE_INTRADAY:
        console.print(
            "\n  [bold yellow]⚠️ 当前盘中 · 涨跌停标签反映当前时刻 · 非收盘 final\n"
            "   (盘中价格仍在变动 · 涨停/跌停状态可能与收盘不同)\n"
            "   建议盘后 15:30 后看 final 数据[/bold yellow]"
        )

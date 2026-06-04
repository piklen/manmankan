"""CLI 数据命令的脊椎与共享 helper · scan/low/high/trend/fetch 共用。

历史背景 (cleanup): 老 `resolve_targets_or_exit` + `run_data_pipeline` 双签名重载
已移除 · CLI 全部走 StockSet 单一路径。

helpers:
  - resolve_stock_set:触发 StockSet.pairs() / .meta() · 把 5 类 source
    错误统一收成 StockSetResolveError。
  - resolve_stock_set_or_exit:CLI 兼容 adapter · 把 StockSetResolveError 转为
    typer.Exit。
  - Freshness + freshness_of:跨 symbols 聚合 max data_cutoff 与 max cache_age,
    一并推导 is_stale / phase。
  - render_freshness_warning:在终端打 stale / 盘中 互斥警告。
  - run_data_pipeline (StockSet 单签名):resolve → auto_fetch → compute → freshness
    一次性编排。各命令注入自己的 compute (scan_batch / trend_batch / ...)。
"""
from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from kan.data.boards import (
    BoardDataUnavailableError,
    BoardNotFoundError,
    ThemeDataUnavailableError,
    ThemeNotFoundError,
)
from kan.data.hot import HotListUnavailableError
from kan.infra.log import debug_log

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.core.stock_set import StockSet


# ── 目标源错误统一处理 (StockSet 路径) ─────────────────────────────────


class StockSetResolveError(Exception):
    """Domain-level stock-set resolution error.

    CLI adapters may render `message` and exit with `exit_code`; service/web
    callers can catch this exception without importing Typer.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        exit_code: int,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.__cause__ = cause


def _print_err(message: str) -> None:
    """CLI error printer adapter, kept patchable for existing tests."""
    from kan.cli.helpers import _print_err as print_err

    print_err(message)


def raise_stock_set_resolve_exit(error: StockSetResolveError) -> NoReturn:
    """Render a StockSetResolveError through the CLI error channel and exit."""
    import typer

    _print_err(error.message)
    raise typer.Exit(error.exit_code)


def resolve_stock_set(
    stock_set: StockSet,
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | ThemeMeta | None]:
    """触发 stock_set.pairs() + .meta() · 把上游异常转 StockSetResolveError。

    错误 exit_code:
      - BoardNotFound / BoardDataUnavailable / HotListUnavailable
        / ThemeDataUnavailable → 1
      - ThemeNotFound → 2 (typo 视为用户输入错)

    错误文案带场景提示 + 后续动作引导，但本函数不打印、不退出；CLI 边界调用
    resolve_stock_set_or_exit / raise_stock_set_resolve_exit 负责展示。

    industry / theme 名从 stock_set 属性 (IndustrySet.industry / ThemeSet.theme)
    抽取 · 用于错误文案中引用用户原始输入。HotRankSet / WatchlistSet 无此属性 ·
    getattr 安全 fallback 到 None。
    """
    industry_name = getattr(stock_set, "industry", None)
    theme_name = getattr(stock_set, "theme", None)
    try:
        targets = stock_set.pairs()
        meta = stock_set.meta()
        return targets, meta
    except BoardNotFoundError:
        raise StockSetResolveError(
            code="board_not_found",
            message=f"❌ 未找到行业「{industry_name}」· 可试更短关键词(如「半导体」「白酒」)",
            exit_code=1,
        ) from None
    except BoardDataUnavailableError as e:
        debug_log(__name__, "industry data fetch failed", e)
        raise StockSetResolveError(
            code="board_data_unavailable",
            message="❌ 行业数据源暂时不可用,稍后再试",
            exit_code=1,
            cause=e,
        ) from e
    except HotListUnavailableError as e:
        debug_log(__name__, "hot list fetch failed", e.__cause__ or e)
        raise StockSetResolveError(
            code="hot_list_unavailable",
            message=(
                f"❌ 东财热榜源暂时不可用 · 可能东财接口波动 / 限流 ({e})\n"
                "   替代:`kan scan --industry <行业名>` 或 `kan scan --theme=<题材>`\n"
                "   详情设 KAN_DEBUG=1 跑同命令看底层错误"
            ),
            exit_code=1,
            cause=e,
        ) from e
    except ThemeNotFoundError:
        raise StockSetResolveError(
            code="theme_not_found",
            message=(
                f"❌ 未找到题材「{theme_name}」· 试更短关键词(如「AI」「华为」) · "
                "或跑 kan theme search 看候选"
            ),
            exit_code=2,
        ) from None
    except ThemeDataUnavailableError as e:
        debug_log(__name__, "theme data fetch failed", e.__cause__ or e)
        raise StockSetResolveError(
            code="theme_data_unavailable",
            message="❌ 题材数据源暂时不可用 · 稍后再试 · 行业扫描可用(--industry)",
            exit_code=1,
            cause=e,
        ) from e


def resolve_stock_set_or_exit(
    stock_set: StockSet,
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | ThemeMeta | None]:
    """CLI adapter for resolve_stock_set, preserving existing Typer exits."""
    try:
        return resolve_stock_set(stock_set)
    except StockSetResolveError as e:
        raise_stock_set_resolve_exit(e)


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
    (与 历史背景各命令的现状一致:无缓存视为 stale)。
    """
    from kan.core.trading_calendar import latest_trade_date, market_phase
    from kan.data.fetcher import cache_age, data_cutoff_date

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
    """在终端打 stale / 盘中 互斥警告。

    优先级互斥:if is_stale → 缓存滞后警告 · elif 盘中 → 实时状态警告 · else 静默。
    理由:stale 状态下用户首动作是 fetch · fetch 后会重 scan · 再判 intraday。

    无 cutoff 时显「无缓存」+ days_behind 显「?」(罕见但需兜底)。

    console 参数 duck-typed · 任何有 .print(str) 方法的对象都接受(rich.Console / Mock 等)。
    """
    from kan.cli.helpers import format_date_compact
    from kan.core.trading_calendar import PHASE_INTRADAY

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


# ── 数据命令统一流水线 ───────────────────────────────────────────────


@dataclass(frozen=True)
class DataCtx:
    """数据命令流水线的产出快照 · 命令层只读不改。

    一次调用产出 4 样东西:
      - targets:  StockSet 解析出的 (symbol, name) 列表 (可能含板块成分股 / 热榜 / 题材)
      - meta:     BoardMeta / HotMeta / ThemeMeta / None (无 source 时)
      - results:  compute(targets, **kwargs) 的原始返回 (未做命令侧过滤)
      - freshness: 基于 results 的 symbols 聚合的 Freshness
      - source_name: StockSet 展示名 (自选股 / 自定义代码池等)

    frozen=True · 命令侧从 ctx 解构后做 filter / format · 不回填到 ctx。
    """

    targets: list[tuple[str, str]]
    meta: BoardMeta | HotMeta | ThemeMeta | None
    results: list
    freshness: Freshness
    source_name: str = ""


def run_data_pipeline(
    stock_set: StockSet,
    *,
    compute: Callable,
    show_progress: bool = True,
    exit_on_resolve_error: bool = True,
    fetch_days: int | None = None,
    **compute_kwargs: Any,
) -> DataCtx:
    """resolve → auto_fetch → compute → freshness 的统一编排 (StockSet 单签名)。

    历史背景 (cleanup) · 老签名 ``run_data_pipeline(industry, only_watchlist,
    watchlist_pairs, *, hot=..., theme=..., compute=...)`` 已移除 · 调用方必须先
    构造 StockSet (`from_flags(...)`) · 再传本函数。

    收口顺序:
      1. resolve_stock_set:触发 stock_set.pairs() + .meta() · 把 5 类 source 错误
         统一成 StockSetResolveError；默认保持 CLI 旧行为转 typer.Exit
      2. _auto_fetch_stale:对落后 / 缺失的 symbols 静默补缺 (网络相关 / 不阻塞)
      3. compute(targets, **compute_kwargs):各命令注入自己的批处理函数
         (scan_batch / trend_batch · 都接 `(targets, **kwargs)` · 要求 result 元素
         有 .symbol 属性供 freshness 聚合)
      4. freshness_of:遍历 results 的 .symbol · 聚合 max(data_cutoff) + max(cache_age)

    设计要点:
      - compute 是 Callable 注入而非内部 dispatch · 不需要为 scan/trend 各开一条
        分支 · 也方便后续命令 (如 trend backtest) 复用
      - **compute_kwargs 把 scan/trend 各自的旋钮 (mode / candle / ...) 透传 ·
        本 helper 不关心也不解释
      - freshness 在原始 results 上算 · 命令侧 exclude_st / --signal / --down
        等过滤是「展示侧」选择,不应该改「我们刚加载了什么数据」的事实
    """
    from kan.cli.helpers import _auto_fetch_stale

    try:
        targets, meta = resolve_stock_set(stock_set)
    except StockSetResolveError as e:
        if not exit_on_resolve_error:
            raise
        raise_stock_set_resolve_exit(e)
    if show_progress:
        if fetch_days is None:
            _auto_fetch_stale(targets)
        else:
            _auto_fetch_stale(targets, days=fetch_days)
    else:
        with contextlib.redirect_stderr(io.StringIO()):
            if fetch_days is None:
                _auto_fetch_stale(targets)
            else:
                _auto_fetch_stale(targets, days=fetch_days)
    results = compute(targets, **compute_kwargs)
    freshness = freshness_of(r.symbol for r in results)
    return DataCtx(
        targets=targets,
        meta=meta,
        results=results,
        freshness=freshness,
        source_name=getattr(stock_set, "name", ""),
    )

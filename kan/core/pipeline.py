"""CLI 数据命令的脊椎与共享 helper · scan/low/high/trend/fetch 共用。

CLI 全部走 StockSet 单一路径(resolve → auto_fetch → compute → freshness)。

helpers:
  - resolve_stock_set:触发 StockSet.pairs() / .meta() · 把 5 类 source
    错误统一收成 StockSetResolveError。
  - resolve_stock_set_or_exit:CLI adapter · 把 StockSetResolveError 转为
    typer.Exit。
  - Freshness + freshness_of:跨 symbols 聚合 max data_cutoff 与 max cache_age,
    一并推导 is_stale / phase。
  - render_freshness_warning:在终端打 stale / 盘中 互斥警告。
  - run_data_pipeline (StockSet 单签名):resolve → auto_fetch → compute → freshness
    一次性编排。各命令注入自己的 compute (scan_batch / trend_batch / ...)。
"""
from __future__ import annotations

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
from kan.data.tushare import TushareDataContractError
from kan.infra.log import debug_log

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from kan.core.models import BoardMeta, HotMeta, ThemeMeta
    from kan.core.stock_set import StockSet
    from kan.infra.lifecycle import OperationLifecycle


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
    from kan.infra.console import print_err

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
    except TushareDataContractError as e:
        debug_log(__name__, "tushare contract validation failed", e)
        raise StockSetResolveError(
            code="tushare_data_contract_error",
            message=(
                f"❌ 全市场数据不完整：{e}\n"
                "   manmankan 已按 Tushare 官方请求语义停止处理，且未写入错误缓存\n"
                "   请检查当前配置的数据源是否完整兼容对应 Tushare 接口"
            ),
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
    min_cutoff      = min(有效截止日) · 用于识别整池日期不一致
    missing_count   = 无有效截止日的候选数
    current_count   = 已到 expected_cutoff 的候选数
    history_incomplete_count = 有缓存但历史行数不足 required_rows 的候选数
    required_rows   = 调用方声明的最小历史行数
    fetched_at      = max(cache_age(sym) for sym in symbols)(ISO datetime string)
    expected_cutoff = latest_trade_date() (helper 调用时的快照)
    is_stale        = 空池 / 任一缺失 / 任一截止日不等于 expected_cutoff
    phase           = market_phase() snapshot

    frozen=True · helper 返回不可变快照 · 命令侧只读不改。
    """

    data_cutoff: date | None
    fetched_at: str | None
    expected_cutoff: date
    is_stale: bool
    phase: str
    min_cutoff: date | None = None
    missing_count: int = 0
    current_count: int = 0
    target_count: int = 0
    history_incomplete_count: int = 0
    required_rows: int | None = None


def freshness_of(symbols: Iterable[str], *, min_rows: int | None = None) -> Freshness:
    """聚合 symbols 列表的 max data_cutoff 与 max cache_age · 推导 is_stale / phase。

    用法:
        freshness = freshness_of(r.symbol for r in results)
        if freshness.data_cutoff:
            title += f" · 数据截止 {format_date_compact(freshness.data_cutoff)} 收盘"
        if freshness.is_stale: ...

    空 symbols / 所有 symbols 都无 cutoff → data_cutoff = None · is_stale = True
    (与各命令的现状一致:无缓存视为 stale)。
    """
    from kan.core.trading_calendar import latest_trade_date, market_phase
    from kan.data.fetcher import cache_age, cache_has_min_rows, data_cutoff_date

    symbol_list = list(symbols)
    cutoffs: list[date] = []
    cutoff_entries: list[tuple[str, date | None]] = []
    fetched_at: str | None = None
    for sym in symbol_list:
        d = data_cutoff_date(sym)
        cutoff_entries.append((sym, d))
        if d is not None:
            cutoffs.append(d)
        t = cache_age(sym)
        if t and (fetched_at is None or t > fetched_at):
            fetched_at = t
    expected = latest_trade_date()
    data_cutoff = max(cutoffs, default=None)
    min_cutoff = min(cutoffs, default=None)
    missing_count = len(symbol_list) - len(cutoffs)
    current_count = sum(cutoff == expected for cutoff in cutoffs)
    required_rows = min_rows if min_rows is not None and min_rows > 0 else None
    history_incomplete_count = (
        sum(
            1
            for symbol, cutoff in cutoff_entries
            if cutoff is not None and not cache_has_min_rows(symbol, required_rows)
        )
        if required_rows is not None
        else 0
    )
    is_stale = (
        not symbol_list
        or missing_count > 0
        or any(cutoff != expected for cutoff in cutoffs)
        or history_incomplete_count > 0
    )
    return Freshness(
        data_cutoff=data_cutoff,
        fetched_at=fetched_at,
        expected_cutoff=expected,
        is_stale=is_stale,
        phase=market_phase(),
        min_cutoff=min_cutoff,
        missing_count=missing_count,
        current_count=current_count,
        target_count=len(symbol_list),
        history_incomplete_count=history_incomplete_count,
        required_rows=required_rows,
    )


# ── 新鲜度警告渲染 ───────────────────────────────────────────────────


def render_freshness_warning(
    freshness: Freshness,
    console: Any,
    *,
    refresh_hint: str = "kan fetch --force",
) -> None:
    """在终端打 stale / 盘中 互斥警告。

    优先级互斥:if is_stale → 缓存滞后警告 · elif 盘中 → 实时状态警告 · else 静默。
    理由:stale 状态下用户首动作是 fetch · fetch 后会重 scan · 再判 intraday。

    无 cutoff 时显「无缓存」+ days_behind 显「?」(罕见但需兜底)。

    console 参数 duck-typed · 任何有 .print(str) 方法的对象都接受(rich.Console / Mock 等)。
    """
    from kan.core.trading_calendar import PHASE_INTRADAY
    from kan.infra.formatting import format_date_compact

    oldest_cutoff = freshness.min_cutoff or freshness.data_cutoff
    latest_incomplete = (
        freshness.data_cutoff is None
        or freshness.missing_count > 0
        or (oldest_cutoff is not None and oldest_cutoff != freshness.expected_cutoff)
    )

    if freshness.is_stale and latest_incomplete:
        expected_str = format_date_compact(freshness.expected_cutoff)
        # 部分滞后:已有股票到最新交易日,但整体不齐 — 不能断言「当前缓存到最旧日」
        stale_count = (
            freshness.target_count - freshness.current_count
            if freshness.target_count > 0
            else 0
        )
        if (
            freshness.current_count > 0
            and stale_count > 0
            and freshness.data_cutoff is not None
        ):
            oldest_str = (
                format_date_compact(oldest_cutoff) if oldest_cutoff else "无缓存"
            )
            console.print(
                f"\n  [bold yellow]⚠️ {stale_count}/{freshness.target_count} 只股票数据滞后"
                f" · 最新 {format_date_compact(freshness.data_cutoff)} 收盘"
                f" · 最旧 {oldest_str}\n"
                f"   运行 `{refresh_hint}` 拉取最新数据[/bold yellow]"
            )
            return
        warning_cutoff = oldest_cutoff
        cutoff_str = (
            format_date_compact(warning_cutoff)
            if warning_cutoff else "无缓存"
        )
        days_behind = (
            (freshness.expected_cutoff - warning_cutoff).days
            if warning_cutoff else "?"
        )
        console.print(
            f"\n  [bold yellow]⚠️ 当前缓存到 {cutoff_str} 收盘 · "
            f"最近交易日是 {expected_str} · 数据滞后 {days_behind} 天\n"
            f"   运行 `{refresh_hint}` 拉取最新数据[/bold yellow]"
        )
    elif freshness.history_incomplete_count > 0:
        console.print(
            f"\n  [bold yellow]⚠️ 最新数据已到 "
            f"{format_date_compact(freshness.expected_cutoff)} 收盘 · "
            f"{freshness.history_incomplete_count} 只股票可用历史不足 "
            f"{freshness.required_rows or '?'} 个交易日\n"
            "   新股会自然缺少历史；连续天数按现有数据计算[/bold yellow]"
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
    auto_fetch: bool = True,
    lifecycle: OperationLifecycle | None = None,
    **compute_kwargs: Any,
) -> DataCtx:
    """resolve → auto_fetch → compute → freshness 的统一编排 (StockSet 单签名)。

    调用方先构造 StockSet (`from_flags(...)`) 再传入;本函数只认 StockSet,
    不做 industry/hot/theme 分发。

    收口顺序:
      1. resolve_stock_set:触发 stock_set.pairs() + .meta() · 把 5 类 source 错误
         统一成 StockSetResolveError；默认保持 CLI 旧行为转 typer.Exit
      2. _auto_fetch_stale:对落后 / 缺失的 symbols 静默补缺 (网络相关 / 不阻塞)
      3. compute(targets, **compute_kwargs):各命令注入自己的批处理函数
         (scan_batch / trend_batch · 都接 `(targets, **kwargs)` · 要求 result 元素
         有 .symbol 属性供 freshness 聚合)
      4. freshness_of:遍历全部 targets · 缺缓存的候选也必须计入新鲜度

    设计要点:
      - compute 是 Callable 注入而非内部 dispatch · 不需要为 scan/trend 各开一条
        分支 · 也方便后续命令 (如 trend backtest) 复用
      - **compute_kwargs 把 scan/trend 各自的旋钮 (mode / candle / ...) 透传 ·
        本 helper 不关心也不解释
      - freshness 在全部 targets 上算 · compute 可能跳过无缓存候选,不能因此把
        不完整结果误报为整池最新；命令侧过滤同样不影响这个事实
      - auto_fetch=False 是本地 Web/测试等只读缓存路径的显式开关;默认 True 保持 CLI 行为
    """
    from kan.core.auto_fetch import auto_fetch_stale

    del show_progress  # 兼容旧 Python API；展示策略由 CLI reporter 决定。
    if lifecycle is not None:
        lifecycle.phase("解析股票池")
    try:
        targets, meta = resolve_stock_set(stock_set)
    except StockSetResolveError as e:
        if not exit_on_resolve_error:
            raise
        raise_stock_set_resolve_exit(e)
    if lifecycle is not None:
        lifecycle.progress(len(targets), len(targets), "股票池已解析")
    if auto_fetch:
        if fetch_days is None and lifecycle is None:
            auto_fetch_stale(targets)
        elif fetch_days is None:
            auto_fetch_stale(targets, lifecycle=lifecycle)
        elif lifecycle is None:
            auto_fetch_stale(targets, days=fetch_days)
        else:
            auto_fetch_stale(targets, days=fetch_days, lifecycle=lifecycle)
    if lifecycle is not None:
        lifecycle.phase("计算扫描结果", target_count=len(targets))
    results = compute(targets, **compute_kwargs)
    if lifecycle is not None:
        lifecycle.progress(len(results), len(targets), "扫描计算完成")
        lifecycle.phase("汇总数据新鲜度", target_count=len(targets))
    freshness = freshness_of(
        (symbol for symbol, _name in targets),
        min_rows=fetch_days,
    )
    return DataCtx(
        targets=targets,
        meta=meta,
        results=results,
        freshness=freshness,
        source_name=getattr(stock_set, "name", ""),
    )

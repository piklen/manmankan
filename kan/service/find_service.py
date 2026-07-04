"""Render-neutral find use cases.

This module owns pool resolution, data loading, enrichment, and filter matching
for `kan find`. CLI code remains responsible for Typer arguments and rendering.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from kan.core.find_registry import DIMENSIONS_UNSUPPORTED_IN_ALL, fields_need_kline
from kan.core.pipeline import StockSetResolveError, run_data_pipeline
from kan.service.find_service_data_gap import _any_rs, _find_data_gap
from kan.service.find_service_metadata import (
    _condition_dimensions,
    _cross_section_dimensions,
    _cross_section_needs_valuation_context,
    availability_dimensions,
    compact_dimensions,
    find_filters,
    find_pools,
    kline_ma_bias_periods,
    kline_scan_periods,
    kline_snapshot_periods,
)
from kan.service.find_service_models import (
    FindCodePoolResult,
    FindCrossSectionRequest,
    FindCrossSectionResult,
    FindKlineRequest,
    FindKlineResult,
    FindOutputProfile,
    FindServiceError,
)
from kan.service.find_service_sort import SORT_FIELD_GETTERS, _sorted_offset_limit

if TYPE_CHECKING:
    from kan.core.stock_set import StockSet


def run_find_cross_section(request: FindCrossSectionRequest) -> FindCrossSectionResult:
    """Run `kan find --all` cross-section use case."""
    conditions = request.conditions
    output = request.output
    if request.source_mode:
        raise FindServiceError(
            code="invalid_all_pool",
            message="--all 与 --industry / --hot / --theme / --codes 互斥",
            hint="例: kan find --all --pe lt:20 --format json",
            exit_code=2,
        )
    if conditions.needs_fundamentals():
        raise FindServiceError(
            code="unsupported_all_filter",
            message="--all 全市场截面不支持 --roe (fina_indicator 逐股，全市场约 5500 只代价高)",
            hint="例: kan find --industry 半导体 --roe gte:15 --format json",
            exit_code=2,
        )
    if conditions.needs_shareholder():
        raise FindServiceError(
            code="unsupported_all_filter",
            message="--all 全市场截面不支持 --holders/--top10/--north (股东数据逐股，全市场约 5500 只代价高)",
            hint="例: kan find --industry 半导体 --top10 gte:50 --format json",
            exit_code=2,
        )
    unsupported_fields = set(output.field_dimensions) & DIMENSIONS_UNSUPPORTED_IN_ALL
    if unsupported_fields:
        raise FindServiceError(
            code="invalid_fields",
            message=(
                "--all 全市场截面不支持这些 --fields 维度: "
                + ", ".join(sorted(unsupported_fields))
            ),
            hint=(
                "去掉逐股维度字段，或缩小候选池后再查。"
                "例: kan find --industry 半导体 --format json --fields @shareholder"
            ),
            exit_code=2,
        )
    if not output.is_export:
        raise FindServiceError(
            code="invalid_all_format",
            message="--all 截面取数请配 --format json 或 --format md (全市场约 5500 只，terminal 表格不适合)",
            hint="例: kan find --all --pe lt:20 --format json",
            exit_code=2,
        )

    from kan.core.cross_section import run_cross_section
    from kan.core.find_filter import apply_cross_section_conditions
    from kan.core.stock_set import AllStocksSet

    included_dimensions = _cross_section_dimensions(conditions, output=output)
    cs = run_cross_section(
        AllStocksSet(),
        need_kline=(
            conditions.has_kline_filters()
            or (output.compact and output.compact_context)
            or fields_need_kline(output.field_paths)
        ),
        kline_periods=kline_snapshot_periods(conditions),
        included_dimensions=included_dimensions,
        need_valuation_context=_cross_section_needs_valuation_context(output),
    )
    if not cs.rows:
        raise FindServiceError(
            code="data_unavailable",
            message="全市场截面无数据",
            hint=(
                "估值/量价/资金/行业分位依赖 tushare；"
                "例: kan config set tushare-token <你的_token>"
            ),
        )
    rows = cs.rows
    if conditions.needs_relative_strength():
        from kan.core.enrich import attach_relative_strength_cross_section

        rows = attach_relative_strength_cross_section(
            rows,
            index_periods=conditions.rs_index_periods(),
            board_periods=conditions.rs_board_periods(),
            index_code=request.rs_index_code,
        )
    matched = apply_cross_section_conditions(rows, conditions)
    limited = _sorted_offset_limit(
        matched, lambda it: it[0], request.sort, request.offset, request.limit
    )
    return FindCrossSectionResult(
        ctx=cs,
        matched=matched,
        limited=limited,
        query_time=_query_time(),
        filters=find_filters(conditions),
        included_dimensions=included_dimensions,
        compact_dimensions=compact_dimensions(conditions, is_export=output.is_export),
    )


def run_find_kline(
    request: FindKlineRequest,
) -> FindKlineResult | FindCodePoolResult:
    """Run non-`--all` find use case."""
    from kan.core.enrich import attach_relative_strength, enrich_results
    from kan.core.find_filter import apply_conditions
    from kan.core.scanner import scan_batch
    from kan.core.stock_set import CodeListSet, from_flags

    output = request.output
    source_mode = (
        request.industry is not None
        or request.hot is not None
        or request.theme is not None
        or request.code_pairs is not None
    )
    watchlist_pairs = (
        []
        if request.code_pairs is not None or request.only_holdings
        else _load_find_watchlist_pairs(
            request.group,
            require_non_empty=not source_mode and request.group is not None,
        )
    )

    stock_set: StockSet
    if request.code_pairs is not None:
        stock_set = CodeListSet(request.code_pairs)
    else:
        stock_set = from_flags(
            industry=request.industry,
            hot=request.hot,
            theme=request.theme,
            watchlist_pairs=watchlist_pairs,
            only_watchlist=request.only_watchlist,
            watchlist_group=request.group,
            only_holdings=request.only_holdings,
        )

    scan_periods = kline_scan_periods(request.conditions)
    ma_bias_periods = kline_ma_bias_periods(request.conditions)
    fetch_days = max(scan_periods) if scan_periods else None
    pipeline_kwargs = {}
    if not request.allow_auto_fetch:
        pipeline_kwargs["auto_fetch"] = False

    try:
        ctx = run_data_pipeline(
            stock_set,
            compute=scan_batch,
            mode="low",
            periods=scan_periods,
            ma_bias_periods=ma_bias_periods,
            fetch_days=fetch_days,
            show_progress=not output.is_export,
            exit_on_resolve_error=False,
            **pipeline_kwargs,
        )
    except StockSetResolveError as e:
        raise _find_error_from_stock_set(e) from e
    if not ctx.targets and request.only_watchlist:
        raise FindServiceError(
            code="empty_intersection",
            message="自选股与当前候选池没有交集",
            hint="例: 去掉 --only-watchlist，或先运行 kan add 600519 把目标股票加进自选",
        )
    if not ctx.targets and request.only_holdings:
        raise FindServiceError(
            code="empty_holdings",
            message="真实持仓为空",
            hint="例: kan hold add 600519 --cost 1680 --shares 100",
        )
    if not ctx.targets and not source_mode and request.group is None:
        raise FindServiceError(
            code="empty_watchlist",
            message="自选股和真实持仓为空",
            hint=(
                "例: kan add 600519；或 kan hold add 600519 --cost 1680 --shares 100；"
                "或 kan find --codes 600519 --format json"
            ),
        )
    if not ctx.results:
        raise FindServiceError(
            code="data_unavailable",
            message="候选池无可用 K 线数据 · 请先拉取数据或使用 --dry-run 预演查询计划",
            hint="例: kan scan --codes 600519,000858 --format json；或 kan find --codes 600519,000858 --format json --dry-run",
            exit_code=1,
        )

    effective_limit = request.limit if request.limit is not None else 50
    need_enrich = (
        (output.is_export and not output.field_paths)
        or request.conditions.has_cross_section_filters()
        or request.conditions.needs_fundamentals()
        or request.conditions.needs_shareholder()
        or bool(output.field_dimensions)
    )
    if need_enrich:
        pool_results = enrich_results(
            ctx.results,
            need_fundamentals=request.conditions.needs_fundamentals()
            or ("fundamentals" in output.field_dimensions),
            need_moneyflow=request.conditions.needs_moneyflow()
            or (output.is_export and request.conditions.is_empty() and not output.field_paths)
            or ("moneyflow" in output.field_dimensions),
            need_technical=request.conditions.needs_technical()
            or (output.is_export and request.conditions.is_empty() and not output.field_paths)
            or ("technical" in output.field_dimensions),
            need_sentiment=request.conditions.needs_sentiment()
            or (output.is_export and request.conditions.is_empty() and not output.field_paths)
            or ("sentiment" in output.field_dimensions),
            need_chip=request.conditions.needs_chip()
            or (output.is_export and request.conditions.is_empty() and not output.field_paths)
            or ("chip" in output.field_dimensions),
            need_shareholder=request.conditions.needs_shareholder()
            or ("shareholder" in output.field_dimensions),
        )
    else:
        pool_results = ctx.results
    try:
        from kan.storage.positions import load_positions

        cash = load_positions().cash
    except Exception:
        cash = None
    from kan.core.retail_facts import apply_retail_facts

    pool_results = [apply_retail_facts(r, cash=cash) for r in pool_results]
    if request.conditions.needs_relative_strength():
        pool_results = attach_relative_strength(
            pool_results,
            index_periods=request.conditions.rs_index_periods(),
            board_periods=request.conditions.rs_board_periods(),
            index_code=request.rs_index_code,
        )
    if request.exclude_star or request.exclude_bj:
        from kan.core.retail_facts import market_board

        pool_results = [
            r for r in pool_results
            if not (request.exclude_star and market_board(r.symbol) == "科创板")
            and not (request.exclude_bj and market_board(r.symbol) == "北交所")
        ]
    gap = _find_data_gap(request.conditions, pool_results)
    if gap is not None:
        code, message, hint = gap
        raise FindServiceError(code=code, message=message, hint=hint)
    matches = apply_conditions(pool_results, request.conditions)
    matches_limited = _sorted_offset_limit(
        matches, lambda m: m.result, request.sort, request.offset, effective_limit
    )
    return FindKlineResult(
        stock_set=stock_set,
        ctx=ctx,
        pool_results=pool_results,
        matches=matches,
        matches_limited=matches_limited,
        effective_limit=effective_limit,
        pools=find_pools(
            request.industry,
            request.hot,
            request.theme,
            request.group,
            request.code_pairs,
            request.only_holdings,
        ),
        filters=find_filters(request.conditions),
        query_time=_query_time(),
        included_dimensions=availability_dimensions(
            request.conditions,
            output=output,
            fields_mode=bool(output.field_paths),
        ),
        compact_dimensions=compact_dimensions(
            request.conditions,
            is_export=output.is_export,
        ),
    )


def _load_find_watchlist_pairs(
    group: str | None,
    *,
    require_non_empty: bool,
) -> list[tuple[str, str]]:
    from kan.storage.watchlist import GroupNotFoundError, load_watchlist

    try:
        pairs = [(s.symbol, s.name) for s in load_watchlist(group).stocks]
    except GroupNotFoundError as e:
        raise FindServiceError(
            code="group_not_found",
            message=str(e),
            hint="例: kan group list；或去掉 --group 使用 default 组",
            exit_code=2,
        ) from e
    if require_non_empty and not pairs:
        label = "自选" if not group else f"「{group}」组"
        suffix = "" if not group else f" --group {group}"
        raise FindServiceError(
            code="empty_watchlist",
            message=f"{label}列表为空",
            hint=f"例: kan add 600519 000858{suffix}；或用 --codes 指定外部代码池",
            exit_code=1,
        )
    return pairs


def _find_error_from_stock_set(error: StockSetResolveError) -> FindServiceError:
    message = error.message.removeprefix("❌ ").strip()
    return FindServiceError(
        code=error.code,
        message=message,
        exit_code=error.exit_code,
    )


def _query_time() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


__all__ = [
    "SORT_FIELD_GETTERS",
    "FindCodePoolResult",
    "FindCrossSectionRequest",
    "FindCrossSectionResult",
    "FindKlineRequest",
    "FindKlineResult",
    "FindOutputProfile",
    "FindServiceError",
    "_any_rs",
    "_condition_dimensions",
    "_find_data_gap",
    "_sorted_offset_limit",
    "availability_dimensions",
    "compact_dimensions",
    "find_filters",
    "find_pools",
    "kline_ma_bias_periods",
    "kline_scan_periods",
    "kline_snapshot_periods",
    "run_find_cross_section",
    "run_find_kline",
]

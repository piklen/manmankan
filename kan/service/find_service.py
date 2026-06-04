"""Render-neutral find use cases.

This module owns pool resolution, data loading, enrichment, and filter matching
for `kan find`. CLI code remains responsible for Typer arguments and rendering.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import TYPE_CHECKING, Any, Literal

from kan.core.find_registry import (
    DIMENSIONS_UNSUPPORTED_IN_ALL,
    FILTER_SPECS,
    condition_attr_for_filter,
    fields_need_kline,
    fields_need_valuation_context,
)
from kan.core.pipeline import DataCtx, StockSetResolveError, run_data_pipeline

if TYPE_CHECKING:
    from kan.core.cross_section import CrossSectionCtx, CrossSectionRow
    from kan.core.find_dsl import ConditionSet
    from kan.core.find_filter import FindMatch, TriggeredFilter
    from kan.core.stock_set import StockSet
    from kan.data.hot import HotList

FindOutputMode = Literal["terminal", "md", "json"]


class FindServiceError(Exception):
    """Domain-level find error, rendered by CLI/API adapters."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        hint: str | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


@dataclass(frozen=True)
class FindOutputProfile:
    """Requested result shape without depending on CLI OutputFormat."""

    mode: FindOutputMode
    compact: bool = False
    compact_context: bool = True
    field_paths: tuple[str, ...] = ()
    field_dimensions: frozenset[str] = frozenset()

    @property
    def is_export(self) -> bool:
        return self.mode != "terminal"


@dataclass(frozen=True)
class FindKlineRequest:
    conditions: ConditionSet
    output: FindOutputProfile
    code_pairs: list[tuple[str, str]] | None = None
    industry: str | None = None
    hot: HotList | None = None
    theme: str | None = None
    only_watchlist: bool = False
    group: str | None = None
    limit: int | None = None
    offset: int = 0
    sort: tuple[str, str] | None = None


@dataclass(frozen=True)
class FindCodePoolResult:
    stock_set: StockSet
    code_pairs: list[tuple[str, str]]
    pools: list[str]
    query_time: str


@dataclass(frozen=True)
class FindKlineResult:
    stock_set: StockSet
    ctx: DataCtx
    pool_results: list[Any]
    matches: list[FindMatch]
    matches_limited: list[FindMatch]
    effective_limit: int
    pools: list[str]
    filters: list[dict]
    query_time: str
    included_dimensions: set[str]
    compact_dimensions: set[str]

    @property
    def entries(self) -> list[tuple[FindMatch, Any]]:
        return [(m, m.result) for m in self.matches_limited]


def _nested(obj: object, attr: str, sub: str) -> float | None:
    """安全取 obj.<attr>.<sub> 数值(子对象/字段缺失 → None)· sort getter 共用。"""
    holder = getattr(obj, attr, None)
    val = getattr(holder, sub, None) if holder is not None else None
    return val if isinstance(val, (int, float)) else None


SORT_FIELD_GETTERS = {
    "pe": lambda o: _nested(o, "valuation", "pe_ttm"),
    "pb": lambda o: _nested(o, "valuation", "pb"),
    "turnover": lambda o: _nested(o, "valuation", "turnover_rate"),
    "market_cap": lambda o: _nested(o, "valuation", "total_mv"),
    "volume_ratio": lambda o: _nested(o, "valuation", "volume_ratio"),
    "moneyflow": lambda o: _nested(o, "moneyflow", "net_amount"),
    "moneyflow_daily": lambda o: _nested(o, "moneyflow", "net_amount"),
    "moneyflow_days": lambda o: _nested(o, "moneyflow", "inflow_days"),
}
"""--sort 支持字段 · key=用户输入名 · value=从 match.result / 截面 row 取裸值。"""


def _sorted_offset_limit(
    items: list,
    key_obj: Any,
    sort: tuple[str, str] | None,
    offset: int,
    limit: int | None,
) -> list:
    """按 sort 排序(None 值恒排末尾)后做 offset/limit 切片 · K 线池 + 截面两路径共用。

    sort: (field, "asc"|"desc") · field 必在 SORT_FIELD_GETTERS(cmds 已校验)。
    key_obj: item → 取字段的对象(K 线池=FindMatch.result · 截面=row tuple[0])。
    """
    out = items
    if sort is not None:
        field, direction = sort
        getter = SORT_FIELD_GETTERS.get(field)
        if getter is not None:
            reverse = direction == "desc"

            def _key(it: Any) -> tuple:
                v = getter(key_obj(it))
                if v is None:
                    return (1, 0.0)  # None 恒排末尾(不论 asc/desc)
                return (0, -v if reverse else v)

            out = sorted(items, key=_key)
    start = max(0, offset)
    end = None if limit is None else start + limit
    return out[start:end]


@dataclass(frozen=True)
class FindCrossSectionRequest:
    conditions: ConditionSet
    output: FindOutputProfile
    source_mode: bool = False
    limit: int | None = None
    offset: int = 0
    sort: tuple[str, str] | None = None


@dataclass(frozen=True)
class FindCrossSectionResult:
    ctx: CrossSectionCtx
    matched: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]]
    limited: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]]
    query_time: str
    filters: list[dict]
    included_dimensions: set[str]
    compact_dimensions: set[str]


def find_pools(
    industry: str | None,
    hot: HotList | None,
    theme: str | None,
    group: str | None,
    code_pairs: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Build machine-readable pool identifiers for find output."""
    if code_pairs is not None:
        return [f"codes:{len(code_pairs)}"]
    if industry is not None:
        return [f"industry:{industry}"]
    if hot is not None:
        return [f"hot:{getattr(hot, 'value', hot)}"]
    if theme is not None:
        return [f"theme:{theme}"]
    return [f"watchlist:{group}"] if group else ["watchlist"]


def find_filters(conditions: ConditionSet) -> list[dict]:
    """Build rule.filters from the parsed DSL for audit-friendly output."""
    out: list[dict] = []
    for filter_type, spec in FILTER_SPECS.items():
        attr = condition_attr_for_filter(filter_type)
        if filter_type == "exclude_st":
            if getattr(conditions, attr):
                out.append({"name": spec.flag})
            continue
        for f in getattr(conditions, attr):
            if hasattr(f, "level"):
                param = f"{f.level}:{f.op}:{f.value:g}"
            elif hasattr(f, "period"):
                param = f"{f.period}:{f.op}:{f.value:g}"
            else:
                param = f"{f.op}:{f.value:g}"
            out.append({"name": spec.flag, "param": param})
    return out


def kline_snapshot_periods(conditions: ConditionSet) -> list[int] | None:
    """Limit `--all` K-line snapshots to periods required by filters."""
    if not conditions.has_kline_filters():
        return None

    from kan.core.scanner import PERIODS

    periods: set[int] = set()
    periods.update(f.period for f in conditions.pos_filters)
    periods.update(f.period for f in conditions.gain_filters)
    periods.update(f.period for f in conditions.ma_bias_filters)
    if conditions.resonance_filters:
        periods.update(PERIODS)
    if conditions.up_days_filters:
        max_days = max(1, max(ceil(f.value) for f in conditions.up_days_filters))
        periods.add(min(max_days, max(PERIODS)))
    return sorted(periods or PERIODS)


def kline_scan_periods(conditions: ConditionSet) -> list[int] | None:
    """Periods to compute for non-`--all` K-line scans.

    Keep the fixed scan display periods for terminal tables/sorting, then add any
    user-requested 2-360 filter period so filters never silently miss data.
    """
    if not conditions.has_kline_filters():
        return None
    from kan.core.scanner import PERIODS

    periods: set[int] = set(PERIODS)
    periods.update(f.period for f in conditions.pos_filters)
    periods.update(f.period for f in conditions.gain_filters)
    periods.update(f.period for f in conditions.ma_bias_filters)
    return sorted(periods)


def kline_ma_bias_periods(conditions: ConditionSet) -> list[int] | None:
    """MA BIAS periods requested by filters, or None when not needed."""
    periods = sorted({f.period for f in conditions.ma_bias_filters})
    return periods or None


def availability_dimensions(
    conditions: ConditionSet,
    *,
    output: FindOutputProfile,
    fields_mode: bool = False,
) -> set[str]:
    """Dimensions this find run attempted to load, for data_availability."""
    dims = _condition_dimensions(conditions)
    dims.update(output.field_dimensions)
    if fields_mode:
        return dims
    if output.is_export:
        dims.add("valuation")
    if conditions.needs_moneyflow() or (output.is_export and conditions.is_empty()):
        dims.add("moneyflow")
    if conditions.needs_technical() or (output.is_export and conditions.is_empty()):
        dims.add("technical")
    if conditions.needs_sentiment() or (output.is_export and conditions.is_empty()):
        dims.add("sentiment")
    if conditions.needs_chip() or (output.is_export and conditions.is_empty()):
        dims.add("chip")
    if conditions.needs_shareholder():
        dims.add("shareholder")
    return dims


def compact_dimensions(conditions: ConditionSet, *, is_export: bool) -> set[str]:
    """Dimensions summarized inline in compact results."""
    if is_export and conditions.is_empty():
        return {"valuation", "moneyflow", "technical", "sentiment", "chip"}
    return _condition_dimensions(conditions)


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
    matched = apply_cross_section_conditions(cs.rows, conditions)
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
    from kan.core.enrich import enrich_results
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
        if request.code_pairs is not None
        else _load_find_watchlist_pairs(
            request.group,
            require_non_empty=not source_mode,
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
        )

    if request.code_pairs is not None and output.is_export and request.conditions.is_empty():
        return FindCodePoolResult(
            stock_set=stock_set,
            code_pairs=request.code_pairs,
            pools=find_pools(
                request.industry,
                request.hot,
                request.theme,
                request.group,
                request.code_pairs,
            ),
            query_time=_query_time(),
        )

    scan_periods = kline_scan_periods(request.conditions)
    ma_bias_periods = kline_ma_bias_periods(request.conditions)
    fetch_days = max(scan_periods) if scan_periods else None

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
        )
    except StockSetResolveError as e:
        raise _find_error_from_stock_set(e) from e
    if not ctx.targets and request.only_watchlist:
        raise FindServiceError(
            code="empty_intersection",
            message="自选股与当前候选池没有交集",
            hint="例: 去掉 --only-watchlist，或先运行 kan add 600519 把目标股票加进自选",
        )
    if not ctx.results and not output.is_export:
        raise FindServiceError(
            code="data_unavailable",
            message="无缓存数据 · 请先拉取数据",
            hint="例: kan fetch；或 kan scan 自动拉取自选股 K 线",
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


def _any_metric(results: list[Any], attr: str, fields: tuple[str, ...]) -> bool:
    """Any result has a non-null value in the requested dimension."""
    for r in results:
        obj = getattr(r, attr, None)
        if obj is None:
            continue
        if any(getattr(obj, field, None) is not None for field in fields):
            return True
    return False


def _any_technical_for_filters(
    results: list[Any],
    conditions: ConditionSet,
) -> bool:
    """Check whether requested technical filter data is available."""
    for r in results:
        t = getattr(r, "technical", None)
        if t is None:
            continue
        if conditions.rsi_filters and getattr(t, "rsi_6", None) is not None:
            return True
        if conditions.macd_dif_filters and getattr(t, "macd_dif", None) is not None:
            return True
        if conditions.macd_filters and getattr(t, "macd", None) is not None:
            return True
        if conditions.kdj_j_filters and getattr(t, "kdj_j", None) is not None:
            return True
        if conditions.atr_pct_filters and t.atr_pct() is not None:
            return True
    return False


def _any_ma_bias_for_filters(
    results: list[Any],
    conditions: ConditionSet,
) -> bool:
    """Check whether requested K-line ma_bias values are available."""
    for r in results:
        values = getattr(r, "ma_biases", None)
        if not isinstance(values, dict):
            continue
        if any(values.get(f.period) is not None for f in conditions.ma_bias_filters):
            return True
    return False


def _find_data_gap(
    conditions: ConditionSet,
    results: list[Any],
) -> tuple[str, str, str] | None:
    """Identify upstream data gaps instead of silently returning zero matches."""
    if not results:
        return None
    token_hint = "例: kan config set tushare-token <你的_token>；或去掉对应 filter"
    if conditions.pe_filters and not _any_metric(results, "valuation", ("pe_ttm",)):
        return ("data_unavailable", "当前候选池缺少估值数据，无法执行 --pe filter", token_hint)
    if conditions.moneyflow_filters and not _any_metric(
        results, "moneyflow", ("net_amount", "net_amount_5d")
    ):
        return ("data_unavailable", "当前候选池缺少资金流数据，无法执行 --moneyflow filter", token_hint)
    if conditions.moneyflow_daily_filters and not _any_metric(results, "moneyflow", ("net_amount",)):
        return ("data_unavailable", "当前候选池缺少单日资金流数据，无法执行 --moneyflow-daily filter", token_hint)
    if conditions.moneyflow_days_filters and not _any_metric(results, "moneyflow", ("inflow_days",)):
        return ("data_unavailable", "当前候选池缺少连续资金流数据，无法执行 --moneyflow-days filter", token_hint)
    if conditions.roe_filters and not _any_metric(results, "fundamentals", ("roe",)):
        return ("data_unavailable", "当前候选池缺少财务数据，无法执行 --roe filter", token_hint)
    if conditions.needs_technical() and not _any_technical_for_filters(results, conditions):
        return ("data_unavailable", "当前候选池缺少技术指标数据，无法执行技术 filter", token_hint)
    if conditions.ma_bias_filters and not _any_ma_bias_for_filters(results, conditions):
        return ("data_unavailable", "当前候选池缺少 K 线乖离率数据，无法执行 --ma-bias filter", token_hint)
    if conditions.winner_filters and not _any_metric(results, "chip", ("winner_rate",)):
        return ("data_unavailable", "当前候选池缺少筹码数据，无法执行 --winner filter", token_hint)
    if conditions.needs_shareholder() and not _any_metric(
        results,
        "shareholder",
        ("holder_chg_pct", "top10_float_ratio", "north_hold_ratio"),
    ):
        return ("data_unavailable", "当前候选池缺少股东持股结构数据，无法执行股东 filter", token_hint)
    return None


def _condition_dimensions(conditions: ConditionSet) -> set[str]:
    dims: set[str] = set()
    if conditions.pe_filters:
        dims.add("valuation")
    if conditions.needs_fundamentals():
        dims.add("fundamentals")
    if conditions.needs_moneyflow():
        dims.add("moneyflow")
    if conditions.needs_technical():
        dims.add("technical")
    if conditions.needs_sentiment():
        dims.add("sentiment")
    if conditions.needs_chip():
        dims.add("chip")
    if conditions.needs_shareholder():
        dims.add("shareholder")
    return dims


def _cross_section_dimensions(
    conditions: ConditionSet,
    *,
    output: FindOutputProfile,
) -> set[str]:
    """Dimensions required by the cross-section path."""
    dims = {"valuation"}
    dims.update(_condition_dimensions(conditions))
    if output.field_paths:
        dims.update(output.field_dimensions)
        return dims
    if output.mode == "md":
        dims.add("moneyflow")
        return dims
    if output.compact:
        dims.update(compact_dimensions(conditions, is_export=True))
        return dims
    dims.update({"moneyflow", "technical", "sentiment", "chip"})
    return dims


def _cross_section_needs_valuation_context(output: FindOutputProfile) -> bool:
    """Compute industry percentile/median only for result shapes that need it."""
    if output.mode == "md":
        return True
    if output.field_paths:
        return fields_need_valuation_context(output.field_paths)
    return output.mode == "json" and not output.compact


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
    "FindCodePoolResult",
    "FindCrossSectionRequest",
    "FindCrossSectionResult",
    "FindKlineRequest",
    "FindKlineResult",
    "FindOutputProfile",
    "FindServiceError",
    "availability_dimensions",
    "compact_dimensions",
    "find_filters",
    "find_pools",
    "kline_snapshot_periods",
    "run_find_cross_section",
    "run_find_kline",
]

"""`kan find --explain/--dry-run` 查询计划。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kan.core.find_registry import (
    DATA_DIMENSIONS,
    DIMENSIONS_UNSUPPORTED_IN_ALL,
    fields_need_kline,
)
from kan.service.find_service_metadata import availability_dimensions, find_filters, find_pools
from kan.storage.export_base import FIND_SCHEMA_VERSION, query_time_now

if TYPE_CHECKING:
    from kan.core.find_dsl import ConditionSet
    from kan.data.hot import HotList
    from kan.service.find_service_models import FindOutputProfile


_DIMENSION_SOURCES = {
    "valuation": "tushare_daily_basic",
    "fundamentals": "tushare_fina_indicator",
    "moneyflow": "tushare_moneyflow",
    "technical": "tushare_stk_factor_pro",
    "sentiment": "tushare_limit_list_d",
    "chip": "tushare_cyq_perf",
    "shareholder": "tushare_shareholder_quarterly",
    "relative_strength": "tushare_index_daily_and_sw_board",
}


def build_find_query_plan(
    *,
    conditions: ConditionSet,
    output: FindOutputProfile,
    industry: str | None = None,
    hot: HotList | None = None,
    theme: str | None = None,
    group: str | None = None,
    code_pairs: list[tuple[str, str]] | None = None,
    only_holdings: bool = False,
    all_stocks: bool = False,
    limit: int | None = None,
    offset: int = 0,
    sort: tuple[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build a factual plan without touching data sources."""
    field_dimensions = set(output.field_dimensions)
    included_dimensions = availability_dimensions(
        conditions,
        output=output,
        fields_mode=bool(output.field_paths),
    )
    if all_stocks:
        pools = ["all"]
        pool_size_estimate: int | str | None = "~5500"
    else:
        pools = find_pools(industry, hot, theme, group, code_pairs, only_holdings)
        pool_size_estimate = len(code_pairs) if code_pairs is not None else None
    kline_required = (
        not all_stocks
        or conditions.has_kline_filters()
        or fields_need_kline(output.field_paths)
    )
    data_sources = ["candidate_pool"]
    if kline_required:
        data_sources.append("local_kline_or_kline_snapshot")
    data_sources.extend(
        _DIMENSION_SOURCES[dim]
        for dim in DATA_DIMENSIONS
        if dim in included_dimensions
    )
    unsupported = sorted(set(included_dimensions) & DIMENSIONS_UNSUPPORTED_IN_ALL) if all_stocks else []
    high_cost = sorted(
        dim for dim in ("fundamentals", "shareholder") if dim in included_dimensions
    )
    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "mode": "query_plan",
        "dry_run": dry_run,
        "query_time": query_time_now(),
        "rule": {
            "pools": pools,
            "filters": find_filters(conditions),
            "match": "any" if conditions.match_any else "all",
        },
        "output": {
            "format": output.mode,
            "result_schema": (
                "agent_summary"
                if output.agent_summary else
                ("fields" if output.field_paths else ("compact" if output.compact else "full"))
            ),
            "fields": list(output.field_paths),
            "field_dimensions": sorted(field_dimensions),
            "included_dimensions": sorted(included_dimensions),
            "compact": output.compact,
            "compact_context": output.compact_context,
            "limit": limit,
            "offset": offset,
            "sort": None if sort is None else {"field": sort[0], "direction": sort[1]},
        },
        "data_plan": {
            "pool_size_estimate": pool_size_estimate,
            "kline_required": kline_required,
            "requires_tushare": any(source.startswith("tushare_") for source in data_sources),
            "data_sources": sorted(dict.fromkeys(data_sources)),
            "high_cost_dimensions": high_cost,
            "unsupported_dimensions": unsupported,
        },
        "next_command": "kan find ... --format json",
    }


__all__ = ["build_find_query_plan"]

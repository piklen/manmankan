"""find service output metadata and required dimension helpers."""
from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from kan.core.find_registry import (
    FILTER_SPECS,
    condition_attr_for_filter,
    fields_need_valuation_context,
)
from kan.service.find_service_models import FindOutputProfile

if TYPE_CHECKING:
    from kan.core.find_dsl import ConditionSet
    from kan.data.hot import HotList


def find_pools(
    industry: str | None,
    hot: HotList | None,
    theme: str | None,
    group: str | None,
    code_pairs: list[tuple[str, str]] | None = None,
    only_holdings: bool = False,
) -> list[str]:
    """Build machine-readable pool identifiers for find output."""
    if only_holdings:
        return ["holdings"]
    if code_pairs is not None:
        return [f"codes:{len(code_pairs)}"]
    if industry is not None:
        return [f"industry:{industry}"]
    if hot is not None:
        return [f"hot:{getattr(hot, 'value', hot)}"]
    if theme is not None:
        return [f"theme:{theme}"]
    return [f"watchlist:{group}"] if group else ["watchlist+holdings"]


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
    periods.update(conditions.relative_strength_periods())
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
    periods.update(conditions.relative_strength_periods())
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


def _condition_dimensions(conditions: ConditionSet) -> set[str]:
    dims: set[str] = set()
    for filter_type, spec in FILTER_SPECS.items():
        if spec.dimension != "valuation":
            continue
        if getattr(conditions, condition_attr_for_filter(filter_type)):
            dims.add("valuation")
            break
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
    if conditions.needs_relative_strength():
        dims.add("relative_strength")
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

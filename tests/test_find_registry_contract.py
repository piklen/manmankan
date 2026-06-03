from __future__ import annotations

from dataclasses import fields

from kan.cli.find_cmds import _find_filters
from kan.core.find_dsl import ConditionSet
from kan.core.find_filter import FIND_MATCH_SEGMENTS
from kan.core.find_registry import FILTER_SPECS, condition_attr_for_filter

_FILTER_EXAMPLES = {
    "pos": "180:lt:5",
    "resonance": "low:gte:3",
    "gain": "30:gt:20",
    "up_days": "gte:3",
    "pe": "lt:20",
    "roe": "gte:15",
    "moneyflow": "gt:0",
    "rsi": "lt:30",
    "macd_dif": "gt:0",
    "macd": "gt:0",
    "kdj_j": "lt:20",
    "ma_bias": "20:gt:0",
    "atr_pct": "lt:5",
    "streak": "gte:3",
    "winner": "gte:50",
    "holders": "lt:0",
    "top10": "gte:50",
    "north": "gte:3",
}


def test_registered_filters_have_conditions_and_match_segments() -> None:
    condition_fields = {field.name for field in fields(ConditionSet)}
    segment_by_type = {segment.filter_type: segment for segment in FIND_MATCH_SEGMENTS}

    for filter_type, spec in FILTER_SPECS.items():
        attr = condition_attr_for_filter(filter_type)
        assert attr in condition_fields
        if filter_type == "exclude_st":
            continue
        segment = segment_by_type.get(filter_type)
        assert segment is not None, f"{spec.flag} missing FIND_MATCH_SEGMENTS entry"
        assert segment.condition_attr == attr
        assert segment.supports_cross_section is spec.supports_all


def test_find_filters_output_is_registry_driven() -> None:
    kwargs: dict[str, object] = {
        filter_type: [raw] for filter_type, raw in _FILTER_EXAMPLES.items()
    }
    kwargs["exclude_st"] = True
    conditions = ConditionSet.from_flags(**kwargs)

    rendered = _find_filters(conditions)
    rendered_by_flag = {row["name"]: row for row in rendered}

    for filter_type, spec in FILTER_SPECS.items():
        row = rendered_by_flag.get(spec.flag)
        assert row is not None, f"{spec.flag} missing from _find_filters output"
        if filter_type != "exclude_st":
            assert row["param"] == _FILTER_EXAMPLES[filter_type]

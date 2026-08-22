"""vNext 选股领域契约测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kan.core.find_registry import FILTER_SPECS
from kan.domain.screen import (
    ComparisonOperator,
    ScreenCondition,
    ScreenFilterType,
    ScreenSort,
    ScreenSpec,
    SortDirection,
    UniverseKind,
    UniverseSpec,
)
from kan.service.screen_catalog import SCREEN_FILTER_CATALOG, screen_filter_groups
from kan.service.screen_service import condition_set_from_spec, content_hash


def test_filter_catalog_exactly_tracks_core_registry() -> None:
    expected = set(FILTER_SPECS) - {"exclude_st"}
    grouped_count = 0
    for group in screen_filter_groups():
        options = group["options"]
        assert isinstance(options, list)
        grouped_count += len(options)

    assert set(SCREEN_FILTER_CATALOG) == expected
    assert {item.value for item in ScreenFilterType} == expected
    assert grouped_count == len(expected)


def test_period_condition_requires_period_and_generates_existing_dsl() -> None:
    condition = ScreenCondition(
        type=ScreenFilterType.POS,
        operator=ComparisonOperator.LT,
        value=35,
        period=180,
    )
    spec = ScreenSpec(name="低位观察", conditions=[condition])

    assert condition.to_dsl() == "180:lt:35"
    assert condition_set_from_spec(spec).pos_filters[0].period == 180
    assert condition_set_from_spec(spec).pos_filters[0].op == "lt"
    assert condition_set_from_spec(spec).pos_filters[0].value == 35

    with pytest.raises(ValidationError, match="必须提供 period"):
        ScreenCondition(
            type=ScreenFilterType.POS,
            operator=ComparisonOperator.LT,
            value=35,
        )


def test_universe_and_screen_reject_ambiguous_shapes() -> None:
    with pytest.raises(ValidationError, match="至少需要一只股票"):
        UniverseSpec(kind=UniverseKind.CODES)

    with pytest.raises(ValidationError, match="至少需要一个筛选条件"):
        ScreenSpec()

    with pytest.raises(ValidationError, match="只有自选股票池"):
        UniverseSpec(kind=UniverseKind.ALL, group="短线")

    with pytest.raises(ValidationError, match="排序字段不能重复"):
        ScreenSpec(
            exclude_st=True,
            sort=[
                ScreenSort(field_id="pe", direction=SortDirection.ASC, nulls="last"),
                ScreenSort(field_id="pe", direction=SortDirection.DESC, nulls="last"),
            ],
        )


def test_content_hash_is_canonical_across_equivalent_models() -> None:
    first = ScreenSpec(
        name="低位观察",
        exclude_st=True,
        universe=UniverseSpec(kind=UniverseKind.WATCHLIST),
    )
    second = ScreenSpec.model_validate(first.model_dump(mode="json"))

    assert content_hash(first) == content_hash(second)

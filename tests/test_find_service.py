"""Unit tests for the render-neutral find service."""
from __future__ import annotations

import pytest

from kan.core.find_dsl import ConditionSet
from kan.core.pipeline import StockSetResolveError
from kan.service.find_service import (
    FindCodePoolResult,
    FindCrossSectionRequest,
    FindKlineRequest,
    FindOutputProfile,
    FindServiceError,
    run_find_cross_section,
    run_find_kline,
)


def test_code_pool_without_filters_skips_kline_pipeline(monkeypatch) -> None:
    def fail_pipeline(*_args, **_kwargs):
        raise AssertionError("code-pool metadata path should not scan K-lines")

    monkeypatch.setattr("kan.service.find_service.run_data_pipeline", fail_pipeline)

    result = run_find_kline(FindKlineRequest(
        conditions=ConditionSet.from_flags(),
        output=FindOutputProfile(mode="json"),
        code_pairs=[("600519", "贵州茅台"), ("000858", "五粮液")],
    ))

    assert isinstance(result, FindCodePoolResult)
    assert result.pools == ["codes:2"]
    assert result.code_pairs == [("600519", "贵州茅台"), ("000858", "五粮液")]


def test_kline_path_wraps_stock_set_error_without_typer_exit(monkeypatch) -> None:
    def fail_pipeline(*_args, **_kwargs):
        raise StockSetResolveError(
            code="board_not_found",
            message="❌ 未找到行业「ghost」",
            exit_code=1,
        )

    monkeypatch.setattr("kan.service.find_service.run_data_pipeline", fail_pipeline)

    with pytest.raises(FindServiceError) as exc_info:
        run_find_kline(FindKlineRequest(
            conditions=ConditionSet.from_flags(pos=["30:lt:20"]),
            output=FindOutputProfile(mode="json"),
            code_pairs=[("600519", "贵州茅台")],
        ))

    assert exc_info.value.code == "board_not_found"
    assert exc_info.value.message == "未找到行业「ghost」"
    assert exc_info.value.exit_code == 1


def test_cross_section_rejects_roe_before_fetch(monkeypatch) -> None:
    def fail_cross_section(*_args, **_kwargs):
        raise AssertionError("unsupported --all filters should fail before fetch")

    monkeypatch.setattr("kan.core.cross_section.run_cross_section", fail_cross_section)

    with pytest.raises(FindServiceError) as exc_info:
        run_find_cross_section(FindCrossSectionRequest(
            conditions=ConditionSet.from_flags(roe=["gte:15"]),
            output=FindOutputProfile(mode="json"),
        ))

    assert exc_info.value.code == "unsupported_all_filter"
    assert exc_info.value.exit_code == 2

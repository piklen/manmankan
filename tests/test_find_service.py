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


def _enriched_with_rs(*, rs_index=None, rs_board=None):
    import datetime

    from kan.core.models import (
        EnrichedResult,
        RelativeStrengthMetrics,
        StockScanResult,
    )

    scan = StockScanResult(
        symbol="600519", name="贵州茅台", current_price=100.0,
        scan_date=datetime.date(2026, 5, 29), periods=[],
        low_resonance=0, high_resonance=0,
    )
    rsm = RelativeStrengthMetrics(rs_index=rs_index or {}, rs_board=rs_board or {})
    return EnrichedResult.from_scan(scan, relative_strength=rsm)


class TestRelativeStrengthService:
    """RS 在 service 层的纯函数:维度登记 / 命中检测 / 缺数据判定。"""

    def test_condition_dimensions_includes_rs(self):
        from kan.service.find_service import _condition_dimensions

        cs = ConditionSet.from_flags(rs_index=["30:gt:0"])
        assert "relative_strength" in _condition_dimensions(cs)

    def test_any_rs_true_when_board_diff(self):
        from kan.service.find_service import _any_rs

        cs = ConditionSet.from_flags(rs_board=["30:gt:0"])
        assert _any_rs([_enriched_with_rs(rs_board={30: -0.29})], cs) is True

    def test_any_rs_true_when_index_diff(self):
        from kan.service.find_service import _any_rs

        cs = ConditionSet.from_flags(rs_index=["30:gt:0"])
        assert _any_rs([_enriched_with_rs(rs_index={30: 5.0})], cs) is True

    def test_any_rs_false_when_empty(self):
        from kan.service.find_service import _any_rs

        cs = ConditionSet.from_flags(rs_board=["30:gt:0"])
        assert _any_rs([_enriched_with_rs(rs_board={})], cs) is False

    def test_find_data_gap_rs_unavailable(self):
        from kan.service.find_service import _find_data_gap

        cs = ConditionSet.from_flags(rs_board=["30:gt:0"])
        gap = _find_data_gap(cs, [_enriched_with_rs(rs_board={})])
        assert gap is not None
        assert gap[0] == "data_unavailable"
        assert "相对强度" in gap[1]

    def test_find_data_gap_rs_ok_when_diff_present(self):
        from kan.service.find_service import _find_data_gap

        cs = ConditionSet.from_flags(rs_board=["30:gt:0"])
        assert _find_data_gap(cs, [_enriched_with_rs(rs_board={30: -0.29})]) is None

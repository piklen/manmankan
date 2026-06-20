"""Unit tests for the render-neutral find service."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from kan.core.find_dsl import ConditionSet
from kan.core.pipeline import StockSetResolveError
from kan.service.find_service import (
    FindCrossSectionRequest,
    FindKlineRequest,
    FindKlineResult,
    FindOutputProfile,
    FindServiceError,
    find_pools,
    run_find_cross_section,
    run_find_kline,
)


def _scan_result():
    import datetime

    from kan.core.models import PeriodResult, StockScanResult

    return StockScanResult(
        symbol="600519",
        name="贵州茅台",
        current_price=100.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[
            PeriodResult(
                period=60,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            ),
        ],
        low_resonance=0,
        high_resonance=0,
    )


def test_codes_without_filters_uses_kline_enrichment_path(monkeypatch) -> None:
    captured = {}
    scan = _scan_result()

    def fake_pipeline(
        stock_set, *, compute, mode, periods, ma_bias_periods, fetch_days,
        show_progress, exit_on_resolve_error,
    ):
        captured["stock_set_name"] = stock_set.name
        captured["periods"] = periods
        return type(
            "Ctx",
            (),
                {
                    "targets": [("600519", "贵州茅台"), ("000858", "五粮液")],
                    "meta": None,
                    "results": [scan],
                    "freshness": None,
                    "source_name": stock_set.name,
                },
            )()

    monkeypatch.setattr("kan.service.find_service.run_data_pipeline", fake_pipeline)
    monkeypatch.setattr("kan.core.enrich.enrich_results", lambda results, **_kw: results)

    result = run_find_kline(FindKlineRequest(
        conditions=ConditionSet.from_flags(),
        output=FindOutputProfile(mode="json"),
        code_pairs=[("600519", "贵州茅台"), ("000858", "五粮液")],
    ))

    assert isinstance(result, FindKlineResult)
    assert result.pools == ["codes:2"]
    assert captured["stock_set_name"] == "自定义代码池(2只)"


def test_kline_path_empty_results_reports_data_unavailable(monkeypatch) -> None:
    def fake_pipeline(
        stock_set, *, compute, mode, periods, ma_bias_periods, fetch_days,
        show_progress, exit_on_resolve_error,
    ):
        return type(
            "Ctx",
            (),
            {
                "targets": [("600519", "贵州茅台")],
                "meta": None,
                "results": [],
                "freshness": None,
                "source_name": stock_set.name,
            },
        )()

    monkeypatch.setattr("kan.service.find_service.run_data_pipeline", fake_pipeline)

    with pytest.raises(FindServiceError) as exc_info:
        run_find_kline(FindKlineRequest(
            conditions=ConditionSet.from_flags(),
            output=FindOutputProfile(mode="json"),
            code_pairs=[("600519", "贵州茅台")],
        ))

    assert exc_info.value.code == "data_unavailable"
    assert "--dry-run" in str(exc_info.value.hint)


def test_default_and_holdings_find_pools() -> None:
    assert find_pools(None, None, None, None, None, False) == ["watchlist+holdings"]
    assert find_pools(None, None, None, None, None, True) == ["holdings"]


def test_named_source_find_pools() -> None:
    assert find_pools("半导体", None, None, None) == ["industry:半导体"]
    assert find_pools(None, SimpleNamespace(value="rank"), None, None) == ["hot:rank"]
    assert find_pools(None, None, "AI应用", None) == ["theme:AI应用"]
    assert find_pools(None, None, None, "短线") == ["watchlist:短线"]


def test_only_holdings_kline_path_skips_watchlist_load(monkeypatch) -> None:
    captured = {}
    scan = _scan_result()

    def fail_watchlist(*_args, **_kwargs):
        raise AssertionError("--only-holdings 不应读取自选池")

    def fake_pipeline(
        stock_set, *, compute, mode, periods, ma_bias_periods, fetch_days,
        show_progress, exit_on_resolve_error,
    ):
        captured["stock_set_name"] = stock_set.name
        return type(
            "Ctx",
            (),
                {
                    "targets": [("600519", "贵州茅台")],
                    "meta": None,
                    "results": [scan],
                    "freshness": None,
                    "source_name": stock_set.name,
                },
            )()

    monkeypatch.setattr("kan.service.find_service._load_find_watchlist_pairs", fail_watchlist)
    monkeypatch.setattr("kan.service.find_service.run_data_pipeline", fake_pipeline)
    monkeypatch.setattr("kan.core.enrich.enrich_results", lambda results, **_kw: results)

    result = run_find_kline(FindKlineRequest(
        conditions=ConditionSet.from_flags(),
        output=FindOutputProfile(mode="json"),
        only_holdings=True,
    ))

    assert isinstance(result, FindKlineResult)
    assert captured["stock_set_name"] == "真实持仓"
    assert result.pools == ["holdings"]


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


class TestFindServiceMetadata:
    def test_kline_snapshot_period_branches(self):
        from kan.core.scanner import PERIODS
        from kan.service.find_service import kline_snapshot_periods

        assert kline_snapshot_periods(ConditionSet.from_flags()) is None
        assert kline_snapshot_periods(ConditionSet.from_flags(resonance=["low:gte:3"])) == PERIODS

    def test_availability_dimensions_fields_mode_and_shareholder(self):
        from kan.service.find_service import availability_dimensions

        fields_only = availability_dimensions(
            ConditionSet.from_flags(pe=["lt:20"]),
            output=FindOutputProfile(mode="json", field_dimensions=frozenset({"technical"})),
            fields_mode=True,
        )
        assert fields_only == {"valuation", "technical"}

        shareholder = availability_dimensions(
            ConditionSet.from_flags(holders=["lt:0"]),
            output=FindOutputProfile(mode="terminal"),
        )
        assert "shareholder" in shareholder

    def test_compact_and_condition_dimensions_cover_all_data_families(self):
        from kan.service.find_service import _condition_dimensions, compact_dimensions

        conditions = ConditionSet.from_flags(
            pe=["lt:20"],
            roe=["gte:15"],
            moneyflow=["gt:0"],
            rsi=["lt:30"],
            streak=["gte:3"],
            winner=["gte:50"],
            holders=["lt:0"],
            rs_index=["30:gt:0"],
        )

        assert compact_dimensions(ConditionSet.from_flags(pe=["lt:20"]), is_export=True) == {
            "valuation"
        }
        assert _condition_dimensions(conditions) == {
            "valuation",
            "fundamentals",
            "moneyflow",
            "technical",
            "sentiment",
            "chip",
            "shareholder",
            "relative_strength",
        }

    def test_cross_section_dimensions_by_output_shape(self):
        from kan.service.find_service import _cross_section_dimensions

        empty = ConditionSet.from_flags()

        fields = _cross_section_dimensions(
            empty,
            output=FindOutputProfile(
                mode="json",
                field_paths=("technical.rsi_6",),
                field_dimensions=frozenset({"technical"}),
            ),
        )
        assert fields == {"valuation", "technical"}

        md_dims = _cross_section_dimensions(empty, output=FindOutputProfile(mode="md"))
        assert md_dims == {"valuation", "moneyflow"}

        compact_dims = _cross_section_dimensions(
            empty,
            output=FindOutputProfile(mode="json", compact=True),
        )
        assert compact_dims == {"valuation", "moneyflow", "technical", "sentiment", "chip"}

        full_json = _cross_section_dimensions(empty, output=FindOutputProfile(mode="json"))
        assert full_json == {"valuation", "moneyflow", "technical", "sentiment", "chip"}

    def test_cross_section_valuation_context_need_by_output_shape(self):
        from kan.service.find_service import _cross_section_needs_valuation_context

        assert _cross_section_needs_valuation_context(FindOutputProfile(mode="md")) is True
        assert _cross_section_needs_valuation_context(
            FindOutputProfile(mode="json", field_paths=("valuation_context.pe_pct_rank",))
        ) is True
        assert _cross_section_needs_valuation_context(FindOutputProfile(mode="json")) is True
        assert _cross_section_needs_valuation_context(
            FindOutputProfile(mode="json", compact=True)
        ) is False


class TestFindServiceDataGap:
    def test_any_metric_detects_present_value(self):
        from kan.service.find_service_data_gap import _any_metric

        assert _any_metric([SimpleNamespace(valuation=None)], "valuation", ("pe_ttm",)) is False
        assert _any_metric(
            [SimpleNamespace(valuation=SimpleNamespace(pe_ttm=12.3))],
            "valuation",
            ("pe_ttm",),
        ) is True

    @pytest.mark.parametrize(
        ("conditions", "needle"),
        [
            (ConditionSet.from_flags(pe=["lt:20"]), "--pe"),
            (ConditionSet.from_flags(moneyflow=["gt:0"]), "--moneyflow filter"),
            (ConditionSet.from_flags(moneyflow_daily=["gt:0"]), "--moneyflow-daily"),
            (ConditionSet.from_flags(moneyflow_days=["gte:3"]), "--moneyflow-days"),
            (ConditionSet.from_flags(roe=["gte:15"]), "--roe"),
            (ConditionSet.from_flags(winner=["gte:50"]), "--winner"),
            (ConditionSet.from_flags(holders=["lt:0"]), "股东 filter"),
        ],
    )
    def test_find_data_gap_reports_missing_dimension(self, conditions, needle):
        from kan.service.find_service import _find_data_gap

        gap = _find_data_gap(conditions, [SimpleNamespace()])

        assert gap is not None
        assert gap[0] == "data_unavailable"
        assert needle in gap[1]

    def test_find_data_gap_accepts_present_valuation(self):
        from kan.service.find_service import _find_data_gap

        conditions = ConditionSet.from_flags(pe=["lt:20"])
        result = SimpleNamespace(valuation=SimpleNamespace(pe_ttm=12.3))

        assert _find_data_gap(conditions, [result]) is None

    def test_find_data_gap_technical_and_ma_bias_paths(self):
        from kan.service.find_service import _find_data_gap

        rsi_filter = ConditionSet.from_flags(rsi=["lt:30"])
        assert _find_data_gap(rsi_filter, [SimpleNamespace(technical=None)]) is not None
        assert _find_data_gap(
            rsi_filter,
            [SimpleNamespace(technical=SimpleNamespace(rsi_6=20.0))],
        ) is None

        ma_bias_filter = ConditionSet.from_flags(ma_bias=["20:gt:0"])
        assert _find_data_gap(ma_bias_filter, [SimpleNamespace(ma_biases=None)]) is not None
        assert _find_data_gap(ma_bias_filter, [SimpleNamespace(ma_biases={20: 1.2})]) is None

    def test_any_rs_skips_missing_relative_strength_object(self):
        from kan.service.find_service import _any_rs

        conditions = ConditionSet.from_flags(rs_index=["30:gt:0"])

        assert _any_rs([SimpleNamespace(relative_strength=None)], conditions) is False

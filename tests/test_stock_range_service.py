"""单股日内偏离分布领域模型与服务测试。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from kan.domain.stock_range import StockRangeRequest
from kan.service import stock_range_service


def _returns_frame(
    events: list[tuple[float, float, float, float]],
    *,
    start: date = date(2026, 1, 1),
    source: str = "test_source",
) -> pd.DataFrame:
    """按 (open, low, high, close) 百分比构造连续、合法的前复权日 K。"""

    rows: list[dict[str, object]] = [{
        "date": start,
        "open": 100.0,
        "high": 100.0,
        "low": 100.0,
        "close": 100.0,
        "_source": source,
    }]
    previous_close = 100.0
    for offset, (open_pct, low_pct, high_pct, close_pct) in enumerate(events, start=1):
        rows.append({
            "date": start + timedelta(days=offset),
            "open": previous_close * (1 + open_pct / 100),
            "high": previous_close * (1 + high_pct / 100),
            "low": previous_close * (1 + low_pct / 100),
            "close": previous_close * (1 + close_pct / 100),
            "_source": source,
        })
        previous_close = float(rows[-1]["close"])
    return pd.DataFrame(rows)


def _patch_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    frame: pd.DataFrame,
    *,
    cutoff: date | None = None,
) -> list[tuple[str, int, bool]]:
    calls: list[tuple[str, int, bool]] = []

    def fake_fetch(symbol: str, *, days: int, force: bool) -> pd.DataFrame:
        calls.append((symbol, days, force))
        return frame.copy()

    monkeypatch.setattr(stock_range_service, "_fetch_stock_history", fake_fetch)
    monkeypatch.setattr(
        stock_range_service,
        "_latest_complete_cutoff",
        lambda: cutoff or max(pd.to_datetime(frame["date"], errors="coerce").dropna()).date(),
    )
    monkeypatch.setattr(
        stock_range_service,
        "_resolve_stock_name",
        lambda _symbol: "测试股份",
    )
    return calls


def test_fetch_boundary_never_shrinks_default_kline_cache(monkeypatch) -> None:
    calls: list[tuple[str, int, bool]] = []
    sentinel = pd.DataFrame({"close": [100]})

    def fake_fetch(symbol: str, *, days: int, force: bool) -> pd.DataFrame:
        calls.append((symbol, days, force))
        return sentinel

    monkeypatch.setattr("kan.data.fetcher.fetch_kline", fake_fetch)

    assert stock_range_service._fetch_stock_history(
        "600519", days=16, force=True,
    ) is sentinel
    assert calls == [("600519", 360, True)]


def test_request_is_strict_and_limits_periods() -> None:
    request = StockRangeRequest(
        symbol="600519",
        periods=[5, 15],
        levels=[75, 85, 90, 95],
    )
    assert request.periods == (5, 15)
    assert request.levels == (75.0, 85.0, 90.0, 95.0)
    zero = StockRangeRequest(
        symbol="600519",
        periods=[5],
        levels=[95],
        down_pct=0,
        up_pct=0,
    )
    assert zero.down_pct == 0
    assert zero.up_pct == 0

    with pytest.raises(ValidationError):
        StockRangeRequest(
            symbol="600519",
            periods=[1],
            levels=[75],
        )
    with pytest.raises(ValidationError):
        StockRangeRequest(
            symbol="600519",
            periods=[361],
            levels=[75],
        )
    with pytest.raises(ValidationError):
        StockRangeRequest(
            symbol="600519",
            periods=[5, 5],
            levels=[75],
        )
    with pytest.raises(ValidationError):
        StockRangeRequest.model_validate({
            "symbol": "600519",
            "periods": [5],
            "levels": [75],
            "unknown": True,
        })
    with pytest.raises(ValidationError):
        StockRangeRequest(
            symbol="600519",
            periods=[5],
            levels=[95],
            down_pct=-0.0001,
        )


def test_study_uses_linear_levels_and_computes_trigger_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _returns_frame([
        (-1.0, -1.0, 1.0, 0.5),
        (-2.0, -2.0, 2.0, -1.0),
        (0.0, -3.0, 3.0, 1.0),
        (-4.0, -4.0, 4.0, -3.0),
        (5.0, -5.0, 5.0, 5.0),
    ])
    calls = _patch_boundaries(monkeypatch, frame)
    request = StockRangeRequest(
        symbol="600519",
        periods=[5],
        levels=[75, 85, 90, 95],
        down_pct=3,
        up_pct=3,
        force=True,
    )

    study = stock_range_service.study_stock_range(request)

    assert calls == [("600519", 6, True)]
    assert study.symbol == "600519"
    assert study.name == "测试股份"
    assert study.source == "test_source"
    assert study.data_start == "2026-01-02"
    assert study.data_cutoff == "2026-01-06"
    assert study.coverage.valid_bars == 6
    assert study.coverage.valid_observations == 5
    window = study.windows[0]
    assert window.period == 5
    assert window.sample_count == 5
    assert window.missing_sample_count == 0
    assert [row.threshold_pct for row in window.downside] == [-4.0, -4.4, -4.6, -4.8]
    assert [row.threshold_pct for row in window.upside] == [4.0, 4.4, 4.6, 4.8]
    assert [row.actual_coverage_pct for row in window.downside] == [80.0] * 4
    assert [row.actual_coverage_pct for row in window.upside] == [80.0] * 4

    down = window.custom_downside
    assert down is not None
    assert down.basis == "custom"
    assert down.level_pct is None
    assert down.threshold_pct == -3.0
    assert down.reference_price == stock_range_service._tick_reference_price(
        study.reference_close,
        -3.0,
    )
    assert down.actual_coverage_pct == 60.0
    assert down.trigger_count == 3
    assert down.trigger_ratio_pct == 60.0
    assert down.close_above_count == 2
    assert down.close_above_ratio_pct == pytest.approx(66.6667)
    assert down.close_at_or_below_count == 1
    assert down.close_at_or_below_ratio_pct == pytest.approx(33.3333)
    assert down.close_positive_count == 2
    assert down.close_positive_ratio_pct == pytest.approx(66.6667)
    assert down.gap_trigger_count == 1
    assert down.gap_trigger_ratio_pct == pytest.approx(33.3333)
    assert down.intraday_trigger_count == 2
    assert down.close_median_pct == 1.0

    up = window.custom_upside
    assert up is not None
    assert up.threshold_pct == 3.0
    assert up.reference_price == stock_range_service._tick_reference_price(
        study.reference_close,
        3.0,
    )
    assert up.actual_coverage_pct == 60.0
    assert up.trigger_count == 3
    assert up.close_at_or_above_count == 1
    assert up.close_at_or_above_ratio_pct == pytest.approx(33.3333)
    assert up.close_below_count == 2
    assert up.close_below_ratio_pct == pytest.approx(66.6667)
    assert up.close_positive_count == 2
    assert up.gap_trigger_count == 1
    assert up.intraday_trigger_count == 2
    assert up.close_median_pct == 1.0
    assert up.pullback_median_pct == 2.0
    assert any("5 日窗口只有 5 个样本" in warning for warning in study.warnings)


def test_custom_threshold_without_triggers_keeps_conditional_ratios_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _returns_frame([
        (0.0, -1.0, 1.0, 0.0),
        (0.0, -1.0, 1.0, 0.0),
        (0.0, -1.0, 1.0, 0.0),
        (0.0, -1.0, 1.0, 0.0),
        (0.0, -1.0, 1.0, 0.0),
    ])
    _patch_boundaries(monkeypatch, frame)
    study = stock_range_service.study_stock_range(StockRangeRequest(
        symbol="600519",
        periods=[5],
        levels=[95],
        down_pct=9,
        up_pct=9,
    ))

    down = study.windows[0].custom_downside
    up = study.windows[0].custom_upside
    assert down is not None and up is not None
    assert down.trigger_count == 0
    assert down.trigger_ratio_pct == 0.0
    assert down.actual_coverage_pct == 100.0
    assert down.close_above_ratio_pct is None
    assert down.close_at_or_below_ratio_pct is None
    assert down.close_positive_ratio_pct is None
    assert down.gap_trigger_ratio_pct is None
    assert down.close_median_pct is None
    assert up.trigger_count == 0
    assert up.trigger_ratio_pct == 0.0
    assert up.close_at_or_above_ratio_pct is None
    assert up.close_below_ratio_pct is None
    assert up.close_positive_ratio_pct is None
    assert up.gap_trigger_ratio_pct is None
    assert up.close_median_pct is None
    assert up.pullback_median_pct is None
    assert sum("触及后比例为空" in warning for warning in study.warnings) == 2


def test_published_threshold_drives_evidence_and_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordinary = [(0.0, -1.0, 1.0, 0.0)] * 56
    near_limit = [
        (0.0, -1.0, 10.000028661754069, 0.0),
        (0.0, -1.0, 10.000046907010374, 0.0),
        (0.0, -1.0, 10.005350454788653, 0.0),
        (0.0, -1.0, 10.024087162793327, 0.0),
    ]
    frame = _returns_frame(ordinary + near_limit)
    _patch_boundaries(monkeypatch, frame)

    study = stock_range_service.study_stock_range(StockRangeRequest(
        symbol="600519",
        periods=[60],
        levels=[95],
        up_pct=10.0,
    ))

    window = study.windows[0]
    empirical = window.upside[0]
    custom = window.custom_upside
    assert custom is not None
    assert empirical.threshold_pct == 10.0
    assert empirical.reference_price == 110.0
    assert empirical.trigger_count == 4
    assert empirical.actual_coverage_pct == pytest.approx(93.3333)
    assert custom.threshold_pct == empirical.threshold_pct
    assert custom.reference_price == empirical.reference_price
    assert custom.trigger_count == empirical.trigger_count
    assert custom.actual_coverage_pct == empirical.actual_coverage_pct


def test_reference_price_uses_cent_tick_and_round_half_up() -> None:
    assert stock_range_service._tick_reference_price(100.0, 0.005) == 100.01
    assert stock_range_service._tick_reference_price(20.0, -2.0) == 19.60


def test_zero_empirical_threshold_round_trips_as_explicit_custom_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _returns_frame([(0.0, 0.0, 0.0, 0.0)] * 5)
    _patch_boundaries(monkeypatch, frame)

    study = stock_range_service.study_stock_range(StockRangeRequest(
        symbol="600519",
        periods=[5],
        levels=[95],
        down_pct=0,
        up_pct=0,
    ))

    window = study.windows[0]
    assert window.custom_downside is not None
    assert window.custom_upside is not None
    assert window.downside[0].threshold_pct == 0
    assert window.upside[0].threshold_pct == 0
    assert window.custom_downside.threshold_pct == 0
    assert window.custom_upside.threshold_pct == 0
    assert window.custom_downside.trigger_count == window.downside[0].trigger_count == 5
    assert window.custom_upside.trigger_count == window.upside[0].trigger_count == 5


def test_normalization_does_not_bridge_across_an_invalid_existing_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame([
        {"date": "2026-01-01", "open": 100, "high": 100, "low": 100, "close": 100, "_source": "tushare"},
        {"date": "2026-01-02", "open": 50, "high": 51, "low": 49, "close": 50, "_source": "tushare"},
        {"date": "2026-01-02", "open": 100, "high": 101, "low": 99, "close": 100, "_source": "tushare"},
        {"date": "2026-01-03", "open": 200, "high": 190, "low": 180, "close": 185, "_source": "bad"},
        {"date": "2026-01-04", "open": 100, "high": 102, "low": 96, "close": 101, "_source": "baostock"},
        {"date": "2026-01-05", "open": 101, "high": 102, "low": 100, "close": 101, "_source": "baostock"},
        {"date": "2026-01-06", "open": 101, "high": 103, "low": 100, "close": 102, "_source": "baostock"},
        {"date": "not-a-date", "open": 100, "high": 101, "low": 99, "close": 100, "_source": "bad"},
    ])
    _patch_boundaries(monkeypatch, frame, cutoff=date(2026, 1, 5))

    study = stock_range_service.study_stock_range(StockRangeRequest(
        symbol="600519",
        periods=[2],
        levels=[75],
        down_pct=5,
    ))

    assert study.source == "baostock + tushare"
    assert study.data_start == "2026-01-05"
    assert study.data_cutoff == "2026-01-05"
    assert study.coverage.model_dump() == {
        "requested_bars": 3,
        "raw_rows": 8,
        "invalid_date_rows": 1,
        "after_cutoff_rows": 1,
        "duplicate_date_rows": 1,
        "invalid_ohlc_rows": 1,
        "invalid_reference_observations": 1,
        "excluded_rows": 4,
        "older_valid_rows_ignored": 1,
        "valid_bars": 3,
        "valid_observations": 1,
    }
    assert study.windows[0].sample_count == 1
    assert study.windows[0].missing_sample_count == 1
    down = study.windows[0].custom_downside
    assert down is not None
    assert down.trigger_count == 0
    assert any("晚于最近完整交易日" in warning for warning in study.warnings)
    assert any("OHLC 无效" in warning for warning in study.warnings)
    assert any("多个数据源" in warning for warning in study.warnings)


def test_short_history_reports_actual_sample_and_stale_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _returns_frame([
        (0.0, -1.0, 2.0, 1.0),
        (0.0, -2.0, 1.0, -1.0),
    ])
    _patch_boundaries(monkeypatch, frame, cutoff=date(2026, 1, 10))

    study = stock_range_service.study_stock_range(StockRangeRequest(
        symbol="600519",
        periods=[5, 15],
        levels=[75, 95],
    ))

    assert [window.sample_count for window in study.windows] == [2, 2]
    assert [window.missing_sample_count for window in study.windows] == [3, 13]
    assert study.coverage.valid_observations == 2
    assert any("有效样本 2 个" in warning for warning in study.warnings)
    assert any("早于最近完整交易日" in warning for warning in study.warnings)


def test_service_errors_are_stable_and_preserve_causes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stock_range_service,
        "_latest_complete_cutoff",
        lambda: date(2026, 1, 6),
    )
    monkeypatch.setattr(
        stock_range_service,
        "_resolve_stock_name",
        lambda _symbol: (_ for _ in ()).throw(ValueError("未找到股票")),
    )
    request = StockRangeRequest(symbol="600519", periods=[5], levels=[95])
    with pytest.raises(stock_range_service.StockRangeServiceError) as invalid_info:
        stock_range_service.study_stock_range(request)
    assert invalid_info.value.code == "invalid_symbol"
    assert invalid_info.value.exit_code == 2
    assert isinstance(invalid_info.value.__cause__, ValueError)

    monkeypatch.setattr(
        stock_range_service,
        "_resolve_stock_name",
        lambda _symbol: (_ for _ in ()).throw(OSError("catalog offline")),
    )
    with pytest.raises(stock_range_service.StockRangeServiceError) as catalog_info:
        stock_range_service.study_stock_range(request)
    assert catalog_info.value.code == "symbol_catalog_unavailable"
    assert catalog_info.value.exit_code == 1
    assert isinstance(catalog_info.value.__cause__, OSError)

    monkeypatch.setattr(stock_range_service, "_resolve_stock_name", lambda _symbol: "测试股份")
    monkeypatch.setattr(
        stock_range_service,
        "_fetch_stock_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    with pytest.raises(stock_range_service.StockRangeServiceError) as fetch_info:
        stock_range_service.study_stock_range(request)
    assert fetch_info.value.code == "data_unavailable"
    assert fetch_info.value.exit_code == 1
    assert isinstance(fetch_info.value.__cause__, OSError)


@pytest.mark.parametrize(
    ("frame", "expected_code"),
    [
        (pd.DataFrame({"date": ["2026-01-01"], "close": [100]}), "invalid_data"),
        (
            pd.DataFrame({
                "date": ["2026-01-01"],
                "open": [100],
                "high": [100],
                "low": [100],
                "close": [100],
            }),
            "insufficient_history",
        ),
    ],
)
def test_invalid_schema_and_one_bar_history_fail_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    frame: pd.DataFrame,
    expected_code: str,
) -> None:
    _patch_boundaries(monkeypatch, frame, cutoff=date(2026, 1, 1))

    with pytest.raises(stock_range_service.StockRangeServiceError) as error_info:
        stock_range_service.study_stock_range(StockRangeRequest(
            symbol="600519",
            periods=[2],
            levels=[95],
        ))

    assert error_info.value.code == expected_code
    assert error_info.value.exit_code == 1

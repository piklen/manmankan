"""`kan range` 命令参数、JSON 契约与终端输出。"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from kan.cli import app
from kan.domain.stock_range import (
    DownsideThresholdStudy,
    StockRangeCoverage,
    StockRangeRequest,
    StockRangeStudy,
    StockRangeWindow,
    UpsideThresholdStudy,
)


def _down(level: float = 75, threshold: float = -2) -> DownsideThresholdStudy:
    return DownsideThresholdStudy(
        basis="empirical_level",
        level_pct=level,
        threshold_pct=threshold,
        actual_coverage_pct=80,
        trigger_count=2,
        trigger_ratio_pct=40,
        close_above_count=1,
        close_above_ratio_pct=50,
        close_at_or_below_count=1,
        close_at_or_below_ratio_pct=50,
        close_positive_count=1,
        close_positive_ratio_pct=50,
        gap_trigger_count=0,
        gap_trigger_ratio_pct=0,
        intraday_trigger_count=2,
        close_median_pct=-1.5,
    )


def _up(level: float = 75, threshold: float = 2.5) -> UpsideThresholdStudy:
    return UpsideThresholdStudy(
        basis="empirical_level",
        level_pct=level,
        threshold_pct=threshold,
        actual_coverage_pct=80,
        trigger_count=2,
        trigger_ratio_pct=40,
        close_at_or_above_count=1,
        close_at_or_above_ratio_pct=50,
        close_below_count=1,
        close_below_ratio_pct=50,
        close_positive_count=2,
        close_positive_ratio_pct=100,
        gap_trigger_count=1,
        gap_trigger_ratio_pct=50,
        intraday_trigger_count=1,
        close_median_pct=2,
        pullback_median_pct=1.2,
    )


def _study(request: StockRangeRequest) -> StockRangeStudy:
    windows = [
        StockRangeWindow(
            period=period,
            sample_count=period,
            missing_sample_count=0,
            start_date="2026-08-01",
            end_date="2026-08-20",
            downside=[_down(level) for level in request.levels],
            upside=[_up(level) for level in request.levels],
            custom_downside=(
                None
                if request.down_pct is None
                else _down(level=75, threshold=-request.down_pct).model_copy(
                    update={"basis": "custom", "level_pct": None},
                )
            ),
            custom_upside=(
                None
                if request.up_pct is None
                else _up(level=75, threshold=request.up_pct).model_copy(
                    update={"basis": "custom", "level_pct": None},
                )
            ),
        )
        for period in request.periods
    ]
    return StockRangeStudy(
        request=request,
        symbol=request.symbol,
        name="示例股份",
        source="fixture",
        data_start="2026-08-01",
        data_cutoff="2026-08-20",
        latest_complete_cutoff="2026-08-20",
        reference_close=20,
        coverage=StockRangeCoverage(
            requested_bars=max(request.periods) + 1,
            raw_rows=max(request.periods) + 1,
            invalid_date_rows=0,
            after_cutoff_rows=0,
            duplicate_date_rows=0,
            invalid_ohlc_rows=0,
            invalid_reference_observations=0,
            excluded_rows=0,
            older_valid_rows_ignored=0,
            valid_bars=max(request.periods) + 1,
            valid_observations=max(request.periods),
        ),
        windows=windows,
        warnings=["5 日窗口只有 5 个样本，新增一个交易日就可能明显改变各档幅度"],
    )


def _stub_service(monkeypatch):
    captured: list[StockRangeRequest] = []

    monkeypatch.setattr(
        "kan.storage.watchlist.resolve_symbol_or_name",
        lambda raw: ("600519", "贵州茅台"),
    )

    def fake(request: StockRangeRequest) -> StockRangeStudy:
        captured.append(request)
        return _study(request)

    monkeypatch.setattr("kan.service.stock_range_service.study_stock_range", fake)
    return captured


def test_range_defaults_are_exact_user_contract(monkeypatch) -> None:
    captured = _stub_service(monkeypatch)

    result = CliRunner().invoke(app, ["range", "600519", "--format", "json"])

    assert result.exit_code == 0, result.output
    request = captured[0]
    assert request.periods == (5, 15)
    assert request.levels == (75.0, 85.0, 90.0, 95.0)
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "range"
    assert payload["study"]["symbol"] == "600519"
    assert [item["period"] for item in payload["study"]["windows"]] == [5, 15]


def test_range_terminal_shows_windows_outcomes_and_disclaimer(monkeypatch) -> None:
    _stub_service(monkeypatch)

    result = CliRunner().invoke(app, ["range", "600519"])

    assert result.exit_code == 0, result.output
    assert "示例股份 600519" in result.output
    assert "近 5 个完整交易日" in result.output
    assert "近 15 个完整交易日" in result.output
    assert "75%档" in result.output
    assert "实80%" in result.output
    assert "收回线" in result.output
    assert "收盘线下" in result.output
    assert "创新低" in result.output
    assert "…" not in result.output


def test_range_custom_periods_levels_and_thresholds(monkeypatch) -> None:
    captured = _stub_service(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "range", "茅台", "--periods", "10,30", "--levels", "80,92.5",
            "--down", "3", "--up", "7", "--format", "json",
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured[0]
    assert request.symbol == "600519"
    assert request.periods == (10, 30)
    assert request.levels == (80.0, 92.5)
    assert request.down_pct == 3
    assert request.up_pct == 7
    payload = json.loads(result.output)
    assert payload["study"]["windows"][0]["custom_downside"]["threshold_pct"] == -3
    assert payload["study"]["windows"][0]["custom_upside"]["threshold_pct"] == 7


def test_range_invalid_lists_keep_json_error_envelope() -> None:
    runner = CliRunner()

    bad_period = runner.invoke(
        app,
        ["range", "600519", "--periods", "1,15", "--format", "json"],
    )
    bad_level = runner.invoke(
        app,
        ["range", "600519", "--levels", "75,100", "--format", "json"],
    )
    bad_down = runner.invoke(
        app,
        ["range", "600519", "--down", "bad", "--format", "json"],
    )
    bad_up = runner.invoke(
        app,
        ["range", "600519", "--up", "bad", "--format", "json"],
    )

    assert bad_period.exit_code == 2
    assert json.loads(bad_period.output)["error"]["code"] == "invalid_periods"
    assert bad_level.exit_code == 2
    assert json.loads(bad_level.output)["error"]["code"] == "invalid_levels"
    assert bad_down.exit_code == 2
    assert json.loads(bad_down.output)["error"]["code"] == "invalid_down"
    assert bad_up.exit_code == 2
    assert json.loads(bad_up.output)["error"]["code"] == "invalid_up"


def test_range_help_exposes_defaults() -> None:
    result = CliRunner().invoke(app, ["range", "--help"])

    assert result.exit_code == 0
    assert "5,15" in result.output
    assert "75,85,90,95" in result.output
    assert "--down" in result.output
    assert "--up" in result.output

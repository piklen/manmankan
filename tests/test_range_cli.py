"""`kan range` 命令参数、JSON 契约与终端输出。"""

from __future__ import annotations

import json

import pytest
from click import unstyle
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
        reference_price=round(20 * (1 + threshold / 100), 4),
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
        reference_price=round(20 * (1 + threshold / 100), 4),
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
        names = {"600519": "示例股份", "000858": "示例二号"}
        return _study(request).model_copy(
            update={"name": names.get(request.symbol, "示例股票")},
        )

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
    first_down = payload["study"]["windows"][0]["downside"][0]
    assert first_down["reference_price"] == 19.6


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
    negative_down = runner.invoke(
        app,
        ["range", "600519", "--down", "-0.01", "--format", "json"],
    )

    assert bad_period.exit_code == 2
    assert json.loads(bad_period.output)["error"]["code"] == "invalid_periods"
    assert bad_level.exit_code == 2
    assert json.loads(bad_level.output)["error"]["code"] == "invalid_levels"
    assert bad_down.exit_code == 2
    assert json.loads(bad_down.output)["error"]["code"] == "invalid_down"
    assert bad_up.exit_code == 2
    assert json.loads(bad_up.output)["error"]["code"] == "invalid_up"
    assert negative_down.exit_code == 2
    assert json.loads(negative_down.output)["error"]["code"] == "invalid_down"


def test_range_zero_threshold_is_explicit_and_distinct_from_omitted(
    monkeypatch,
) -> None:
    captured = _stub_service(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "range", "600519", "--down", "0", "--up", "0", "--format", "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured[0].down_pct == 0
    assert captured[0].up_pct == 0
    window = json.loads(result.output)["study"]["windows"][0]
    assert window["custom_downside"]["threshold_pct"] == 0
    assert window["custom_upside"]["threshold_pct"] == 0


def test_range_codes_json_preserves_input_order_and_batch_shape(monkeypatch) -> None:
    captured = _stub_service(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["range", "--codes", "600519,000858", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert [request.symbol for request in captured] == ["600519", "000858"]
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["partial"] is False
    assert payload["errors"] == []
    assert payload["stats"] == {
        "requested": 2,
        "succeeded": 2,
        "failed": 0,
        "windows": 4,
    }
    assert [study["symbol"] for study in payload["studies"]] == [
        "600519",
        "000858",
    ]
    assert payload["studies"][0]["windows"][0]["upside"][0][
        "reference_price"
    ] == 20.5


def test_range_codes_normalizes_exchange_affixes_and_empty_edge_tokens(
    monkeypatch,
) -> None:
    captured = _stub_service(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "range", "--codes", ",SH600519,000858.SZ,", "--format", "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [request.symbol for request in captured] == ["600519", "000858"]


def test_range_codes_terminal_is_compact_and_deduplicates_common_warnings(
    monkeypatch,
) -> None:
    _stub_service(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["range", "--codes", "600519,000858"],
    )

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert "多股日内上下行范围" in output
    assert "示例股份" in output and "600519" in output
    assert "示例二号" in output and "000858" in output
    assert "下90" in output
    assert "上95" in output
    assert "-2%" in output and "19.60元" in output
    assert "实80%" in output and "触2/5" in output
    assert output.count("5 日窗口只有 5 个样本") == 1
    assert "共同提示" in output
    assert "创新低" in output
    assert "…" not in output


def test_batch_renderer_keeps_long_period_evidence_at_width_80() -> None:
    from io import StringIO

    from rich.console import Console

    from kan.render.terminal_range import render_stock_range_batch

    request = StockRangeRequest(
        symbol="600519",
        periods=[60, 250],
        levels=[75, 85, 90, 95],
    )
    base_study = _study(request)
    study = base_study.model_copy(update={
        "warnings": [],
        "windows": [
            window.model_copy(update={
                "upside": [
                    row.model_copy(update={
                        "threshold_pct": 10.0001,
                        "reference_price": 22.0,
                    })
                    for row in window.upside
                ],
            })
            for window in base_study.windows
        ],
    })
    output = StringIO()

    render_stock_range_batch(
        Console(file=output, width=80, color_system=None),
        [study],
        failures=[],
    )

    rendered = output.getvalue()
    assert "60/60" in rendered
    assert "250/250" in rendered
    assert "触2/60" in rendered
    assert "触2/250" in rendered
    assert "+10.0001%" in rendered
    assert "…" not in rendered


def test_terminal_threshold_precision_is_consistent_for_single_and_batch(
    monkeypatch,
) -> None:
    _stub_service(monkeypatch)
    runner = CliRunner()

    single = runner.invoke(app, ["range", "600519", "--up", "10.0001"])
    batch = runner.invoke(
        app,
        ["range", "--codes", "600519,000858", "--up", "10.0001"],
    )
    zero = runner.invoke(app, ["range", "600519", "--up", "0"])

    assert single.exit_code == 0, single.output
    assert batch.exit_code == 0, batch.output
    assert zero.exit_code == 0, zero.output
    assert "+10.0001%" in unstyle(single.output)
    assert "+10.0001%" in unstyle(batch.output)
    zero_output = unstyle(zero.output)
    assert "0%" in zero_output
    assert "+0%" not in zero_output
    assert "-0%" not in zero_output


def test_range_codes_terminal_shows_custom_thresholds_and_stock_warnings(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "kan.storage.watchlist.resolve_symbol_or_name",
        lambda raw: ("600519", "示例股份"),
    )

    def varied_service(request: StockRangeRequest) -> StockRangeStudy:
        common = "共同样本提示"
        unique = "第一只数据提示" if request.symbol == "600519" else "第二只数据提示"
        name = "示例股份" if request.symbol == "600519" else "示例二号"
        return _study(request).model_copy(
            update={"name": name, "warnings": [common, unique]},
        )

    monkeypatch.setattr(
        "kan.service.stock_range_service.study_stock_range",
        varied_service,
    )

    result = CliRunner().invoke(
        app,
        [
            "range", "--codes", "600519,000858", "--levels", "75,85",
            "--down", "3",
        ],
    )

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert "下75" in output and "下85" in output
    assert "用户指定幅度复核" in output
    assert "-3%" in output
    assert "共同提示：共同样本提示" in output
    assert "示例股份 600519：第一只数据提示" in output
    assert "示例二号 000858：第二只数据提示" in output


@pytest.mark.parametrize(
    ("args", "error_code"),
    [
        (["range", "--format", "json"], "invalid_target"),
        (
            [
                "range", "600519", "--codes", "000858", "--format", "json",
            ],
            "invalid_target",
        ),
        (["range", "--codes", "", "--format", "json"], "empty_codes"),
        (["range", "--codes", ",，;", "--format", "json"], "empty_codes"),
        (
            [
                "range", "--codes", "600519,600519", "--format", "json",
            ],
            "duplicate_codes",
        ),
        (
            ["range", "--codes", "600519,bad", "--format", "json"],
            "invalid_codes",
        ),
        (
            [
                "range",
                "--codes",
                ",".join(f"60{index:04d}" for index in range(21)),
                "--format",
                "json",
            ],
            "too_many_codes",
        ),
    ],
)
def test_range_target_and_code_pool_errors_are_json(
    args: list[str],
    error_code: str,
) -> None:
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == error_code


def test_range_codes_partial_failure_keeps_results_and_returns_nonzero(
    monkeypatch,
) -> None:
    _stub_service(monkeypatch)
    from kan.service.stock_range_service import StockRangeServiceError

    def partial_service(request: StockRangeRequest) -> StockRangeStudy:
        if request.symbol == "000858":
            raise StockRangeServiceError(
                "data_unavailable",
                "000858 的日 K 数据暂不可用",
                hint="稍后重试",
            )
        return _study(request)

    monkeypatch.setattr(
        "kan.service.stock_range_service.study_stock_range",
        partial_service,
    )

    result = CliRunner().invoke(
        app,
        ["range", "--codes", "600519,000858", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["partial"] is True
    assert payload["error"]["code"] == "batch_partial"
    assert payload["error"]["reason"] == "batch_partial"
    assert payload["stats"]["succeeded"] == 1
    assert payload["stats"]["failed"] == 1
    assert [study["symbol"] for study in payload["studies"]] == ["600519"]
    assert payload["errors"] == [{
        "symbol": "000858",
        "error": {
            "code": "data_unavailable",
            "message": "000858 的日 K 数据暂不可用",
            "hint": "稍后重试",
            "exit_code": 1,
        },
    }]


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_exit"),
    [
        (ValueError("未找到股票"), "invalid_symbol", 2),
        (OSError("catalog offline"), "symbol_catalog_unavailable", 1),
    ],
)
def test_range_single_symbol_resolution_errors_are_json(
    monkeypatch,
    failure: Exception,
    expected_code: str,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        "kan.storage.watchlist.resolve_symbol_or_name",
        lambda _raw: (_ for _ in ()).throw(failure),
    )

    result = CliRunner().invoke(
        app,
        ["range", "600519", "--format", "json"],
    )

    assert result.exit_code == expected_exit
    assert json.loads(result.output)["error"]["code"] == expected_code


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_exit"),
    [
        ("service", "data_unavailable", 1),
        (ValueError("bad request"), "invalid_request", 2),
        (OSError("provider offline"), "data_unavailable", 1),
    ],
)
def test_range_single_service_errors_are_json(
    monkeypatch,
    failure,
    expected_code: str,
    expected_exit: int,
) -> None:
    _stub_service(monkeypatch)
    from kan.service.stock_range_service import StockRangeServiceError

    actual_failure = (
        StockRangeServiceError("data_unavailable", "日 K 暂不可用")
        if failure == "service"
        else failure
    )
    monkeypatch.setattr(
        "kan.service.stock_range_service.study_stock_range",
        lambda _request: (_ for _ in ()).throw(actual_failure),
    )

    result = CliRunner().invoke(
        app,
        ["range", "600519", "--format", "json"],
    )

    assert result.exit_code == expected_exit
    assert json.loads(result.output)["error"]["code"] == expected_code


def test_range_codes_wraps_value_error_as_per_stock_error(monkeypatch) -> None:
    _stub_service(monkeypatch)

    def partial_service(request: StockRangeRequest) -> StockRangeStudy:
        if request.symbol == "000858":
            raise ValueError("bad request")
        return _study(request)

    monkeypatch.setattr(
        "kan.service.stock_range_service.study_stock_range",
        partial_service,
    )

    result = CliRunner().invoke(
        app,
        ["range", "--codes", "600519,000858", "--format", "json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["partial"] is True
    assert payload["errors"][0]["error"]["code"] == "invalid_request"


def test_range_codes_all_unexpected_failures_keep_json_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.service.stock_range_service.study_stock_range",
        lambda _request: (_ for _ in ()).throw(OSError("provider offline")),
    )

    result = CliRunner().invoke(
        app,
        ["range", "--codes", "600519,000858", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["partial"] is False
    assert payload["error"]["code"] == "batch_failed"
    assert payload["error"]["reason"] == "batch_failed"
    assert payload["studies"] == []
    assert [item["error"]["code"] for item in payload["errors"]] == [
        "data_unavailable",
        "data_unavailable",
    ]


def test_range_codes_all_failures_render_terminal_and_disclaimer(monkeypatch) -> None:
    from kan.service.stock_range_service import StockRangeServiceError

    monkeypatch.setattr(
        "kan.service.stock_range_service.study_stock_range",
        lambda request: (_ for _ in ()).throw(StockRangeServiceError(
            "data_unavailable",
            f"{request.symbol} 暂无日 K",
        )),
    )

    result = CliRunner().invoke(
        app,
        ["range", "--codes", "600519,000858"],
    )

    assert result.exit_code == 1
    output = unstyle(result.output)
    assert "成功 0 · 失败 2" in output
    assert "600519：600519 暂无日 K" in output
    assert "000858：000858 暂无日 K" in output
    assert "创新低" in output


def test_range_help_exposes_defaults() -> None:
    result = CliRunner().invoke(app, ["range", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "5,15" in output
    assert "75,85,90,95" in output
    assert "--down" in output
    assert "--up" in output
    assert "--codes" in output
    assert "20" in output
    assert "0/3" in output
    assert "0/7" in output

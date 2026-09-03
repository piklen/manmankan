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


def _evidence_cells(output: str) -> list[tuple[list[str], list[str]]]:
    """成对读取数据行及其比例行，避免导语或脚注满足证据断言。"""

    lines = unstyle(output).splitlines()
    rows = []
    for index, line in enumerate(lines[:-1]):
        cells = [cell.strip() for cell in line.split("│")[1:-1]]
        if len(cells) == 6 and cells[0].endswith("%档"):
            details = [cell.strip() for cell in lines[index + 1].split("│")[1:-1]]
            rows.append((cells, details))
    return rows


def _render_study(study: StockRangeStudy, *, batch: bool) -> str:
    from io import StringIO

    from rich.console import Console

    from kan.render.terminal_range import render_stock_range, render_stock_range_batch

    output = StringIO()
    console = Console(file=output, width=80, color_system=None)
    if batch:
        render_stock_range_batch(console, [study], failures=[])
    else:
        render_stock_range(console, study)
    return output.getvalue()


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
    assert "未越80%" in result.output
    assert "收回/到过" in result.output
    assert "收涨/到过" in result.output
    assert "未守住/到过" in result.output
    assert "守住/到过" in result.output
    assert "创新低" in result.output
    assert "…" not in result.output


@pytest.mark.parametrize(
    ("target", "stock_count"),
    [(["600519"], 1), (["--codes", "600519,000858"], 2)],
)
def test_terminal_keeps_all_levels_adjacent_periods_and_conditional_evidence(
    monkeypatch, target: list[str], stock_count: int,
) -> None:
    _stub_service(monkeypatch)

    result = CliRunner().invoke(app, ["range", *target])

    assert result.exit_code == 0, result.output
    rows = _evidence_cells(result.output)
    expected_order = [
        (f"{level}%档", f"{period}日")
        for level in (75, 85, 90, 95)
        for period in (5, 15)
    ]
    assert [(cells[0], cells[1]) for cells, _ in rows] == expected_order * 2 * stock_count
    for cells, details in rows:
        period = cells[1].removesuffix("日")
        assert cells[3] == f"2/{period}天"
        assert cells[4:] == ["1/2次", "1/2次"]
        assert details[4:] == ["50%", "50%"]
    output = unstyle(result.output)
    assert output.index("5 日窗口只有 5 个样本") < output.index("历史幅度对照")
    assert "日涨跌幅相对前收，不是持仓盈亏" in output
    assert "不是未来有95%的把握" in output
    if stock_count == 2:
        assert output.index("示例股份 600519") < output.index("示例二号 000858")
        assert output.count("读法：") == 1
        assert output.count("5 日窗口只有 5 个样本") == 1
        assert output.count("历史价格不预示未来") == 1


@pytest.mark.parametrize("target", [["600519"], ["--codes", "600519,000858"]])
def test_custom_summary_answers_before_each_stocks_history_tables(
    monkeypatch, target: list[str],
) -> None:
    _stub_service(monkeypatch)

    result = CliRunner().invoke(app, ["range", *target, "--down", "3", "--up", "7"])

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert output.index("5 日窗口只有 5 个样本") < output.index("你输入的幅度")
    summaries = output.split("你输入的幅度")[1:]
    assert len(summaries) == (2 if "--codes" in target else 1)
    for stock in summaries:
        summary, _tables = stock.split("历史幅度对照", 1)
        assert summary.index("下跌 -3%") < summary.index("上涨 +7%")
        assert "按本次参考收盘折算 19.40 元" in summary
        assert "按本次参考收盘折算 21.40 元" in summary
        for period in (5, 15):
            assert (
                f"近 {period} 日：2/{period} 天到过；"
                "收盘收回 1/2 次（50%）；收盘上涨 1/2 次（50%）"
            ) in summary
            assert (
                f"近 {period} 日：2/{period} 天到过；"
                "收盘未守住 1/2 次（50%）；守住 1/2 次（50%）"
            ) in summary


@pytest.mark.parametrize("batch", [False, True])
def test_zero_touches_are_no_samples_not_zero_probability(batch: bool) -> None:
    request = StockRangeRequest(
        symbol="600519", periods=[5], levels=[75, 85, 90, 95], down_pct=3, up_pct=7,
    )
    base = _study(request)
    common = {
        "actual_coverage_pct": 100,
        "trigger_count": 0,
        "trigger_ratio_pct": 0,
        "close_positive_count": 0,
        "close_positive_ratio_pct": None,
        "gap_trigger_count": 0,
        "gap_trigger_ratio_pct": None,
        "intraday_trigger_count": 0,
        "close_median_pct": None,
    }
    down = {
        **common,
        "close_above_count": 0,
        "close_above_ratio_pct": None,
        "close_at_or_below_count": 0,
        "close_at_or_below_ratio_pct": None,
    }
    up = {
        **common,
        "close_below_count": 0,
        "close_below_ratio_pct": None,
        "close_at_or_above_count": 0,
        "close_at_or_above_ratio_pct": None,
        "pullback_median_pct": None,
    }
    window = base.windows[0]
    assert window.custom_downside is not None
    assert window.custom_upside is not None
    study = base.model_copy(update={
        "windows": [window.model_copy(update={
            "downside": [row.model_copy(update=down) for row in window.downside],
            "upside": [row.model_copy(update=up) for row in window.upside],
            "custom_downside": window.custom_downside.model_copy(update=down),
            "custom_upside": window.custom_upside.model_copy(update=up),
        })],
    })

    output = _render_study(study, batch=batch)

    summary = output.split("你输入的幅度", 1)[1].split("历史幅度对照", 1)[0]
    assert summary.count("0/5 天到过；无触及样本") == 2
    assert "0%" not in summary
    rows = _evidence_cells(output)
    assert len(rows) == 8
    for cells, details in rows:
        assert cells[3:] == ["0/5天", "无样本", "无样本"]
        assert details[3] == "0%"
        assert details[4:] == ["", ""]
    assert "0/0" not in output


@pytest.mark.parametrize("batch", [False, True])
def test_one_touch_keeps_denominator_alongside_hundred_percent(batch: bool) -> None:
    request = StockRangeRequest(symbol="600519", periods=[5], levels=[75, 85, 90, 95])
    base = _study(request)
    common = {
        "actual_coverage_pct": 80,
        "trigger_count": 1,
        "trigger_ratio_pct": 20,
        "close_positive_count": 1,
        "close_positive_ratio_pct": 100,
        "gap_trigger_count": 0,
        "gap_trigger_ratio_pct": 0,
        "intraday_trigger_count": 1,
        "close_median_pct": 1,
    }
    study = base.model_copy(update={
        "windows": [window.model_copy(update={
            "downside": [row.model_copy(update={
                **common,
                "close_above_count": 1,
                "close_above_ratio_pct": 100,
                "close_at_or_below_count": 0,
                "close_at_or_below_ratio_pct": 0,
            }) for row in window.downside],
            "upside": [row.model_copy(update={
                **common,
                "close_below_count": 1,
                "close_below_ratio_pct": 100,
                "close_at_or_above_count": 0,
                "close_at_or_above_ratio_pct": 0,
                "pullback_median_pct": 1.5,
            }) for row in window.upside],
        }) for window in base.windows],
    })

    rows = _evidence_cells(_render_study(study, batch=batch))

    assert len(rows) == 8
    for index, (cells, details) in enumerate(rows):
        assert cells[3] == "1/5天"
        assert cells[4] == "1/1次"
        assert details[4] == "100%"
        assert cells[5] == ("1/1次" if index < 4 else "0/1次")
        assert details[5] == ("100%" if index < 4 else "0%")


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


def test_range_codes_terminal_is_complete_and_deduplicates_common_warnings(
    monkeypatch,
) -> None:
    _stub_service(monkeypatch)

    result = CliRunner().invoke(
        app,
        ["range", "--codes", "600519,000858"],
    )

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert "多股日涨跌幅历史复核" in output
    assert "示例股份" in output and "600519" in output
    assert "示例二号" in output and "000858" in output
    assert "75%档" in output and "85%档" in output
    assert "90%档" in output and "95%档" in output
    assert "-2%" in output and "19.60元" in output
    assert "未越80%" in output and "2/5天" in output
    assert output.count("5 日窗口只有 5 个样本") == 1
    assert "共同提示" in output
    assert "创新低" in output
    assert "…" not in output


@pytest.mark.parametrize("batch", [False, True])
def test_renderer_keeps_long_period_evidence_at_width_80(batch: bool) -> None:
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
                "downside": [
                    row.model_copy(update={
                        "trigger_count": window.period,
                        "trigger_ratio_pct": 100,
                        "close_above_count": window.period // 2,
                        "close_at_or_below_count": window.period // 2,
                        "close_positive_count": window.period // 2,
                        "actual_coverage_pct": 0,
                        "intraday_trigger_count": window.period,
                    })
                    for row in window.downside
                ],
                "upside": [
                    row.model_copy(update={
                        "threshold_pct": 10.0001,
                        "reference_price": 22.0,
                        "trigger_count": window.period,
                        "trigger_ratio_pct": 100,
                        "close_below_count": window.period // 2,
                        "close_at_or_above_count": window.period // 2,
                        "close_positive_count": window.period,
                        "actual_coverage_pct": 0,
                        "gap_trigger_count": 0,
                        "gap_trigger_ratio_pct": 0,
                        "intraday_trigger_count": window.period,
                    })
                    for row in window.upside
                ],
            })
            for window in base_study.windows
        ],
    })
    rendered = _render_study(study, batch=batch)
    assert "60/60" in rendered
    assert "250/250" in rendered
    assert "60/60天" in rendered
    assert "250/250天" in rendered
    assert "+10.0001%" in rendered
    assert "…" not in rendered
    rows = _evidence_cells(rendered)
    assert len(rows) == 16
    for cells, details in rows:
        period = int(cells[1].removesuffix("日"))
        assert cells[4:] == [f"{period // 2}/{period}次"] * 2
        assert details[4:] == ["50%", "50%"]
        if cells[2].startswith("+"):
            assert cells[2] == "+10.0001%"


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
    assert "75%档" in output and "85%档" in output
    assert "你输入的幅度" in output
    assert "-3%" in output
    assert "共同提示：共同样本提示" in output
    assert "示例股份 600519：第一只数据提示" in output
    assert "示例二号 000858：第二只数据提示" in output
    first_table = output.index("历史幅度对照")
    for warning in ("共同样本提示", "第一只数据提示", "第二只数据提示"):
        assert output.index(warning) < first_table


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
    assert "填3表示相对前收下跌3%" in output
    assert "填7表示相对前收上涨7%" in output
    assert "可填0" in output
    assert "无需先填阈值" in output
    assert "不是持仓盈亏" in output
    assert "非未来概率" in output
    assert "…" not in output

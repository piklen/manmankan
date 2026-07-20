"""股票池型命令 --all 回归测试 · 不打真实网络。"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest
import typer
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import PeriodResult, StockScanResult
from kan.core.scanner import TrendResult
from kan.data.tushare import TushareDataContractError
from kan.infra.lifecycle import CollectingReporter, OperationState

ALL_PAIRS = [("600519", "贵州茅台"), ("000858", "五粮液")]


def _scan_result(symbol: str, name: str, period: int = 30) -> StockScanResult:
    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=100.0,
        scan_date=date(2026, 6, 26),
        periods=[
            PeriodResult(
                period=period,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=0,
        high_resonance=0,
    )


@pytest.fixture
def all_pool_runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """隔离全市场池、自动补数、新鲜度和外部 enrich。"""
    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", lambda: list(ALL_PAIRS))
    monkeypatch.setattr("kan.core.auto_fetch.auto_fetch_stale", lambda _pairs, **_kw: None)
    monkeypatch.setattr("kan.cli.extreme_cmds._auto_fetch_stale", lambda _pairs, **_kw: None)
    monkeypatch.setattr("kan.core.enrich.enrich_scan_rows", lambda rows, **_kw: rows)
    monkeypatch.setattr("kan.data.fetcher.data_cutoff_date", lambda _sym: date(2026, 6, 26))
    monkeypatch.setattr("kan.data.fetcher.cache_age", lambda _sym: "2026-06-26 15:30")
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 6, 26))
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    monkeypatch.setattr("kan.core.scanner.get_limit_threshold", lambda *a, **k: 10.0)
    return CliRunner()


def test_scan_all_uses_all_stocks_pool(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[tuple[str, str]]] = {}

    monkeypatch.setattr(
        "kan.cli.scan_cmds._get_watchlist_pairs",
        lambda group=None: (_ for _ in ()).throw(AssertionError("不应读取自选")),
    )

    def fake_scan(input_pairs, mode="low", periods=None):
        captured["pairs"] = list(input_pairs)
        return [_scan_result(symbol, name) for symbol, name in input_pairs]

    monkeypatch.setattr("kan.core.scanner.scan_batch", fake_scan)

    result = all_pool_runner.invoke(app, ["scan", "--all", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert captured["pairs"] == ALL_PAIRS
    assert '"command": "scan"' in result.output


def test_scan_all_rejects_diff(all_pool_runner: CliRunner) -> None:
    result = all_pool_runner.invoke(app, ["scan", "--all", "--diff", "--format", "json"])

    assert result.exit_code == 2
    assert "invalid_diff_pool" in result.output


@pytest.mark.parametrize(
    "args,expected",
    [
        (["scan", "--all", "--only-watchlist", "--format", "json"], "invalid_all_pool"),
        (["scan", "--all", "--group", "观察", "--format", "json"], "invalid_all_pool"),
    ],
)
def test_scan_all_rejects_pool_modifiers(
    all_pool_runner: CliRunner,
    args: list[str],
    expected: str,
) -> None:
    result = all_pool_runner.invoke(app, args)

    assert result.exit_code == 2
    assert expected in result.output


def test_scan_all_empty_pool_has_specific_error(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", lambda: [])
    monkeypatch.setattr("kan.core.scanner.scan_batch", lambda _pairs, **_kw: [])

    result = all_pool_runner.invoke(app, ["scan", "--all", "--format", "json"])

    assert result.exit_code == 1
    assert "empty_all_stocks" in result.output


def test_trend_all_uses_all_stocks_pool(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "kan.cli.trend_cmds._get_watchlist_pairs",
        lambda group=None: (_ for _ in ()).throw(AssertionError("不应读取自选")),
    )

    # --all 走截面路径 · mock fetch_recent_daily_bars(返空 panel) + trend_batch_cross_section(接收 targets)
    def fake_recent_daily_bars(days, **kw):
        captured["fetch_symbols"] = kw.get("symbols")
        captured["on_progress"] = kw.get("on_progress")
        kw["on_progress"](1, days, date(2026, 6, 26), len(ALL_PAIRS))
        return pd.DataFrame(columns=["symbol", "date", "open", "close"])

    monkeypatch.setattr("kan.data.kline_snapshot.fetch_recent_daily_bars", fake_recent_daily_bars)

    def fake_trend_cross(input_pairs, *, candle=False, panel=None, **_kw):
        captured["pairs"] = list(input_pairs)
        return [
            TrendResult(
                symbol=symbol,
                name=name,
                current_price=100.0,
                streak=-3,
                streak_pct=-2.5,
                daily_changes=[("2026-06-26", -0.8)],
            )
            for symbol, name in input_pairs
        ]

    monkeypatch.setattr(
        "kan.core.scanner_trend.trend_batch_cross_section",
        fake_trend_cross,
    )

    result = all_pool_runner.invoke(app, ["trend", "--all"])

    assert result.exit_code == 0, result.output
    assert captured["pairs"] == ALL_PAIRS
    assert captured["fetch_symbols"] == ["600519", "000858"]
    assert callable(captured["on_progress"])
    assert "A股全市场连续涨跌" in result.output


@pytest.mark.parametrize("fmt", ["json", "md"])
def test_trend_all_progress_does_not_pollute_structured_stdout(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    fmt: str,
) -> None:
    """全市场进度反馈只能走 stderr，不能污染 JSON / Markdown stdout。"""

    def fake_recent_daily_bars(days, **kw):
        kw["on_progress"](1, days, date(2026, 6, 26), len(ALL_PAIRS))
        return pd.DataFrame(columns=["symbol", "date", "open", "close"])

    monkeypatch.setattr("kan.data.kline_snapshot.fetch_recent_daily_bars", fake_recent_daily_bars)

    def fake_trend_cross(input_pairs, *, candle=False, panel=None, **_kw):
        return [
            TrendResult(
                symbol=symbol,
                name=name,
                current_price=100.0,
                streak=2,
                streak_pct=1.5,
                daily_changes=[("2026-06-26", 0.8)],
            )
            for symbol, name in input_pairs
        ]

    monkeypatch.setattr(
        "kan.core.scanner_trend.trend_batch_cross_section",
        fake_trend_cross,
    )

    result = all_pool_runner.invoke(app, ["trend", "--all", "--format", fmt])

    assert result.exit_code == 0, result.output
    for progress_text in ("加载全市场股票池", "拉取全市场日线截面", "计算连续涨跌"):
        assert progress_text not in result.stdout
    if fmt == "json":
        data = json.loads(result.stdout)
        assert data["command"] == "trend"
        assert len(data["results"]) == len(ALL_PAIRS)
    else:
        assert "慢慢看 · A股全市场连续涨跌" in result.stdout


def test_trend_all_uses_one_operation_through_output_construction(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporter = CollectingReporter()
    monkeypatch.setattr("kan.infra.progress.operation_reporter", lambda **_kw: reporter)
    original_echo = typer.echo

    def echo_after_close(message, **kwargs):
        assert reporter.events[-1].state is OperationState.SUCCEEDED
        original_echo(message, **kwargs)

    monkeypatch.setattr("kan.cli.trend_cmds.typer.echo", echo_after_close)

    def fake_recent_daily_bars(days, **kw):
        kw["on_progress"](days, days, date(2026, 6, 26), len(ALL_PAIRS))
        return pd.DataFrame(columns=["symbol", "date", "open", "close"])

    monkeypatch.setattr("kan.data.kline_snapshot.fetch_recent_daily_bars", fake_recent_daily_bars)
    monkeypatch.setattr(
        "kan.core.scanner_trend.trend_batch_cross_section",
        lambda input_pairs, **_kw: [
            TrendResult(symbol, name, 100.0, 2, 1.5, [("2026-06-26", 0.8)])
            for symbol, name in input_pairs
        ],
    )

    result = all_pool_runner.invoke(app, ["trend", "--all", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert [event.state for event in reporter.events if event.state is not None] == [
        OperationState.STARTED,
        OperationState.SUCCEEDED,
    ]
    messages = [event.message for event in reporter.events]
    assert "解析全市场股票池" in messages
    assert "计算日线截面新鲜度" in messages
    assert "过滤连续涨跌结果" in messages
    assert "构造趋势输出" in messages
    assert json.loads(result.stdout)["command"] == "trend"


def test_trend_plain_all_arg_points_to_flag(all_pool_runner: CliRunner) -> None:
    result = all_pool_runner.invoke(app, ["trend", "all"])

    assert result.exit_code == 2
    assert "kan trend --all" in result.output


@pytest.mark.parametrize(
    "args,expected",
    [
        (["trend", "--all", "--only-watchlist"], "--only-watchlist"),
        (["trend", "--all", "--group", "观察"], "--group"),
    ],
)
def test_trend_all_rejects_pool_modifiers(
    all_pool_runner: CliRunner,
    args: list[str],
    expected: str,
) -> None:
    result = all_pool_runner.invoke(app, args)

    assert result.exit_code == 2
    assert expected in result.output


def test_trend_all_empty_pool_has_specific_error(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", lambda: [])
    monkeypatch.setattr("kan.core.scanner.trend_batch", lambda _pairs, candle=False: [])

    result = all_pool_runner.invoke(app, ["trend", "--all"])

    assert result.exit_code == 1
    assert "全市场股票池为空" in result.output


def test_trend_all_surfaces_daily_contract_failure(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TushareDataContractError(
                "stk_factor_pro",
                "trade_date=20260626 仅返回 200 只，低于全市场截面校验下界 3000",
            )
        ),
    )

    result = all_pool_runner.invoke(app, ["trend", "--all"])

    assert result.exit_code == 1
    assert "stk_factor_pro" in result.output
    assert "仅返回 200 只" in " ".join(result.output.split())
    assert "未写入错误缓存" in result.output


def test_low_all_uses_all_stocks_pool(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[tuple[str, str]]] = {}

    def fake_extreme(input_pairs, periods, mode="low"):
        captured["pairs"] = list(input_pairs)
        return {}

    monkeypatch.setattr("kan.core.scanner.filter_extreme", fake_extreme)

    result = all_pool_runner.invoke(app, ["low", "30", "--all"])

    assert result.exit_code == 0, result.output
    assert captured["pairs"] == ALL_PAIRS
    assert "A股全市场中没有触及 30 日低点" in result.output


@pytest.mark.parametrize(
    "args,expected",
    [
        (["low", "30", "--all", "--only-watchlist"], "--only-watchlist"),
        (["low", "30", "--all", "--group", "观察"], "--group"),
    ],
)
def test_low_all_rejects_pool_modifiers(
    all_pool_runner: CliRunner,
    args: list[str],
    expected: str,
) -> None:
    result = all_pool_runner.invoke(app, args)

    assert result.exit_code == 2
    assert expected in result.output


def test_low_all_empty_pool_has_specific_error(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", lambda: [])

    result = all_pool_runner.invoke(app, ["low", "30", "--all"])

    assert result.exit_code == 1
    assert "全市场股票池为空" in result.output


def test_fetch_all_pulls_all_stocks(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[list[str]] = []

    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda _symbol: False)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, force=False, **kw: (
            fetched.append(list(symbols))
            or {symbol: pd.DataFrame({"close": [1.0]}) for symbol in symbols},
            {},
        ),
    )

    result = all_pool_runner.invoke(app, ["fetch", "--all"])

    assert result.exit_code == 0, result.output
    assert fetched == [["600519", "000858"]]


@pytest.mark.parametrize(
    "args,expected",
    [
        (["fetch", "--all", "--industry", "半导体"], "互斥"),
        (["fetch", "--all", "600519"], "股票代码"),
        (["fetch", "--all", "--only-watchlist"], "--only-watchlist"),
        (["fetch", "--all", "--group", "观察"], "--group"),
        (["fetch", "--industry", "半导体", "600519"], "股票代码"),
    ],
)
def test_fetch_all_rejects_invalid_pool_combinations(
    all_pool_runner: CliRunner,
    args: list[str],
    expected: str,
) -> None:
    result = all_pool_runner.invoke(app, args)

    assert result.exit_code == 2
    assert expected in result.output


def test_fetch_all_empty_pool_has_specific_error(
    all_pool_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", lambda: [])

    result = all_pool_runner.invoke(app, ["fetch", "--all"])

    assert result.exit_code == 1
    assert "全市场股票池为空" in result.output


@pytest.mark.parametrize(
    "args,expected",
    [
        (["find", "--all", "--industry", "半导体", "--format", "json"], "mutually_exclusive_pool"),
        (["find", "--all", "--only-watchlist", "--format", "json"], "invalid_all_pool"),
        (["find", "--all", "--group", "观察", "--format", "json"], "invalid_all_pool"),
    ],
)
def test_find_all_rejects_pool_modifiers(
    all_pool_runner: CliRunner,
    args: list[str],
    expected: str,
) -> None:
    result = all_pool_runner.invoke(app, args)

    assert result.exit_code == 2
    assert expected in result.output

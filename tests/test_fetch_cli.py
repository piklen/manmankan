"""kan fetch 批量主路径与生命周期回归测试。"""
from __future__ import annotations

import pandas as pd
from typer.testing import CliRunner

from kan.cli import app
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, OperationState


def _frame(rows: int = 1) -> pd.DataFrame:
    return pd.DataFrame({"close": [1.0] * rows})


def test_fetch_stably_deduplicates_and_partitions_fresh_symbols(monkeypatch):
    freshness_checks: list[str] = []
    batch_calls: list[tuple[list[str], bool]] = []

    def is_fresh(symbol: str) -> bool:
        freshness_checks.append(symbol)
        return symbol == "000858"

    def fetch_batch(symbols: list[str], force: bool = False, **kwargs):
        batch_calls.append((list(symbols), force))
        return ({symbol: _frame() for symbol in symbols}, {})

    monkeypatch.setattr("kan.data.fetcher.is_fresh", is_fresh)
    monkeypatch.setattr("kan.data.fetcher.fetch_batch", fetch_batch)

    result = CliRunner().invoke(
        app,
        ["fetch", "600519", "000858", "600519", "000001"],
    )

    assert result.exit_code == 0, result.output
    assert freshness_checks == ["600519", "000858", "000001"]
    assert batch_calls == [(["600519", "000001"], False)]
    assert "更新 2 只 · 已最新 1 只" in result.output


def test_fetch_force_skips_freshness_and_batches_every_unique_symbol(monkeypatch):
    batch_calls: list[tuple[list[str], bool]] = []

    def unexpected_freshness_check(symbol: str) -> bool:
        raise AssertionError(f"--force 不应检查 freshness: {symbol}")

    def fetch_batch(symbols: list[str], force: bool = False, **kwargs):
        batch_calls.append((list(symbols), force))
        return ({symbol: _frame() for symbol in symbols}, {})

    monkeypatch.setattr("kan.data.fetcher.is_fresh", unexpected_freshness_check)
    monkeypatch.setattr("kan.data.fetcher.fetch_batch", fetch_batch)

    result = CliRunner().invoke(
        app,
        ["fetch", "600519", "600519", "000858", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert batch_calls == [(["600519", "000858"], True)]
    assert "更新 2 只" in result.output


def test_fetch_partial_failure_is_failed_lifecycle_with_stable_safe_preview(monkeypatch):
    reporter = CollectingReporter()
    monkeypatch.setattr(
        "kan.infra.progress.operation_reporter",
        lambda **_kwargs: reporter,
    )
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda _symbol: False)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, force=False, **kw: (
            {"000003": _frame(2)},
            {
                "000005": "第五个错误",
                "000004": "第四个错误",
                "000002": "第二个错误",
                "000001": "第一个错误",
            },
        ),
    )

    result = CliRunner().invoke(
        app,
        ["fetch", "000001", "000002", "000003", "000004", "000005"],
    )

    assert result.exit_code == 1
    assert "拉取失败 4 只 · 成功 1 只" in result.output
    first = result.output.index("000001: 第一个错误")
    second = result.output.index("000002: 第二个错误")
    fourth = result.output.index("000004: 第四个错误")
    assert first < second < fourth
    assert "000005" not in result.output
    terminal = reporter.events[-1]
    assert terminal.kind is LifecycleKind.OPERATION
    assert terminal.state is OperationState.FAILED


def test_fetch_writes_final_output_after_lifecycle_closes(monkeypatch):
    reporter = CollectingReporter()
    written: list[str] = []
    monkeypatch.setattr("kan.infra.progress.operation_reporter", lambda **_kwargs: reporter)
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda _symbol: False)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, force=False, **kw: ({symbol: _frame() for symbol in symbols}, {}),
    )
    def record_echo(message: str, **_kwargs: object) -> None:
        assert reporter.events[-1].state is OperationState.SUCCEEDED
        written.append(message)

    monkeypatch.setattr("kan.cli.fetch_cmds.typer.echo", record_echo)

    result = CliRunner().invoke(app, ["fetch", "600519"])

    assert result.exit_code == 0, result.output
    assert len(written) == 1
    assert written[0].startswith("🔄 更新 1 只 · 耗时 ")


def test_fetch_verbose_keeps_input_order_for_mixed_results(monkeypatch):
    monkeypatch.setattr(
        "kan.data.fetcher.is_fresh",
        lambda symbol: symbol == "000002",
    )
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, force=False, **kw: (
            {"000003": _frame(3)},
            {"000001": "第一只失败"},
        ),
    )

    result = CliRunner().invoke(
        app,
        ["fetch", "000001", "000002", "000003", "--verbose"],
    )

    assert result.exit_code == 1
    failed = result.output.index("000001 拉取失败")
    fresh = result.output.index("000002 已是最新")
    updated = result.output.index("000003 拉取成功")
    assert failed < fresh < updated
    assert result.output.count("000001") == 1

"""find CLI 边界 helper 的直接回归测试。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import typer

from kan.cli import find_io, find_runner
from kan.service.find_service import (
    FindCodePoolResult,
    FindKlineResult,
    FindServiceError,
)
from kan.storage import export


class _Conditions:
    match_any = False


class _Console:
    width = 120

    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, value: object = "") -> None:
        self.messages.append(str(value))


def _runner_kwargs(**overrides):
    values = {
        "code_pairs": None,
        "source_mode": False,
        "industry": None,
        "hot": None,
        "theme": None,
        "only_watchlist": False,
        "only_holdings": False,
        "group": None,
        "conditions": _Conditions(),
        "field_dimensions": set(),
        "field_paths": (),
        "fmt": export.OutputFormat.json,
        "compact": False,
        "compact_context": True,
        "is_export": True,
        "limit": None,
        "offset": 0,
        "sort": None,
        "rs_index_code": "000300.SH",
        "console": _Console(),
        "find_disclaimer": "免责声明",
    }
    values.update(overrides)
    return values


def test_find_output_profile_maps_cli_format() -> None:
    profile = find_runner._find_output_profile(
        fmt=export.OutputFormat.json,
        compact=True,
        compact_context=False,
        field_paths=("code",),
        field_dimensions={"valuation"},
    )

    assert profile.mode == "json"
    assert profile.compact is True
    assert profile.compact_context is False
    assert profile.field_paths == ("code",)
    assert profile.field_dimensions == frozenset({"valuation"})


def test_find_codes_invalid_json_envelope(capsys) -> None:
    with pytest.raises(typer.Exit) as exc:
        find_io._resolve_code_pairs_or_exit_json(
            "bad1 bad2 bad3 bad4 bad5 bad6",
            export.OutputFormat.json,
        )

    assert exc.value.exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_codes"
    assert payload["error"]["hint"].startswith("例: kan find --codes")


def test_find_codes_empty_terminal_error(monkeypatch) -> None:
    printed: list[str] = []
    monkeypatch.setattr(find_io, "_print_err", printed.append)

    with pytest.raises(typer.Exit) as exc:
        find_io._resolve_code_pairs_or_exit_json("   ", export.OutputFormat.terminal)

    assert exc.value.exit_code == 2
    assert printed
    assert "--codes 为空" in printed[0]
    assert "kan find --codes 600519,000858" in printed[0]


def test_find_codes_cache_failure_falls_back_to_code(monkeypatch) -> None:
    def fail_cache(*, allow_stale: bool = False):
        raise RuntimeError("cache broken")

    monkeypatch.setattr("kan.storage.watchlist.load_stock_names_cache", fail_cache)

    assert find_io._resolve_code_pairs_or_exit_json(
        "600519",
        export.OutputFormat.json,
    ) == [("600519", "600519")]


def test_find_service_error_uses_find_error_exit(capsys) -> None:
    err = FindServiceError(
        code="data_unavailable",
        message="数据不可用",
        hint="稍后重试",
        exit_code=3,
    )

    with pytest.raises(typer.Exit) as exc:
        find_io._exit_find_service_error(export.OutputFormat.json, err)

    assert exc.value.exit_code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "data_unavailable"
    assert payload["error"]["hint"] == "稍后重试"


def test_render_terminal_handles_empty_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.core.pipeline.render_freshness_warning",
        lambda freshness, console: console.print(f"freshness={freshness}"),
    )
    console = _Console()

    find_runner._render_terminal(
        console=console,
        stock_set=SimpleNamespace(name="自选池"),
        ctx=SimpleNamespace(results=[1], freshness="fresh"),
        matches=[],
        matches_limited=[],
        effective_limit=50,
        find_disclaimer="免责声明",
    )

    assert any("无股票符合" in message for message in console.messages)
    assert console.messages[-1] == "免责声明"


def test_render_terminal_lists_triggered_filters(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.core.pipeline.render_freshness_warning",
        lambda freshness, console: console.print(f"freshness={freshness}"),
    )
    monkeypatch.setattr("kan.render.base.responsive_periods", lambda width: [20])
    monkeypatch.setattr("kan.render.terminal.scan_table", lambda *args, **kwargs: "TABLE")
    console = _Console()
    result = SimpleNamespace(symbol="600519", name="贵州茅台")
    trigger = SimpleNamespace(filter_type="ma_bias", param="20:gt:-100", value=-3.4)
    matches = [SimpleNamespace(result=result, triggered=[])]
    matches.extend(SimpleNamespace(result=result, triggered=[trigger]) for _ in range(22))

    find_runner._render_terminal(
        console=console,
        stock_set=SimpleNamespace(name="自选池"),
        ctx=SimpleNamespace(results=list(range(30)), freshness="fresh"),
        matches=matches,
        matches_limited=matches,
        effective_limit=20,
        find_disclaimer="免责声明",
    )

    joined = "\n".join(console.messages)
    assert "TABLE" in joined
    assert "600519 贵州茅台" in joined
    assert "还有" in joined


def test_run_all_stocks_json_output(monkeypatch, capsys) -> None:
    captured_request = None

    def fake_run(request):
        nonlocal captured_request
        captured_request = request
        row = SimpleNamespace(code="600519")
        ctx = SimpleNamespace(pool_size=1, data_cutoff="2026-06-09", stale=False, rows=[row])
        return SimpleNamespace(
            limited=[(row, ())],
            matched=[(row, ())],
            ctx=ctx,
            query_time="now",
            filters=[],
            included_dimensions={"valuation"},
            compact_dimensions={"valuation"},
        )

    monkeypatch.setattr(find_runner, "run_find_cross_section", fake_run)
    monkeypatch.setattr(find_runner.export, "cross_section_payload", lambda *a, **kw: {"ok": True, **kw})
    monkeypatch.setattr(
        find_runner.export,
        "to_json",
        lambda payload: json.dumps(payload, default=str),
    )

    find_runner._run_all_stocks_path(
        source_mode=False,
        conditions=_Conditions(),
        field_dimensions={"valuation"},
        field_paths=("code",),
        fmt=export.OutputFormat.json,
        compact=True,
        compact_context=False,
        is_export=True,
        limit=5,
        offset=1,
        sort=("pe", "asc"),
        rs_index_code="000300.SH",
    )

    assert captured_request.limit == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["match_mode"] == "all"
    assert payload["compact"] is True


def test_run_all_stocks_markdown_and_service_error(monkeypatch, capsys) -> None:
    row = SimpleNamespace(code="600519")
    result = SimpleNamespace(
        limited=[(row, ())],
        matched=[(row, ())],
        ctx=SimpleNamespace(pool_size=1),
        query_time="now",
        filters=[],
        included_dimensions=set(),
        compact_dimensions=set(),
    )
    monkeypatch.setattr(find_runner, "run_find_cross_section", lambda request: result)
    monkeypatch.setattr(find_runner.export, "cross_section_markdown", lambda rows, **kw: f"MD:{kw['title']}")

    find_runner._run_all_stocks_path(
        source_mode=False,
        conditions=_Conditions(),
        field_dimensions=set(),
        field_paths=(),
        fmt=export.OutputFormat.md,
        compact=False,
        compact_context=True,
        is_export=True,
        limit=None,
        offset=0,
        sort=None,
        rs_index_code="000300.SH",
    )
    assert "A股全市场截面" in capsys.readouterr().out

    monkeypatch.setattr(
        find_runner,
        "run_find_cross_section",
        lambda request: (_ for _ in ()).throw(FindServiceError(code="x", message="坏")),
    )
    with pytest.raises(typer.Exit):
        find_runner._run_all_stocks_path(
            source_mode=False,
            conditions=_Conditions(),
            field_dimensions=set(),
            field_paths=(),
            fmt=export.OutputFormat.terminal,
            compact=False,
            compact_context=True,
            is_export=False,
            limit=None,
            offset=0,
            sort=None,
            rs_index_code="000300.SH",
        )


def test_run_kline_code_pool_outputs(monkeypatch, capsys) -> None:
    result = FindCodePoolResult(
        stock_set=SimpleNamespace(name="代码池"),
        code_pairs=[("600519", "贵州茅台")],
        pools=["codes:1"],
        query_time="now",
    )
    monkeypatch.setattr(find_runner, "run_find_kline", lambda request: result)
    monkeypatch.setattr(find_runner.export, "code_pool_payload", lambda *a, **kw: {"pool": kw["pools"]})
    monkeypatch.setattr(find_runner.export, "to_json", json.dumps)

    find_runner._run_kline_path(**_runner_kwargs(fmt=export.OutputFormat.json))
    assert json.loads(capsys.readouterr().out)["pool"] == ["codes:1"]

    monkeypatch.setattr(find_runner.export, "code_pool_markdown", lambda pairs, **kw: f"MD:{kw['title']}")
    find_runner._run_kline_path(**_runner_kwargs(fmt=export.OutputFormat.md))
    assert "代码池" in capsys.readouterr().out


def test_run_kline_code_pool_invalid_fields(monkeypatch) -> None:
    result = FindCodePoolResult(
        stock_set=SimpleNamespace(name="代码池"),
        code_pairs=[("600519", "贵州茅台")],
        pools=["codes:1"],
        query_time="now",
    )
    monkeypatch.setattr(find_runner, "run_find_kline", lambda request: result)
    monkeypatch.setattr(
        find_runner.export,
        "code_pool_payload",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad fields")),
    )

    with pytest.raises(typer.Exit) as exc:
        find_runner._run_kline_path(**_runner_kwargs(fmt=export.OutputFormat.json))

    assert exc.value.exit_code == 2


def test_run_kline_export_and_terminal_paths(monkeypatch, capsys) -> None:
    result_row = SimpleNamespace(symbol="600519", name="贵州茅台")
    match = SimpleNamespace(result=result_row, triggered=[])
    result = FindKlineResult(
        stock_set=SimpleNamespace(name="自选池"),
        ctx=SimpleNamespace(results=[result_row], freshness="fresh"),
        pool_results=[],
        matches=[match],
        matches_limited=[match],
        effective_limit=50,
        pools=["watchlist"],
        filters=[],
        query_time="now",
        included_dimensions=set(),
        compact_dimensions=set(),
    )
    monkeypatch.setattr(find_runner, "run_find_kline", lambda request: result)
    monkeypatch.setattr(find_runner.export, "find_payload", lambda *a, **kw: {"matched": kw["matched_total"]})
    monkeypatch.setattr(find_runner.export, "find_markdown", lambda entries, **kw: f"MD:{kw['matched_total']}")
    monkeypatch.setattr(find_runner.export, "to_json", json.dumps)

    find_runner._run_kline_path(**_runner_kwargs(fmt=export.OutputFormat.json, is_export=True))
    assert json.loads(capsys.readouterr().out)["matched"] == 1

    find_runner._run_kline_path(**_runner_kwargs(fmt=export.OutputFormat.md, is_export=True))
    assert "MD:1" in capsys.readouterr().out

    calls: list[dict] = []
    monkeypatch.setattr(find_runner, "_render_terminal", lambda **kw: calls.append(kw))
    find_runner._run_kline_path(
        **_runner_kwargs(fmt=export.OutputFormat.terminal, is_export=False)
    )
    assert calls[0]["stock_set"].name == "自选池"


def test_run_kline_service_error(monkeypatch) -> None:
    monkeypatch.setattr(
        find_runner,
        "run_find_kline",
        lambda request: (_ for _ in ()).throw(FindServiceError(code="x", message="坏")),
    )

    with pytest.raises(typer.Exit):
        find_runner._run_kline_path(**_runner_kwargs(fmt=export.OutputFormat.terminal))

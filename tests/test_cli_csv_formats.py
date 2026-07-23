"""CLI 层 --format csv 与错误 envelope 集成测试。

覆盖合并引入的各命令 csv 输出分支与 json 错误 envelope:
- kan index / board rank / compare / daily / low / trend / hold / info / theme trend --format csv
- compare / info 的错误 envelope (json) 与终端错误分支
- scan --sort pos 排序方向 · 空结果错误出口 · --group 不存在 envelope
- find terminal 180 日位置分布摘要

全部离线:service / data 层 monkeypatch 掉。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from io import StringIO
from types import SimpleNamespace

import pandas as pd
import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import PeriodResult, StockScanResult
from kan.core.pipeline import Freshness
from kan.core.scanner import TrendResult

BOM = "\ufeff"


def _output_json(result) -> dict:
    """从 CliRunner 混合输出解析首个 JSON 文档。

    CliRunner 默认 mix_stderr=True · 产品侧 JSON 走 stdout、降级警告走
    stderr(正确),但测试捕获混在一起;offline 环境下交易日历降级等
    stderr 警告会尾随 JSON,json.loads 整串会 Extra data。
    """
    payload, _ = json.JSONDecoder().raw_decode(result.output.lstrip())
    return payload


def _period(period: int, pct: float, *, insufficient: bool = False) -> PeriodResult:
    return PeriodResult(
        period=period, n_low=90.0, n_high=110.0, position_pct=pct,
        at_low=pct <= 5, at_high=pct >= 95, insufficient=insufficient,
    )


def _scan_result(
    symbol: str = "600519", name: str = "贵州茅台", pct_180: float = 38.7,
) -> StockScanResult:
    return StockScanResult(
        symbol=symbol, name=name, current_price=100.0,
        scan_date=date(2026, 5, 14),
        periods=[
            _period(30, 50.0),
            _period(60, 60.0),
            _period(180, pct_180),
        ],
        low_resonance=1 if pct_180 <= 10 else 0,
        high_resonance=1 if pct_180 >= 90 else 0,
    )


def _freshness(*, stale: bool = False) -> Freshness:
    return Freshness(
        data_cutoff=date(2026, 6, 18), fetched_at="2026-06-18 23:41",
        expected_cutoff=date(2026, 6, 18), is_stale=stale, phase="post",
    )


# ── kan index --format csv (ai_cmds) ──────────────────────────────────


def _stub_index_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.data import index as index_data

    start = date(2026, 1, 1)
    df = pd.DataFrame({
        "date": [start + timedelta(days=i) for i in range(90)],
        "open": [100 + i for i in range(90)],
        "high": [101 + i for i in range(90)],
        "low": [99 + i for i in range(90)],
        "close": [100 + i for i in range(90)],
        "volume": [1000 + i for i in range(90)],
    })
    monkeypatch.setattr(index_data, "fetch_index_daily", lambda *_args, **_kw: df)


def test_index_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_index_daily(monkeypatch)

    result = CliRunner().invoke(app, ["index", "sh", "--period", "60", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    lines = out.lstrip(BOM).splitlines()
    assert lines[0] == "指数,代码,收盘,位置%,涨幅%,数据日"
    assert "000001.SH" in lines[1]
    assert "上证指数" in lines[1]


# ── kan board rank --format csv (board_cmds) ──────────────────────────


def _stub_board_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.data.board_leaderboard import BoardRankRow

    rows = [
        BoardRankRow(
            kind="industry", code="801120", name="食品饮料", close=1234.5,
            position_pct=18.2, gain_pct=4.5, moneyflow_net=120000.0,
            data_date=date(2026, 5, 29),
        ),
        BoardRankRow(
            kind="industry", code="801080", name="电子", close=None,
            position_pct=None, gain_pct=None, moneyflow_net=None,
            data_date=date(2026, 5, 29),
        ),
    ]
    monkeypatch.setattr(
        "kan.data.board_leaderboard.load_board_leaderboard",
        lambda **_kw: (rows, []),
    )


def test_board_rank_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_board_rows(monkeypatch)

    result = CliRunner().invoke(app, ["board", "rank", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    lines = out.lstrip(BOM).splitlines()
    assert lines[0] == "排名,板块,代码,现价,位置%,涨幅%,主力净额(万)"
    assert lines[1] == "1,食品饮料,801120,1234.50,18.2,4.50,120000"
    # None 字段 → "-"
    assert lines[2] == "2,电子,801080,-,-,-,-"


# ── kan compare --format csv + resolve 错误 (compare_cmds) ─────────────


def _stub_compare_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    names = {
        "600519": ("600519", "贵州茅台"),
        "000858": ("000858", "五粮液"),
    }
    monkeypatch.setattr(
        "kan.storage.watchlist.resolve_symbol_or_name", lambda raw: names[raw],
    )
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda _sym: True)
    monkeypatch.setattr(
        "kan.data.fetcher.get_cached",
        lambda _sym: pd.DataFrame({"close": [100.0], "date": [date(2026, 5, 14)]}),
    )
    monkeypatch.setattr(
        "kan.core.scanner.scan_stock",
        lambda _df, symbol, name, periods=None: StockScanResult(
            symbol=symbol, name=name, current_price=100.0,
            scan_date=date(2026, 5,14),
            periods=[_period(p, 50.0) for p in (periods or [5, 30, 180])],
            low_resonance=0, high_resonance=0,
        ),
    )


def test_compare_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_compare_chain(monkeypatch)

    result = CliRunner().invoke(app, ["compare", "600519", "000858", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    lines = out.lstrip(BOM).splitlines()
    assert lines[0] == "指标,600519,000858"
    assert lines[1] == "股票,贵州茅台,五粮液"
    assert "现价,100.00,100.00" in lines
    assert "180日位置%,50.0,50.0" in lines


def _raise_for_badname(raw: str):
    if raw == "badname":
        raise ValueError(f"无法识别 {raw}")
    return ("600519", "贵州茅台")


def test_compare_resolve_error_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kan.storage.watchlist.resolve_symbol_or_name", _raise_for_badname)

    result = CliRunner().invoke(app, ["compare", "600519", "badname", "--format", "json"])

    assert result.exit_code == 1
    payload = _output_json(result)
    assert payload["ok"] is False
    assert payload["command"] == "compare"
    assert payload["error"]["code"] == "not_found"
    assert "无法识别 badname" in payload["error"]["message"]


def test_compare_resolve_error_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kan.storage.watchlist.resolve_symbol_or_name", _raise_for_badname)

    result = CliRunner().invoke(app, ["compare", "600519", "badname"])

    assert result.exit_code == 1
    assert "无法识别 badname" in result.output


# ── kan daily --format md / csv / terminal 对比变化 (daily_cmds) ────────


def _stub_daily(
    monkeypatch: pytest.MonkeyPatch,
    *,
    previous_pct: float | None = 50.0,
) -> None:
    rows = [
        _scan_result("600519", "低位股", pct_180=5.0),
        _scan_result("688981", "高位股", pct_180=95.0),
    ]
    fake_result = SimpleNamespace(
        results=rows,
        all_results=rows,
        ctx=SimpleNamespace(freshness=_freshness()),
    )
    monkeypatch.setattr(
        "kan.service.scan_service.run_scan",
        lambda _request, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist",
        lambda: SimpleNamespace(stocks=[object(), object()]),
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: SimpleNamespace(positions=[object()], cash=10000),
    )
    previous = None
    if previous_pct is not None:
        previous = (date(2026, 6, 17), {"600519": {"180": {"pct": previous_pct}}})
    monkeypatch.setattr(
        "kan.core.scanner_snapshot.load_previous_web_daily_snapshot",
        lambda _before: previous,
    )


def test_daily_markdown_with_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_daily(monkeypatch)

    result = CliRunner().invoke(app, ["daily", "--format", "md"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "# 慢慢看 · 一日事实概览" in out
    assert "池内 180 日中位位置" in out
    assert "与 2026-06-17 相比: " in out
    assert "条位置变化" in out
    assert "## 可复制命令" in out


def test_daily_csv_with_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_daily(monkeypatch)

    result = CliRunner().invoke(app, ["daily", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    body = out.lstrip(BOM)
    assert "指标,值" in body
    assert "数据截止,2026-06-18" in body
    assert "自选股数,2" in body
    assert "持仓股数,1" in body
    assert "现金配置,是" in body
    assert "180日中位位置%," in body
    assert "180日<=10%股数,1" in body
    assert "180日>=90%股数,1" in body
    assert "位置变化数," in body
    assert "对比日期,2026-06-17" in body


def test_daily_terminal_with_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_daily(monkeypatch)

    result = CliRunner().invoke(app, ["daily"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "180日中位位置" in out
    # terminal 标题用紧凑日期 format_date_compact → 06-17
    assert "与 06-17 相比" in out
    assert "条变化" in out
    # 变化明细行: 名称 + 代码 + 描述
    assert "低位股 600519" in out


def test_daily_terminal_no_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    # 上一份快照 180 日位置与当前同档(都 <=10) → 无跨档变化
    _stub_daily(monkeypatch, previous_pct=6.0)

    result = CliRunner().invoke(app, ["daily"])

    assert result.exit_code == 0, result.output
    assert "与 06-17 相比 · 无关键位置变化" in result.output


# ── kan low --format csv (extreme_cmds) ────────────────────────────────


@pytest.fixture
def extreme_runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """隔离 low/high 全链路 · 走 mock 数据(参照 tests/test_scan_cli.py scan_runner)。"""
    fake_period_180 = _period(180, 8.0)
    fake_scan_result = StockScanResult(
        symbol="600519", name="测试", current_price=100.0,
        scan_date=date(2026, 5, 14),
        periods=[fake_period_180],
        low_resonance=1, high_resonance=0,
    )
    fake_pairs = [("600519", "测试")]
    fake_stock = type("S", (), {"symbol": "600519", "name": "测试"})()
    fake_watchlist = type("WL", (), {"stocks": [fake_stock]})()
    fake_positions = type("Book", (), {"positions": []})()
    monkeypatch.setattr(
        "kan.cli.extreme_cmds._get_watchlist_pairs", lambda group=None: fake_pairs,
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist", lambda group=None: fake_watchlist,
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions", lambda: fake_positions,
    )
    monkeypatch.setattr(
        "kan.cli.extreme_cmds._auto_fetch_stale", lambda _pairs, **_kw: None,
    )
    monkeypatch.setattr(
        "kan.core.scanner.scan_batch",
        lambda _pairs, mode="low", periods=None: [fake_scan_result],
    )
    monkeypatch.setattr(
        "kan.core.scanner.filter_extreme",
        lambda _results, periods, mode="low": (
            {p: [(fake_scan_result, fake_period_180)] for p in periods}
            if mode == "low" else {}
        ),
    )
    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 14),
    )
    monkeypatch.setattr(
        "kan.data.fetcher.cache_age", lambda _sym: "2026-05-14 12:00",
    )
    monkeypatch.setattr(
        "kan.core.scanner.get_limit_threshold", lambda *a, **k: 10.0,
    )
    return CliRunner()


def test_low_csv(extreme_runner: CliRunner) -> None:
    result = extreme_runner.invoke(app, ["low", "180", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    lines = out.lstrip(BOM).splitlines()
    assert lines[0] == "周期,股票,代码,现价,区间最低,区间最高,位置%"
    assert lines[1] == "180日低点,测试,600519,100.00,90.00,110.00,8.0"


# ── kan trend --format csv (trend_cmds) ────────────────────────────────


@pytest.fixture
def trend_runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """隔离 trend 全链路(参照 tests/test_trend_cli.py runner fixture)。"""
    fake_watchlist = type("WL", (), {
        "stocks": [type("S", (), {"symbol": "600519", "name": "测试跌5"})()],
    })()
    fake_positions = type("Book", (), {"positions": []})()
    monkeypatch.setattr(
        "kan.cli.trend_cmds._get_watchlist_pairs",
        lambda group=None: [("600519", "测试跌5")],
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist", lambda group=None: fake_watchlist,
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions", lambda: fake_positions,
    )
    monkeypatch.setattr("kan.core.auto_fetch.auto_fetch_stale", lambda _pairs, **_kw: None)
    monkeypatch.setattr(
        "kan.core.scanner.trend_batch",
        lambda *_args, **_kwargs: [
            TrendResult("600519", "测试跌5", 100.0, -5, -8.0, [
                ("2026-05-08", -2.0), ("2026-05-09", -1.5),
            ]),
        ],
    )
    monkeypatch.setattr("kan.data.fetcher.cache_age", lambda _sym: "2026-05-08 12:00")
    monkeypatch.setattr("kan.core.scanner.get_limit_threshold", lambda *a, **k: 10.0)
    return CliRunner()


def test_trend_csv(trend_runner: CliRunner) -> None:
    result = trend_runner.invoke(app, ["trend", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    lines = out.lstrip(BOM).splitlines()
    assert lines[0].startswith("股票,代码,现价,连续,累计%")
    assert "测试跌5,600519,100.00,跌5天,8.00" in lines[1]


# ── kan hold --format csv (hold_cmds) ──────────────────────────────────


def _fake_hold_summary():
    from kan.core.positions import (
        AccountView,
        PositionHealth,
        PositionsSummary,
        PositionView,
    )

    row = PositionView(
        symbol="600519", name="贵州茅台", cost=1680.5, shares=100,
        price=1700.0, prev_close=1690.0, market_value=170000.0,
        cost_value=168050.0, weight_pct=70.0, daily_pnl=1000.0,
        daily_pnl_pct=0.59, total_pnl=1950.0, total_pnl_pct=1.16,
        positions={30: 20.0, 60: 50.0, 180: 80.0},
        price_source="realtime", price_status="ok",
    )
    return PositionsSummary(
        results=[row],
        account=AccountView(
            cash=73000.0, total_market_value=170000.0, total_assets=243000.0,
            total_position_pct=69.96, daily_pnl=1000.0, total_pnl=1950.0,
        ),
        health=PositionHealth(
            high_count=1, low_count=0, middle_count=0,
            profit_count=1, loss_count=0, flat_count=0,
        ),
        price_mode="realtime",
        data_cutoff=date(2026, 6, 5),
        notes=["盈亏按裸价差计算，未计佣金/印花税。"],
    )


def test_hold_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.cli import hold_cmds

    monkeypatch.setattr(
        hold_cmds, "_build_summary", lambda *, no_refresh: _fake_hold_summary(),
    )

    result = CliRunner().invoke(app, ["hold", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    lines = out.lstrip(BOM).splitlines()
    assert lines[0].startswith("代码,名称,现价,成本,股数,")
    assert lines[1].startswith('600519,"贵州茅台",1700.00,1680.5000,100,')


def test_hold_csv_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.cli import hold_cmds

    monkeypatch.setattr(
        hold_cmds, "_build_summary", lambda *, no_refresh: _fake_hold_summary(),
    )

    result = CliRunner().invoke(app, ["hold", "--format", "csv", "--mask"])

    assert result.exit_code == 0, result.output
    row = result.output.lstrip(BOM).splitlines()[1]
    assert "1680.5000" not in row
    assert row.startswith('600519,"贵州茅台",1700.00,,,')


# ── kan info --format csv + 错误 envelope (info_cmds) ───────────────────


def _fake_info_result():
    from kan.core.models import VolumeState
    from kan.service.info_service import InfoServiceResult

    return InfoServiceResult(
        symbol="600519", name="贵州茅台",
        result=_scan_result(),
        trend=TrendResult("600519", "贵州茅台", 100.0, 3, 4.5, []),
        volume=VolumeState(ratio=1.42, label="温和放大", window=5),
        data_cutoff=date(2026, 5, 14), fetched_at=None, stale=False,
    )


def test_info_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kan.service.info_service.get_stock_info", lambda _request: _fake_info_result(),
    )

    result = CliRunner().invoke(app, ["info", "600519", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    body = out.lstrip(BOM)
    assert "股票,贵州茅台" in body
    assert "代码,600519" in body
    assert "成交量状态,温和放大" in body
    assert "周期,最低,最高,位置%,距低,距低%,距高,距高%" in body
    assert "180日,90.00,110.00,38.7" in body


def test_info_not_found_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_request):
        raise ValueError("无法识别 xxx")

    monkeypatch.setattr("kan.service.info_service.get_stock_info", _raise)

    result = CliRunner().invoke(app, ["info", "xxx", "--format", "json"])

    assert result.exit_code == 1
    payload = _output_json(result)
    assert payload["ok"] is False
    assert payload["command"] == "info"
    assert payload["error"]["code"] == "not_found"


def test_info_not_found_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_request):
        raise ValueError("无法识别 xxx")

    monkeypatch.setattr("kan.service.info_service.get_stock_info", _raise)

    result = CliRunner().invoke(app, ["info", "xxx"])

    assert result.exit_code == 1
    assert "无法识别 xxx" in result.output


def test_info_fetch_error_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.service.info_service import InfoFetchError

    def _raise(_request):
        raise InfoFetchError("600519", "贵州茅台", RuntimeError("down"))

    monkeypatch.setattr("kan.service.info_service.get_stock_info", _raise)

    result = CliRunner().invoke(app, ["info", "600519", "--format", "json"])

    assert result.exit_code == 1
    payload = _output_json(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "fetch_error"


def test_info_data_unavailable_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.service.info_service import InfoDataUnavailableError

    def _raise(_request):
        raise InfoDataUnavailableError("600519")

    monkeypatch.setattr("kan.service.info_service.get_stock_info", _raise)

    result = CliRunner().invoke(app, ["info", "600519", "--format", "json"])

    assert result.exit_code == 1
    payload = _output_json(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "data_unavailable"


# ── kan theme trend --format csv (theme_cmds) ───────────────────────────


@pytest.fixture
def theme_csv_runner(monkeypatch: pytest.MonkeyPatch, tmp_path) -> CliRunner:
    """隔离 boards 缓存 + stub 题材榜数据(参照 tests/test_theme_trend_cli.py)。"""
    from kan.data import boards
    from kan.data.theme_leaderboard import LeaderboardDiagnosis

    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr(boards, "ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.storage.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.ensure_dirs", lambda: None)

    results = [
        TrendResult("886108", "AI应用", 1245.3, 7, 12.5, [
            ("2026-05-20", 1.2), ("2026-05-21", 2.0), ("2026-05-22", 3.4),
        ]),
        TrendResult("885525", "白酒", 805.2, -6, -8.4, [
            ("2026-05-20", -1.2), ("2026-05-21", -1.5), ("2026-05-22", -1.8),
        ]),
    ]
    diagnosis = LeaderboardDiagnosis(
        em_attempted=True, em_total=len(results), em_failed_count=0,
    )
    monkeypatch.setattr(
        "kan.data.theme_leaderboard.load_theme_leaderboard",
        lambda **kw: (results, [], "em", diagnosis),
    )
    return CliRunner()


def test_theme_trend_csv(theme_csv_runner: CliRunner) -> None:
    result = theme_csv_runner.invoke(app, ["theme", "trend", "--format", "csv"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith(BOM)
    lines = out.lstrip(BOM).splitlines()
    assert lines[0] == "排名,题材,代码,现价,连续,累计%"
    # 默认按 |streak| 排序 · AI应用(7) 在前
    assert lines[1] == "1,AI应用,886108,1245.30,涨7天,12.50"
    assert lines[2] == "2,白酒,885525,805.20,跌6天,8.40"


# ── scan --sort pos 排序方向 (scan_cmds._sort_scan_results) ─────────────


def test_sort_scan_results_pos180_direction() -> None:
    from kan.cli.scan_cmds import _sort_scan_results

    low = SimpleNamespace(periods=[_period(180, 10.0)], current_price=1.0)
    mid = SimpleNamespace(periods=[_period(180, 50.0)], current_price=2.0)
    high = SimpleNamespace(periods=[_period(180, 90.0)], current_price=3.0)
    results = [mid, high, low]

    # 低点模式升序(最低在前) · 高点模式降序(最高在前)
    assert [r.periods[0].position_pct for r in _sort_scan_results(results, "pos180", "low")] == [10.0, 50.0, 90.0]
    assert [r.periods[0].position_pct for r in _sort_scan_results(results, "pos180", "high")] == [90.0, 50.0, 10.0]


# ── scan 空结果错误出口 (scan_cmds._prepare_scan_render) ────────────────


def _prepare_render_kwargs(**overrides):
    kwargs = {
        "lifecycle": SimpleNamespace(phase=lambda *a, **k: None),
        "console": None,
        "fmt": __import__("kan.storage.export", fromlist=["OutputFormat"]).OutputFormat.json,
        "mode": "low",
        "high": False,
        "signal": False,
        "diff": False,
        "all_stocks": False,
        "only_holdings": False,
        "only_watchlist": False,
        "source_mode": False,
        "code_pairs": None,
        "period_list": [30, 60, 180],
        "display_periods": [30, 60, 180],
        "show_context_columns": False,
        "include_external_context": False,
    }
    kwargs.update(overrides)
    return kwargs


def test_prepare_scan_render_data_unavailable_with_targets(capsys) -> None:
    from kan.cli.scan_cmds import _prepare_scan_render

    service_result = SimpleNamespace(
        ctx=SimpleNamespace(targets=[("600519", "测试")], results=[]),
        meta=None, all_results=[], results=[],
    )
    with pytest.raises(typer.Exit) as exc_info:
        _prepare_scan_render(service_result, **_prepare_render_kwargs())

    assert exc_info.value.exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "data_unavailable"
    assert payload["error"]["message"] == "无缓存数据"


def test_prepare_scan_render_empty_pool_without_targets(capsys) -> None:
    from kan.cli.scan_cmds import _prepare_scan_render

    service_result = SimpleNamespace(
        ctx=SimpleNamespace(targets=[], results=[]),
        meta=None, all_results=[], results=[],
    )
    with pytest.raises(typer.Exit) as exc_info:
        _prepare_scan_render(service_result, **_prepare_render_kwargs())

    assert exc_info.value.exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "empty_pool"
    assert payload["error"]["message"] == "候选池为空"


def test_scan_group_not_found_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.storage.watchlist_models import GroupNotFoundError

    def _raise(group=None):
        raise GroupNotFoundError(f"组不存在: {group}")

    monkeypatch.setattr("kan.storage.watchlist.load_watchlist", _raise)

    result = CliRunner().invoke(app, ["scan", "--group", "不存在的组", "--format", "json"])

    assert result.exit_code == 2
    payload = _output_json(result)
    assert payload["ok"] is False
    assert payload["command"] == "scan"
    assert payload["error"]["code"] == "group_not_found"
    assert "不存在的组" in payload["error"]["message"]


# ── find terminal 180 日位置分布摘要 (find_runner._render_terminal) ──────


def test_find_terminal_position_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    from kan.cli.find_runner import _render_terminal
    from kan.core.find_filter import TriggeredFilter

    monkeypatch.setattr(
        "kan.render.terminal.scan_table", lambda *a, **k: "SCAN_TABLE",
    )
    scans = [
        _scan_result("600519", "低位股", pct_180=10.0),
        _scan_result("000858", "中位股", pct_180=50.0),
        _scan_result("601318", "高位股", pct_180=90.0),
    ]
    trig = TriggeredFilter(filter_type="pos", param="180:lt:95", value=10.0)
    matches = [SimpleNamespace(result=s, triggered=(trig,)) for s in scans]
    # 无 180 周期的命中 → 分布统计跳过
    no_180 = _scan_result("000001", "缺周期")
    no_180.periods = [p for p in no_180.periods if p.period != 180]
    matches.append(SimpleNamespace(result=no_180, triggered=()))

    output = StringIO()
    console = Console(file=output, width=120)
    ctx = SimpleNamespace(freshness=_freshness(), results=[m.result for m in matches])

    _render_terminal(
        console=console,
        stock_set=SimpleNamespace(name="默认池"),
        ctx=ctx,
        matches=matches,
        matches_limited=matches,
        effective_limit=50,
        find_disclaimer="慢慢看是观察工具",
    )

    out = output.getvalue()
    assert "180日位置分布" in out
    assert "低位≤20%: 1" in out
    assert "中位: 1" in out
    assert "高位≥80%: 1" in out
    # 触发的 filter 明细仍渲染
    assert "pos=180:lt:95@10.0" in out


def test_daily_terminal_more_than_six_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """变化超过 6 条 → 折叠为 '… 及其他 N 条'。"""
    rows = [
        _scan_result(f"60051{i}", f"低位股{i}", pct_180=5.0) for i in range(8)
    ]
    fake_result = SimpleNamespace(
        results=rows,
        all_results=rows,
        ctx=SimpleNamespace(freshness=_freshness()),
    )
    monkeypatch.setattr(
        "kan.service.scan_service.run_scan",
        lambda _request, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist",
        lambda: SimpleNamespace(stocks=[object()]),
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: SimpleNamespace(positions=[], cash=0),
    )
    previous = (
        date(2026, 6, 17),
        {f"60051{i}": {"180": {"pct": 50.0}} for i in range(8)},
    )
    monkeypatch.setattr(
        "kan.core.scanner_snapshot.load_previous_web_daily_snapshot",
        lambda _before: previous,
    )

    result = CliRunner().invoke(app, ["daily"])

    assert result.exit_code == 0, result.output
    assert "8 条变化" in result.output
    assert "及其他 2 条" in result.output

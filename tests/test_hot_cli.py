"""scan/low/high/trend/fetch --hot 集成测试 · mock hot 层 · 不走真网络。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.core.models import PeriodResult, StockScanResult
from kan.data import hot
from kan.data.hot import HotEntry, HotListUnavailableError


def _fake_scan_result(symbol: str, name: str) -> StockScanResult:
    return StockScanResult(
        symbol=symbol, name=name, current_price=100.0,
        scan_date=date(2026, 5, 21),
        periods=[PeriodResult(
            period=3, n_low=90.0, n_high=110.0, position_pct=50.0,
            at_low=False, at_high=False,
        )],
        low_resonance=0, high_resonance=0,
    )


@pytest.fixture
def hot_runner(monkeypatch):
    """mock hot 层 + watchlist + fetch + scan_batch。"""
    entries = [
        HotEntry(rank=1, symbol="000725", name="京东方Ａ"),
        HotEntry(rank=2, symbol="600519", name="贵州茅台"),
    ]
    monkeypatch.setattr(hot, "fetch_hot_list", lambda which, force=False: entries)
    monkeypatch.setattr(
        "kan.cli.scan_cmds._get_watchlist_pairs", lambda group=None: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.core.auto_fetch.auto_fetch_stale", lambda _p, **_kw: None)
    monkeypatch.setattr(
        "kan.cli.scan_cmds._load_watchlist_pairs", lambda group=None: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr(
        "kan.cli.trend_cmds._get_watchlist_pairs", lambda group=None: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.core.auto_fetch.auto_fetch_stale", lambda _p, **_kw: None)
    monkeypatch.setattr(
        "kan.cli.trend_cmds._load_watchlist_pairs", lambda group=None: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr(
        "kan.cli.extreme_cmds._get_watchlist_pairs", lambda group=None: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.cli.extreme_cmds._auto_fetch_stale", lambda _p, **_kw: None)
    monkeypatch.setattr(
        "kan.cli.extreme_cmds._load_watchlist_pairs", lambda group=None: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr(
        "kan.core.scanner.scan_batch",
        lambda pairs, mode="low", periods=None: [_fake_scan_result(s, n) for s, n in pairs],
    )
    monkeypatch.setattr(
        "kan.core.enrich.enrich_scan_rows",
        lambda rows, **_kw: rows,
    )
    monkeypatch.setattr("kan.data.fetcher.cache_age", lambda _s: "2026-05-21 12:00")
    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date", lambda _s: date(2026, 5, 21)
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 21)
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "pre")
    return CliRunner()


def test_scan_hot_rank_runs(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(app, ["scan", "--hot", "rank"])
    assert result.exit_code == 0, result.output
    assert "京东方" in result.output         # 热榜成员
    assert "东财人气榜" in result.output      # 标题
    assert "⭐" in result.output             # 茅台在自选 · 高亮
    assert "非慢慢看观点" in result.output    # 热榜 caption · 证明走了 hot 渲染路径(榜列)


def test_scan_hot_conflicts_with_industry(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(
        app, ["scan", "--hot", "rank", "--industry=半导体"]
    )
    assert result.exit_code == 2
    assert "不能同时" in result.output or "互斥" in result.output


def test_scan_hot_data_unavailable(hot_runner, monkeypatch):
    from kan.app import app

    def _raise(which, force=False):
        raise HotListUnavailableError("network down")

    monkeypatch.setattr(hot, "fetch_hot_list", _raise)
    result = hot_runner.invoke(app, ["scan", "--hot", "rank"])
    assert result.exit_code == 1
    assert "东财热榜源暂时不可用" in result.output
    assert "替代:" in result.output  # P0-10 fallback 引导


def test_scan_hot_only_watchlist_intersects(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(
        app, ["scan", "--hot", "rank", "--only-watchlist"]
    )
    assert result.exit_code == 0, result.output
    assert "贵州茅台" in result.output       # 茅台在自选 ∩ 热榜
    assert "京东方" not in result.output     # 京东方不在自选


def test_only_watchlist_without_source_is_allowed(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(app, ["scan", "--only-watchlist"])
    assert "需配合" not in result.output


def test_low_hot_runs(hot_runner, monkeypatch):
    from kan.app import app
    monkeypatch.setattr(
        "kan.core.scanner.filter_extreme",
        lambda pairs, periods, mode="low": {},
    )
    result = hot_runner.invoke(app, ["low", "30", "--hot", "surge"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "东财飙升榜" in result.output


def test_high_hot_runs(hot_runner, monkeypatch):
    from kan.app import app
    monkeypatch.setattr(
        "kan.core.scanner.filter_extreme",
        lambda pairs, periods, mode="low": {},
    )
    result = hot_runner.invoke(app, ["high", "30", "--hot", "rank"])
    assert result.exit_code == 0
    assert "Traceback" not in result.output


def test_trend_hot_runs(hot_runner, monkeypatch):
    from kan.app import app

    class _Tr:
        def __init__(self, sym, name):
            self.symbol, self.name = sym, name
            self.current_price, self.streak, self.streak_pct = 100.0, 0, 0.0
            self.daily_changes = []
            self.direction = "平"

    monkeypatch.setattr(
        "kan.core.scanner.trend_batch",
        lambda pairs, candle=False: [_Tr(s, n) for s, n in pairs],
    )
    result = hot_runner.invoke(app, ["trend", "--hot", "rank"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "东财人气榜" in result.output
    assert "⭐" in result.output


def test_fetch_hot_runs(hot_runner, monkeypatch):
    from kan.app import app
    fetched: list[list[str]] = []
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, force=False, **kw: (
            fetched.append(list(symbols))
            or {symbol: pd.DataFrame() for symbol in symbols},
            {},
        ),
    )
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda sym: False)
    result = hot_runner.invoke(app, ["fetch", "--hot", "rank"])
    assert result.exit_code == 0, result.output
    assert fetched == [["000725", "600519"]]


def test_trend_hot_latest_uneven_daily_changes(hot_runner, monkeypatch):
    """trend --hot --latest · 各股 daily_changes 长度不一时,榜列 + 日期列不错位。"""
    from kan.app import app

    class _Tr:
        def __init__(self, sym, name, days):
            self.symbol, self.name = sym, name
            self.current_price, self.streak, self.streak_pct = 100.0, 0, 0.0
            self.daily_changes = days
            self.direction = "平"

    # 第 1 只 3 天、第 2 只 1 天 —— 行宽不齐,验证 base_cols=5(含榜列)补齐逻辑
    rows = {
        "000725": [("2026-05-21", 1.5), ("2026-05-20", -2.0), ("2026-05-19", 0.3)],
        "600519": [("2026-05-21", 0.8)],
    }
    monkeypatch.setattr(
        "kan.core.scanner.trend_batch",
        lambda pairs, candle=False: [_Tr(s, n, rows[s]) for s, n in pairs],
    )
    result = hot_runner.invoke(app, ["trend", "--hot", "rank", "--latest", "3"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "东财人气榜" in result.output

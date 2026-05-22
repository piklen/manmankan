"""scan/low/high/trend/fetch --hot 集成测试 · mock hot 层 · 不走真网络。"""
from __future__ import annotations

from datetime import date

import pytest
from typer.testing import CliRunner

from kan import hot
from kan.hot import HotEntry, HotListUnavailableError
from kan.models import PeriodResult, StockScanResult


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
        "kan.cli_scan_cmds._get_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.cli_scan_cmds._auto_fetch_stale", lambda _p: None)
    monkeypatch.setattr(
        "kan.cli_scan_cmds._load_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr(
        "kan.cli_trend_cmds._get_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.cli_trend_cmds._auto_fetch_stale", lambda _p: None)
    monkeypatch.setattr(
        "kan.cli_trend_cmds._load_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr(
        "kan.scanner.scan_batch",
        lambda pairs, mode="low": [_fake_scan_result(s, n) for s, n in pairs],
    )
    monkeypatch.setattr("kan.fetcher.cache_age", lambda _s: "2026-05-21 12:00")
    monkeypatch.setattr(
        "kan.fetcher.data_cutoff_date", lambda _s: date(2026, 5, 21)
    )
    monkeypatch.setattr(
        "kan.trading_calendar.latest_trade_date", lambda: date(2026, 5, 21)
    )
    monkeypatch.setattr("kan.trading_calendar.market_phase", lambda: "pre")
    return CliRunner()


def test_scan_hot_rank_runs(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(app, ["scan", "--hot", "rank"])
    assert result.exit_code == 0, result.output
    assert "京东方" in result.output         # 热榜成员
    assert "东财人气榜" in result.output      # 标题
    assert "⭐" in result.output             # 茅台在自选 · 高亮


def test_scan_hot_conflicts_with_industry(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(
        app, ["scan", "--hot", "rank", "--industry=半导体"]
    )
    assert result.exit_code == 2
    assert "不能同时使用" in result.output


def test_scan_hot_data_unavailable(hot_runner, monkeypatch):
    from kan.app import app

    def _raise(which, force=False):
        raise HotListUnavailableError("network down")

    monkeypatch.setattr(hot, "fetch_hot_list", _raise)
    result = hot_runner.invoke(app, ["scan", "--hot", "rank"])
    assert result.exit_code == 1
    assert "热榜数据源暂时不可用" in result.output


def test_scan_hot_only_watchlist_intersects(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(
        app, ["scan", "--hot", "rank", "--only-watchlist"]
    )
    assert result.exit_code == 0, result.output
    assert "贵州茅台" in result.output       # 茅台在自选 ∩ 热榜
    assert "京东方" not in result.output     # 京东方不在自选


def test_only_watchlist_needs_source(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(app, ["scan", "--only-watchlist"])
    assert result.exit_code == 1
    assert "--only-watchlist" in result.output

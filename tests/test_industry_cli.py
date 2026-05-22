"""7 命令 --industry 集成测试 · mock boards 层 · 不走真网络。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan import boards
from kan.models import Board, PeriodResult, StockScanResult


def _fake_kline():
    return pd.DataFrame({
        "date": [date(2026, 5, 20), date(2026, 5, 21)],
        "open": [1290.0, 1305.0], "high": [1325.0, 1330.0],
        "low": [1288.0, 1300.0], "close": [1300.0, 1320.0],
        "volume": [1e8, 1.1e8], "amount": [2e11, 2.1e11],
    })


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
def industry_runner(monkeypatch):
    """mock boards 层 + watchlist + fetch + scan_batch。"""
    board = Board(code="801016", name="食品饮料", level=2, size=2)
    cons = [("600519", "贵州茅台"), ("000998", "隆平高科")]

    monkeypatch.setattr(boards, "search_industry", lambda q: board)
    monkeypatch.setattr(
        boards, "get_industry_constituents", lambda b, force=False: cons
    )
    monkeypatch.setattr(
        boards, "fetch_industry_kline", lambda b, force=False: _fake_kline()
    )
    monkeypatch.setattr(
        "kan.cli_scan_cmds._get_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.cli_scan_cmds._auto_fetch_stale", lambda _p: None)
    monkeypatch.setattr(
        "kan.cli_trend_cmds._get_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.cli_trend_cmds._auto_fetch_stale", lambda _p: None)
    monkeypatch.setattr(
        "kan.scanner.scan_batch",
        lambda pairs, mode="low": [_fake_scan_result(s, n) for s, n in pairs],
    )
    monkeypatch.setattr(
        "kan.scanner.scan_stock",
        lambda df, sym, name, periods=None: _fake_scan_result(sym, name),
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


def test_scan_industry_three_layers(industry_runner):
    from kan.app import app
    result = industry_runner.invoke(app, ["scan", "--industry=食品饮料"])
    assert result.exit_code == 0, result.output
    assert "🏛️" in result.output            # 板块指数行
    assert "贵州茅台" in result.output         # 成分股
    assert "⭐" in result.output             # 自选高亮(茅台在自选)


def test_scan_industry_not_found(industry_runner, monkeypatch):
    from kan.app import app

    def _raise(q):
        raise boards.BoardNotFoundError(q)

    monkeypatch.setattr(boards, "search_industry", _raise)
    result = industry_runner.invoke(app, ["scan", "--industry=不存在"])
    assert result.exit_code == 1
    assert "未找到行业" in result.output


def test_scan_industry_data_unavailable(industry_runner, monkeypatch):
    from kan.app import app

    def _raise(q):
        raise boards.BoardDataUnavailableError("network down")

    monkeypatch.setattr(boards, "search_industry", _raise)
    result = industry_runner.invoke(app, ["scan", "--industry=食品饮料"])
    assert result.exit_code == 1
    assert "数据源暂时不可用" in result.output


def test_only_watchlist_needs_industry(industry_runner):
    from kan.app import app
    result = industry_runner.invoke(app, ["scan", "--only-watchlist"])
    assert result.exit_code == 1
    assert "--only-watchlist" in result.output


def test_low_industry_runs(industry_runner, monkeypatch):
    from kan.app import app
    monkeypatch.setattr(
        "kan.scanner.filter_extreme",
        lambda pairs, periods, mode="low": {},
    )
    result = industry_runner.invoke(app, ["low", "30", "--industry=食品饮料"])
    assert result.exit_code == 0
    assert "Traceback" not in result.output


def test_high_industry_runs(industry_runner, monkeypatch):
    from kan.app import app
    monkeypatch.setattr(
        "kan.scanner.filter_extreme",
        lambda pairs, periods, mode="low": {},
    )
    result = industry_runner.invoke(app, ["high", "30", "--industry=食品饮料"])
    assert result.exit_code == 0


def test_trend_industry_runs(industry_runner, monkeypatch):
    from kan.app import app

    class _Tr:
        def __init__(self, sym, name):
            self.symbol, self.name = sym, name
            self.current_price, self.streak, self.streak_pct = 100.0, 0, 0.0
            self.daily_changes = []
            self.direction = "平"

    monkeypatch.setattr(
        "kan.scanner.trend_batch",
        lambda pairs, candle=False: [_Tr(s, n) for s, n in pairs],
    )
    result = industry_runner.invoke(app, ["trend", "--industry=食品饮料"])
    assert result.exit_code == 0
    assert "Traceback" not in result.output
    assert "⭐" in result.output  # 茅台在自选


def test_info_industry_shows_board_card(industry_runner):
    from kan.app import app
    result = industry_runner.invoke(app, ["info", "--industry=食品饮料"])
    assert result.exit_code == 0, result.output
    assert "食品饮料" in result.output
    assert "成分股" in result.output       # 成分股数那一行
    assert "Traceback" not in result.output


def test_info_industry_conflicts_with_symbol(industry_runner):
    from kan.app import app
    result = industry_runner.invoke(
        app, ["info", "600519", "--industry=食品饮料"]
    )
    assert result.exit_code != 0

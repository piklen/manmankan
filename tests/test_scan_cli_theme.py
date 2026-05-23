"""kan scan --theme CLI 真测 · CliRunner runtime · 不 bootstrap 字符串作弊。"""
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _mock_adata(monkeypatch):
    mock_adata = MagicMock()
    monkeypatch.setitem(sys.modules, "adata", mock_adata)
    monkeypatch.setitem(sys.modules, "adata.stock", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock.info", MagicMock())
    return mock_adata


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.paths.WATCHLIST_PATH", tmp_path / "wl.json")
    monkeypatch.setattr("kan.paths.DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


def _stub_theme_calls(monkeypatch):
    """scan --theme=AI应用 → 返回 2 行成分股 + 完整 K 线。"""
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    kline_df = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * 100,
            "high": [105.0] * 100,
            "low": [95.0] * 100,
            "close": [102.0] * 100,
            "volume": [1e6] * 100,
            "amount": [1e8] * 100,
        }
    )
    monkeypatch.setattr("kan.boards.fetch_theme_kline", lambda theme, force=False: kline_df)


def _stub_fetch_kline(monkeypatch):
    """单股 K 线 stub 供 scan 位置计算。"""
    dates = pd.date_range("2026-01-01", periods=250, freq="B").date
    kline_df = pd.DataFrame(
        {
            "date": dates,
            "open": list(range(100, 100 + 250)),
            "high": list(range(101, 101 + 250)),
            "low": list(range(99, 99 + 250)),
            "close": list(range(100, 100 + 250)),
            "volume": [1e6] * 250,
            "amount": [1e8] * 250,
        }
    )
    # fetcher 接口名不确定 · 用宽 mock
    monkeypatch.setattr("kan.fetcher.fetch_kline", lambda symbol, **kw: kline_df)
    # 也 patch is_fresh / cache_age 等 helper · 防 scan 走真路径
    monkeypatch.setattr("kan.fetcher.is_fresh", lambda symbol: True)
    monkeypatch.setattr("kan.fetcher.cache_age", lambda symbol: None)
    monkeypatch.setattr("kan.fetcher.data_cutoff_date", lambda symbol: None)
    # scan_batch · 让它走真路径但底层 fetch 被 mock
    # 直接 mock scan_batch 返回 stubs · 更稳
    from datetime import date

    from kan.models import PeriodResult, StockScanResult
    def fake_scan_batch(targets, mode):
        return [
            StockScanResult(
                symbol=code,
                name=name,
                current_price=100.0,
                scan_date=date(2026, 5, 23),
                periods=[
                    PeriodResult(period=p, n_low=90, n_high=110, position_pct=0.5,
                                 at_low=False, at_high=False)
                    for p in [10, 20, 30, 60, 90, 120, 250]
                ],
                low_resonance=0,
                high_resonance=0,
            )
            for code, name in targets
        ]
    monkeypatch.setattr("kan.scanner.scan_batch", fake_scan_batch)
    monkeypatch.setattr("kan.cli_scan_cmds._auto_fetch_stale", lambda targets: None)


def test_scan_theme_runs(monkeypatch, _isolate_all):
    """kan scan --theme=AI应用 不报错 + 输出含题材名 + 成分股代码。"""
    _stub_theme_calls(monkeypatch)
    _stub_fetch_kline(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output
    assert "002230" in result.output or "科大讯飞" in result.output


def test_scan_theme_industry_mutually_exclusive(_isolate_all):
    """--theme + --industry 同时 → exit 2 + 错误提示。"""
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2
    assert "互斥" in result.output or "不能同时" in result.output


def test_scan_theme_not_found(monkeypatch, _isolate_all):
    """题材名找不到 → exit 2 + 友好提示。"""
    from kan.boards import ThemeNotFoundError

    def raise_(q):
        raise ThemeNotFoundError(q)

    monkeypatch.setattr("kan.boards.search_theme", raise_)
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=不存在题材xyz"])
    assert result.exit_code == 2
    assert "未找到" in result.output or "kan theme search" in result.output


def test_scan_theme_disclaimer_shown(monkeypatch, _isolate_all):
    """题材扫描输出必须含 4 行 disclaimer(spec §12.1 LOCKED)。"""
    _stub_theme_calls(monkeypatch)
    _stub_fetch_kline(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "位置 ≠ 买卖信号" in result.output
    assert "题材分类各家口径不同" in result.output
    assert "题材跟风风险高于行业" in result.output
    assert "不预测涨跌" in result.output or "不荐股" in result.output

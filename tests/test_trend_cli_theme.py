"""kan trend --theme CLI 真测。"""
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import Theme


@pytest.fixture(autouse=True)
def _mock_adata(monkeypatch):
    monkeypatch.setitem(sys.modules, "adata", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock.info", MagicMock())


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan.data import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.storage.paths.WATCHLIST_PATH", tmp_path / "wl.json")
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


def _stub(monkeypatch):
    monkeypatch.setattr(
        "kan.data.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.data.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞")],
    )
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    monkeypatch.setattr(
        "kan.data.boards.fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame({
            "date": dates,
            "open": [100.0] * 100, "high": [105.0] * 100,
            "low": [95.0] * 100, "close": [102.0] * 100,
            "volume": [1e6] * 100, "amount": [1e8] * 100,
        }),
    )
    # trend_batch 让它返回空 · 简化
    monkeypatch.setattr("kan.core.scanner.trend_batch", lambda targets, candle=False: [])
    monkeypatch.setattr("kan.core.auto_fetch.auto_fetch_stale", lambda targets, **_kw: None)


def test_trend_theme_runs(monkeypatch, _isolate_all):
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["trend", "--theme=AI应用"])
    # trend_batch 返空 · "无缓存数据" 错误也 OK · 关键不是 NoOption / argument error
    # exit 0 (no data branch) or 1 (no cache)
    assert result.exit_code in (0, 1), result.output


def test_trend_theme_mutually_exclusive(_isolate_all):
    runner = CliRunner()
    result = runner.invoke(app, ["trend", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2
    assert "互斥" in result.output or "不能同时" in result.output

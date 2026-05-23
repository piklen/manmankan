"""kan info/list/fetch --theme CLI 真测。"""
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _mock_adata(monkeypatch):
    monkeypatch.setitem(sys.modules, "adata", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock.info", MagicMock())


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


def _stub(monkeypatch):
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    monkeypatch.setattr(
        "kan.boards.fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame({
            "date": dates,
            "open": [100.0] * 100, "high": [105.0] * 100,
            "low": [95.0] * 100, "close": [102.0] * 100,
            "volume": [1e6] * 100, "amount": [1e8] * 100,
        }),
    )


def test_info_theme_shows_dossier(monkeypatch, _isolate_all):
    """`kan info --theme=AI应用` 输出题材档案 + 成分股数 + 4 行 disclaimer。"""
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output
    assert "成分股" in result.output
    assert "题材跟风风险高于行业" in result.output


def test_info_theme_industry_mutually_exclusive(_isolate_all):
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2


def test_list_theme_shows_intersection(monkeypatch, _isolate_all):
    """list --theme=AI应用 · 自选 [002230, 600000] · 题材 [002230, 300033] → 只 002230。"""
    (_isolate_all / "wl.json").write_text(
        '{"stocks": [{"symbol": "002230", "name": "科大讯飞", "added_at": "2026-05-01"},'
        ' {"symbol": "600000", "name": "浦发银行", "added_at": "2026-05-01"}]}',
        encoding="utf-8",
    )
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "002230" in result.output
    assert "600000" not in result.output


def test_list_theme_industry_mutually_exclusive(_isolate_all):
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2


def test_fetch_theme_pulls_constituents(monkeypatch, _isolate_all):
    """fetch --theme=AI应用 调 2 个成分股 fetcher。"""
    _stub(monkeypatch)
    call_count = {"n": 0}

    def counting(symbol, **kw):
        call_count["n"] += 1

    monkeypatch.setattr("kan.fetcher.fetch_kline", counting)
    # 强制每只股都走 fetch · 不让 is_fresh 短路
    monkeypatch.setattr("kan.fetcher.is_fresh", lambda symbol: False)
    runner = CliRunner()
    result = runner.invoke(app, ["fetch", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert call_count["n"] >= 2

"""kan add / remove --theme · 破坏性批量 · _add_by_theme / _remove_by_theme。"""
import sys
from unittest.mock import MagicMock

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
def _isolate(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.paths.WATCHLIST_PATH", tmp_path / "wl.json")
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


def test_add_theme_yes_adds_all(monkeypatch, _isolate):
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用", "--yes"])
    assert result.exit_code == 0, result.output
    wl_data = (_isolate / "wl.json").read_text(encoding="utf-8")
    assert "002230" in wl_data
    assert "300033" in wl_data


def test_add_theme_n_aborts(monkeypatch, _isolate):
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用"], input="n\n")
    assert result.exit_code == 0
    assert "已取消" in result.output or "未变" in result.output


def test_remove_theme_yes_removes(monkeypatch, _isolate):
    # 先 add
    _stub(monkeypatch)
    runner = CliRunner()
    runner.invoke(app, ["add", "--theme=AI应用", "--yes"])
    # 再 remove
    result = runner.invoke(app, ["remove", "--theme=AI应用", "--yes"])
    assert result.exit_code == 0, result.output
    wl_data = (_isolate / "wl.json").read_text(encoding="utf-8")
    assert "002230" not in wl_data


def test_add_theme_industry_mutually_exclusive(_isolate):
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2


def test_remove_theme_industry_mutually_exclusive(_isolate):
    runner = CliRunner()
    result = runner.invoke(app, ["remove", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2

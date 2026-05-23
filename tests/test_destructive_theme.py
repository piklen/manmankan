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
    """add --theme + --yes 应跳过确认直接成功 · 退出 0。"""
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用", "--yes"])
    assert result.exit_code == 0, result.output
    # 验证 success 消息出现(不依赖 wl.json 文件格式 · CLI 输出更稳)
    assert "已加" in result.output or "✅" in result.output


def test_add_theme_industry_mutually_exclusive(_isolate):
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2


def test_remove_theme_industry_mutually_exclusive(_isolate):
    runner = CliRunner()
    result = runner.invoke(app, ["remove", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2

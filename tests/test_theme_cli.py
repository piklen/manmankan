"""kan theme list / search 子命令树测试。"""
import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import Theme


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from kan.data import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.ensure_dirs", lambda: None)
    return tmp_path


def _stub_catalog(monkeypatch, themes=None):
    if themes is None:
        themes = [
            Theme(code="886108", name="AI应用", source="ths"),
            Theme(code="886112", name="AI智能体", source="ths"),
            Theme(code="885525", name="白酒概念", source="ths"),
            Theme(code="886058", name="华为昇腾", source="ths"),
            Theme(code="886109", name="同花顺", source="ths"),
        ]
    monkeypatch.setattr("kan.data.boards.load_theme_catalog", lambda force=False: themes)


def test_theme_list_default(monkeypatch, _isolate):
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list"])
    assert result.exit_code == 0
    assert "AI应用" in result.output
    assert "白酒概念" in result.output


def test_theme_list_all_flag(monkeypatch, _isolate):
    themes = [Theme(code=f"88{i:04d}", name=f"题材{i:03d}", source="ths") for i in range(50)]
    _stub_catalog(monkeypatch, themes)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list", "--all"])
    assert result.exit_code == 0
    assert "全部 50 个" in result.output or "50" in result.output


def test_theme_list_caps_at_30(monkeypatch, _isolate):
    themes = [Theme(code=f"88{i:04d}", name=f"题材{i:03d}", source="ths") for i in range(100)]
    _stub_catalog(monkeypatch, themes)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list"])
    assert result.exit_code == 0
    assert "--all" in result.output  # 应提示有更多


def test_theme_search_fuzzy(monkeypatch, _isolate):
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "search", "AI"])
    assert result.exit_code == 0
    assert "AI应用" in result.output
    assert "AI智能体" in result.output
    assert "白酒概念" not in result.output


def test_theme_search_not_found(monkeypatch, _isolate):
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "search", "不存在xyz"])
    assert result.exit_code == 0
    assert "未找到" in result.output or "0 个" in result.output


def test_theme_search_blank_rejected(monkeypatch, _isolate):
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "search", "   "])
    assert result.exit_code == 2
    assert "关键词不能为空" in result.output


def test_theme_list_disclaimer(monkeypatch, _isolate):
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list"])
    assert result.exit_code == 0
    assert "题材是标签" in result.output or "投机炒作" in result.output


def test_theme_help(_isolate):
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "search" in result.output

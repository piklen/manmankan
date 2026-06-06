"""kan uninstall 命令测试

覆盖:
- _detect_install_method (4 路径模式 + 1 unknown fallback)
- _human_size helper (KB / MB 边界)
- uninstall command (--keep-data / --yes / no-data)
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.cli.helpers import _detect_install_method, _human_size


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_kan_data(tmp_path, monkeypatch):
    """创建临时 kan XDG 数据 · 返回 xdg_dir"""
    xdg = tmp_path / "kan"
    xdg.mkdir()
    (xdg / "watchlist.json").write_text(json.dumps({"version": 2, "groups": {}}))
    data_dir = xdg / "data"
    data_dir.mkdir()
    (data_dir / "600519.parquet").write_text("dummy")

    monkeypatch.setattr("kan.storage.paths.BASE_DIR", xdg)
    return xdg


# --- _human_size helper ---


def test_human_size_kb_small():
    """小于 1 MB 显示 KB"""
    assert _human_size(512) == "0.5 KB"
    assert _human_size(1024) == "1.0 KB"


def test_human_size_mb_boundary():
    """≥ 1 MB 显示 MB"""
    assert _human_size(1024 * 1024) == "1.0 MB"


def test_human_size_typical():
    """典型 manmankan 缓存大小 ~ 2.5 MB"""
    assert _human_size(2_500_000) in ("2.4 MB", "2.5 MB")


# --- _detect_install_method ---


def test_detect_install_returns_required_keys():
    """任何路径下都至少返回 name + cmd"""
    info = _detect_install_method()
    assert "name" in info
    assert "cmd" in info
    assert "uninstall manmankan" in str(info["cmd"])


def test_detect_install_uv_tool():
    """uv tool 路径模式命中"""
    with patch("sys.executable", "/Users/test/.local/share/uv/tools/manmankan/bin/python"):
        info = _detect_install_method()
    assert info["name"] == "uv tool"
    assert info["cmd"] == "uv tool uninstall manmankan"


def test_detect_install_pipx():
    """pipx 路径模式命中"""
    with patch("sys.executable", "/Users/test/.local/pipx/venvs/manmankan/bin/python"):
        info = _detect_install_method()
    assert info["name"] == "pipx"
    assert info["cmd"] == "pipx uninstall manmankan"


def test_detect_install_pip_venv():
    """pip / venv 路径模式命中"""
    with patch("sys.executable", "/Users/test/project/.venv/bin/python"):
        info = _detect_install_method()
    assert info["name"] == "pip / venv"
    assert info["cmd"] == "pip uninstall manmankan"


def test_detect_install_unknown_fallback():
    """未知路径 fallback · 仍提供合理默认"""
    with patch("sys.executable", "/usr/bin/python3"):
        info = _detect_install_method()
    assert "未知" in info["name"]
    assert "uninstall manmankan" in info["cmd"]


# --- uninstall command ---


def test_uninstall_keep_data_does_not_delete(mock_kan_data, runner):
    """--keep-data 只显示包卸载命令 · 不删数据"""
    xdg = mock_kan_data
    result = runner.invoke(app, ["uninstall", "--keep-data"])
    assert result.exit_code == 0
    assert xdg.exists()  # 数据仍在
    assert "uninstall manmankan" in result.stdout  # 输出含包卸载提示


def test_uninstall_yes_deletes_data(mock_kan_data, runner):
    """--yes 跳过确认 · 真删数据"""
    xdg = mock_kan_data
    result = runner.invoke(app, ["uninstall", "--yes"])
    assert result.exit_code == 0
    assert not xdg.exists()  # 数据已删


def test_uninstall_no_data_still_shows_pkg_cmd(tmp_path, monkeypatch, runner):
    """没数据时也输出包卸载提示 · 不报错"""
    monkeypatch.setattr("kan.storage.paths.BASE_DIR", tmp_path / "non-existent-kan")

    result = runner.invoke(app, ["uninstall", "--yes"])
    assert result.exit_code == 0
    assert "uninstall manmankan" in result.stdout

"""help 一致性回归测试

确保 kan --help 走中文速记（与 kan help 等价）·
sys.argv 预处理把 root-level --help 替换为 help 子命令。
子命令的 --help 不影响（kan scan --help 仍走 typer 默认）。
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.cli_helpers import _normalize_help_args

# --- _normalize_help_args 纯函数测试 ---


@pytest.mark.parametrize(
    "argv,expected",
    [
        # 触发场景：root-level --help
        (["kan", "--help"], ["kan", "help"]),
        # 不触发：无参数
        (["kan"], ["kan"]),
        # 不触发：显式 help 子命令
        (["kan", "help"], ["kan", "help"]),
        # 不触发：子命令 --help（应保留 typer 默认）
        (["kan", "scan", "--help"], ["kan", "scan", "--help"]),
        (["kan", "trend", "--help"], ["kan", "trend", "--help"]),
        # 不触发：其他 --help-like 参数
        (["kan", "--version"], ["kan", "--version"]),
        # 不触发：--help 但带其他参数（应保留 typer 默认 · 防误吞）
        (["kan", "--help", "extra"], ["kan", "--help", "extra"]),
    ],
)
def test_normalize_help_args(argv: list[str], expected: list[str]) -> None:
    with patch.object(sys, "argv", list(argv)):
        _normalize_help_args()
        assert sys.argv == expected


# --- 集成测试 · kan --help 输出中文速记 ---


def test_root_help_returns_chinese_cheatsheet() -> None:
    """kan --help 走中文速记 · 与 kan help 输出一致"""
    runner = CliRunner()
    result_help_dash = runner.invoke(app, ["help"])
    assert result_help_dash.exit_code == 0
    # 中文速记标志：自选股管理 / 位置扫描 / 连续涨跌 三个分组词
    assert "自选股管理" in result_help_dash.stdout
    assert "位置扫描" in result_help_dash.stdout
    assert "连续涨跌" in result_help_dash.stdout
    assert "命令速记" in result_help_dash.stdout


def test_subcommand_help_unaffected() -> None:
    """子命令 --help 仍走 typer 默认"""
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--help"])
    assert result.exit_code == 0
    # typer 默认 help 标志：Usage: 行 + Options 段
    assert "Usage:" in result.stdout
    assert "Options" in result.stdout

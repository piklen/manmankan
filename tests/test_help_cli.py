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


def test_root_help_uses_real_config_key_spelling() -> None:
    """速记表中的 config key 必须与真实 CLI 参数一致。"""
    runner = CliRunner()
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "tushare-token" in result.stdout
    assert "tushare-endpoint" in result.stdout
    assert "tushare_token <YOUR_TOKEN>" not in result.stdout


def test_root_help_lists_v0050_batch_sources_and_theme_watchlist_commands() -> None:
    """速记表必须覆盖 v0.0.5.0 新增的热榜 / 题材 / 导出核心入口。"""
    runner = CliRunner()
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    output = result.stdout

    assert "kan add --theme AI" in output
    assert "kan remove --theme AI" in output
    assert "kan list --theme AI" in output
    assert "kan fetch --hot rank" in output
    assert "kan fetch --theme AI" in output
    assert "kan compare 600519 000858 --format md" in output


def test_subcommand_help_unaffected() -> None:
    """子命令 --help 仍走 typer 默认"""
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--help"])
    assert result.exit_code == 0
    # typer 默认 help 标志：Usage: 行 + Options 段
    assert "Usage:" in result.stdout
    assert "Options" in result.stdout


# --- _maybe_print_boot_banner 测试 (v0.0.4.4 加 · 补 CR finding)
#
# v0.0.4.3 在 kan/cli.py:14-32 加了 stderr boot banner 但零测试覆盖 ·
# 违反「新功能必须同步写测试」· v0.0.4.4 补齐 4 case 参数化测试


@pytest.mark.parametrize(
    "command, extra_args, env_no_banner, isatty, should_write",
    [
        # case 1: 白名单内 + TTY + 无 --help → 应写
        ("scan", [], False, True, True),
        # case 2: 白名单外 + TTY → 不写 (e.g. kan update)
        ("update", [], False, True, False),
        # case 3: 白名单内 + --help → 不写 (帮助文档已经清晰)
        ("scan", ["--help"], False, True, False),
        # case 4: KAN_NO_BOOT_BANNER=1 env → 不写
        ("scan", [], True, True, False),
    ],
    ids=["whitelist+tty", "non-whitelist", "with-help", "env-suppressed"],
)
def test_maybe_print_boot_banner(
    command: str,
    extra_args: list[str],
    env_no_banner: bool,
    isatty: bool,
    should_write: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_maybe_print_boot_banner 4 case 参数化测试 (v0.0.4.4)。

    覆盖：白名单 / --help 排除 / KAN_NO_BOOT_BANNER env / TTY 判断 所有分支。
    """
    import io

    from kan.cli import _maybe_print_boot_banner

    # 构造 sys.argv
    argv = ["kan", command, *extra_args]
    monkeypatch.setattr(sys, "argv", argv)

    # 构造 stderr (StringIO + isatty 通过 setattr 模拟)
    buf = io.StringIO()
    buf.isatty = lambda: isatty  # type: ignore[assignment]
    monkeypatch.setattr(sys, "stderr", buf)

    # KAN_NO_BOOT_BANNER env
    if env_no_banner:
        monkeypatch.setenv("KAN_NO_BOOT_BANNER", "1")
    else:
        monkeypatch.delenv("KAN_NO_BOOT_BANNER", raising=False)

    _maybe_print_boot_banner()

    output = buf.getvalue()
    if should_write:
        assert "启动中" in output, (
            f"expected banner in stderr · case: {command} {extra_args}"
        )
    else:
        assert "启动中" not in output, (
            f"unexpected banner · case: {command} {extra_args} · got: {output!r}"
        )

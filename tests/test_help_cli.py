"""help 一致性回归测试

确保 kan --help 走中文速记（与 kan help 等价）·
sys.argv 预处理把 root-level --help 替换为 help 子命令。
子命令的 --help 不影响（kan scan --help 仍走 typer 默认）。
"""

from __future__ import annotations

import builtins
import re
import sys
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.cli.helpers import _normalize_help_args

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_PATTERN.sub("", text)


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


def test_console_script_root_help_bypasses_full_cli_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """kan --help 走 entrypoint fast path,避免加载全部命令注册图。"""
    from kan import _entry

    real_import = builtins.__import__

    def guarded_import(name: str, *args, **kwargs):
        if name == "kan.cli" or name.startswith("kan.cli."):
            raise AssertionError("root help fast path imported full CLI")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(sys, "argv", ["kan", "--help"])
    monkeypatch.delenv("_KAN_COMPLETE", raising=False)
    monkeypatch.delenv("_TYPER_COMPLETE_ARGS", raising=False)
    monkeypatch.setattr(_entry, "_maybe_print_boot_banner", lambda: None)
    monkeypatch.setattr(_entry, "_print_fast_help", lambda: print("FAST_HELP"))
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    _entry.main()

    assert capsys.readouterr().out.strip() == "FAST_HELP"


def test_console_script_root_help_skips_completion_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """completion 子调用必须交回 Typer,不能被 fast help 污染输出。"""
    from kan import _entry

    monkeypatch.setenv("_KAN_COMPLETE", "complete_zsh")

    assert not _entry._should_print_fast_help(["kan", "--help"])


def test_root_help_uses_real_config_key_spelling() -> None:
    """速记表中的 config key 必须与真实 CLI 参数一致。"""
    runner = CliRunner()
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "tushare-token" in result.stdout
    assert "tushare-endpoint" in result.stdout
    assert "tushare_token <YOUR_TOKEN>" not in result.stdout


def test_root_help_has_no_release_version_badges() -> None:
    """root 速记页不展示具体发布版本号。"""
    runner = CliRunner()
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0

    assert "慢慢看 · 命令速记" in result.stdout
    assert "v0." not in result.stdout
    assert "当前版本" not in result.stdout


def test_root_help_lists_batch_sources_and_theme_watchlist_commands() -> None:
    """速记表必须覆盖热榜 / 题材 / 导出核心入口。"""
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
    assert "kan find --codes 600519,000858" in output
    assert "kan hold add 600519 --cost 1680 --shares 100" in output
    assert "kan hold --format json --mask" in output
    assert "kan board rank --kind industry --by moneyflow" in output
    assert "kan scan --periods 5,20,60,180" in output
    assert "kan scan --wide" in output
    assert "kan scan --compact" in output


def test_root_help_lists_find_registry_flags_and_presets() -> None:
    """root 速记页的 find 面必须覆盖 registry 里登记的 filter / preset."""
    from kan.core.find_registry import FILTER_SPECS, FIND_FIELD_PRESETS

    runner = CliRunner()
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    output = result.stdout

    for spec in FILTER_SPECS.values():
        assert spec.flag in output
    for preset in FIND_FIELD_PRESETS:
        assert preset in output
    assert "单维度 filter 只反映该维度" in output
    assert "命中不等于整体位置低/高" in output
    assert "核心层 · 位置 / 共振 / ST" in output
    assert "估值 / 质量 / 资金" in output
    assert "进阶 · 需理解指标口径" in output
    assert "新手从 kan scan 和 kan find 开始" in output


def test_subcommand_help_unaffected() -> None:
    """子命令 --help 仍走 typer 默认"""
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--help"])
    assert result.exit_code == 0
    # typer 默认 help 标志：Usage: 行 + Options 段
    assert "Usage:" in result.stdout
    assert "Options" in result.stdout


def test_low_high_help_points_to_find_pos_shortcut() -> None:
    runner = CliRunner()
    for command in ("low", "high"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0
        assert "find --pos" in strip_ansi(result.stdout)


# --- _maybe_print_boot_banner 测试 (背景 · 补 CR finding)
#
# 历史背景在 kan/cli.py:14-32 加了 stderr boot banner 但零测试覆盖 ·
# 违反「新功能必须同步写测试」· 补齐 4 case 参数化测试


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
        # case 5: theme 子命令组 + TTY → 应写 (补 · 防 banner 漏 theme 子命令组的 cold-start 黑屏回归)
        ("theme", [], False, True, True),
        # case 6: board 子命令组 + TTY → 应写
        ("board", [], False, True, True),
    ],
    ids=[
        "whitelist+tty",
        "non-whitelist",
        "with-help",
        "env-suppressed",
        "theme-whitelisted",
        "board-whitelisted",
    ],
)
def test_maybe_print_boot_banner(
    command: str,
    extra_args: list[str],
    env_no_banner: bool,
    isatty: bool,
    should_write: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_maybe_print_boot_banner 4 case 参数化测试 (历史背景)。

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

"""CLI 命令注册 canary · cli.py 拆分后的保险丝。

拆分后命令实现散落在 4 个 cli_*_cmds.py 子模块 · 依赖 kan/cli.py 末尾的
显式 import 触发 @app.command() 装饰器执行。任何子模块漏 import 都会让
对应命令"神秘消失"，而单元测试可能只覆盖自己关注的命令分支，不会发现整组
命令注册丢失。

这个 canary 作为最后一道防线：
  - 命令总数断言（数量 drift）
  - 命令名集合断言（重命名 / 漏注册 / 多注册）

未来加新命令时这个测试必须同步更新 · 视为「设计契约」。
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from kan import __version__
from kan.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]

# 命令分布（加新命令时同步更新此 canary）：
# - cli_watchlist_cmds (6): help / add / remove / list / import / clear
# - cli_scan_cmds (6):      fetch / scan / low / high / info / compare
# - cli_trend_cmds (1):     trend
# - cli_meta_cmds (4):      update / uninstall / completion / setup
# - cli_ai_cmds (3):        examples / schema / index
# - cli_daily_cmds (2):     guide / daily
# - cli_move_export_cmds (2): move / export   (历史背景多分组管理)
# - cli_find_cmds (1):      find             (历史背景选股 DSL)
# - cli_history_cmds (1):   history          (位置历史回溯)
# - cli_range_cmds (1):     range            (日内范围复核)
# - cli_research_cmds (1):  research         (研究证据包)
# - cli_status_cmds (1):    status           (本地数据状态)
# - cli_web_cmds (1):       web              (本地 Web 看盘台)
# 注:`kan group`/`kan config`/`kan theme`/`kan fields`/`kan mcp`/`kan hold` 是 sub-Typer
# (app.add_typer) · 不进 registered_commands · 不需 canary。
_EXPECTED_COMMANDS = {
    "help",
    "add",
    "remove",
    "list",
    "import",
    "clear",
    "fetch",
    "scan",
    "low",
    "high",
    "info",
    "compare",
    "history",
    "range",
    "research",
    "trend",
    "status",
    "update",
    "uninstall",
    "completion",
    "setup",
    "examples",
    "schema",
    "index",
    "guide",
    "daily",
    "move",
    "export",
    "find",
    "web",
}


def _registered_names() -> set[str]:
    """从 typer.Typer.registered_commands 提取命令名集合。

    typer command name 来自 @app.command(name=...) 或函数名 fallback。
    """
    names = set()
    for cmd in app.registered_commands:
        # CommandInfo.name 为 None 时 typer 用函数名
        name = cmd.name or cmd.callback.__name__
        names.add(name)
    return names


def test_command_count_matches_expected() -> None:
    """命令总数必须 = 预期 · 任何子模块漏 import 立刻红。"""
    registered = _registered_names()
    assert len(registered) == len(_EXPECTED_COMMANDS), (
        f"命令数 drift: 注册了 {len(registered)} 个 ({sorted(registered)}), "
        f"预期 {len(_EXPECTED_COMMANDS)} 个 ({sorted(_EXPECTED_COMMANDS)})"
    )


def test_command_names_match_expected() -> None:
    """命令名集合必须等于预期 · 重命名 / 漏注册 / 多注册都炸。"""
    registered = _registered_names()
    missing = _EXPECTED_COMMANDS - registered
    extra = registered - _EXPECTED_COMMANDS
    assert not missing and not extra, (
        f"命令集合不匹配 · 缺失: {sorted(missing)} · 多出: {sorted(extra)}"
    )


def test_release_version_matches_package_metadata_and_changelog_top_entry() -> None:
    """发布版本必须在 runtime / pyproject / CHANGELOG 顶部三处一致。"""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
    match = re.search(r"^## \[(?P<version>\d+(?:\.\d+){2,})\]", changelog, re.M)
    assert match is not None, "CHANGELOG.md must start with a versioned release section"

    assert __version__ == pyproject["project"]["version"] == match.group("version")


def test_console_script_uses_thin_entrypoint() -> None:
    """console script should keep import-time failure guard outside kan.cli."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["scripts"]["kan"] == "kan._entry:main"
    assert pyproject["project"]["scripts"]["kan-mcp"] == "kan.mcp.server:main"

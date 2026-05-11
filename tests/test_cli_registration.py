"""CLI 命令注册 canary · v0.0.3 cli.py 拆分后的保险丝。

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

from kan.cli import app

# v0.0.3 拆分时锁定 · 12 个命令分布：
# - cli_watchlist_cmds (6): help / add / remove / list / import / clear
# - cli_scan_cmds (5):      fetch / scan / low / high / info
# - cli_trend_cmds (1):     trend
# - cli_meta_cmds (3):      update / uninstall / completion
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
    "trend",
    "update",
    "uninstall",
    "completion",
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

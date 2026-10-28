"""kan.cli · CLI 包入口。

- 暴露 cli_main，实际 console-script 从 kan._entry 进入
- 暴露 app (typer.Typer 单例 · 跨子模块共享)
- 模块顶部 import 所有 *_cmds 触发 @app.command() 装饰器装命令到 app
  命令由共享 Typer 实例统一收集
"""

# ruff: noqa: F401 — 这些 import 的副作用就是注册命令 · ruff 不识别
from kan._entry import _fast_subcommand_help_command
from kan.app import app

if _fast_subcommand_help_command() == "find":
    from kan.cli import find_cmds
else:
    from kan.cli import (
        ai_cmds,
        atexit,
        board_cmds,
        compare_cmds,
        config_cmds,
        daily_cmds,
        extreme_cmds,
        fetch_cmds,
        find_cmds,
        group_cmds,
        help,
        helpers,
        history_cmds,
        hold_cmds,
        info_cmds,
        meta_cmds,
        move_export_cmds,
        range_cmds,
        research_cmds,
        scan_cmds,
        screen_cmds,
        status_cmds,
        study_cmds,
        theme_cmds,
        trend_cmds,
        tui_cmds,
        watchlist_cmds,
        web_cmds,
        workspace_cmds,
    )
from kan.cli.main import cli_main

"""kan.cli · CLI 包入口。

- 暴露 cli_main (pyproject `kan = "kan.cli:cli_main"` script 入口)
- 暴露 app (typer.Typer 单例 · 跨子模块共享)
- 暴露 _maybe_print_boot_banner (boot banner · 测试 import)
- 模块顶部 import 所有 *_cmds 触发 @app.command() 装饰器装命令到 app
  (不能省 · pytest collect 阶段就会校验命令是否注册)
"""

# ruff: noqa: F401 — 这些 import 的副作用就是注册命令 · ruff 不识别
from kan.app import app
from kan.cli import (
    atexit,
    compare_cmds,
    config_cmds,
    extreme_cmds,
    fetch_cmds,
    help,
    helpers,
    info_cmds,
    meta_cmds,
    scan_cmds,
    theme_cmds,
    trend_cmds,
    watchlist_cmds,
)
from kan.cli.main import _maybe_print_boot_banner, cli_main

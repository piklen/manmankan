"""终端交互工作台入口；脚本与管道继续使用一次性 CLI。"""

from __future__ import annotations

import sys

import typer

from kan.app import app


@app.command()
def tui() -> None:
    """打开键盘筛选：明确连续涨跌天数，查看当前日线，按需保存与核对历史。"""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        typer.echo(
            "kan tui 需要交互终端。请在终端直接运行；"
            "脚本筛选可用 kan trend --help；历史研究用 kan study --help。",
            err=True,
        )
        raise typer.Exit(2)

    from kan.tui.app import StudyApp

    StudyApp().run()

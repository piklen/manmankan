"""终端交互工作台入口；脚本与管道继续使用一次性 CLI。"""

from __future__ import annotations

import sys

import typer

from kan.app import app


@app.command()
def tui() -> None:
    """打开键盘工作台：我的关注、行情变化、证据与观察笔记。"""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        typer.echo(
            "kan tui 需要交互终端。请在终端直接运行；"
            "脚本可用 kan daily --format json，网页使用 kan web。",
            err=True,
        )
        raise typer.Exit(2)

    from kan.tui.app import FocusApp

    FocusApp().run()

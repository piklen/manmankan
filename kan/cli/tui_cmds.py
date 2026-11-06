"""终端交互工作台入口；脚本与管道继续使用一次性 CLI。"""

from __future__ import annotations

import sys

import typer

from kan.app import app


@app.command()
def tui() -> None:
    """打开市场观察：查看分布与变化，沿行业、成员下钻日线；f 进入高级筛选。"""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        typer.echo(
            "kan tui 需要交互终端。请在终端直接运行；"
            "脚本筛选可用 kan trend --help；历史研究用 kan study --help。",
            err=True,
        )
        raise typer.Exit(2)

    from kan.tui.app import StudyApp

    StudyApp().run()

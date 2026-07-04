"""CLI 反馈层：统一重命令的 status / progress 输出。

所有反馈写 stderr，避免污染 JSON / Markdown stdout。命令层只描述当前阶段，
Rich 组件和样式在这里集中管理，防止各命令各自发明一套动效。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


def feedback_console():
    """返回 CLI 反馈专用 console。"""
    from rich.console import Console

    return Console(stderr=True)


@contextmanager
def cli_status(message: str, *, console=None, spinner: str = "dots") -> Iterator:
    """统一的短阶段 spinner。"""
    if console is None:
        console = feedback_console()
    with console.status(f"[yellow]{message}[/yellow]", spinner=spinner) as status:
        yield status


def determinate_progress(*, console=None, transient: bool = False):
    """统一的批量进度条：spinner + 描述 + 百分比 + 计数 + 耗时。"""
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    if console is None:
        console = feedback_console()
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[dim]({task.completed}/{task.total})[/dim]"),
        TimeElapsedColumn(),
        console=console,
        transient=transient,
    )

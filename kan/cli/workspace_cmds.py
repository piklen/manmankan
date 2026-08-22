"""工作台状态迁移与恢复命令。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from kan.app import app
from kan.storage import export
from kan.storage.workspace_migration import (
    WorkspaceMigrationReport,
    migrate_workspace_state,
    rollback_workspace_state,
    workspace_status,
)


class WorkspaceOutputFormat(StrEnum):
    terminal = "terminal"
    json = "json"


workspace_app = typer.Typer(
    name="workspace",
    help="迁移、检查或回退本机工作台状态",
    no_args_is_help=True,
)
app.add_typer(workspace_app, name="workspace")


def _render(report: WorkspaceMigrationReport, fmt: WorkspaceOutputFormat) -> None:
    payload = {
        "ok": True,
        "schema_version": 1,
        "command": "workspace",
        "backend": report.backend,
        "migrated": list(report.migrated),
        "exported": list(report.exported),
        "backups": list(report.backups),
    }
    if fmt is WorkspaceOutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    typer.echo(f"工作台状态后端: {report.backend}")
    typer.echo(f"SQLite 命名空间: {', '.join(report.migrated) or '无'}")
    if report.exported:
        typer.echo(f"已导出到 JSON: {', '.join(report.exported)}")
    if report.backups:
        typer.echo("原始备份:")
        for path in report.backups:
            typer.echo(f"  · {path}")


@workspace_app.command("status")
def status(
    fmt: Annotated[
        WorkspaceOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = WorkspaceOutputFormat.terminal,
) -> None:
    """查看当前用户状态后端与迁移备份。"""
    _render(workspace_status(), fmt)


@workspace_app.command("migrate")
def migrate(
    fmt: Annotated[
        WorkspaceOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = WorkspaceOutputFormat.terminal,
) -> None:
    """把 config/watchlist/positions 安全迁移到 SQLite。"""
    _render(migrate_workspace_state(), fmt)


@workspace_app.command("rollback")
def rollback(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="确认切回 JSON；先导出 SQLite 当前值"),
    ] = False,
    fmt: Annotated[
        WorkspaceOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = WorkspaceOutputFormat.terminal,
) -> None:
    """导出 SQLite 当前状态并切回旧 JSON backend。"""
    if not yes:
        if fmt is WorkspaceOutputFormat.json:
            typer.echo(
                export.to_json(
                    export.error_payload(
                        "workspace rollback",
                        code="confirmation_required",
                        message="切回 JSON backend 需要 --yes",
                    )
                )
            )
        else:
            typer.echo("❌ 切回 JSON backend 需要 --yes", err=True)
        raise typer.Exit(2)
    _render(rollback_workspace_state(), fmt)

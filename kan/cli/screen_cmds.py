"""``kan screen``：稳定 ScreenSpec 与不可变 ScreenRun 的 CLI 入口。"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import BaseModel, ValidationError

from kan.app import app
from kan.domain.screen import SavedScreen, ScreenRun, ScreenSpec, ScreenVersion
from kan.service import screen_service
from kan.storage import export, workspace_db


class ScreenOutputFormat(StrEnum):
    terminal = "terminal"
    json = "json"


screen_app = typer.Typer(
    name="screen",
    help="保存、运行和审计 vNext 选股规则",
    no_args_is_help=True,
)
app.add_typer(screen_app, name="screen")


def _load_spec(source: str) -> ScreenSpec:
    raw = (
        sys.stdin.read()
        if source == "-"
        else Path(source).read_text(encoding="utf-8")
    )
    return ScreenSpec.model_validate_json(raw)


def _json_payload(command: str, key: str, value: object) -> dict[str, object]:
    serialized: object
    if isinstance(value, BaseModel):
        serialized = value.model_dump(mode="json")
    elif isinstance(value, list):
        serialized = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in value
        ]
    else:
        serialized = value
    return {
        "ok": True,
        "schema_version": 1,
        "command": command,
        key: serialized,
    }


def _fail(
    fmt: ScreenOutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> NoReturn:
    if fmt is ScreenOutputFormat.json:
        typer.echo(
            export.to_json(
                export.error_payload(
                    "screen",
                    code=code,
                    message=message,
                    hint=hint,
                )
            )
        )
    else:
        typer.echo(f"❌ {message}", err=True)
        if hint:
            typer.echo(f"   {hint}", err=True)
    raise typer.Exit(exit_code)


def _render_saved(screen: SavedScreen, fmt: ScreenOutputFormat) -> None:
    if fmt is ScreenOutputFormat.json:
        typer.echo(export.to_json(_json_payload("screen show", "screen", screen)))
        return
    typer.echo(
        f"{screen.name} · {screen.screen_id} · v{screen.current_version}\n"
        f"规则哈希: {screen.spec_hash}\n"
        f"条件: {len(screen.spec.conditions)} · 上限: {screen.spec.limit}"
    )


def _render_run(run: ScreenRun, fmt: ScreenOutputFormat) -> None:
    if fmt is ScreenOutputFormat.json:
        typer.echo(export.to_json(_json_payload("screen run", "run", run)))
        return
    from rich.console import Console
    from rich.table import Table

    table = Table(title=f"{run.spec.name} · {len(run.rows)} 只")
    table.add_column("排名", justify="right")
    table.add_column("代码")
    table.add_column("名称")
    table.add_column("价格", justify="right")
    table.add_column("命中证据", justify="right")
    for row in run.rows:
        table.add_row(
            str(row.rank),
            row.symbol,
            row.name,
            "-" if row.price is None else f"{row.price:g}",
            str(len(row.evidence)),
        )
    console = Console()
    console.print(table)
    console.print(
        f"[dim]run {run.run_id} · snapshot {run.snapshot_id[:12]} · "
        f"覆盖 {run.coverage.evaluated}/{run.coverage.universe_size} · "
        f"耗时 {run.duration_ms}ms[/dim]"
    )


def _render_versions(items: list[ScreenVersion], fmt: ScreenOutputFormat) -> None:
    if fmt is ScreenOutputFormat.json:
        typer.echo(export.to_json(_json_payload("screen versions", "versions", items)))
        return
    if not items:
        typer.echo("没有可用版本")
        return
    for item in items:
        typer.echo(
            f"v{item.version:<3}  {item.spec_hash[:12]}  "
            f"{item.created_at.isoformat()}  {len(item.spec.conditions)} 条件"
        )


@screen_app.command("filters")
def list_filters(
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """列出 ScreenSpec 可用的筛选条件目录。"""
    from kan.service.screen_catalog import screen_filter_groups

    groups = screen_filter_groups()
    if fmt is ScreenOutputFormat.json:
        typer.echo(export.to_json(_json_payload("screen filters", "groups", groups)))
        return
    for group in groups:
        typer.echo(str(group["label"]))
        options = group["options"]
        if not isinstance(options, list):
            continue
        for item in options:
            if not isinstance(item, dict):
                continue
            typer.echo(
                f"  {item['type']:<16} {item['label']}"
                f" · {item['input']} · {item['unit'] or '无单位'}"
            )


@screen_app.command("save")
def save(
    source: Annotated[str, typer.Argument(help="ScreenSpec JSON 文件；- 表示 stdin")],
    screen_id: Annotated[
        str | None,
        typer.Option("--id", help="更新既有 Screen；省略则新建"),
    ] = None,
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """保存 ScreenSpec；内容变化时自动追加版本。"""
    try:
        saved = screen_service.save_screen(_load_spec(source), screen_id=screen_id)
    except FileNotFoundError:
        _fail(fmt, code="spec_not_found", message=f"找不到规则文件: {source}")
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        _fail(fmt, code="invalid_spec", message=str(exc))
    _render_saved(saved, fmt)


@screen_app.command("list")
def list_saved(
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """列出已保存 Screen。"""
    items = screen_service.list_screens()
    if fmt is ScreenOutputFormat.json:
        typer.echo(export.to_json(_json_payload("screen list", "screens", items)))
        return
    if not items:
        typer.echo("还没有保存的 Screen · 用 kan screen save spec.json 创建")
        return
    for item in items:
        typer.echo(
            f"{item.screen_id}  v{item.current_version:<3}  "
            f"{item.name}  {len(item.spec.conditions)} 条件"
        )


@screen_app.command("show")
def show(
    screen_id: Annotated[str, typer.Argument(help="Screen ID")],
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """显示一份 Screen 的当前版本。"""
    item = workspace_db.get_screen(screen_id)
    if item is None:
        _fail(fmt, code="screen_not_found", message=f"Screen 不存在: {screen_id}")
    _render_saved(item, fmt)


@screen_app.command("versions")
def versions(
    screen_id: Annotated[str, typer.Argument(help="Screen ID")],
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """列出一份 Screen 的全部不可变规则版本。"""
    if workspace_db.get_screen(screen_id) is None:
        _fail(fmt, code="screen_not_found", message=f"Screen 不存在: {screen_id}")
    _render_versions(workspace_db.list_screen_versions(screen_id), fmt)


@screen_app.command("restore")
def restore(
    screen_id: Annotated[str, typer.Argument(help="Screen ID")],
    version: Annotated[int, typer.Argument(min=1, help="要恢复的历史版本号")],
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """把历史规则恢复成一个新的当前版本，不覆盖历史。"""
    historical = workspace_db.get_screen_version(screen_id, version)
    if historical is None:
        _fail(
            fmt,
            code="screen_version_not_found",
            message=f"Screen {screen_id} 不存在 v{version}",
        )
    _render_saved(
        screen_service.save_screen(historical.spec, screen_id=screen_id),
        fmt,
    )


@screen_app.command("run")
def run(
    screen_id: Annotated[str, typer.Argument(help="Screen ID")],
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """运行已保存 Screen，并保存不可变 ScreenRun。"""
    try:
        result = screen_service.run_saved_screen(screen_id)
    except screen_service.ScreenServiceError as exc:
        _fail(fmt, code=exc.code, message=exc.message, hint=exc.hint)
    _render_run(result, fmt)


@screen_app.command("run-spec")
def run_spec(
    source: Annotated[str, typer.Argument(help="ScreenSpec JSON 文件；- 表示 stdin")],
    no_persist: Annotated[
        bool,
        typer.Option("--no-persist", help="只运行，不写入 ScreenRun 历史"),
    ] = False,
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """不保存 Screen，直接运行一份 ScreenSpec。"""
    try:
        result = screen_service.run_screen(
            _load_spec(source),
            persist=not no_persist,
        )
    except FileNotFoundError:
        _fail(fmt, code="spec_not_found", message=f"找不到规则文件: {source}")
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        _fail(fmt, code="invalid_spec", message=str(exc))
    except screen_service.ScreenServiceError as exc:
        _fail(fmt, code=exc.code, message=exc.message, hint=exc.hint)
    _render_run(result, fmt)


@screen_app.command("runs")
def runs(
    screen_id: Annotated[
        str | None,
        typer.Argument(help="可选 Screen ID；省略则列出全部运行"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=200, help="最多返回多少次运行"),
    ] = 20,
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """列出不可变 ScreenRun 历史。"""
    items = workspace_db.list_runs(screen_id=screen_id, limit=limit)
    if fmt is ScreenOutputFormat.json:
        typer.echo(export.to_json(_json_payload("screen runs", "runs", items)))
        return
    if not items:
        typer.echo("还没有 ScreenRun")
        return
    for item in items:
        typer.echo(
            f"{item.run_id}  {item.spec.name}  {item.coverage.returned} 只  "
            f"{item.created_at.isoformat()}"
        )


@screen_app.command("show-run")
def show_run(
    run_id: Annotated[str, typer.Argument(help="ScreenRun ID")],
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """显示一份不可变 ScreenRun 与逐行证据。"""
    item = workspace_db.get_run(run_id)
    if item is None:
        _fail(fmt, code="run_not_found", message=f"ScreenRun 不存在: {run_id}")
    _render_run(item, fmt)


@screen_app.command("delete")
def delete(
    screen_id: Annotated[str, typer.Argument(help="Screen ID")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="确认删除 Screen 与其版本；运行记录保留"),
    ] = False,
    fmt: Annotated[
        ScreenOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = ScreenOutputFormat.terminal,
) -> None:
    """删除 Screen 定义；历史 ScreenRun 保留。"""
    if not yes:
        _fail(
            fmt,
            code="confirmation_required",
            message="删除 Screen 需要 --yes",
            exit_code=2,
        )
    deleted = workspace_db.delete_screen(screen_id)
    if fmt is ScreenOutputFormat.json:
        typer.echo(
            export.to_json(
                _json_payload("screen delete", "deleted", deleted)
            )
        )
        return
    typer.echo("已删除" if deleted else "Screen 不存在")

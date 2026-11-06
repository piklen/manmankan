"""保留当时的认识，再显式核对同一批成员。"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from kan.app import app
from kan.cli.trend_cmds import TrendFormat
from kan.domain.observation import (
    ObservationRecord,
    ObservationReviewResult,
    ObservationSaveRequest,
)
from kan.service import observation

observe_app = typer.Typer(help="保存观察、读取原事实并显式复看同一范围", no_args_is_help=True)
app.add_typer(observe_app, name="observe")


def _show(value: BaseModel | list[BaseModel], output: TrendFormat) -> None:
    if output is TrendFormat.json:
        payload = [item.model_dump(mode="json") for item in value] if isinstance(value, list) else value.model_dump(mode="json")
        typer.echo(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        return
    from rich.console import Console
    from rich.table import Table

    console = Console()
    if isinstance(value, list):
        table = Table("观察 ID", "名称", "原日期", "窗口", "成员")
        for item in value:
            fields = item.model_dump()
            table.add_row(str(fields["id"]), str(fields["title"]), str(fields["as_of"]), str(fields["window"]), str(fields["total"]))
        console.print(table)
        return
    record = value.observation if isinstance(value, ObservationReviewResult) else value
    if isinstance(record, ObservationRecord):
        console.print(f"{record.title} · {record.snapshot.as_of} · {record.query.window} 日 · {len(record.snapshot.members)} 只")
        console.print(record.note or "尚未记录自己的想法", markup=False)
        for fact in record.snapshot.group.observations:
            console.print(f"{fact.title}\n{fact.detail}", markup=False)
        console.print(f"观察 ID {record.id}")
    if isinstance(value, ObservationReviewResult):
        comparison = value.comparison
        console.print(f"\n复看 {value.current.as_of} · 同一范围 · 共同完整 {comparison.available} 只 · 无法比较 {comparison.missing} 只")
        if comparison.available:
            console.print(f"上涨占比 {comparison.previous_positive_share:.1f}% → {comparison.current_positive_share:.1f}%（{comparison.breadth_delta_pp:+.1f} 个百分点）")
            console.print(f"收益中位数 {comparison.previous_median:+.2f}% → {comparison.current_median:+.2f}%")
        for item in value.transitions:
            console.print(f"{item.label} {item.count} 只")
        console.print("原事实与想法未被覆盖。滚动窗口可能重叠，不等于持有收益或因果验证。")


def _error(exc: Exception, output: TrendFormat) -> None:
    if output is TrendFormat.json:
        typer.echo(json.dumps({"error": {"message": str(exc)}}, ensure_ascii=False))
    else:
        typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@observe_app.command("save")
def save(
    request_file: Annotated[str, typer.Argument(help="ObservationSaveRequest JSON 文件，- 从标准输入读取；query.as_of须明确")],
    format: Annotated[TrendFormat, typer.Option("--format")] = TrendFormat.terminal,
) -> None:
    try:
        raw = sys.stdin.read() if request_file == "-" else Path(request_file).read_text(encoding="utf-8")
        _show(observation.save_observation(ObservationSaveRequest.model_validate_json(raw)), format)
    except (ValueError, OSError) as exc:
        _error(exc, format)


@observe_app.command("list")
def list_saved(format: Annotated[TrendFormat, typer.Option("--format")] = TrendFormat.terminal) -> None:
    _show(list(observation.list_observations()), format)


@observe_app.command("show")
def show(observation_id: str, format: Annotated[TrendFormat, typer.Option("--format")] = TrendFormat.terminal) -> None:
    try:
        _show(observation.get_observation(observation_id), format)
    except ValueError as exc:
        _error(exc, format)


@observe_app.command("review")
def review(
    observation_id: str,
    as_of: Annotated[str | None, typer.Option("--as-of", help="明确复看日期，留空使用最近完整收盘")] = None,
    format: Annotated[TrendFormat, typer.Option("--format")] = TrendFormat.terminal,
) -> None:
    try:
        _show(observation.review_observation(observation_id, date.fromisoformat(as_of) if as_of else None), format)
    except (ValueError, OSError) as exc:
        _error(exc, format)


@observe_app.command("schema")
def schema() -> None:
    typer.echo(json.dumps(ObservationSaveRequest.model_json_schema(), ensure_ascii=False))

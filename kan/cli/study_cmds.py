"""研究实验台 CLI；JSON 与 Web、终端共用同一结果。"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from kan.app import app
from kan.domain.market_study import StudyQuery, StudyResult
from kan.service import market_study

study_app = typer.Typer(help="用明确日线条件检索市场并核对历史样本", no_args_is_help=True)
app.add_typer(study_app, name="study")


class StudyFormat(StrEnum):
    terminal = "terminal"
    json = "json"


def _show(value: BaseModel | list[BaseModel], output: StudyFormat) -> None:
    if output is StudyFormat.json:
        payload = [item.model_dump(mode="json") for item in value] if isinstance(value, list) else value.model_dump(mode="json")
        typer.echo(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        return
    from rich.console import Console
    from rich.table import Table

    console = Console()
    if isinstance(value, StudyResult):
        console.print(f"{value.query.title} · 截止 {value.as_of}")
        coverage = value.coverage
        console.print(f"当前匹配 {coverage.current_matches}/{coverage.total_symbols} · 条件资料不足 {coverage.current_missing}")
        console.print(f"历史事件 {coverage.selected_events} · 完整 {coverage.complete_events} · 未成熟 {coverage.pending_events} · 缺行情 {coverage.missing_events}")
        distribution = value.distribution
        if distribution.count:
            console.print(f"完整样本后续 {value.query.forward_days} 日：中位 {distribution.median_pct:+.2f}% · 上涨 {distribution.positive}/{distribution.count}")
        table = Table("代码", "名称", "收盘", "条件实际值")
        for row in value.current_matches:
            table.add_row(row.symbol, row.name, f"{row.close:.2f}", " · ".join(f"{key}={number:.2f}" if number is not None else f"{key}=缺失" for key, number in row.values.items()))
        console.print(table)
        console.print(f"研究 ID {value.study_id} · 运行 ID {value.run_id}")
        console.print("历史报价分布不等于成交收益或未来概率；图证与全部样本可在 kan web 查看。")
    elif isinstance(value, list):
        table = Table("研究 ID", "名称", "数据日", "当前匹配", "历史事件")
        for item in value:
            data = item.model_dump()
            table.add_row(str(data["study_id"]), str(data["title"]), str(data["as_of"]), str(data["current_count"]), str(data["event_count"]))
        console.print(table)
    else:
        console.print_json(value.model_dump_json())


def _error(exc: Exception, output: StudyFormat) -> None:
    if output is StudyFormat.json:
        typer.echo(json.dumps({"error": {"message": str(exc)}}, ensure_ascii=False))
    else:
        typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@study_app.command("run")
def run(
    query_file: Annotated[str, typer.Argument(help="StudyQuery JSON 文件；- 从标准输入读取")],
    format: Annotated[StudyFormat, typer.Option("--format")] = StudyFormat.terminal,
) -> None:
    try:
        raw = sys.stdin.read() if query_file == "-" else Path(query_file).read_text(encoding="utf-8")
        _show(market_study.run_study(StudyQuery.model_validate_json(raw)), format)
    except (OSError, ValueError) as exc:
        _error(exc, format)


@study_app.command("list")
def list_saved(format: Annotated[StudyFormat, typer.Option("--format")] = StudyFormat.terminal) -> None:
    _show(list(market_study.list_studies()), format)


@study_app.command("show")
def show(study_id: str, format: Annotated[StudyFormat, typer.Option("--format")] = StudyFormat.terminal) -> None:
    try:
        _show(market_study.get_study(study_id), format)
    except ValueError as exc:
        _error(exc, format)


@study_app.command("rerun")
def rerun(study_id: str, format: Annotated[StudyFormat, typer.Option("--format")] = StudyFormat.terminal, latest: Annotated[bool, typer.Option("--latest", help="推进到最近完整收盘，保留条件和形态参照")] = False) -> None:
    try:
        _show(market_study.rerun_study(study_id, latest=latest), format)
    except ValueError as exc:
        _error(exc, format)


@study_app.command("catalog")
def catalog() -> None:
    """输出可用字段的中文定义和单位，不预置选股条件。"""
    typer.echo(json.dumps(market_study.FIELD_CATALOG, ensure_ascii=False))


@study_app.command("schema")
def schema() -> None:
    """输出研究输入的 JSON Schema，供 AI 和脚本构造明确条件。"""
    typer.echo(json.dumps(StudyQuery.model_json_schema(), ensure_ascii=False))

"""`kan board` 子命令组 · 板块级资金 / 涨幅 / 位置榜。"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from kan.app import app
from kan.render.base import DISCLAIMER
from kan.storage import export

board_app = typer.Typer(
    name="board",
    help="板块榜单(行业 / 题材 · 资金 / 涨幅 / 位置裸值)",
    no_args_is_help=True,
)
app.add_typer(board_app, name="board")


class BoardKind(StrEnum):
    industry = "industry"
    theme = "theme"


class BoardMetric(StrEnum):
    moneyflow = "moneyflow"
    gain = "gain"
    pos = "pos"


def _fmt_num(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def _rows_payload(rows) -> list[dict]:
    return [
        {
            "kind": r.kind,
            "code": r.code,
            "name": r.name,
            "close": r.close,
            "position_pct": r.position_pct,
            "gain_pct": r.gain_pct,
            "moneyflow_net": r.moneyflow_net,
            "data_date": r.data_date.isoformat() if r.data_date else None,
        }
        for r in rows
    ]


def _markdown(rows, *, title: str) -> str:
    headers = ["排名", "板块", "现价", "位置", "涨幅", "主力净额(万)"]
    md_rows = []
    for idx, r in enumerate(rows, start=1):
        md_rows.append([
            str(idx),
            f"{r.name} {r.code}",
            _fmt_num(r.close),
            _fmt_num(r.position_pct, digits=1, suffix="%"),
            _fmt_num(r.gain_pct, digits=2, suffix="%"),
            _fmt_num(r.moneyflow_net, digits=0),
        ])
    body = export.md_table(headers, md_rows) if md_rows else "_无板块数据_"
    return f"# {title}\n\n{body}\n\n> {DISCLAIMER.strip()}"


def _table(rows, *, title: str) -> Table:
    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("排名", justify="right", style="cyan", min_width=4)
    table.add_column("板块", style="white", no_wrap=True)
    table.add_column("现价", justify="right")
    table.add_column("位置", justify="right")
    table.add_column("涨幅", justify="right")
    table.add_column("主力净额(万)", justify="right")
    for idx, r in enumerate(rows, start=1):
        table.add_row(
            str(idx),
            f"{r.name} {r.code}",
            _fmt_num(r.close),
            _fmt_num(r.position_pct, digits=1, suffix="%"),
            _fmt_num(r.gain_pct, digits=2, suffix="%"),
            _fmt_num(r.moneyflow_net, digits=0),
        )
    return table


@board_app.command("rank")
def rank_cmd(
    kind: Annotated[
        BoardKind,
        typer.Option("--kind", help="板块类型: industry(申万行业) / theme(题材概念)"),
    ] = BoardKind.industry,
    by: Annotated[
        BoardMetric,
        typer.Option("--by", help="排序口径: moneyflow(主力净额) / gain(区间涨幅) / pos(位置分位)"),
    ] = BoardMetric.moneyflow,
    period: Annotated[
        int,
        typer.Option("--period", "-p", help="涨幅 / 位置周期(日)", min=3, max=180),
    ] = 30,
    level: Annotated[
        int,
        typer.Option("--level", help="申万行业层级(仅 industry 有效 · 默认一级)", min=1, max=3),
    ] = 1,
    limit: Annotated[
        int,
        typer.Option("--limit", help="显示前 N", min=1, max=500),
    ] = 30,
    force: Annotated[
        bool,
        typer.Option("--force", help="强刷板块 K 线 / 成分股缓存"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式:terminal(默认)/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """板块级资金 / 涨幅 / 位置榜 · 只展示客观裸值。"""
    from kan.cli.helpers import _print_err, _with_heavy_imports_spinner
    from kan.data.board_leaderboard import load_board_leaderboard

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载板块数据..."):
        rows, errors = load_board_leaderboard(
            kind=kind.value,
            metric=by.value,
            period=period,
            level=level,
            limit=limit,
            force=force,
        )

    if not rows:
        _print_err("❌ 板块榜无数据 · 检查网络 / token / 上游数据源后重试")
        raise typer.Exit(1)

    kind_label = "申万行业" if kind is BoardKind.industry else "题材概念"
    metric_label = {
        BoardMetric.moneyflow: "主力净额",
        BoardMetric.gain: f"{period}日涨幅",
        BoardMetric.pos: f"{period}日位置",
    }[by]
    title = f"慢慢看 · {kind_label}板块榜 · 按{metric_label}排序"

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json({
            "command": "board_rank",
            "kind": kind.value,
            "sort": by.value,
            "period": period,
            "level": level if kind is BoardKind.industry else None,
            "shown": len(rows),
            "errors_count": len(errors),
            "results": _rows_payload(rows),
            "disclaimer": DISCLAIMER.strip(),
        }))
        return
    if fmt is export.OutputFormat.md:
        typer.echo(_markdown(rows, title=title))
        return

    console = Console()
    console.print(_table(rows, title=title))
    if errors:
        console.print(f"\n[dim]ℹ️  {len(errors)} 个板块数据不完整 · 可 --force 重试[/dim]")
    console.print(DISCLAIMER, style="dim")

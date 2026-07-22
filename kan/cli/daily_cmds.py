"""散户日常入口命令: guide / daily。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.storage import export

_DAILY_SCHEMA_VERSION = "0.1"


_GUIDE_TOPICS: dict[str, list[tuple[str, str]]] = {
    "start": [
        ("打开本地观察台", "kan web"),
        ("在终端看一日概览", "kan daily"),
        ("只看自选", "kan scan --only-watchlist"),
        ("只看持仓", "kan hold scan"),
    ],
    "holdings": [
        ("录入持仓", "kan hold add 600519 --cost 1680 --shares 100"),
        ("更新现金", "kan hold cash 73000"),
        ("持仓总览", "kan hold --mask"),
        ("只扫持仓", "kan hold scan"),
    ],
    "pool": [
        ("行业扫描", "kan scan --industry 半导体"),
        ("题材搜索", "kan theme search 数据要素"),
        ("题材扫描", "kan scan --theme AI应用"),
        ("外部代码池", "kan scan --codes 600519,000858"),
    ],
    "ai": [
        ("结构 smoke", "kan find --codes 600519,000858 --format json"),
        ("真实坐标 JSON", "kan scan --codes 600519,000858 --format json"),
        ("字段清单", "kan fields list --format json"),
        ("schema", "kan schema --format json --section find --compact"),
    ],
}


@app.command()
def guide(
    topic: Annotated[
        str,
        typer.Option("--topic", help="start / holdings / pool / ai"),
    ] = "start",
) -> None:
    """按常见意图展示可复制命令。"""
    key = topic.strip().lower()
    if key not in _GUIDE_TOPICS:
        keys = " / ".join(_GUIDE_TOPICS)
        typer.echo(f"❌ 未知 topic: {topic} · 可选 {keys}", err=True)
        raise typer.Exit(2)
    typer.echo("慢慢看 · 意图导航")
    typer.echo()
    for title, command in _GUIDE_TOPICS[key]:
        typer.echo(f"{title}")
        typer.echo(f"  {command}")
    typer.echo()
    typer.echo("普通用户优先用 kan web · 工具输出客观数据，不替你做交易决定")


def _command_rows() -> list[str]:
    return [
        "kan scan --only-watchlist",
        "kan hold scan",
        "kan find --pos 180:lt:10 --pe lt:30",
        "kan info <代码>",
    ]


def _count_period(results, *, period: int, low: float | None = None, high: float | None = None):
    rows = []
    for row in results:
        pr = next((p for p in row.periods if p.period == period and not p.insufficient), None)
        if pr is None:
            continue
        if (
            (low is not None and pr.position_pct <= low)
            or (high is not None and pr.position_pct >= high)
        ):
            rows.append(row)
    return rows


def _names(rows, limit: int = 8) -> list[str]:
    return [f"{r.name.replace(' ', '')} {r.symbol}" for r in rows[:limit]]


@app.command()
def daily(
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json / md"),
    ] = export.OutputFormat.terminal,
) -> None:
    """默认池一日事实概览。"""
    from rich.console import Console

    from kan.cli.helpers import format_date_compact
    from kan.core.pipeline import render_freshness_warning
    from kan.core.stock_set import from_flags
    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter
    from kan.render.base import DISCLAIMER
    from kan.service.scan_service import ScanRequest, run_scan
    from kan.storage.positions import load_positions
    from kan.storage.watchlist import load_watchlist

    console = Console()
    reporter = operation_reporter()
    with operation("生成一日事实概览", reporter=reporter) as lifecycle:
        result = run_scan(
            ScanRequest(
                stock_set=from_flags(),
                mode="low",
                periods=[30, 60, 180],
                show_progress=fmt is export.OutputFormat.terminal,
            ),
            lifecycle=lifecycle,
        )
        lifecycle.phase("汇总一日事实")
        watchlist_count = len(load_watchlist().stocks)
        book = load_positions()
        holding_count = len(book.positions)
        rows = result.results
        low_180 = _count_period(rows, period=180, low=10)
        high_180 = _count_period(rows, period=180, high=90)
        permission_rows = [r for r in rows if r.permission_note]
        lifecycle.phase("构造一日事实输出", format=fmt.value)
        payload = {
            "ok": True,
            "schema_version": _DAILY_SCHEMA_VERSION,
            "command": "daily",
            "data_cutoff": (
                result.ctx.freshness.data_cutoff.isoformat()
                if result.ctx.freshness.data_cutoff else None
            ),
            "fetched_at": result.ctx.freshness.fetched_at,
            "stale": result.ctx.freshness.is_stale,
            "pool": {
                "watchlist_count": watchlist_count,
                "holding_count": holding_count,
                "scanned_count": len(rows),
                "cash_configured": book.cash > 0,
            },
            "facts": {
                "period_180_low_lte_10_count": len(low_180),
                "period_180_low_lte_10": _names(low_180),
                "period_180_high_gte_90_count": len(high_180),
                "period_180_high_gte_90": _names(high_180),
                "permission_note_count": len(permission_rows),
                "permission_notes": [
                    {
                        "code": r.symbol,
                        "name": r.name.replace(" ", ""),
                        "note": r.permission_note,
                    }
                    for r in permission_rows[:12]
                ],
            },
            "next_commands": _command_rows(),
            "disclaimer": DISCLAIMER.strip(),
        }
        markdown = None
        if fmt is export.OutputFormat.md:
            markdown = "\n".join([
                "# 慢慢看 · 一日事实概览", "",
                f"- 默认池: 自选 {watchlist_count} 只 / 持仓 {holding_count} 只 / 已扫描 {len(rows)} 只",
                f"- 现金: {'已配置' if book.cash > 0 else '未配置'}",
                f"- 180 日位置 <=10%: {len(low_180)} 只",
                f"- 180 日位置 >=90%: {len(high_180)} 只",
                f"- 特殊权限提示: {len(permission_rows)} 只", "",
                "## 可复制命令", *[f"- `{cmd}`" for cmd in _command_rows()], "",
                "> " + DISCLAIMER.strip(),
            ])
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    if fmt is export.OutputFormat.md:
        assert markdown is not None
        typer.echo(markdown)
        return

    console.print("\n[bold]慢慢看 · 一日事实概览[/bold]")
    cutoff = result.ctx.freshness.data_cutoff
    cutoff_text = format_date_compact(cutoff) if cutoff else "无缓存"
    console.print(f"  数据截止 [cyan]{cutoff_text}[/cyan] · 默认池已扫描 [bold]{len(rows)}[/bold] 只")
    console.print(
        f"  自选 {watchlist_count} 只 · 持仓 {holding_count} 只 · "
        f"现金 {'[green]已配置[/green]' if book.cash > 0 else '[dim]未配置[/dim]'}"
    )
    # 池概况：涨跌停/连阳
    limit_up = sum(1 for r in rows if r.limit_up)
    limit_down = sum(1 for r in rows if r.limit_down)
    up_streak = sum(1 for r in rows if getattr(r, "up_days", 0) >= 3)
    summary_parts: list[str] = []
    if limit_up:
        summary_parts.append(f"[red]涨停 {limit_up}[/red]")
    if limit_down:
        summary_parts.append(f"[green]跌停 {limit_down}[/green]")
    if up_streak:
        summary_parts.append(f"连阳≥3天 {up_streak} 只")
    if summary_parts:
        console.print(f"  {' · '.join(summary_parts)}")
    console.print(
        f"  180日位置 [green]<=10%[/green] · [bold]{len(low_180)}[/bold] 只: "
        f"{', '.join(_names(low_180)) or '-'}"
    )
    console.print(
        f"  180日位置 [red]>=90%[/red] · [bold]{len(high_180)}[/bold] 只: "
        f"{', '.join(_names(high_180)) or '-'}"
    )
    if permission_rows:
        console.print(f"  特殊权限提示 · {len(permission_rows)} 只: {', '.join(_names(permission_rows))}")
    render_freshness_warning(result.ctx.freshness, console)
    console.print("\n[bold]可复制命令[/bold]")
    for command in _command_rows():
        console.print(f"  [cyan]{command}[/cyan]")
    console.print(DISCLAIMER, style="dim")

"""history · 单只股票的位置百分位历史回溯（纯离线 · 只读每日快照）。

数据来源 = `kan scan`(全量自选 · 非 industry/theme)每天落的 snapshots/YYYY-MM-DD.json。
只有曾进过自选、且当天跑过扫描的股票才有历史。全程不触网络。
"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err
from kan.service.history_service import HistoryRequest, HistoryServiceError, get_symbol_history
from kan.storage import export


def _exit_history_error(
    fmt: export.OutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> None:
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.error_payload(
            "history",
            code=code,
            message=message,
            hint=hint,
        )))
    else:
        text = f"❌ {message}"
        if hint:
            text += f"\n   {hint}"
        _print_err(text)
    raise typer.Exit(exit_code)


@app.command()
def history(
    symbol: Annotated[str, typer.Argument(help="股票代码或名称")],
    period: Annotated[
        int,
        typer.Option("--period", "-p", help="回溯周期(2-360 · 默认 30 · 仅展示历史快照中已记录的周期)"),
    ] = 30,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """看一只股票过去 N 天「位置百分位」的变化轨迹（纯离线 · 读每日扫描快照）"""
    try:
        service_result = get_symbol_history(HistoryRequest(symbol_or_name=symbol, period=period))
    except HistoryServiceError as e:
        _exit_history_error(
            fmt,
            code=e.code,
            message=e.message,
            hint=e.hint,
            exit_code=e.exit_code,
        )
    sym = service_result.symbol
    name = service_result.name
    entries = service_result.entries

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.history_payload(
            sym,
            name,
            entries,
            period=service_result.period,
        )))
        return
    if fmt is export.OutputFormat.md:
        name_short = name.replace(" ", "")
        title = f"慢慢看 · {name_short} {sym} · {service_result.period}日位置回溯"
        typer.echo(export.history_markdown(
            entries,
            period=service_result.period,
            title=title,
        ))
        return

    from rich.console import Console

    from kan.render import terminal
    from kan.render.base import DISCLAIMER

    console = Console()
    console.print(terminal.history_table(sym, name, entries, period=service_result.period))
    # 趋势摘要：从有效位置值中提取趋势
    valid_pcts = [
        e.periods[service_result.period]["pct"]
        for e in entries
        if service_result.period in e.periods
    ]
    if len(valid_pcts) >= 2:
        # entries 是新→旧，反转成旧→新显示趋势
        trend_vals = list(reversed(valid_pcts[-6:]))
        trend_str = " → ".join(f"{v:.0f}%" for v in trend_vals)
        first, last = trend_vals[0], trend_vals[-1]
        if last < first - 5:
            direction = "[green]整体下行[/green]"
        elif last > first + 5:
            direction = "[red]整体上行[/red]"
        else:
            direction = "横盘整理"
        console.print(
            f"\n[dim]趋势(旧→新): {trend_str} · {direction}[/dim]"
        )
    console.print(
        f"\n[dim]共 {len(entries)} 个快照日(新→旧)· 只含跑过 kan scan 的日子 · "
        "换周期 --period 60[/dim]"
    )
    console.print(DISCLAIMER, style="dim")

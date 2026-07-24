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
    symbol: Annotated[str | None, typer.Argument(help="股票代码或名称(--pool 时省略)")] = None,
    period: Annotated[
        int | None,
        typer.Option("--period", "-p", help="回溯周期(2-360 · 单股默认 30 · --pool 默认 180)"),
    ] = None,
    pool: Annotated[
        bool,
        typer.Option("--pool", help="池级模式:全部快照日的池内位置中位/低位/高位趋势"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """看一只股票过去 N 天「位置百分位」的变化轨迹（纯离线 · 读每日扫描快照）"""
    if pool:
        _pool_history(period if period is not None else 180, fmt)
        return
    if not symbol:
        _exit_history_error(
            fmt,
            code="missing_symbol",
            message="缺少股票代码或名称",
            hint="例: kan history 600519；池级趋势用 kan history --pool",
            exit_code=2,
        )
    try:
        service_result = get_symbol_history(HistoryRequest(symbol_or_name=symbol, period=period or 30))
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
    if fmt is export.OutputFormat.csv:
        typer.echo(export.history_csv(
            entries,
            period=service_result.period,
        ))
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


def _pool_history(period: int, fmt: export.OutputFormat) -> None:
    """`kan history --pool` · 池级位置趋势(中位/低位/高位 · 纯离线聚合)。"""
    from kan.core.scanner_history import load_pool_history
    from kan.render.base import DISCLAIMER

    entries = load_pool_history(period)
    if not entries:
        _exit_history_error(
            fmt,
            code="no_pool_history",
            message=f"没有可用的池级历史(周期 {period})",
            hint="池级趋势来自每日 canonical `kan scan` 快照 · 先跑几天 kan scan 再看",
        )

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json({
            "ok": True,
            "schema_version": 1,
            "command": "history",
            "mode": "pool",
            "period": period,
            "entries": [
                {
                    "date": e.snapshot_date.isoformat(),
                    "stock_count": e.stock_count,
                    "median_pct": e.median_pct,
                    "low_count": e.low_count,
                    "high_count": e.high_count,
                }
                for e in entries
            ],
            "disclaimer": DISCLAIMER.strip(),
        }))
        return

    from rich.console import Console
    from rich.table import Table

    from kan.infra.formatting import format_date_compact

    console = Console()
    title = f"慢慢看 · 池内 {period}日位置趋势"
    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("日期", style="white")
    table.add_column("中位", justify="right")
    table.add_column("低位≤20%", justify="right")
    table.add_column("高位≥80%", justify="right")
    table.add_column("只数", justify="right", style="dim")
    for e in entries:
        table.add_row(
            format_date_compact(e.snapshot_date),
            f"{e.median_pct:.0f}%",
            str(e.low_count),
            str(e.high_count),
            str(e.stock_count),
        )
    console.print(table)
    if len(entries) >= 2:
        # entries 是新→旧 · 趋势按旧→新展示
        trend_vals = [e.median_pct for e in reversed(entries[-7:])]
        trend_str = " → ".join(f"{v:.0f}%" for v in trend_vals)
        first, last = trend_vals[0], trend_vals[-1]
        if last < first - 5:
            direction = "[green]整体下行[/green]"
        elif last > first + 5:
            direction = "[red]整体上行[/red]"
        else:
            direction = "横盘整理"
        console.print(f"\n[dim]趋势(旧→新): {trend_str} · {direction}[/dim]")
    console.print(
        f"\n[dim]共 {len(entries)} 个快照日(新→旧)· 只含跑过 canonical kan scan 的日子 · "
        "残缺快照日(自定义周期/分组扫描)已跳过[/dim]"
    )
    console.print(DISCLAIMER, style="dim")

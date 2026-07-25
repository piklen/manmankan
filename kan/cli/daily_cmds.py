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


def _direction_counts(rows) -> dict[str, int]:
    """按量价事实的收盘方向统计涨/跌/平家数 · 无量价数据的行不计入。"""
    counts = {"up": 0, "down": 0, "flat": 0}
    for r in rows:
        state = getattr(r, "volume_price_state", None) or ""
        if state.endswith("收涨"):
            counts["up"] += 1
        elif state.endswith("收跌"):
            counts["down"] += 1
        elif state.endswith("收平"):
            counts["flat"] += 1
    return counts


def _wrap_names(prefix: str, names: list[str], width: int) -> str:
    """prefix + 名单一行输出 · 超宽按显示宽度折行,续行悬挂缩进 4 格。

    不能用 textwrap:CJK 按字符数而非显示宽折行会溢出;markup 标签
    需经 Text.from_markup 测宽,不计入显示宽度。
    """
    from rich.text import Text

    sep = ", "
    if not names:
        return prefix + "-"
    if Text.from_markup(prefix + sep.join(names)).cell_len <= width:
        return prefix + sep.join(names)
    lines: list[str] = []
    current = prefix
    for i, name in enumerate(names):
        token = name if i == 0 else sep + name
        if current != prefix and Text.from_markup(current + token).cell_len > width:
            lines.append(current)
            current = "    " + name
        else:
            current += token
    lines.append(current)
    return "\n".join(lines)


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
    from kan.core.scanner_snapshot import load_previous_web_daily_snapshot
    from kan.core.stock_set import from_flags
    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter
    from kan.render.base import DISCLAIMER
    from kan.service.daily_service import build_daily_overview
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
        direction = _direction_counts(rows)
        # 池内 180 日中位位置
        p180_values = sorted(
            p.position_pct
            for r in rows
            for p in r.periods
            if p.period == 180 and not p.insufficient
        )
        median_180 = p180_values[len(p180_values) // 2] if p180_values else None
        # 加载上一份快照用于对比变化
        freshness = result.ctx.freshness
        comparison = (
            load_previous_web_daily_snapshot(freshness.data_cutoff)
            if freshness.data_cutoff and not freshness.is_stale else None
        )
        comparison_date = comparison[0] if comparison else None
        previous_snapshot = comparison[1] if comparison else None
        overview = build_daily_overview(
            result,
            previous_snapshot=previous_snapshot,
            comparison_date=comparison_date,
        )
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
                "median_position_180": round(median_180, 1) if median_180 is not None else None,
            },
            "facts": {
                "direction_up": direction["up"],
                "direction_down": direction["down"],
                "direction_flat": direction["flat"],
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
            "comparison": {
                "date": comparison_date.isoformat() if comparison_date else None,
                "changes": [
                    {
                        "code": c.code,
                        "name": c.name,
                        "period": c.period,
                        "description": c.description,
                    }
                    for c in overview.changes
                ],
            },
            "next_commands": _command_rows(),
            "disclaimer": DISCLAIMER.strip(),
        }
        markdown = None
        if fmt is export.OutputFormat.md:
            md_lines = [
                "# 慢慢看 · 一日事实概览", "",
                f"- 默认池: 自选 {watchlist_count} 只 / 持仓 {holding_count} 只 / 已扫描 {len(rows)} 只",
                f"- 现金: {'已配置' if book.cash > 0 else '未配置'}",
            ]
            if median_180 is not None:
                md_lines.append(f"- 池内 180 日中位位置: {median_180:.0f}%")
            if any(direction.values()):
                md_lines.append(
                    f"- 今日收盘方向: 涨 {direction['up']} / 跌 {direction['down']} / 平 {direction['flat']}"
                )
            md_lines.extend([
                f"- 180 日位置 <=10%: {len(low_180)} 只",
                f"- 180 日位置 >=90%: {len(high_180)} 只",
                f"- 特殊权限提示: {len(permission_rows)} 只",
            ])
            if overview.changes and comparison_date:
                md_lines.append(f"- 与 {comparison_date.isoformat()} 相比: {len(overview.changes)} 条位置变化")
            md_lines.extend(["",
                "## 可复制命令", *[f"- `{cmd}`" for cmd in _command_rows()], "",
                "> " + DISCLAIMER.strip(),
            ])
            markdown = "\n".join(md_lines)
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    if fmt is export.OutputFormat.csv:
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["指标", "值"])
        writer.writerow(["数据截止", payload["data_cutoff"] or "-"])
        writer.writerow(["自选股数", str(watchlist_count)])
        writer.writerow(["持仓股数", str(holding_count)])
        writer.writerow(["已扫描股数", str(len(rows))])
        writer.writerow(["现金配置", "是" if book.cash > 0 else "否"])
        if median_180 is not None:
            writer.writerow(["180日中位位置%", f"{median_180:.1f}"])
        writer.writerow(["180日<=10%股数", str(len(low_180))])
        writer.writerow(["180日>=90%股数", str(len(high_180))])
        writer.writerow(["特殊权限提示股数", str(len(permission_rows))])
        if any(direction.values()):
            writer.writerow(["今日涨", str(direction["up"])])
            writer.writerow(["今日跌", str(direction["down"])])
            writer.writerow(["今日平", str(direction["flat"])])
        if overview.changes and comparison_date:
            writer.writerow(["位置变化数", str(len(overview.changes))])
            writer.writerow(["对比日期", comparison_date.isoformat()])
        typer.echo("\ufeff" + output.getvalue())
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
    if any(direction.values()):
        console.print(
            f"  今日 [red]涨 {direction['up']}[/red] · "
            f"[green]跌 {direction['down']}[/green] · 平 {direction['flat']}"
        )
    if median_180 is not None:
        console.print(f"  池内 180日中位位置 [bold]{median_180:.0f}%[/bold]（{len(p180_values)} 只有效）")
    console.print(_wrap_names(
        f"  180日位置 [green]<=10%[/green] · [bold]{len(low_180)}[/bold] 只: ",
        _names(low_180),
        console.width,
    ))
    console.print(_wrap_names(
        f"  180日位置 [red]>=90%[/red] · [bold]{len(high_180)}[/bold] 只: ",
        _names(high_180),
        console.width,
    ))
    if permission_rows:
        console.print(_wrap_names(
            f"  特殊权限提示 · {len(permission_rows)} 只: ",
            _names(permission_rows),
            console.width,
        ))
    # 与上一份数据的变化
    if overview.changes and comparison_date:
        console.print(f"  [bold]与 {format_date_compact(comparison_date)} 相比[/bold] · {len(overview.changes)} 条变化:")
        for change in overview.changes[:6]:
            console.print(f"    {change.name} {change.code} · {change.description}")
        if len(overview.changes) > 6:
            console.print(f"    [dim]… 及其他 {len(overview.changes) - 6} 条[/dim]")
    elif comparison_date:
        console.print(f"  与 {format_date_compact(comparison_date)} 相比 · 无关键位置变化")
    # 位置变动 TOP3（对比上一份快照）
    if previous_snapshot:
        top_moves: list[tuple[str, str, float]] = []
        for r in rows:
            prev = previous_snapshot.get(r.symbol, {})
            prev_period = prev.get("180")
            prev_180 = prev_period.get("pct") if isinstance(prev_period, dict) else None
            cur_180 = next(
                (p.position_pct for p in r.periods if p.period == 180 and not p.insufficient),
                None,
            )
            if prev_180 is not None and cur_180 is not None:
                delta = cur_180 - prev_180
                if abs(delta) >= 1:
                    top_moves.append((r.name.replace(" ", ""), r.symbol, delta))
        if top_moves:
            top_moves.sort(key=lambda x: abs(x[2]), reverse=True)
            console.print("  [bold]180日位置变动 TOP3[/bold]")
            for name, code, delta in top_moves[:3]:
                arrow = "[red]↑" if delta > 0 else "[green]↓"
                console.print(f"    {name} {code} · {arrow}{abs(delta):.1f}%[/]")
    # 持仓今日贡献
    if book.positions:
        from kan.service.hold_service import build_hold_summary

        try:
            hold_result = build_hold_summary()
            if hold_result.results:
                sorted_by_pnl = sorted(
                    hold_result.results,
                    key=lambda r: abs(r.daily_pnl) if r.daily_pnl is not None else 0,
                    reverse=True,
                )
                top_contrib = sorted_by_pnl[0]
                if top_contrib.daily_pnl is not None and top_contrib.daily_pnl != 0:
                    sign = "+" if top_contrib.daily_pnl > 0 else ""
                    color = "red" if top_contrib.daily_pnl > 0 else "green"
                    console.print(
                        f"  持仓今日最大贡献: "
                        f"{top_contrib.name.replace(' ', '')} {top_contrib.symbol} "
                        f"[{color}]{sign}{top_contrib.daily_pnl:.0f}元[/]"
                    )
        except Exception:
            pass  # 持仓不可用时静默跳过
    render_freshness_warning(result.ctx.freshness, console)
    console.print("\n[bold]可复制命令[/bold]")
    for command in _command_rows():
        console.print(f"  [cyan]{command}[/cyan]")
    console.print(DISCLAIMER, style="dim")

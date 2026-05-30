"""history · 单只股票的位置百分位历史回溯（纯离线 · 只读每日快照）。

数据来源 = `kan scan`(全量自选 · 非 industry/theme)每天落的 snapshots/YYYY-MM-DD.json。
只有曾进过自选、且当天跑过扫描的股票才有历史。全程不触网络。
"""
from __future__ import annotations

import re
from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err
from kan.storage import export


def _resolve_in_snapshots(raw: str, universe: dict[str, str]) -> tuple[str, str]:
    """把用户输入(代码 / 名称)解析成 (symbol, name) · 解析域 = 有历史的股票。

    6 位代码 → 直接查;非 6 位 → 在快照名称里模糊搜。0 / 多匹配抛 typer.Exit + 引导。
    跟 resolve_symbol_or_name 的 UX 一致,但纯离线(只认快照里出现过的股)。
    """
    cleaned = re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    if re.match(r"^\d{6}$", cleaned):
        if cleaned in universe:
            return cleaned, universe[cleaned]
        _print_err(
            f"没有「{raw}」的历史 · `kan history` 只能看曾在自选、且跑过 `kan scan` 的股票"
        )
        raise typer.Exit(1)
    if not cleaned:
        _print_err("空字符串不是有效股票名 / 代码 · 例: kan history 600519 或 kan history 茅台")
        raise typer.Exit(2)
    q = cleaned.replace(" ", "")
    matches = [(s, n) for s, n in universe.items() if q in n.replace(" ", "")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        _print_err(
            f"快照历史里没有匹配「{raw}」的股票 · `kan history` 只覆盖曾在自选、"
            "且跑过 `kan scan` 的股票 · 试 6 位代码"
        )
        raise typer.Exit(1)
    preview = "; ".join(f"{s} {n.replace(' ', '')}" for s, n in matches[:8])
    if len(matches) > 8:
        preview += f"; …等 {len(matches)} 只"
    _print_err(f"「{raw}」匹配到 {len(matches)} 只 · 候选: {preview} · 请用代码精确指定")
    raise typer.Exit(1)


@app.command()
def history(
    symbol: Annotated[str, typer.Argument(help="股票代码或名称")],
    period: Annotated[
        int,
        typer.Option("--period", "-p", help="回溯周期(默认 30 · 可选 3/5/7/10/15/30/60/90/120/180)"),
    ] = 30,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """看一只股票过去 N 天「位置百分位」的变化轨迹（纯离线 · 读每日扫描快照）"""
    from kan.core.scanner import PERIODS, load_symbol_history, snapshot_symbol_names

    if period not in PERIODS:
        _print_err(
            f"❌ 周期不支持：{period} · 可选 {'/'.join(map(str, PERIODS))}"
        )
        raise typer.Exit(2)

    universe = snapshot_symbol_names()
    if not universe:
        _print_err("还没有任何扫描历史 · 先跑 `kan scan` 积累每日快照,之后才能回溯位置")
        raise typer.Exit(1)

    sym, name = _resolve_in_snapshots(symbol, universe)
    entries = load_symbol_history(sym)
    if not entries:  # 理论上不会(sym 来自 universe)· 防快照在两次读之间被改
        _print_err(f"没有「{name} {sym}」的历史快照")
        raise typer.Exit(1)

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.history_payload(sym, name, entries, period=period)))
        return
    if fmt is export.OutputFormat.md:
        name_short = name.replace(" ", "")
        title = f"慢慢看 · {name_short} {sym} · {period}日位置回溯"
        typer.echo(export.history_markdown(entries, period=period, title=title))
        return

    from rich.console import Console

    from kan.render import terminal
    from kan.render.base import DISCLAIMER

    console = Console()
    console.print(terminal.history_table(sym, name, entries, period=period))
    console.print(
        f"\n[dim]共 {len(entries)} 个快照日(新→旧)· 只含跑过 kan scan 的日子 · "
        f"换周期 --period 60[/dim]"
    )
    console.print(DISCLAIMER, style="dim")

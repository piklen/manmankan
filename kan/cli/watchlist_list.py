"""`kan list` 执行逻辑。"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from kan.cli.helpers import _print_err


def run_list_stocks(
    *,
    industry: str | None,
    theme: str | None,
    group: str | None,
    show_all: bool,
) -> None:
    """执行 `kan list`。"""
    from kan.storage.watchlist import (
        GroupNotFoundError,
        list_all,
        load_grouped_watchlist,
    )

    if industry is not None and theme is not None:
        _print_err("❌ --industry 与 --theme 不能同时使用")
        raise typer.Exit(2)
    if show_all and group is not None:
        _print_err("❌ --all 与 --group 不能同时使用 (--all 已列所有组)")
        raise typer.Exit(2)

    if show_all:
        gw = load_grouped_watchlist()
        if not any(gw.groups.values()):
            typer.echo("所有组都是空的 · 先加几只: `kan add 600519 茅台 000858`")
            return
        console = Console()
        for gname, stocks in gw.groups.items():
            tag = " (默认)" if gname == gw.default else ""
            if not stocks:
                console.print(f"\n[dim]📋 {gname}{tag} · 空[/dim]")
                continue
            table = Table(title=f"📋 {gname}{tag} · {len(stocks)} 只")
            table.add_column("代码", style="cyan")
            table.add_column("名称", style="white")
            table.add_column("添加日期", style="dim")
            for stock in stocks:
                table.add_row(stock.symbol, stock.name.replace(" ", ""), str(stock.added_at))
            console.print(table)
        return

    try:
        stocks = list_all(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None

    group_label = f"「{group}」" if group else "自选"
    empty_hint = (
        "自选列表为空 · 先加几只:`kan add 600519 茅台 000858` (代码或名称都行)"
        if not group
        else f"「{group}」组为空 · `kan add 600519 --group {group}` 添加"
    )
    if not stocks:
        typer.echo(empty_hint)
        return

    title = f"{group_label}股列表 · 共 {len(stocks)} 只"
    if industry is not None:
        from kan.data import boards

        try:
            board = boards.search_industry(industry)
            cons_codes = {c for c, _ in boards.get_industry_constituents(board)}
        except boards.BoardNotFoundError:
            _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词")
            raise typer.Exit(1) from None
        except boards.BoardDataUnavailableError:
            _print_err("❌ 行业数据源暂时不可用,稍后再试")
            raise typer.Exit(1) from None
        stocks = [s for s in stocks if s.symbol in cons_codes]
        if not stocks:
            typer.echo(f"{group_label}组里没有属于「{board.name}」行业的")
            return
        title = f"{group_label}组 · {board.name} 行业 · {len(stocks)} 只"
    elif theme is not None:
        from kan.data import boards

        try:
            themed = boards.search_theme(theme)
            cons_codes = {c for c, _ in boards.get_theme_constituents(themed)}
        except boards.ThemeNotFoundError:
            _print_err(f"❌ 未找到题材「{theme}」· 试更短关键词")
            raise typer.Exit(2) from None
        except boards.ThemeDataUnavailableError:
            _print_err("❌ 题材数据源暂时不可用,稍后再试")
            raise typer.Exit(1) from None
        stocks = [s for s in stocks if s.symbol in cons_codes]
        if not stocks:
            typer.echo(f"{group_label}组里没有属于「{themed.name}」题材的")
            return
        title = f"{group_label}组 · {themed.name} 题材 · {len(stocks)} 只"

    table = Table(title=title)
    table.add_column("代码", style="cyan")
    table.add_column("名称", style="white")
    table.add_column("添加日期", style="dim")
    for stock in stocks:
        table.add_row(stock.symbol, stock.name.replace(" ", ""), str(stock.added_at))
    Console().print(table)

"""compare · 横向对比多只股票的多周期位置（转置表）。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err, _safe_error_msg, _with_heavy_imports_spinner
from kan.storage import export

MAX_COMPARE_SYMBOLS = 30
COMPARE_PAGE_SIZE = 8


@app.command()
def compare(
    symbols: Annotated[list[str], typer.Argument(help="股票代码或名称（2-30 只）")],
    periods: Annotated[
        str,
        typer.Option(
            "--periods", "-p",
            help="周期(2-360 · 默认 5,30,180 短中长 · 逗号分隔多个:7,20,90)"
        ),
    ] = "5,30,180",
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """横向对比多只股票的多周期位置（转置表 · 指标为行 · 个股为列）"""
    if len(symbols) < 2:
        _print_err("❌ kan compare 至少需要 2 只股票 · 例: kan compare 600519 000858")
        raise typer.Exit(2)
    if len(symbols) > MAX_COMPARE_SYMBOLS:
        _print_err(
            f"❌ 最多对比 {MAX_COMPARE_SYMBOLS} 只 · 当前 {len(symbols)} 只 · "
            "请分批输入或导出 CSV 后拆分"
        )
        raise typer.Exit(2)

    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.scanner import MAX_PERIOD, MIN_PERIOD, scan_stock
        from kan.data.fetcher import fetch_kline, get_cached, is_fresh
        from kan.render import terminal
        from kan.render.base import DISCLAIMER
        from kan.storage.watchlist import resolve_symbol_or_name

    console = Console()

    try:
        period_list = [int(p.strip()) for p in periods.split(",") if p.strip()]
    except ValueError:
        _print_err(f"❌ --periods 格式错误：{periods!r} · 应为逗号分隔整数")
        raise typer.Exit(2) from None
    invalid = [p for p in period_list if p < MIN_PERIOD or p > MAX_PERIOD]
    if invalid or not period_list:
        _print_err(
            f"❌ 周期不支持：{invalid or periods!r} · 范围 {MIN_PERIOD}-{MAX_PERIOD}"
        )
        raise typer.Exit(2)
    period_list = sorted(dict.fromkeys(period_list))

    results = []
    seen: set[str] = set()
    for raw in symbols:
        try:
            sym, name = resolve_symbol_or_name(raw)
        except ValueError as e:
            _print_err(f"❌ {raw}：{e}")
            raise typer.Exit(1) from e
        if sym in seen:
            continue  # 静默去重 · `compare 茅台 600519 茅台` 这种用户重复输入
        seen.add(sym)
        if not is_fresh(sym):
            try:
                with status_console.status(
                    f"[yellow]⏳ 拉取数据... {name.replace(' ', '')} ({sym})[/yellow]",
                    spinner="dots",
                ):
                    fetch_kline(sym, force=True)
            except Exception as e:
                _print_err(f"❌ {sym} 拉取失败：{_safe_error_msg(e)}")
                raise typer.Exit(1) from e
        df = get_cached(sym)
        if df is None:
            _print_err(f"❌ {sym} 无数据")
            raise typer.Exit(1)
        results.append(scan_stock(df, sym, name, periods=period_list))

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.compare_payload(results, periods=period_list)))
        return
    if fmt is export.OutputFormat.md:
        typer.echo(export.compare_markdown(results, periods=period_list))
        return

    pages = [
        results[i:i + COMPARE_PAGE_SIZE]
        for i in range(0, len(results), COMPARE_PAGE_SIZE)
    ]
    for idx, page in enumerate(pages, start=1):
        if len(pages) > 1:
            console.print(f"\n[bold]kan compare · 第 {idx}/{len(pages)} 页[/bold]")
        table = terminal.compare_table(page, periods=period_list)
        console.print(table)

    # 窄屏 + 多列时给提示 · 80 列下 ≥5 只表头会折断或裁掉
    # 经验阈值:每只股大约要 12-14 列(名称 + 代码 + 现价 + N 周期位置)
    estimated_width_per_col = 14
    overhead = 12  # "指标" 列宽 + 表格边框
    widest_page = max((len(p) for p in pages), default=0)
    needed = overhead + widest_page * estimated_width_per_col
    if console.width < needed:
        console.print(
            f"\n[dim]💡 窄屏模式 · 终端 {console.width} 列 / 建议 ≥ {needed} 列容 {widest_page} 只"
            f" · 太窄时名称/代码会被裁 · 降低每次输入数量 / 加宽终端 / 用 --format md 看完整表[/dim]"
        )
    console.print(DISCLAIMER, style="dim")

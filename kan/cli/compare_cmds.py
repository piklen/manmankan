"""compare · 横向对比多只股票的多周期位置（转置表）。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err
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

    from kan.core.scanner import MAX_PERIOD, MIN_PERIOD, scan_stock
    from kan.data.fetcher import fetch_batch, get_cached, is_fresh
    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter
    from kan.render import terminal
    from kan.render.base import DISCLAIMER
    from kan.storage.watchlist import resolve_symbol_or_name

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

    reporter = operation_reporter()

    def _render() -> None:
        pass

    try:
        with operation("横向对比", reporter=reporter) as lifecycle:
            lifecycle.phase("解析股票")
            # 第一遍：解析名称、去重、收集 stale 标的
            resolved: list[tuple[str, str]] = []  # (sym, name)
            stale: list[str] = []
            seen: set[str] = set()
            for raw in symbols:
                try:
                    sym, name = resolve_symbol_or_name(raw)
                except ValueError as e:
                    _print_err(f"❌ {raw}：{e}")
                    raise typer.Exit(1) from e
                if sym in seen:
                    continue
                seen.add(sym)
                resolved.append((sym, name))
                if not is_fresh(sym):
                    stale.append(sym)

            # 第二遍：一次 batch 拉取所有 stale 标的
            if stale:
                lifecycle.phase("批量拉取数据", total=len(stale))
                _, fetch_errors = fetch_batch(stale, force=True, lifecycle=lifecycle)

                failed = {sym for sym in stale if sym in fetch_errors}
                if failed:
                    for sym in failed:
                        _print_err(f"❌ {sym} 拉取失败：{fetch_errors[sym]}")
                    raise typer.Exit(1)

            # 第三遍：读缓存 + 扫描
            lifecycle.phase("计算位置", total=len(resolved))
            results = []
            for idx, (sym, name) in enumerate(resolved, start=1):
                df = get_cached(sym)
                if df is None:
                    _print_err(f"❌ {sym} 无数据")
                    raise typer.Exit(1)
                results.append(scan_stock(df, sym, name, periods=period_list))
                lifecycle.progress(idx, len(resolved), "计算位置")

            lifecycle.phase("准备输出")

            if fmt is export.OutputFormat.json:
                json_str = export.to_json(
                    export.compare_payload(results, periods=period_list)
                )
                def _render_json() -> None:
                    typer.echo(json_str)
                _render = _render_json
            elif fmt is export.OutputFormat.md:
                md_str = export.compare_markdown(results, periods=period_list)
                def _render_md() -> None:
                    typer.echo(md_str)
                _render = _render_md
            else:
                console = Console()
                pages = [
                    results[i:i + COMPARE_PAGE_SIZE]
                    for i in range(0, len(results), COMPARE_PAGE_SIZE)
                ]

                def _render_terminal() -> None:
                    for idx, page in enumerate(pages, start=1):
                        if len(pages) > 1:
                            console.print(
                                f"\n[bold]kan compare · 第 {idx}/{len(pages)} 页[/bold]"
                            )
                        table = terminal.compare_table(page, periods=period_list)
                        console.print(table)

                    estimated_width_per_col = 14
                    overhead = 12
                    widest_page = max((len(p) for p in pages), default=0)
                    needed = overhead + widest_page * estimated_width_per_col
                    if console.width < needed:
                        console.print(
                            f"\n[dim]💡 窄屏模式 · 终端 {console.width} 列"
                            f" / 建议 ≥ {needed} 列容 {widest_page} 只"
                            " · 太窄时名称/代码会被裁"
                            " · 降低每次输入数量 / 加宽终端 / 用 --format md 看完整表[/dim]"
                        )
                    console.print(DISCLAIMER, style="dim")

                _render = _render_terminal

    except typer.Exit:
        raise

    _render()

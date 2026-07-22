"""scan · 自选股多周期位置扫描（10 周期全景 · --diff / --signal / --exclude-st）。

本文件只装 scan 命令;fetch / low / high / info / compare 各自在
fetch_cmds / extreme_cmds / info_cmds / compare_cmds。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

import typer

from kan.app import app
from kan.cli.helpers import (
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _parse_codes,
    _print_err,
    format_date_compact,
)
from kan.data.hot import HotList
from kan.storage import export


def _render_cutoff_summary(results: list, console) -> None:
    """Render per-cutoff stock counts for terminal scan output."""
    from collections import Counter

    from kan.data.fetcher import data_cutoff_date

    counts = Counter(
        d
        for r in results
        if (d := data_cutoff_date(getattr(r, "symbol", ""))) is not None
    )
    if not counts:
        return
    parts = [
        f"{count}只 {format_date_compact(day)}"
        for day, count in sorted(counts.items(), reverse=True)
    ]
    console.print(f"\n  [dim]数据截止: {' / '.join(parts)}[/dim]")


def _exit_scan_error(
    fmt: export.OutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> None:
    """scan 错误出口 · json 模式保持机器可读 envelope。"""
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.error_payload(
            "scan",
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


def _resolve_scan_code_pairs(
    raw: str,
    *,
    command: str,
    fmt: export.OutputFormat,
) -> list[tuple[str, str]]:
    """Resolve `kan scan --codes`, preserving JSON error envelopes in json mode."""
    import sys

    from kan.infra.log import debug_log

    text = sys.stdin.read() if raw == "-" else raw
    codes, invalid = _parse_codes(text)
    if invalid:
        preview = ", ".join(invalid[:5])
        suffix = "..." if len(invalid) > 5 else ""
        _exit_scan_error(
            fmt,
            code="invalid_codes",
            message=f"--codes 含非法代码: {preview}{suffix} · 需 6 位 A 股代码",
            hint=f"例: {command} --codes 600519,000858",
            exit_code=2,
        )
    if not codes:
        _exit_scan_error(
            fmt,
            code="empty_codes",
            message="--codes 为空",
            hint=f"例: {command} --codes 600519,000858",
            exit_code=2,
        )
    try:
        from kan.storage.watchlist import preload_stock_names

        names = preload_stock_names()
    except Exception as e:
        debug_log(__name__, "preload stock names for scan --codes", e)
        names = {}
    return [(code, names.get(code, code)) for code in codes]


def _parse_scan_periods(raw: str | None, fmt: export.OutputFormat) -> list[int] | None:
    """Parse `kan scan --periods` as a 2-360 integer list."""
    if raw is None:
        return None
    from kan.core.scanner import MAX_PERIOD, MIN_PERIOD

    parts = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
    if not parts:
        _exit_scan_error(
            fmt,
            code="invalid_periods",
            message="--periods 为空",
            hint="例: kan scan --periods 5,20,60,180",
            exit_code=2,
        )
    periods: list[int] = []
    invalid: list[str] = []
    for part in parts:
        try:
            period = int(part)
        except ValueError:
            invalid.append(part)
            continue
        if period < MIN_PERIOD or period > MAX_PERIOD:
            invalid.append(part)
            continue
        periods.append(period)
    if invalid:
        _exit_scan_error(
            fmt,
            code="invalid_periods",
            message=f"--periods 含无效周期: {', '.join(invalid[:5])} · 范围 {MIN_PERIOD}-{MAX_PERIOD}",
            hint="例: kan scan --periods 5,20,60,180",
            exit_code=2,
        )
    return sorted(dict.fromkeys(periods))


def _compact_display_periods(periods: list[int]) -> list[int]:
    """Stable short/mid/long terminal subset for explicit compact scan output."""
    preferred = [5, 20, 30, 60, 180, 360]
    chosen = [p for p in preferred if p in periods]
    if chosen:
        return chosen
    if len(periods) <= 3:
        return periods
    return sorted({periods[0], periods[len(periods) // 2], periods[-1]})


def _sort_scan_results(results: list, sort_key: str, mode: str) -> list:
    """按指定键排序 scan 结果。"""
    key = sort_key.strip().lower()

    def _period_pct(r, period: int) -> float:
        pr = next((p for p in r.periods if p.period == period and not p.insufficient), None)
        return pr.position_pct if pr else 999.0

    if key == "resonance":
        attr = "high_resonance" if mode == "high" else "low_resonance"
        return sorted(results, key=lambda r: getattr(r, attr, 0), reverse=True)
    if key.startswith("pos"):
        try:
            period = int(key[3:])
        except ValueError:
            _print_err(f"⚠️ --sort {sort_key} 无效周期 · 可用: resonance / pos30 / pos60 / pos180 / price / change")
            return results
        return sorted(results, key=lambda r: _period_pct(r, period))
    if key == "price":
        return sorted(results, key=lambda r: r.current_price, reverse=True)
    if key == "change":
        return sorted(results, key=lambda r: getattr(r, "up_days", 0), reverse=True)
    _print_err(f"⚠️ --sort {sort_key} 未知 · 可用: resonance / pos30 / pos60 / pos180 / price / change")
    return results


def _scan_csv(results: list, periods: list[int], mode: str) -> str:
    """将 scan 结果序列化为 CSV 文本（BOM 头兼容 Excel）。"""
    header = ["代码", "名称", "现价"] + [f"{p}日位置%" for p in periods] + ["低点共振", "高点共振"]
    lines = [",".join(header)]
    for r in results:
        cols = [r.symbol, f'"{r.name.replace(" ", "")}"', f"{r.current_price:.2f}"]
        for p in periods:
            pr = next((x for x in r.periods if x.period == p), None)
            cols.append(f"{pr.position_pct:.1f}" if pr and not pr.insufficient else "")
        cols.append(str(r.low_resonance))
        cols.append(str(r.high_resonance))
        lines.append(",".join(cols))
    return "\ufeff" + "\n".join(lines)


def _prepare_scan_render(
    service_result: Any,
    *,
    lifecycle: Any,
    console: Any,
    fmt: export.OutputFormat,
    mode: Literal["low", "high"],
    high: bool,
    signal: bool,
    diff: bool,
    all_stocks: bool,
    only_holdings: bool,
    only_watchlist: bool,
    source_mode: bool,
    code_pairs: list[tuple[str, str]] | None,
    period_list: list[int],
    display_periods: list[int],
    show_context_columns: bool,
    include_external_context: bool,
    sort_key: str | None = None,
) -> Callable[[], None]:
    """在 lifecycle 内准备 scan 输出/快照，返回关闭 Live 后执行的渲染闭包。"""
    from kan.core.models import HotMeta, ThemeMeta
    from kan.core.pipeline import render_freshness_warning
    from kan.core.scanner import compute_diff, load_snapshot, save_snapshot
    from kan.render import terminal
    from kan.render.base import DISCLAIMER

    ctx = service_result.ctx
    board_meta = service_result.meta
    can_write_snapshot = (
        board_meta is None
        and code_pairs is None
        and not all_stocks
        and not only_holdings
    )
    lifecycle.phase("检查扫描结果", target_count=len(ctx.targets))
    if not ctx.targets:
        if all_stocks:
            _exit_scan_error(
                fmt, code="empty_all_stocks", message="全市场股票池为空",
                hint="例: kan config set tushare-token <YOUR_TOKEN>；或稍后重试",
            )
        if only_holdings:
            _exit_scan_error(
                fmt, code="empty_holdings", message="真实持仓为空",
                hint="例: kan hold add 600519 --cost 1680 --shares 100",
            )
        if only_watchlist and not source_mode:
            _exit_scan_error(
                fmt, code="empty_watchlist", message="自选股为空",
                hint="例: kan add 600519 000858",
            )
    if not ctx.results:
        _exit_scan_error(
            fmt, code="data_unavailable", message="无缓存数据",
            hint="例: kan fetch；或 kan scan 自动拉取默认池 K 线",
        )

    all_results = service_result.all_results
    results = service_result.results
    if sort_key:
        results = _sort_scan_results(results, sort_key, mode)
    previous = load_snapshot() if diff and can_write_snapshot else None
    changes = compute_diff(all_results, previous) if previous else []
    lifecycle.phase("构造扫描输出", format=fmt.value, result_count=len(results))

    if signal and not results and fmt is export.OutputFormat.terminal:
        if can_write_snapshot:
            lifecycle.phase("写入扫描快照", result_count=len(all_results))
            save_snapshot(all_results)
        return lambda: console.print("没有股票触及极值区 · 无多周期共振状态")

    title = terminal.scan_title(ctx, high_mode=high, signal_only=signal)
    if fmt is export.OutputFormat.json:
        rendered = export.to_json(export.scan_payload(
            results,
            mode=mode,
            data_cutoff=ctx.freshness.data_cutoff,
            fetched_at=ctx.freshness.fetched_at,
            stale=ctx.freshness.is_stale,
        ))

        def render() -> None:
            typer.echo(rendered)
    elif fmt is export.OutputFormat.csv:
        rendered = _scan_csv(results, period_list, mode)

        def render() -> None:
            typer.echo(rendered)
    elif fmt is export.OutputFormat.md:
        rendered = export.scan_markdown(
            results,
            periods=period_list,
            mode=mode,
            title=title,
            show_context=True,
        )

        def render() -> None:
            typer.echo(rendered)
    else:
        table = terminal.scan_table(
            ctx,
            results,
            display_periods=display_periods,
            high_mode=high,
            signal_only=signal,
            board_index_result=service_result.board_index_result,
            show_context=show_context_columns,
            show_retail_facts=include_external_context,
        )
        is_compact = len(display_periods) < len(period_list)
        is_hot = isinstance(board_meta, HotMeta)

        def render_terminal() -> None:
            from kan.render.terminal_scan import pool_summary_line

            console.print("[dim]💡 慢慢看是观察工具 · 不预测涨跌 · 详见底部免责[/dim]")
            console.print(pool_summary_line(results), highlight=True)
            console.print(table)
            if is_compact:
                shown = "/".join(str(period) for period in display_periods)
                console.print(
                    f"\n  [dim]周期显示: {len(display_periods)}/{len(period_list)}"
                    f"（{shown}日）· 加 --wide 可见全部 · --periods 可自定义[/dim]"
                )
            render_freshness_warning(ctx.freshness, console)
            _render_cutoff_summary(all_results, console)
            if can_write_snapshot and diff and previous:
                if changes:
                    console.print()
                    console.print("[bold]与上次扫描的变化：[/bold]")
                    for symbol, name, _, description in changes:
                        console.print(f"  {name.replace(' ', '')} {symbol} · {description}")
                elif not ctx.freshness.is_stale:
                    console.print("\n  [dim]与上次扫描无变化（同日数据，次日再对比可见变化）[/dim]")
                else:
                    console.print("\n  与上次扫描无变化")
            elif diff and not previous:
                console.print("\n  [dim]首次扫描，无历史对比（下次 --diff 将显示变化）[/dim]")
            console.print()
            if high:
                console.print("[dim]  \\[x%] = 触及高点(≥95%) · 100%=区间最高 · 越高=越接近 N 日最高价[/dim]")
            else:
                console.print("[dim]  \\[x%] = 触及极值 · \\[0%] 触低(≤5%) · \\[100%] 触高(≥95%) · 越低越接近 N 日最低[/dim]")
            if is_hot:
                console.print(
                    "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单\n"
                    "  💡 涨停 / 大幅上涨个股天然在区间高位 · [100%] 是数学结果 不是 「过热信号」[/dim]"
                )
            if isinstance(board_meta, ThemeMeta):
                from kan.render.theme import render_theme_disclaimer

                render_theme_disclaimer()
            else:
                console.print(DISCLAIMER, style="dim")

        render = render_terminal

    if can_write_snapshot:
        lifecycle.phase("写入扫描快照", result_count=len(all_results))
        save_snapshot(all_results)
    return render


@app.command()
def scan(
    symbols: Annotated[
        list[str] | None,
        typer.Argument(help="可选代码列表（逗号/空格分隔）· 例: kan scan 600519,000858"),
    ] = None,
    high: Annotated[bool, typer.Option("--high", help="高点模式（默认低点模式）")] = False,
    signal: Annotated[bool, typer.Option("--signal", "-S", "-s", help="仅显示多周期共振状态")] = False,
    diff: Annotated[bool, typer.Option("--diff", "-d", help="增量模式：显示与上次扫描的变化")] = False,
    exclude_st: Annotated[bool, typer.Option("--exclude-st", help="排除 ST/*ST 股票")] = False,
    exclude_star: Annotated[bool, typer.Option("--exclude-star", help="排除科创板股票")] = False,
    exclude_bj: Annotated[bool, typer.Option("--exclude-bj", help="排除北交所股票")] = False,
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="只扫描指定代码池（逗号/空格/换行分隔；- 从 stdin 读）"),
    ] = None,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="扫指定申万行业全部成分股 · 自选股 ⭐ 高亮"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="扫东财热榜 · rank=人气榜 / surge=飙升榜 · 自选股 ⭐ 高亮"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="扫指定题材全成分股 · 自选 ⭐ 高亮 · 题材 ≠ 行业,一股归多个"),
    ] = None,
    all_stocks: Annotated[
        bool,
        typer.Option("--all", help="扫描 A 股全市场池（约 5500 只；首次会补 K 线缓存，耗时较久）"),
    ] = False,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="只看自选；配合 --industry / --hot / --theme 时取交集"),
    ] = False,
    only_holdings: Annotated[
        bool,
        typer.Option("--only-holdings", help="只扫描真实持仓池"),
    ] = False,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="选自选股分组 (默认 default 组 · 跑 kan group list 查看)"),
    ] = None,
    periods: Annotated[
        str | None,
        typer.Option("--periods", help="计算/展示周期（2-360，逗号或空格分隔）· 例: 5,20,60,180"),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="终端只展示短/中/长关键周期；JSON/Markdown 不受影响"),
    ] = False,
    wide: Annotated[
        bool,
        typer.Option("--wide", help="终端展示全部计算周期，可能超过窄屏宽度；JSON/Markdown 不受影响"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json / csv"),
    ] = export.OutputFormat.terminal,
    sort: Annotated[
        str | None,
        typer.Option("--sort", help="排序：resonance / pos30 / pos60 / pos180 / price / change（默认自选顺序）"),
    ] = None,
) -> None:
    """扫描自选股多周期位置（全景模式 · --group 切换分组）"""
    from rich.console import Console

    from kan.core.scanner import PERIODS
    from kan.render.base import responsive_periods

    console = Console()
    period_list = _parse_scan_periods(periods, fmt) or list(PERIODS)
    if compact and wide:
        _exit_scan_error(
            fmt,
            code="invalid_display_mode",
            message="--compact 与 --wide 不能同时使用",
            hint="例: kan scan --wide；或 kan scan --compact",
            exit_code=2,
        )
    positional_codes = " ".join(symbols or []) or None
    if codes is not None and positional_codes is not None:
        _exit_scan_error(
            fmt,
            code="mutually_exclusive_codes",
            message="位置参数代码 与 --codes 不能同时使用",
            hint="例: kan scan --codes 600519,000858",
            exit_code=2,
        )
    raw_codes = codes if codes is not None else positional_codes
    code_pairs = (
        _resolve_scan_code_pairs(raw_codes, command="kan scan", fmt=fmt)
        if raw_codes else None
    )
    pool_count = sum(1 for x in (industry, hot, theme, code_pairs) if x is not None) + int(all_stocks)
    if pool_count > 1:
        _exit_scan_error(
            fmt,
            code="mutually_exclusive_pool",
            message="--industry / --hot / --theme / --codes / --all 互斥 · 同时只能用一个",
            hint="例: kan scan --all；或 kan scan --industry 半导体；或 kan scan --codes 600519,000858",
            exit_code=2,
        )
    source_mode = (
        industry is not None
        or hot is not None
        or theme is not None
        or code_pairs is not None
        or all_stocks
    )
    if all_stocks and only_watchlist:
        _exit_scan_error(
            fmt,
            code="invalid_all_pool",
            message="--all 与 --only-watchlist 不能同时使用",
            hint="例: kan scan --all",
            exit_code=2,
        )
    if all_stocks and group is not None:
        _exit_scan_error(
            fmt,
            code="invalid_all_pool",
            message="--all 已指定全市场池，不再叠加 --group",
            hint="例: kan scan --all；或 kan scan --group <组名>",
            exit_code=2,
        )
    if all_stocks and diff:
        _exit_scan_error(
            fmt,
            code="invalid_diff_pool",
            message="--diff 仅支持默认池 / 自选池扫描 · 全市场池不写入扫描快照",
            hint="例: kan scan --diff；或 kan scan --all",
            exit_code=2,
        )
    if only_holdings and source_mode:
        _exit_scan_error(
            fmt,
            code="invalid_holdings_pool",
            message="--only-holdings 不能和 --industry / --hot / --theme / --codes / --all 同时使用",
            hint="例: kan scan --only-holdings",
            exit_code=2,
        )
    if only_holdings and group is not None:
        _exit_scan_error(
            fmt,
            code="invalid_holdings_pool",
            message="--only-holdings 已指定真实持仓池，不再叠加 --group",
            hint="例: kan scan --only-holdings",
            exit_code=2,
        )
    if only_holdings and only_watchlist:
        _exit_scan_error(
            fmt,
            code="invalid_holdings_pool",
            message="--only-holdings 与 --only-watchlist 不能同时使用",
            hint="例: kan scan --only-holdings",
            exit_code=2,
        )
    watchlist_pairs = (
        [] if code_pairs is not None or all_stocks or only_holdings or (
            not source_mode and group is None
        ) else (
            _load_watchlist_pairs(group) if source_mode else _get_watchlist_pairs(group)
        )
    )
    if code_pairs is not None and only_watchlist:
        _exit_scan_error(
            fmt,
            code="invalid_codes_pool",
            message="--codes 与 --only-watchlist 不能同时使用",
            hint="例: kan scan --codes 600519,000858",
            exit_code=2,
        )
    if code_pairs is not None and group is not None:
        _exit_scan_error(
            fmt,
            code="invalid_codes_pool",
            message="--codes 已显式指定代码池，不再叠加 --group",
            hint="例: kan scan --codes 600519,000858",
            exit_code=2,
        )
    if code_pairs is not None and diff:
        _exit_scan_error(
            fmt,
            code="invalid_diff_pool",
            message="--diff 仅支持自选股扫描 · 自定义代码池不写入扫描快照",
            hint="例: kan scan --diff；或 kan scan --codes 600519,000858",
            exit_code=2,
        )
    # OOP 路径:CLI 构造 StockSet 再喂 pipeline · meta/highlight/filter 全部由 Set 承担
    from kan.core.pipeline import StockSetResolveError, raise_stock_set_resolve_exit
    from kan.core.stock_set import CodeListSet, from_flags
    from kan.service.scan_service import ScanRequest, run_scan
    mode: Literal["low", "high"] = "high" if high else "low"
    stock_set = (
        CodeListSet(code_pairs)
        if code_pairs is not None else
        from_flags(
            industry=industry, hot=hot, theme=theme,
            watchlist_pairs=watchlist_pairs,
            only_watchlist=only_watchlist,
            watchlist_group=group,
            only_holdings=only_holdings,
            all_stocks=all_stocks,
        )
    )
    if wide or periods is not None:
        display_periods = period_list
    elif compact:
        display_periods = _compact_display_periods(period_list)
    else:
        display_periods = responsive_periods(console.width - 56, period_list)
    show_context_columns = (
        fmt is export.OutputFormat.terminal
        and console.width >= 140
        and not wide
        and periods is None
    )
    include_external_context = (
        fmt is not export.OutputFormat.terminal or show_context_columns
    )
    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter

    reporter = operation_reporter()
    try:
        with operation("扫描股票池", reporter=reporter) as lifecycle:
            service_result = run_scan(
                ScanRequest(
                    stock_set=stock_set,
                    mode=mode,
                    periods=period_list,
                    signal_only=signal,
                    exclude_st=exclude_st,
                    exclude_star=exclude_star,
                    exclude_bj=exclude_bj,
                    show_progress=fmt is export.OutputFormat.terminal,
                    include_external_context=include_external_context,
                ),
                lifecycle=lifecycle,
            )
            render = _prepare_scan_render(
                service_result,
                lifecycle=lifecycle,
                console=console,
                fmt=fmt,
                mode=mode,
                high=high,
                signal=signal,
                diff=diff,
                all_stocks=all_stocks,
                only_holdings=only_holdings,
                only_watchlist=only_watchlist,
                source_mode=source_mode,
                code_pairs=code_pairs,
                period_list=period_list,
                display_periods=display_periods,
                show_context_columns=show_context_columns,
                include_external_context=include_external_context,
                sort_key=sort,
            )
    except StockSetResolveError as e:
        raise_stock_set_resolve_exit(e)
    render()

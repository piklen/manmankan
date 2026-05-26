"""kan find · 用户主导的选股 DSL (v0.0.6.4 MVP)

按用户输入条件 · 在自选/行业/题材/热榜池里筛符合的股票。
"工具仅返回数据 · 不替你判断"

合规(manmankan/docs/compliance.md §7):
- 用户显式指定 filter · 不内置 preset
- 输出 "符合条件的股票" · 不"推荐"
- 强制 disclaimer · 衍生不可删
"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _with_heavy_imports_spinner,
)
from kan.data.hot import HotList

FIND_DISCLAIMER = (
    "[bold dim]候选 ≠ 买入信号 · 工具仅返回符合您设置规则的股票数据 · "
    "不构成任何形式的推荐或建议 · 用户自行评估[/bold dim]"
)


@app.command()
def find(
    pos: Annotated[
        list[str],
        typer.Option(
            "--pos",
            help="位置 filter PERIOD:OP:VAL 例 180:lt:5 (180 日位置 < 5%) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    resonance: Annotated[
        list[str],
        typer.Option(
            "--resonance",
            help="共振 filter LEVEL:OP:VAL 例 low:gte:3 (低点共振 ≥ 3 周期) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    exclude_st: Annotated[
        bool,
        typer.Option("--exclude-st", help="排除 ST/*ST 股票"),
    ] = False,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="池: 申万行业 (例 半导体)"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="池: 东财热榜 rank|surge"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="池: 题材成分股 (例 AI应用)"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option(
            "--only-watchlist",
            help="池仅自选 ∩ industry/hot/theme · 需配合 pool flag",
        ),
    ] = False,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="自选股分组 (默认 default 组)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="输出条数上限 (默认 50)"),
    ] = 50,
) -> None:
    """按你的规则筛股 · 不替你定规则 (v0.0.6.4 MVP)

    示例:
      kan find --pos 180:lt:5                          # 180 日位置 < 5%
      kan find --resonance low:gte:3                   # 低点共振 ≥ 3 周期
      kan find --pos 60:lt:10 --resonance low:gte:2    # 多条件 AND
      kan find --industry 半导体 --pos 180:lt:10       # 半导体里 180 日跌透
      kan find --exclude-st --pos 180:lt:5             # 排 ST + 位置 filter

    Filter MVP (v0.0.6.4):
      --pos PERIOD:OP:VAL    PERIOD 取 3/5/7/10/15/30/60/90/120/180 · OP 取 lt/lte/gt/gte/eq/ne
      --resonance LEVEL:OP:VAL   LEVEL 取 low/high · OP 同上 · VAL 取 [0, 10]
      --exclude-st           排 ST (quiet · 不记 triggered)

    池 selector (跟 kan scan 一致 · 三者互斥):
      --industry NAME / --hot rank|surge / --theme NAME (不指定默认自选)
      --only-watchlist (需配合 pool · 取交集)
      --group GROUP (选自选股具名组)
    """
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.find_dsl import ConditionSet, FilterParseError
        from kan.core.find_filter import apply_conditions
        from kan.core.pipeline import render_freshness_warning, run_data_pipeline
        from kan.core.scanner import scan_batch
        from kan.core.stock_set import from_flags
        from kan.render import terminal
        from kan.render.base import responsive_periods

    console = Console()

    # 1. Parse DSL flags
    try:
        conditions = ConditionSet.from_flags(
            pos=pos,
            resonance=resonance,
            exclude_st=exclude_st,
        )
    except FilterParseError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from e

    if conditions.is_empty():
        _print_err(
            "❌ 至少需要一个 filter (--pos / --resonance / --exclude-st)\n"
            "💡 例: kan find --pos 180:lt:5 (找 180 日位置 < 5% 的股票)"
        )
        raise typer.Exit(1)

    # 2. Validate pool flags (复用 scan 互斥校验)
    if sum(1 for x in (industry, hot, theme) if x is not None) > 1:
        _print_err("❌ --industry / --hot / --theme 三者互斥")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None
    watchlist_pairs = (
        _load_watchlist_pairs(group) if source_mode else _get_watchlist_pairs(group)
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry/--hot/--theme")
        raise typer.Exit(1)

    # 3. Build StockSet · 复用 from_flags
    stock_set = from_flags(
        industry=industry,
        hot=hot,
        theme=theme,
        watchlist_pairs=watchlist_pairs,
        only_watchlist=only_watchlist,
        watchlist_group=group,
    )

    # 4. Fetch + scan (复用 pipeline · low mode 算位置 + 共振)
    ctx = run_data_pipeline(stock_set, compute=scan_batch, mode="low")
    if not ctx.results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    # 5. Apply conditions
    matches = apply_conditions(ctx.results, conditions)

    # 6. Limit output
    matches_limited = matches[:limit]

    # 7. Render
    console.print(
        f"\n[bold]🔍 kan find · {stock_set.name} · "
        f"命中 {len(matches)} / {len(ctx.results)} 只"
        f"{f' · 限 {limit} 显示' if len(matches) > limit else ''}[/bold]"
    )

    if not matches_limited:
        console.print("\n[yellow]  无股票符合您设置的所有 filter[/yellow]")
        console.print(
            "[dim]  💡 尝试放宽条件 · 例 --pos 180:lt:10 替代 --pos 180:lt:5[/dim]"
        )
        render_freshness_warning(ctx.freshness, console)
        console.print()
        console.print(FIND_DISCLAIMER)
        return

    # Reuse scan_table for visual consistency
    results_only = [m.result for m in matches_limited]
    display_periods = responsive_periods(console.width)
    table = terminal.scan_table(
        ctx,
        results_only,
        display_periods=display_periods,
        high_mode=False,
        signal_only=False,
        board_index_result=None,
    )
    console.print("[dim]💡 慢慢看是观察工具 · 不预测涨跌 · 详见底部免责[/dim]")
    console.print(table)

    # Triggered filters audit trail
    console.print()
    console.print("[bold]📋 触发的 filter:[/bold]")
    shown = 0
    for m in matches_limited:
        if not m.triggered:
            continue
        if shown >= 20:
            console.print(f"  [dim](还有 {len(matches_limited) - shown} 只 · 展开请用 --format json)[/dim]")
            break
        trigs = " · ".join(
            f"{t.filter_type}={t.param}@{t.value:.1f}" for t in m.triggered
        )
        console.print(f"  [dim]{m.result.symbol} {m.result.name}[/dim] · {trigs}")
        shown += 1

    render_freshness_warning(ctx.freshness, console)
    console.print()
    console.print(FIND_DISCLAIMER)

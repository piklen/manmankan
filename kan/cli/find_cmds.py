"""kan find · 用户主导的条件筛选 DSL。

按用户输入条件 · 在自选/行业/题材/热榜池里筛符合的股票。
"工具仅返回数据 · 不替你判断"

AI JSON 层 (AI 消费入口):
- `--format json`:命中股票带全维度 metadata (triggered_filters + context + valuation)
- `--format md`:markdown 表格
- 无 filter + `--format json|md`:整池全维度 (= AI 取数环节 · 不带 filter = 数据 provider)
- 强制 disclaimer 字段 (compliance §5/§7 · 衍生不可删 · 测试守护)

合规(manmankan/docs/compliance.md §7):
- 用户显式指定 filter · 不内置筛选策略 preset
- 输出 "符合条件的股票" · 不"推荐"
- 估值/质量/资金/技术/股东等裸值可按用户 filter 输出
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _parse_codes,
    _print_err,
    _with_heavy_imports_spinner,
)
from kan.core.find_registry import (
    dimensions_from_fields,
    format_find_field_presets,
    parse_find_fields,
)
from kan.data.hot import HotList
from kan.data.relative_strength import DEFAULT_RS_INDEX
from kan.service.find_service import (
    FindCodePoolResult,
    FindCrossSectionRequest,
    FindKlineRequest,
    FindKlineResult,
    FindOutputProfile,
    FindServiceError,
    run_find_cross_section,
    run_find_kline,
)
from kan.storage import export

if TYPE_CHECKING:
    from kan.core.find_dsl import ConditionSet


def _resolve_code_pairs_or_exit_json(
    raw: str,
    fmt: export.OutputFormat,
) -> list[tuple[str, str]]:
    """Resolve `kan find --codes`, preserving JSON error envelopes in json mode."""
    import sys

    from kan.infra.log import debug_log

    text = sys.stdin.read() if raw == "-" else raw
    codes, invalid = _parse_codes(text)
    if invalid:
        preview = ", ".join(invalid[:5])
        suffix = "..." if len(invalid) > 5 else ""
        _exit_find_error(
            fmt,
            code="invalid_codes",
            message=f"--codes 含非法代码: {preview}{suffix} · 需 6 位 A 股代码",
            hint="例: kan find --codes 600519,000858 --pos 180:lt:20",
            exit_code=2,
        )
    if not codes:
        _exit_find_error(
            fmt,
            code="empty_codes",
            message="--codes 为空",
            hint="例: kan find --codes 600519,000858 --pos 180:lt:20",
            exit_code=2,
        )
    try:
        from kan.storage.watchlist import load_stock_names_cache

        names = load_stock_names_cache(allow_stale=True) or {}
    except Exception as e:
        debug_log(__name__, "load cached stock names for find --codes", e)
        names = {}
    return [(code, names.get(code, code)) for code in codes]


def _exit_find_error(
    fmt: export.OutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> None:
    """find 专用错误出口 · json 模式输出机器可读 envelope。"""
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.error_payload(
            "find",
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


def _exit_find_service_error(fmt: export.OutputFormat, error: FindServiceError) -> None:
    _exit_find_error(
        fmt,
        code=error.code,
        message=error.message,
        hint=error.hint,
        exit_code=error.exit_code,
    )


def _find_output_profile(
    *,
    fmt: export.OutputFormat,
    compact: bool,
    compact_context: bool,
    field_paths: tuple[str, ...],
    field_dimensions: set[str],
) -> FindOutputProfile:
    return FindOutputProfile(
        mode=fmt.value,
        compact=compact,
        compact_context=compact_context,
        field_paths=field_paths,
        field_dimensions=frozenset(field_dimensions),
    )


def _render_terminal(
    *,
    console,
    stock_set,
    ctx,
    matches,
    matches_limited,
    effective_limit: int,
    find_disclaimer: str,
) -> None:
    """Render terminal output for the K-line path."""
    from kan.core.pipeline import render_freshness_warning
    from kan.render import terminal
    from kan.render.base import responsive_periods

    console.print(
        f"\n[bold]🔍 kan find · {stock_set.name} · "
        f"命中 {len(matches)} / {len(ctx.results)} 只"
        f"{f' · 限 {effective_limit} 显示' if len(matches) > effective_limit else ''}[/bold]"
    )

    if not matches_limited:
        console.print("\n[yellow]  无股票符合您设置的所有 filter[/yellow]")
        console.print(
            "[dim]  💡 尝试放宽条件 · 例: kan find --pos 180:lt:10[/dim]"
        )
        render_freshness_warning(ctx.freshness, console)
        console.print()
        console.print(find_disclaimer)
        return

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

    console.print()
    console.print("[bold]📋 触发的 filter:[/bold]")
    shown = 0
    for m in matches_limited:
        if not m.triggered:
            continue
        if shown >= 20:
            remaining = sum(1 for x in matches_limited[shown:] if x.triggered)
            if remaining > 0:
                console.print(
                    f"  [dim](还有 {remaining} 只命中 · 调小 filter 或减 --limit 看完整)[/dim]"
                )
            break
        trigs = " · ".join(
            f"{t.filter_type}={t.param}@{t.value:.1f}" for t in m.triggered
        )
        console.print(f"  [dim]{m.result.symbol} {m.result.name}[/dim] · {trigs}")
        shown += 1

    render_freshness_warning(ctx.freshness, console)
    console.print()
    console.print(find_disclaimer)


def _run_all_stocks_path(
    *,
    source_mode: bool,
    conditions: ConditionSet,
    field_dimensions: set[str],
    field_paths: tuple[str, ...],
    fmt: export.OutputFormat,
    compact: bool,
    compact_context: bool,
    is_export: bool,
    limit: int | None,
    offset: int,
    sort: tuple[str, str] | None,
    rs_index_code: str,
) -> None:
    """CLI adapter for `kan find --all` cross-section service."""
    output = _find_output_profile(
        fmt=fmt,
        compact=compact,
        compact_context=compact_context,
        field_paths=field_paths,
        field_dimensions=field_dimensions,
    )
    try:
        result = run_find_cross_section(FindCrossSectionRequest(
            conditions=conditions,
            output=output,
            source_mode=source_mode,
            limit=limit,
            offset=offset,
            sort=sort,
            rs_index_code=rs_index_code,
        ))
    except FindServiceError as e:
        _exit_find_service_error(fmt, e)

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.cross_section_payload(
            result.limited,
            query_time=result.query_time,
            pool_size=result.ctx.pool_size,
            matched_total=len(result.matched),
            data_cutoff=result.ctx.data_cutoff,
            stale=result.ctx.stale,
            filters=result.filters,
            match_mode="any" if conditions.match_any else "all",
            compact=compact,
            availability_rows=result.ctx.rows,
            included_dimensions=result.included_dimensions,
            compact_dimensions=result.compact_dimensions,
            fields=field_paths,
            compact_context=compact_context,
        )))
    else:
        typer.echo(export.cross_section_markdown(
            [r for r, _ in result.limited],
            title="慢慢看 · kan find · A股全市场截面",
            pool_size=result.ctx.pool_size,
        ))


def _run_kline_path(
    *,
    code_pairs: list[tuple[str, str]] | None,
    source_mode: bool,
    industry: str | None,
    hot: HotList | None,
    theme: str | None,
    only_watchlist: bool,
    group: str | None,
    conditions: ConditionSet,
    field_dimensions: set[str],
    field_paths: tuple[str, ...],
    fmt: export.OutputFormat,
    compact: bool,
    compact_context: bool,
    is_export: bool,
    limit: int | None,
    offset: int,
    sort: tuple[str, str] | None,
    rs_index_code: str,
    console,
    find_disclaimer: str,
) -> None:
    """CLI adapter for the non-`--all` K-line find service."""
    output = _find_output_profile(
        fmt=fmt,
        compact=compact,
        compact_context=compact_context,
        field_paths=field_paths,
        field_dimensions=field_dimensions,
    )
    try:
        result = run_find_kline(FindKlineRequest(
            conditions=conditions,
            output=output,
            code_pairs=code_pairs,
            industry=industry,
            hot=hot,
            theme=theme,
            only_watchlist=only_watchlist,
            group=group,
            limit=limit,
            offset=offset,
            sort=sort,
            rs_index_code=rs_index_code,
        ))
    except FindServiceError as e:
        _exit_find_service_error(fmt, e)

    if isinstance(result, FindCodePoolResult):
        if fmt is export.OutputFormat.json:
            try:
                payload = export.code_pool_payload(
                    result.code_pairs,
                    query_time=result.query_time,
                    pools=result.pools,
                    fields=field_paths,
                )
            except ValueError as e:
                _exit_find_error(
                    fmt,
                    code="invalid_fields",
                    message=str(e),
                    hint=(
                        "例: kan find --codes 600519,000858 "
                        "--format json --fields code,name"
                    ),
                    exit_code=2,
                )
            typer.echo(export.to_json(payload))
        else:
            typer.echo(export.code_pool_markdown(
                result.code_pairs,
                title=f"慢慢看 · kan find · {result.stock_set.name}",
            ))
        return

    assert isinstance(result, FindKlineResult)

    if is_export:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.find_payload(
                result.entries,
                query_time=result.query_time,
                pools=result.pools,
                filters=result.filters,
                pool_size=len(result.ctx.results),
                matched_total=len(result.matches),
                freshness=result.ctx.freshness,
                match_mode="any" if conditions.match_any else "all",
                compact=compact,
                availability_results=result.pool_results,
                included_dimensions=result.included_dimensions,
                compact_dimensions=result.compact_dimensions,
                fields=field_paths,
                compact_context=compact_context,
            )))
        else:
            typer.echo(export.find_markdown(
                result.entries,
                title=f"慢慢看 · kan find · {result.stock_set.name}",
                pool_size=len(result.ctx.results),
                matched_total=len(result.matches),
            ))
        return

    _render_terminal(
        console=console,
        stock_set=result.stock_set,
        ctx=result.ctx,
        matches=result.matches,
        matches_limited=result.matches_limited,
        effective_limit=result.effective_limit,
        find_disclaimer=find_disclaimer,
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
    match_any: Annotated[
        bool,
        typer.Option("--any", help="任一 filter 命中即返回；默认所有 filter 都需命中"),
    ] = False,
    pe: Annotated[
        list[str],
        typer.Option(
            "--pe",
            help="估值 filter OP:VAL 例 lt:20 (PE TTM < 20 · 裸值筛) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    pb: Annotated[
        list[str],
        typer.Option(
            "--pb",
            help="估值 filter OP:VAL 例 lt:3 (PB < 3 · 裸值筛) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    turnover: Annotated[
        list[str],
        typer.Option(
            "--turnover",
            help="换手率 filter OP:VAL 例 gt:5 (换手 > 5% · 裸值筛) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    market_cap: Annotated[
        list[str],
        typer.Option(
            "--market-cap",
            help="总市值 filter OP:VAL 例 gt:100 (总市值 > 100 亿 · 单位亿元) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    volume_ratio: Annotated[
        list[str],
        typer.Option(
            "--volume-ratio",
            help="量比 filter OP:VAL 例 gt:1.5 (量比 > 1.5 · 裸值筛) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    roe: Annotated[
        list[str],
        typer.Option(
            "--roe",
            help="质量 filter OP:VAL 例 gte:15 (ROE ≥ 15%) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    moneyflow: Annotated[
        list[str],
        typer.Option(
            "--moneyflow",
            help="主力资金 filter OP:VAL 例 gt:0 (近 5 日合计优先 · 单位万元) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    moneyflow_daily: Annotated[
        list[str],
        typer.Option(
            "--moneyflow-daily",
            help="单日主力净额 filter OP:VAL 例 gt:0 (单位万元) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    moneyflow_days: Annotated[
        list[str],
        typer.Option(
            "--moneyflow-days",
            help="连续主力净流入天数 filter OP:VAL 例 gte:3 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rsi: Annotated[
        list[str],
        typer.Option(
            "--rsi",
            help="技术 filter OP:VAL 例 lt:30 (RSI 6 日 · 前复权裸值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    macd_dif: Annotated[
        list[str],
        typer.Option(
            "--macd-dif",
            help="技术 filter OP:VAL 例 gt:0 (MACD DIF 快线) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    macd: Annotated[
        list[str],
        typer.Option(
            "--macd",
            help="技术 filter OP:VAL 例 gt:0 (MACD 柱 · 柱>0=DIF 在 DEA 上方) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    kdj_j: Annotated[
        list[str],
        typer.Option(
            "--kdj-j",
            help="技术 filter OP:VAL 例 lt:20 (KDJ J 值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    streak: Annotated[
        list[str],
        typer.Option(
            "--streak",
            help="情绪 filter OP:VAL 例 gte:3 (连板天数 ≥ 3 · 不含 ST) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    winner: Annotated[
        list[str],
        typer.Option(
            "--winner",
            help="筹码 filter OP:VAL 例 gte:50 (获利盘 ≥ 50%) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    ma_bias: Annotated[
        list[str],
        typer.Option(
            "--ma-bias",
            help="乖离率 filter PERIOD:OP:VAL 例 20:gt:0 (收盘距 20 日线 % · 裸值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    gain: Annotated[
        list[str],
        typer.Option(
            "--gain",
            help="涨幅 filter PERIOD:OP:VAL 例 30:gt:20 (近 30 日涨幅 % · K 线池) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    atr_pct: Annotated[
        list[str],
        typer.Option(
            "--atr-pct",
            help="波动率 filter OP:VAL 例 lt:5 (ATR/close % · 裸值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    up_days: Annotated[
        list[str],
        typer.Option(
            "--up-days",
            help="连阳天数 filter OP:VAL 例 gte:3 (连续阳线数 · K 线池) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rs_index: Annotated[
        list[str],
        typer.Option(
            "--rs-index",
            help="相对大盘 filter PERIOD:OP:VAL 例 30:gt:0 (个股 − 大盘指数 涨幅差% · 跑赢=正) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rs_board: Annotated[
        list[str],
        typer.Option(
            "--rs-board",
            help="相对行业 filter PERIOD:OP:VAL 例 30:gt:0 (个股 − 所属申万一级行业 涨幅差% · 跑赢=正) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rs_index_code: Annotated[
        str,
        typer.Option(
            "--rs-index-code",
            help="--rs-index 对照指数 (默认沪深300 · 支持别名 上证/深成/创业板/沪深300 或 ts_code)",
        ),
    ] = DEFAULT_RS_INDEX,
    holders: Annotated[
        list[str],
        typer.Option(
            "--holders",
            help="股东 filter OP:VAL 例 lt:0 (户数环比减少) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    top10: Annotated[
        list[str],
        typer.Option(
            "--top10",
            help="股东 filter OP:VAL 例 gte:50 (前十大流通集中度%) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    north: Annotated[
        list[str],
        typer.Option(
            "--north",
            help="股东 filter OP:VAL 例 gte:3 (北向持股% · 香港中央结算季度代理) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
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
        int | None,
        typer.Option(
            "--limit",
            help="输出条数上限 (默认 K 线模式 50 · --all 截面模式全量)",
        ),
    ] = None,
    offset: Annotated[
        int,
        typer.Option(
            "--offset",
            help="跳过前 N 条 (配合 --limit 分页 · 默认 0)",
        ),
    ] = 0,
    sort: Annotated[
        str | None,
        typer.Option(
            "--sort",
            help=(
                "排序 FIELD:asc|desc · FIELD 取 "
                "pe/pb/turnover/market-cap/volume-ratio/moneyflow/moneyflow-daily/moneyflow-days · "
                "例 moneyflow:desc"
            ),
        ),
    ] = None,
    all_stocks: Annotated[
        bool,
        typer.Option(
            "--all",
            help="全市场截面取数 ~5500 只 (估值/资金/技术/位置/涨幅/连阳 · 需 token)",
        ),
    ] = False,
    codes: Annotated[
        str | None,
        typer.Option(
            "--codes",
            help="池: 自定义代码列表 (逗号/空格/换行分隔；传 - 从 stdin 读)",
        ),
    ] = None,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式:terminal(默认)/ md / json(AI 消费)"),
    ] = export.OutputFormat.terminal,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help="仅用于 --format json:输出低字段量结果 + data_availability",
        ),
    ] = False,
    compact_context: Annotated[
        bool,
        typer.Option(
            "--compact-context/--no-compact-context",
            help="仅用于 --format json --compact:是否输出位置/共振 K 线上下文",
        ),
    ] = True,
    fields: Annotated[
        list[str],
        typer.Option(
            "--fields",
            help=(
                "仅用于 --format json:字段白名单或 @preset,"
                f"可用 {format_find_field_presets()}"
            ),
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
) -> None:
    """按你的规则筛股 · 不替你定规则。

    示例:
      kan find --pos 180:lt:5                          # 180 日位置 < 5%
      kan find --resonance low:gte:3                   # 低点共振 ≥ 3 周期
      kan find --pos 60:lt:10 --resonance low:gte:2    # 多条件 AND
      kan find --any --pos 20:lt:10 --moneyflow-daily gt:10000  # 任一 filter 命中
      kan find --industry 半导体 --pos 180:lt:10       # 半导体里 180 日位置 < 10%
      kan find --exclude-st --pos 180:lt:5             # 排 ST + 位置 filter
      kan find --industry 半导体 --format json         # 整池全维度 JSON(AI 取数)
      kan find --industry 半导体 --pe lt:30 --moneyflow-daily gt:0  # 估值+资金组合
      kan find --all --pe lt:20 --format json          # 全市场 PE<20 截面筛
      kan find --all --pe lt:20 --format json --compact --no-compact-context
      kan find --all --pe lt:20 --format json --fields @core,@valuation
      kan find --codes 600519,000858 --pos 180:lt:20   # 自定义代码池里筛位置
      printf "600519\n000858\n" | kan find --codes - --gain 30:gt:10
      kan find --all --rsi lt:30 --streak gte:3 --format json  # 全市场 RSI<30 + 连板≥3
      kan find --industry 半导体 --top10 gte:50 --format json  # 半导体里前十大流通集中度≥50%

    Filter:
      单维度 filter 只反映该维度 · 命中不等于整体位置低/高 · 多维度请叠加 filter 或用 kan info 看全周期
      默认所有 filter 都需命中；加 --any 时任一 filter 命中即返回，triggered_filters 记录实际命中项
      核心层:
        --pos PERIOD:OP:VAL    PERIOD 取 2-360 任意整数 · OP 取 lt/lte/gt/gte/eq/ne
        --resonance LEVEL:OP:VAL   LEVEL 取 low/high · OP 同上 · VAL 取 [0, 10]
        --exclude-st           排 ST (quiet · 不记 triggered)
      估值 / 质量 / 资金:
        --pe OP:VAL            PE TTM 裸值筛 · 例 lt:20
        --pb OP:VAL            PB 裸值筛 · 例 lt:3
        --turnover OP:VAL      换手率% 裸值筛 · 例 gt:5
        --market-cap OP:VAL    总市值(亿元)裸值筛 · 例 gt:100
        --volume-ratio OP:VAL  量比裸值筛 · 例 gt:1.5
        --roe OP:VAL           ROE % 裸值筛 · 例 gte:15 · 逐股 · --all 不支持
        --moneyflow OP:VAL     主力净额(万元) · 近 5 日合计优先,缺失回落单日 · 例 gt:0
        --moneyflow-daily OP:VAL  单日主力净额(万元) · 例 gt:0
        --moneyflow-days OP:VAL   连续主力净流入天数 · 例 gte:3
      技术 / 趋势动量（进阶 · 需理解口径）:
        --rsi/--macd-dif/--macd/--kdj-j OP:VAL  技术裸值筛 · 前复权 · 例 --rsi lt:30
        --ma-bias PERIOD:OP:VAL  乖离率 · PERIOD 取 2-360 任意整数 · 例 20:gt:0
        --gain PERIOD:OP:VAL   近 N 日涨幅% · 例 30:gt:20 · K 线池/--all 预计算快照
        --atr-pct OP:VAL       ATR 波动率% · 例 lt:5 (atr/close · 裸值)
        --up-days OP:VAL       连阳天数 · 例 gte:3 · K 线池/--all 预计算快照
      情绪 / 筹码 / 股东（进阶 · 需理解披露与缺数据口径）:
        --streak OP:VAL        连板天数 · 例 gte:3 · 不含 ST
        --winner OP:VAL        获利盘% · 例 gte:50
        --holders OP:VAL       股东户数环比% · 例 lt:0 · 逐股 · --all 不支持
        --top10 OP:VAL         前十大流通集中度% · 例 gte:50 · 逐股 · --all 不支持
        --north OP:VAL         北向持股% · 例 gte:3 (香港中央结算季度代理) · 逐股 · --all 不支持

    输出 (AI JSON 层):
      --format terminal  默认 · Rich 表格 (需至少一个 filter)
      --format json      AI 友好 · 命中带 metadata · 无 filter = 整池取数
      --compact          json 低字段量输出 · 适合脚本/外部模型首轮筛选
      --no-compact-context  compact 不输出 positions/resonance,避免无 K 线 filter 时取快照
      --fields LIST      json 字段白名单或 @preset · 例 @core,@valuation
      --format md        markdown 表格

    池 selector (跟 kan scan 一致 · 三者互斥):
      --industry NAME / --hot rank|surge / --theme NAME (不指定默认自选)
      --codes LIST (逗号/空格/换行分隔 · `--codes -` 从 stdin 读)
      --only-watchlist (需配合 pool · 取交集)
      --group GROUP (选自选股具名组)
    """
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.find_dsl import ConditionSet, FilterParseError
        from kan.render.base import FIND_DISCLAIMER_TEXT

    console = Console()
    find_disclaimer = f"[bold dim]{FIND_DISCLAIMER_TEXT}[/bold dim]"
    is_export = fmt is not export.OutputFormat.terminal
    if compact and fmt is not export.OutputFormat.json:
        _exit_find_error(
            fmt,
            code="invalid_compact",
            message="--compact 仅支持 --format json",
            hint="例: kan find --pos 180:lt:5 --format json --compact",
            exit_code=2,
        )
    if not compact_context and not compact:
        _exit_find_error(
            fmt,
            code="invalid_compact_context",
            message="--no-compact-context 只能和 --format json --compact 一起使用",
            hint="例: kan find --all --pe lt:20 --format json --compact --no-compact-context",
            exit_code=2,
        )
    if fields and fmt is not export.OutputFormat.json:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message="--fields 仅支持 --format json",
            hint="例: kan find --industry 半导体 --format json --fields @core,@valuation",
            exit_code=2,
        )
    if compact and fields:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message="--fields 与 --compact 不能同时使用",
            hint=(
                "二者都定义结果字段形态；需要显式字段时只用 --fields。"
                "例: kan find --format json --fields @core,@valuation"
            ),
            exit_code=2,
        )
    try:
        field_paths = parse_find_fields(fields)
    except ValueError as e:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message=str(e),
            hint="例: --fields @core,@valuation 或 --fields code,name,price",
            exit_code=2,
        )
    field_dimensions = dimensions_from_fields(field_paths)

    # 0. Validate --limit · 防 Python 负切片导致的 silent data loss
    # limit=None 哨兵:K 线模式后续解析为 50 · 截面模式 (--all) 为全量。
    if limit is not None and limit <= 0:
        _exit_find_error(
            fmt,
            code="invalid_limit",
            message="--limit 必须为正整数",
            hint="例: kan find --pos 180:lt:5 --limit 20",
            exit_code=2,
        )

    # 1. Parse DSL flags
    try:
        conditions = ConditionSet.from_flags(
            pos=pos,
            resonance=resonance,
            pe=pe,
            pb=pb,
            turnover=turnover,
            market_cap=market_cap,
            volume_ratio=volume_ratio,
            roe=roe,
            moneyflow=moneyflow,
            moneyflow_daily=moneyflow_daily,
            moneyflow_days=moneyflow_days,
            rsi=rsi,
            macd_dif=macd_dif,
            macd=macd,
            kdj_j=kdj_j,
            streak=streak,
            winner=winner,
            ma_bias=ma_bias,
            gain=gain,
            atr_pct=atr_pct,
            up_days=up_days,
            rs_index=rs_index,
            rs_board=rs_board,
            holders=holders,
            top10=top10,
            north=north,
            exclude_st=exclude_st,
            match_any=match_any,
        )
    except FilterParseError as e:
        _exit_find_error(
            fmt,
            code="invalid_filter",
            message=str(e),
            hint="例: kan find --pos 180:lt:5 或 kan find --resonance low:gte:3",
            exit_code=2,
        )

    # 解析 --sort FIELD:asc|desc → (field, direction) · 校验字段与方向
    sort_spec: tuple[str, str] | None = None
    if sort is not None:
        from kan.service.find_service import SORT_FIELD_GETTERS
        raw_parts = sort.split(":")
        field = raw_parts[0].strip().replace("-", "_")  # market-cap → market_cap
        direction = raw_parts[1].strip().lower() if len(raw_parts) > 1 else "desc"
        if field not in SORT_FIELD_GETTERS:
            _exit_find_error(
                fmt,
                code="invalid_sort",
                message=f"--sort 字段 '{raw_parts[0]}' 不支持",
                hint=f"可选: {', '.join(SORT_FIELD_GETTERS)} · 例: --sort moneyflow:desc",
                exit_code=2,
            )
        if direction not in ("asc", "desc"):
            _exit_find_error(
                fmt,
                code="invalid_sort",
                message=f"--sort 方向 '{direction}' 不支持",
                hint="只支持 asc|desc · 例: --sort pe:asc",
                exit_code=2,
            )
        sort_spec = (field, direction)

    # 无 filter:terminal 默认报错引导 (人类 UX 不变 · 测试守护);
    # json/md 放开 = AI 取数环节 (整池全维度 · 不带 filter = 数据 provider)。
    if conditions.is_empty() and not is_export and not all_stocks:
        _exit_find_error(
            fmt,
            code="missing_filter",
            message="terminal 模式至少需要一个 filter",
            hint=(
                "例: kan find --pos 180:lt:5；kan find --pe lt:20；"
                "取数模式例: kan find --codes 600519,000858 --format json"
            ),
            exit_code=1,
        )

    # 2. Validate pool flags (复用 scan 互斥校验)
    if sum(1 for x in (industry, hot, theme, codes) if x is not None) > 1:
        _exit_find_error(
            fmt,
            code="mutually_exclusive_pool",
            message="--industry / --hot / --theme / --codes 四者互斥",
            hint="例: kan find --industry 半导体 --pos 180:lt:10",
            exit_code=2,
        )
    source_mode = industry is not None or hot is not None or theme is not None or codes is not None
    if codes is not None and only_watchlist:
        _exit_find_error(
            fmt,
            code="invalid_codes_pool",
            message="--codes 与 --only-watchlist 不能同时使用",
            hint="例: kan find --codes 600519,000858 --pos 180:lt:20",
            exit_code=2,
        )
    if codes is not None and group is not None:
        _exit_find_error(
            fmt,
            code="invalid_codes_pool",
            message="--codes 已显式指定候选池，不再叠加 --group",
            hint="例: kan find --codes 600519,000858 --gain 30:gt:10",
            exit_code=2,
        )
    code_pairs = _resolve_code_pairs_or_exit_json(codes, fmt) if codes is not None else None
    if only_watchlist and not source_mode:
        _exit_find_error(
            fmt,
            code="invalid_only_watchlist",
            message="--only-watchlist 需配合 --industry/--hot/--theme",
            hint="例: kan find --industry 半导体 --only-watchlist --pos 180:lt:10",
            exit_code=1,
        )

    # 2.5 全市场截面取数 (--all) · 不走 K 线管线 · 早返回不读自选
    if all_stocks:
        _run_all_stocks_path(
            source_mode=source_mode,
            conditions=conditions,
            field_dimensions=field_dimensions,
            field_paths=field_paths,
            fmt=fmt,
            compact=compact,
            compact_context=compact_context,
            is_export=is_export,
            limit=limit,
            offset=offset,
            sort=sort_spec,
            rs_index_code=rs_index_code,
        )
        return

    _run_kline_path(
        code_pairs=code_pairs,
        source_mode=source_mode,
        industry=industry,
        hot=hot,
        theme=theme,
        only_watchlist=only_watchlist,
        group=group,
        conditions=conditions,
        field_dimensions=field_dimensions,
        field_paths=field_paths,
        fmt=fmt,
        compact=compact,
        compact_context=compact_context,
        is_export=is_export,
        limit=limit,
        offset=offset,
        sort=sort_spec,
        rs_index_code=rs_index_code,
        console=console,
        find_disclaimer=find_disclaimer,
    )

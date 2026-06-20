"""`kan find` service 调用和输出适配。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

from kan.cli.find_io import _exit_find_error, _exit_find_service_error
from kan.data.hot import HotList
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
    console: Any,
    stock_set: Any,
    ctx: Any,
    matches: list[Any],
    matches_limited: list[Any],
    effective_limit: int,
    find_disclaimer: str,
) -> None:
    """渲染 K 线路径的 terminal 输出。"""
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
    """`kan find --all` 全市场截面 service 的 CLI adapter。"""
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
    only_holdings: bool,
    exclude_star: bool,
    exclude_bj: bool,
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
    console: Any,
    find_disclaimer: str,
) -> None:
    """非 `--all` K 线路径 find service 的 CLI adapter。"""
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
            only_holdings=only_holdings,
            exclude_star=exclude_star,
            exclude_bj=exclude_bj,
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

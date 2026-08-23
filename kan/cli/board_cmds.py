"""`kan board` 子命令组 · 板块级资金 / 涨幅 / 位置 / 连续涨跌。"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from kan.app import app
from kan.core.scanner import MAX_PERIOD, MIN_PERIOD
from kan.render.base import DISCLAIMER
from kan.storage import export

board_app = typer.Typer(
    name="board",
    help="板块榜单(行业 / 题材 · 资金 / 涨幅 / 位置 / 连续涨跌)",
    no_args_is_help=True,
)
app.add_typer(board_app, name="board")


class BoardKind(StrEnum):
    industry = "industry"
    theme = "theme"


class BoardMetric(StrEnum):
    moneyflow = "moneyflow"
    gain = "gain"
    pos = "pos"


class BoardTrendSort(StrEnum):
    streak = "streak"
    latest = "latest"
    moneyflow = "moneyflow"


def _fmt_num(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def _rows_payload(rows) -> list[dict]:
    return [
        {
            "kind": r.kind,
            "code": r.code,
            "name": r.name,
            "close": r.close,
            "position_pct": r.position_pct,
            "gain_pct": r.gain_pct,
            "moneyflow_net": r.moneyflow_net,
            "data_date": r.data_date.isoformat() if r.data_date else None,
        }
        for r in rows
    ]


def _markdown(rows, *, title: str) -> str:
    headers = ["排名", "板块", "现价", "位置", "涨幅", "主力净额(万)"]
    md_rows = []
    for idx, r in enumerate(rows, start=1):
        md_rows.append([
            str(idx),
            f"{r.name} {r.code}",
            _fmt_num(r.close),
            _fmt_num(r.position_pct, digits=1, suffix="%"),
            _fmt_num(r.gain_pct, digits=2, suffix="%"),
            _fmt_num(r.moneyflow_net, digits=0),
        ])
    body = export.md_table(headers, md_rows) if md_rows else "_无板块数据_"
    return f"# {title}\n\n{body}\n\n> {DISCLAIMER.strip()}"


def _table(rows, *, title: str) -> Table:
    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("排名", justify="right", style="cyan", min_width=4)
    table.add_column("板块", style="white", no_wrap=True)
    table.add_column("现价", justify="right")
    table.add_column("位置", justify="right")
    table.add_column("涨幅", justify="right")
    table.add_column("主力净额(万)", justify="right")
    for idx, r in enumerate(rows, start=1):
        table.add_row(
            str(idx),
            f"{r.name} {r.code}",
            _fmt_num(r.close),
            _fmt_num(r.position_pct, digits=1, suffix="%"),
            _fmt_num(r.gain_pct, digits=2, suffix="%"),
            _fmt_num(r.moneyflow_net, digits=0),
        )
    return table


@board_app.command("rank")
def rank_cmd(
    kind: Annotated[
        BoardKind,
        typer.Option("--kind", help="板块类型: industry(申万行业) / theme(题材概念)"),
    ] = BoardKind.industry,
    by: Annotated[
        BoardMetric,
        typer.Option("--by", help="排序口径: moneyflow(主力净额) / gain(区间涨幅) / pos(位置分位)"),
    ] = BoardMetric.moneyflow,
    period: Annotated[
        int,
        typer.Option(
            "--period",
            "-p",
            help=f"涨幅 / 位置周期(日，{MIN_PERIOD}-{MAX_PERIOD})",
            min=MIN_PERIOD,
            max=MAX_PERIOD,
        ),
    ] = 30,
    level: Annotated[
        int,
        typer.Option("--level", help="申万行业层级(仅 industry 有效 · 默认一级)", min=1, max=3),
    ] = 1,
    limit: Annotated[
        int,
        typer.Option("--limit", help="显示前 N", min=1, max=500),
    ] = 30,
    force: Annotated[
        bool,
        typer.Option("--force", help="强刷板块 K 线 / 成分股缓存"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式:terminal(默认)/ md / json / csv"),
    ] = export.OutputFormat.terminal,
) -> None:
    """板块级资金 / 涨幅 / 位置榜 · 只展示客观裸值。"""
    from kan.cli.helpers import _print_err
    from kan.data.board_leaderboard import load_board_leaderboard
    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter

    reporter = operation_reporter()

    def _render() -> None:
        pass

    try:
        with operation("板块榜单", reporter=reporter) as lifecycle:
            lifecycle.phase("加载板块数据")
            rows, errors = load_board_leaderboard(
                kind=kind.value,
                metric=by.value,
                period=period,
                level=level,
                limit=None,  # lifecycle 模式下全量拉取，后面再截断
                force=force,
                lifecycle=lifecycle,
            )

            if not rows:
                if fmt is export.OutputFormat.json:
                    typer.echo(export.to_json(export.error_payload(
                        "board_rank",
                        code="data_unavailable",
                        message="板块榜无数据",
                        hint="检查网络 / token / 上游数据源后重试 · 例: kan board rank --kind industry --by moneyflow --format json",
                    )))
                else:
                    _print_err("❌ 板块榜无数据 · 检查网络 / token / 上游数据源后重试")
                raise typer.Exit(1)

            lifecycle.phase("准备输出")
            # CLI limit 裁剪
            shown = rows[:limit]

            kind_label = "申万行业" if kind is BoardKind.industry else "题材概念"
            metric_label = {
                BoardMetric.moneyflow: "主力净额",
                BoardMetric.gain: f"{period}日涨幅",
                BoardMetric.pos: f"{period}日位置",
            }[by]
            title = f"慢慢看 · {kind_label}板块榜 · 按{metric_label}排序"

            if fmt is export.OutputFormat.json:
                payload = export.success_envelope(
                    "board_rank",
                    disclaimer=DISCLAIMER.strip(),
                    stats={
                        "shown": len(shown),
                        "errors_count": len(errors),
                        "period": period,
                    },
                    data_availability={
                        "basis": "board_rank",
                        "pool_size": len(rows),
                    },
                )
                payload.update({
                    "kind": kind.value,
                    "sort": by.value,
                    "period": period,
                    "level": level if kind is BoardKind.industry else None,
                    "shown": len(shown),
                    "errors_count": len(errors),
                    "results": _rows_payload(shown),
                })
                json_str = export.to_json(payload)
                def _render_json() -> None:
                    typer.echo(json_str)
                _render = _render_json
            elif fmt is export.OutputFormat.md:
                md_str = _markdown(shown, title=title)
                def _render_md() -> None:
                    typer.echo(md_str)
                _render = _render_md
            elif fmt is export.OutputFormat.csv:
                import csv
                import io

                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["排名", "板块", "代码", "现价", "位置%", "涨幅%", "主力净额(万)"])
                for idx, r in enumerate(shown, start=1):
                    writer.writerow([
                        str(idx),
                        r.name,
                        r.code,
                        f"{r.close:.2f}" if r.close is not None else "-",
                        f"{r.position_pct:.1f}" if r.position_pct is not None else "-",
                        f"{r.gain_pct:.2f}" if r.gain_pct is not None else "-",
                        f"{r.moneyflow_net:.0f}" if r.moneyflow_net is not None else "-",
                    ])
                csv_str = "\ufeff" + output.getvalue()
                def _render_csv() -> None:
                    typer.echo(csv_str)
                _render = _render_csv
            else:
                console = Console()
                table = _table(shown, title=title)

                def _render_terminal() -> None:
                    console.print(table)
                    if errors:
                        console.print(
                            f"\n[dim]ℹ️  {len(errors)} 个板块数据不完整"
                            " · 可 --force 重试[/dim]"
                        )
                    console.print(DISCLAIMER, style="dim")

                _render = _render_terminal

    except typer.Exit:
        raise

    _render()


def _exit_board_trend_error(
    fmt: export.OutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> None:
    """board trend 在机器输出模式下保持结构化错误信封。"""
    from kan.cli.helpers import _print_err

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.error_payload(
            "board_trend",
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


@board_app.command("trend")
def trend_cmd(
    kind: Annotated[
        BoardKind,
        typer.Option("--kind", help="板块类型: industry(申万行业) / theme(概念题材)"),
    ] = BoardKind.industry,
    up: Annotated[
        int | None,
        typer.Option("--up", help="只看连续上涨 ≥ N 天的板块(1-30)"),
    ] = None,
    down: Annotated[
        int | None,
        typer.Option("--down", help="只看连续下跌 ≥ N 天的板块(1-30)"),
    ] = None,
    min_streak: Annotated[
        int | None,
        typer.Option("--min-streak", help="只看连续涨跌绝对天数 ≥ N 的板块(1-30)"),
    ] = None,
    sort: Annotated[
        BoardTrendSort,
        typer.Option(
            "--sort",
            help="排序口径: streak(连续天数) / latest(最新单日涨幅) / moneyflow(主力净额)",
        ),
    ] = BoardTrendSort.streak,
    latest: Annotated[
        int | None,
        typer.Option("--latest", "-l", help="展示近 N 天每日 ▲▼ 明细(1-30)", min=1, max=30),
    ] = None,
    candle: Annotated[
        bool,
        typer.Option("--candle", "-c", help="阳线阴线口径(默认收盘价较前收口径)"),
    ] = False,
    level: Annotated[
        int,
        typer.Option("--level", help="申万行业层级(仅 industry 有效 · 默认一级)", min=1, max=3),
    ] = 1,
    limit: Annotated[
        int,
        typer.Option("--limit", help="显示前 N(默认 30 · --all 显示全部)", min=1, max=500),
    ] = 30,
    all_: Annotated[
        bool,
        typer.Option("--all", help="显示全部符合条件的板块(无视 --limit)"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="强刷板块指数 K 线缓存"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式:terminal(默认)/ md / json / csv"),
    ] = export.OutputFormat.terminal,
) -> None:
    """把行业或题材指数当作 OHLC 标的，查连续上涨 / 下跌 / 阳线 / 阴线。"""
    if up is not None and down is not None:
        _exit_board_trend_error(
            fmt,
            code="mutually_exclusive_filters",
            message="--up 和 --down 不能同时使用",
            hint="例: kan board trend --kind industry --up 3",
            exit_code=2,
        )
    for name, value in (("--up", up), ("--down", down), ("--min-streak", min_streak)):
        if value is not None and not 1 <= value <= 30:
            _exit_board_trend_error(
                fmt,
                code="invalid_streak_days",
                message=f"{name} 的值必须在 1-30 之间(当前:{value})",
                hint="例: kan board trend --kind theme --up 3",
                exit_code=2,
            )
    if sort is BoardTrendSort.moneyflow and kind is BoardKind.industry and level != 1:
        _exit_board_trend_error(
            fmt,
            code="unsupported_moneyflow_level",
            message="申万行业主力净额当前只支持一级行业",
            hint="改用 --level 1，或将 --sort 改为 streak / latest",
            exit_code=2,
        )

    from rich.console import Console

    from kan.data import boards
    from kan.data.board_trend import (
        board_trend_moneyflow_map,
        load_board_trends,
        sort_board_trends,
    )
    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter
    from kan.render import terminal as render_terminal

    reporter = operation_reporter()

    def _render() -> None:
        pass

    try:
        operation_label = "申万行业趋势榜" if kind is BoardKind.industry else "概念题材趋势榜"
        with operation(operation_label, reporter=reporter) as lifecycle:
            lifecycle.phase("加载板块指数数据")
            try:
                all_results, errors, source, diagnosis = load_board_trends(
                    kind=kind.value,
                    level=level,
                    candle=candle,
                    force=force,
                    lifecycle=lifecycle,
                )
            except (boards.BoardDataUnavailableError, boards.ThemeDataUnavailableError) as exc:
                _exit_board_trend_error(
                    fmt,
                    code="data_unavailable",
                    message=f"{operation_label}不可用: {exc}",
                    hint="检查网络 / token / 上游数据源后重试，或去掉 --force 使用本地缓存",
                )

            if not all_results:
                if kind is BoardKind.theme and diagnosis is not None and fmt is not export.OutputFormat.json:
                    from kan.cli.theme_cmds import _render_failure_diagnosis

                    for line in _render_failure_diagnosis(diagnosis):
                        from kan.cli.helpers import _print_err

                        _print_err(line)
                    raise typer.Exit(1)
                _exit_board_trend_error(
                    fmt,
                    code="data_unavailable",
                    message=f"{operation_label}无可用指数 K 线",
                    hint="检查网络 / token / 上游数据源后重试",
                )

            moneyflow = None
            if sort is BoardTrendSort.moneyflow:
                lifecycle.phase("聚合板块资金")
                moneyflow = board_trend_moneyflow_map(
                    kind.value,
                    all_results,
                    force=force,
                    lifecycle=lifecycle,
                )

            lifecycle.phase("过滤与排序板块趋势")
            sorted_results = sort_board_trends(
                all_results,
                up_filter=up,
                down_filter=down,
                min_streak=min_streak,
                sort_by=sort.value,
                moneyflow=moneyflow,
            )
            shown_results = sorted_results if all_ else sorted_results[:limit]
            total_boards = len(all_results) + len(errors)
            entity_label = "申万行业" if kind is BoardKind.industry else "概念题材"
            data_dates = [
                result.daily_changes[0][0]
                for result in all_results
                if result.daily_changes
            ]
            data_cutoff = max(data_dates) if data_dates else None

            filter_label = ""
            if up is not None:
                filter_label = f" · 连涨≥{up}天"
            elif down is not None:
                filter_label = f" · 连跌≥{down}天"
            if min_streak is not None:
                filter_label += f" · 连续≥{min_streak}天"
            if sort is not BoardTrendSort.streak:
                sort_label = "最新单日涨幅" if sort is BoardTrendSort.latest else "主力净额"
                filter_label += f" · 按{sort_label}排序"

            lifecycle.phase("准备板块趋势输出", result_count=len(shown_results))
            title = render_terminal.theme_leaderboard_title(
                total_themes=total_boards,
                shown=len(shown_results),
                candle=candle,
                filter_label=filter_label,
                errors_count=len(errors),
                entity_label=entity_label,
            )

            if fmt is export.OutputFormat.json:
                payload = export.board_trend_payload(
                    shown_results,
                    kind=kind.value,
                    level=level if kind is BoardKind.industry else None,
                    candle=candle,
                    total_boards=total_boards,
                    errors_count=len(errors),
                    source=source,
                    data_cutoff=data_cutoff,
                    sort_by=sort.value,
                    up=up,
                    down=down,
                    min_streak=min_streak,
                )
                json_str = export.to_json(payload)

                def _render_json() -> None:
                    typer.echo(json_str)

                _render = _render_json
            elif fmt is export.OutputFormat.md:
                markdown = export.board_trend_markdown(
                    shown_results,
                    title=title,
                    latest=latest,
                    entity_label=entity_label,
                )

                def _render_markdown() -> None:
                    typer.echo(markdown)

                _render = _render_markdown
            elif fmt is export.OutputFormat.csv:
                csv_output = export.board_trend_csv(
                    shown_results,
                    latest=latest,
                    entity_label=entity_label,
                )

                def _render_csv() -> None:
                    typer.echo(csv_output)

                _render = _render_csv
            elif not shown_results:
                direction = "上涨" if up is not None else "下跌" if down is not None else "涨跌"
                threshold = up if up is not None else down if down is not None else min_streak
                message = (
                    f"没有连续{direction} ≥{threshold} 天的{entity_label}"
                    if threshold is not None
                    else f"没有符合条件的{entity_label}"
                )

                def _render_empty() -> None:
                    Console().print(message)

                _render = _render_empty
            else:
                console = Console()
                from kan.render.base import max_trend_dates

                actual_latest = (
                    min(latest, max_trend_dates(console.width))
                    if latest is not None
                    else None
                )
                table = render_terminal.theme_leaderboard_table(
                    shown_results,
                    total_themes=total_boards,
                    latest=actual_latest,
                    candle=candle,
                    filter_label=filter_label,
                    errors_count=len(errors),
                    entity_label=entity_label,
                    include_code=True,
                )
                error_names = ", ".join(item.name for item, _ in errors[:10])

                def _render_terminal() -> None:
                    console.print(table)
                    if latest and actual_latest is not None and actual_latest < latest:
                        console.print(
                            f"\n  [dim]窄屏模式 · 显示近 {actual_latest}/{latest} 天"
                            " · 加宽终端可见全部[/dim]"
                        )
                    if not all_ and len(sorted_results) > limit:
                        console.print(
                            f"\n  [dim]显示前 {limit}/{len(sorted_results)}"
                            f" · 看全部:kan board trend --kind {kind.value} --all[/dim]"
                        )
                    if errors:
                        detail = f":{error_names}" if error_names and len(errors) <= 10 else ""
                        console.print(
                            f"\n  [dim]ℹ️  {len(errors)} 个{entity_label}数据不可用{detail}[/dim]"
                        )
                    if candle:
                        console.print(
                            "[dim]  阳线阴线口径:收盘 > 开盘 = ▲"
                            " · 收盘 < 开盘 = ▼ · 平盘不断连续[/dim]"
                        )
                    else:
                        console.print(
                            "[dim]  收盘价口径:今日收盘 > 昨日收盘 = ▲"
                            " · 今日收盘 < 昨日收盘 = ▼ · 平盘不断连续[/dim]"
                        )
                    if kind is BoardKind.theme:
                        from kan.render.theme import render_theme_trend_disclaimer

                        render_theme_trend_disclaimer(source=source)
                    else:
                        console.print(DISCLAIMER, style="dim")

                _render = _render_terminal
    except typer.Exit:
        raise

    _render()

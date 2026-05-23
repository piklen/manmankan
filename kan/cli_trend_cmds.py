"""连续涨跌看板命令：trend。

单独一个文件因为命令逻辑独立（不跟 scan/low/high 共享代码 · 用单独的 trend_batch
算法 + 自己的日期列头逻辑），且日后可能加入更多 trend 衍生命令（如 trend backtest 等）。
"""
from typing import Annotated

import typer

from kan import export
from kan.app import app
from kan.cli_helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)
from kan.hot import HotList


@app.command()
def trend(
    latest: Annotated[int | None, typer.Option("--latest", "-l", help="展示近 N 天走势详情（1-180）", min=1, max=180)] = None,
    down: Annotated[int | None, typer.Option("--down", help="只看连跌≥N天（不带 N 默认 3）")] = None,
    up: Annotated[int | None, typer.Option("--up", help="只看连涨≥N天（不带 N 默认 3）")] = None,
    candle: Annotated[bool, typer.Option("--candle", "-c", help="阳线阴线口径（默认收盘价口径）")] = False,
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
        typer.Option("--theme", help="扫指定题材全成分股 · 自选 ⭐ 高亮"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜/题材(需配合 --industry / --hot / --theme)"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """连续涨跌看板"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import cache_age, data_cutoff_date
        from kan.render import DISCLAIMER, max_trend_dates
        from kan.scanner import trend_batch
        from kan.trading_calendar import (
            PHASE_INTRADAY,
            latest_trade_date,
            market_phase,
        )

    console = Console()
    if sum(1 for x in (industry, hot, theme) if x is not None) > 1:
        _print_err("❌ --industry / --hot / --theme 三者互斥 · 同时只能用一个")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None
    watchlist_pairs = (
        _load_watchlist_pairs() if source_mode else _get_watchlist_pairs()
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry / --hot / --theme 使用")
        raise typer.Exit(1)
    from kan._scan_targets import BoardMeta, HotMeta, ThemeMeta, resolve_scan_targets
    from kan.boards import (
        BoardDataUnavailableError,
        BoardNotFoundError,
        ThemeDataUnavailableError,
        ThemeNotFoundError,
    )
    from kan.hot import HotListUnavailableError
    try:
        targets, board_meta = resolve_scan_targets(
            industry, only_watchlist, watchlist_pairs, hot=hot, theme=theme,
        )
    except BoardNotFoundError:
        _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词")
        raise typer.Exit(1) from None
    except BoardDataUnavailableError:
        _print_err("❌ 行业数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    except HotListUnavailableError:
        _print_err("❌ 热榜数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    except ThemeNotFoundError:
        _print_err(
            f"❌ 未找到题材「{theme}」· 试更短关键词 · 或跑 kan theme search 看候选"
        )
        raise typer.Exit(2) from None
    except ThemeDataUnavailableError:
        _print_err("❌ 题材数据源暂时不可用 · 稍后再试")
        raise typer.Exit(1) from None
    _auto_fetch_stale(targets)
    if down is not None and up is not None:
        _print_err("❌ --down 和 --up 不能同时使用")
        raise typer.Exit(1)
    for name, val in [("--down", down), ("--up", up)]:
        if val is not None and not (2 <= val <= 30):
            _print_err(f"❌ {name} 的值必须在 2-30 之间（当前：{val}）")
            raise typer.Exit(1)

    results = trend_batch(targets, candle=candle)

    if not results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    # 筛选连续涨/跌
    filter_label = ""
    if down is not None:
        results = [r for r in results if r.streak <= -down]
        filter_label = f" · 连跌≥{down}天"
        if not results and fmt is export.OutputFormat.terminal:
            console.print(f"没有连续跌 {down} 天以上的股票")
            return
    elif up is not None:
        results = [r for r in results if r.streak >= up]
        filter_label = f" · 连涨≥{up}天"
        if not results and fmt is export.OutputFormat.terminal:
            console.print(f"没有连续涨 {up} 天以上的股票")
            return

    # v0.0.4.5: 数据截止 / 拉取时间分离展示
    data_cutoff = None
    fetched_at = None
    for r in results:
        d = data_cutoff_date(r.symbol)
        if d is not None and (data_cutoff is None or d > data_cutoff):
            data_cutoff = d
        t = cache_age(r.symbol)
        if t and (fetched_at is None or t > fetched_at):
            fetched_at = t

    expected_cutoff = latest_trade_date()
    is_stale = data_cutoff is None or data_cutoff < expected_cutoff
    phase = market_phase()

    mode_label = "阳线阴线口径" if candle else "收盘价口径"
    title = f"慢慢看 · 连续涨跌看板 · {mode_label}{filter_label}"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    if isinstance(board_meta, BoardMeta):
        title = f"慢慢看 · {board_meta.board.name} 行业连续涨跌 · {mode_label}{filter_label}"
    elif isinstance(board_meta, HotMeta):
        title = f"慢慢看 · {board_meta.list_name} 连续涨跌 · {mode_label}{filter_label}"
    elif isinstance(board_meta, ThemeMeta):
        title = f"慢慢看 · {board_meta.theme.name} 题材连续涨跌 · {mode_label}{filter_label}"

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.trend_payload(
                results, candle=candle, data_cutoff=data_cutoff,
                fetched_at=fetched_at, stale=is_stale,
            )))
        else:
            typer.echo(export.trend_markdown(results, title=title, latest=latest))
        return

    is_hot = isinstance(board_meta, HotMeta)
    rank_map = board_meta.rank_map if is_hot else {}
    base_cols = 5 if is_hot else 4

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white")
    table.add_column("连续", justify="center")
    table.add_column("累计", justify="right")

    # 有 --latest 时加日期列头（新→旧，最近日期在左）
    date_headers: list[str] = []
    if latest and results:
        max_dates = max_trend_dates(console.width)
        actual_latest = min(latest, max_dates)
        ref = results[0]
        days = ref.daily_changes[:actual_latest]
        for date_str, _ in days:
            short = date_str[-5:]  # MM-DD
            date_headers.append(short)
            table.add_column(short, justify="right", min_width=7)

    highlight = board_meta.highlight if board_meta else set()
    for r in results:
        name_short = r.name.replace(" ", "")

        if r.streak < 0:
            streak_text = Text(r.direction, style="bold green")
            cum_text = Text(f"{abs(r.streak_pct):.2f}%", style="green")
        elif r.streak > 0:
            streak_text = Text(r.direction, style="bold red")
            cum_text = Text(f"{abs(r.streak_pct):.2f}%", style="red")
        else:
            streak_text = Text("平", style="dim")
            cum_text = Text("0%", style="dim")

        star = "⭐ " if r.symbol in highlight else ""
        row: list[str | Text] = []
        if is_hot:
            rank = rank_map.get(r.symbol)
            row.append(str(rank) if rank is not None else "-")
        row += [
            f"{star}{name_short} {r.symbol}",
            f"{r.current_price:.2f}",
            streak_text,
            cum_text,
        ]

        if latest:
            from kan.scanner import get_limit_threshold
            limit = get_limit_threshold(r.symbol, r.name)

            days_data = r.daily_changes[:actual_latest]  # 新→旧 · 按终端宽度截取
            for _, chg in days_data:
                abs_chg = abs(chg)
                if chg > 0 and abs_chg >= limit - 0.1:
                    row.append(Text("涨停", style="bold red"))
                elif chg < 0 and abs_chg >= limit - 0.1:
                    row.append(Text("跌停", style="bold green"))
                elif chg > 0:
                    row.append(Text(f"▲{abs_chg:.2f}%", style="red"))
                elif chg < 0:
                    row.append(Text(f"▼{abs_chg:.2f}%", style="green"))
                else:
                    row.append(Text("—", style="dim"))
            # 补齐列数（某些股票交易日可能少）· base_cols 含热榜名次列
            while len(row) < base_cols + len(date_headers):
                row.append(Text("-", style="dim"))

        table.add_row(*row)

    console.print(table)

    if latest and actual_latest < latest:
        console.print(
            f"\n  [dim]窄屏模式 · 显示近 {actual_latest}/{latest} 天"
            " · 加宽终端可见全部[/dim]"
        )

    # ***REMOVED***: 双警告互斥渲染 (if/elif 替代 if/if · 与 scan 一致)
    if is_stale:
        cutoff_str = format_date_compact(data_cutoff) if data_cutoff else "无缓存"
        expected_str = format_date_compact(expected_cutoff)
        days_behind = (expected_cutoff - data_cutoff).days if data_cutoff else "?"
        console.print(
            f"\n  [bold yellow]⚠️ 当前缓存到 {cutoff_str} 收盘 · "
            f"最近交易日是 {expected_str} · 数据滞后 {days_behind} 天\n"
            "   运行 `kan fetch --force` 拉取最新数据[/bold yellow]"
        )
    elif phase == PHASE_INTRADAY:
        console.print(
            "\n  [bold yellow]⚠️ 当前盘中 · 涨跌停标签反映当前时刻 · 非收盘 final\n"
            "   (盘中价格仍在变动 · 涨停/跌停状态可能与收盘不同)\n"
            "   建议盘后 15:30 后看 final 数据[/bold yellow]"
        )

    console.print()
    if candle:
        console.print("[dim]  阳线阴线口径：收盘 > 开盘 = ▲ · 收盘 < 开盘 = ▼ · 平盘不断连续[/dim]")
    else:
        console.print("[dim]  收盘价口径：今日收盘 > 昨日收盘 = ▲ · 今日收盘 < 昨日收盘 = ▼ · 平盘不断连续[/dim]")
    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单[/dim]"
        )
    if isinstance(board_meta, ThemeMeta):
        from kan.render_theme import render_theme_disclaimer
        render_theme_disclaimer()
    else:
        console.print(DISCLAIMER, style="dim")

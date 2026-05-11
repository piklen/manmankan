"""连续涨跌看板命令：trend。

单独一个文件因为命令逻辑独立（不跟 scan/low/high 共享代码 · 用单独的 trend_batch
算法 + 自己的日期列头逻辑），且日后可能加入更多 trend 衍生命令（如 trend backtest 等）。
"""
from typing import Annotated

import typer

from kan.app import app
from kan.cli_helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _print_err,
    _with_heavy_imports_spinner,
)


@app.command()
def trend(
    latest: Annotated[int | None, typer.Option("--latest", "-l", help="展示近 N 天走势详情（1-180）", min=1, max=180)] = None,
    down: Annotated[int | None, typer.Option("--down", help="只看连跌≥N天（不带 N 默认 3）")] = None,
    up: Annotated[int | None, typer.Option("--up", help="只看连涨≥N天（不带 N 默认 3）")] = None,
    candle: Annotated[bool, typer.Option("--candle", "-c", help="阳线阴线口径（默认收盘价口径）")] = False,
) -> None:
    """连续涨跌看板"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import cache_age
        from kan.render import DISCLAIMER, max_trend_dates
        from kan.scanner import trend_batch

    console = Console()
    watchlist_pairs = _get_watchlist_pairs()
    _auto_fetch_stale(watchlist_pairs)
    if down is not None and up is not None:
        _print_err("❌ --down 和 --up 不能同时使用")
        raise typer.Exit(1)
    for name, val in [("--down", down), ("--up", up)]:
        if val is not None and not (2 <= val <= 30):
            _print_err(f"❌ {name} 的值必须在 2-30 之间（当前：{val}）")
            raise typer.Exit(1)

    results = trend_batch(watchlist_pairs, candle=candle)

    if not results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    # 筛选连续涨/跌
    filter_label = ""
    if down is not None:
        results = [r for r in results if r.streak <= -down]
        filter_label = f" · 连跌≥{down}天"
        if not results:
            console.print(f"没有连续跌 {down} 天以上的股票")
            return
    elif up is not None:
        results = [r for r in results if r.streak >= up]
        filter_label = f" · 连涨≥{up}天"
        if not results:
            console.print(f"没有连续涨 {up} 天以上的股票")
            return

    latest_time = None
    for r in results:
        t = cache_age(r.symbol)
        if t:
            latest_time = t

    mode_label = "阳线阴线口径" if candle else "收盘价口径"
    title = f"慢慢看 · 连续涨跌看板 · {mode_label}{filter_label}"
    if latest_time:
        title += f" · {latest_time} 更新"

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
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

        row: list[str | Text] = [
            f"{name_short} {r.symbol}",
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
            # 补齐列数（某些股票交易日可能少）
            while len(row) < 4 + len(date_headers):
                row.append(Text("-", style="dim"))

        table.add_row(*row)

    console.print(table)

    if latest and actual_latest < latest:
        console.print(
            f"\n  [dim]窄屏模式 · 显示近 {actual_latest}/{latest} 天"
            " · 加宽终端可见全部[/dim]"
        )

    console.print()
    if candle:
        console.print("[dim]  阳线阴线口径：收盘 > 开盘 = ▲ · 收盘 < 开盘 = ▼ · 平盘不断连续[/dim]")
    else:
        console.print("[dim]  收盘价口径：今日收盘 > 昨日收盘 = ▲ · 今日收盘 < 昨日收盘 = ▼ · 平盘不断连续[/dim]")
    console.print(DISCLAIMER, style="dim")

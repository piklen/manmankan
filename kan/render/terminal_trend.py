"""trend / theme trend 终端表格渲染。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from kan.infra.formatting import format_date_compact, format_fetched_at_compact

if TYPE_CHECKING:
    from datetime import date

    from kan.core.pipeline import DataCtx
    from kan.core.scanner import TrendResult


# ── trend ─────────────────────────────────────────────────────────────


def trend_title(
    ctx: DataCtx,
    *,
    candle: bool,
    filter_label: str = "",
    max_width: int | None = None,
) -> str:
    """构造 trend 命令标题 · terminal + md export 共用。

    max_width:终端可用宽度 · 与 scan_title 同策略 — 超宽先舍 fetched_at,
    再舍数据截止后缀,避免窄终端标题折行难看。md export 不传 → 完整标题。
    """
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta

    meta = ctx.meta
    data_cutoff = ctx.freshness.data_cutoff
    fetched_at = ctx.freshness.fetched_at
    mode_label = "阳线阴线口径" if candle else "收盘价口径"

    if isinstance(meta, BoardMeta):
        return (
            f"慢慢看 · {meta.board.name} 行业连续涨跌"
            f" · {mode_label}{filter_label}"
        )
    if isinstance(meta, HotMeta):
        return (
            f"慢慢看 · {meta.list_name} 连续涨跌 · {mode_label}{filter_label}"
        )
    if isinstance(meta, ThemeMeta):
        return (
            f"慢慢看 · {meta.theme.name} 题材连续涨跌"
            f" · {mode_label}{filter_label}"
        )
    source_name = getattr(ctx, "source_name", "")
    if source_name == "A股全市场":
        title = f"慢慢看 · {source_name}连续涨跌 · {mode_label}{filter_label}"
    else:
        title = f"慢慢看 · 连续涨跌看板 · {mode_label}{filter_label}"

    from kan.render.base import trim_title_to_width

    # 价值从高到低:数据截止 > 拉取时间
    suffixes: list[str] = []
    if data_cutoff:
        suffixes.append(f" · 数据截止 {format_date_compact(data_cutoff)} 收盘")
    if fetched_at:
        suffixes.append(f" · {format_fetched_at_compact(fetched_at)} 拉取")
    return trim_title_to_width(title, suffixes, max_width)


def trend_table(
    ctx: DataCtx,
    results: list[TrendResult],
    *,
    latest: int | None = None,
    candle: bool = False,
    filter_label: str = "",
    console_width: int | None = None,
) -> Table:
    """连续涨跌看板 · 行=股票 · 列=股票/现价/连续/累计(+ 可选近 N 天明细)。

    Args:
        ctx: 数据流水线产出快照 · 提供 meta(title 分支)+ freshness(cutoff/fetched_at)。
        results: trend_batch 产出后再经 --down/--up 过滤的 TrendResult 列表。
        latest: 已经过 max_trend_dates(console.width) 截断的有效日期列数 ·
                None 或 0 时不加日期列。原 --latest=N 由 caller 截断为窄屏 N′ 后传入。
        candle: 阳线阴线口径 · 影响 mode_label。
        filter_label: " · 连跌≥3天" / " · 连涨≥5天" / "" · caller 构造好传入。
        console_width: 终端宽度 · 传给 trend_title 防窄屏标题折行。
    """
    from kan.core.models import HotMeta

    meta = ctx.meta
    title = trend_title(
        ctx, candle=candle, filter_label=filter_label, max_width=console_width,
    )
    is_hot = isinstance(meta, HotMeta)
    rank_map = meta.rank_map if is_hot else {}
    highlight = meta.highlight if meta else set()
    base_cols = 5 if is_hot else 4

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white")
    table.add_column("连续", justify="center")
    table.add_column("累计", justify="right")

    date_headers: list[str] = []
    if latest and results:
        ref = results[0]
        for date_str, _ in ref.daily_changes[:latest]:
            short = date_str[-5:]
            date_headers.append(short)
            table.add_column(short, justify="right", min_width=7)

    for r in results:
        name_short = r.name.replace(" ", "")

        if r.streak < 0:
            streak_text = Text(r.direction, style="bold green")
            # 显式负号:管道/重定向丢失颜色时方向仍可读
            cum_text = Text(f"-{abs(r.streak_pct):.2f}%", style="green")
        elif r.streak > 0:
            streak_text = Text(r.direction, style="bold red")
            cum_text = Text(f"+{abs(r.streak_pct):.2f}%", style="red")
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
            from kan.core.scanner import get_limit_threshold
            limit = get_limit_threshold(r.symbol, r.name)
            for _, chg in r.daily_changes[:latest]:
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
            while len(row) < base_cols + len(date_headers):
                row.append(Text("-", style="dim"))

        table.add_row(*row)

    return table


# ── 题材榜 leaderboard(`kan theme trend`)───────────────────


def theme_leaderboard_title(
    *,
    total_themes: int,
    shown: int,
    candle: bool,
    filter_label: str = "",
    data_cutoff: date | None = None,
    fetched_at: str | None = None,
    errors_count: int = 0,
) -> str:
    """题材榜标题 · terminal + md export 共用。"""
    mode_label = "阳线阴线口径" if candle else "收盘价口径"
    title = f"慢慢看 · 题材连续涨跌榜 · {mode_label}{filter_label}"
    title += f" · {shown}/{total_themes} 题材"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    if errors_count:
        title += f" · {errors_count} 题材数据不可用"
    return title


def theme_leaderboard_table(
    results: list[TrendResult],
    *,
    total_themes: int,
    latest: int | None = None,
    candle: bool = False,
    filter_label: str = "",
    data_cutoff: date | None = None,
    fetched_at: str | None = None,
    errors_count: int = 0,
) -> Table:
    """题材连续涨跌榜 · 行=题材 · 列=排名/题材/现价/连续/累计(+ 可选近 N 天明细)。

    跟 trend_table(行=股票)结构平行 · 但不带 ⭐ 高亮 / 不带"榜"列(排名是本地排序)。

    Args:
        results: sort_leaderboard 产出的 TrendResult 列表(已过滤 + 排序 + 截断)。
        total_themes: 总题材数(catalog 长度)· 用于标题 "N/391 题材" 文案。
        latest: 已经过 max_trend_dates(console.width) 截断的有效日期列数 ·
                None 或 0 时不加日期列。原 --latest=N 由 caller 截断为窄屏 N′ 后传入。
        candle: 阳线阴线口径 · 影响 mode_label。
        filter_label: " · 连跌≥3天" / " · 连涨≥5天" / "" · caller 构造好传入。
        data_cutoff: 数据截止日 · None 时省略。
        fetched_at: 拉取时间 · None 时省略。
        errors_count: 失败题材数 · > 0 时标题追加提示。
    """
    title = theme_leaderboard_title(
        total_themes=total_themes,
        shown=len(results),
        candle=candle,
        filter_label=filter_label,
        data_cutoff=data_cutoff,
        fetched_at=fetched_at,
        errors_count=errors_count,
    )

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("排名", justify="right", style="cyan", min_width=4)
    table.add_column("题材", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white")
    table.add_column("连续", justify="center")
    table.add_column("累计", justify="right")
    show_moneyflow = any(getattr(r, "moneyflow_net", None) is not None for r in results)
    if show_moneyflow:
        table.add_column("主力净额(万)", justify="right")

    if latest and results:
        ref = results[0]
        for date_str, _ in ref.daily_changes[:latest]:
            short = date_str[-5:]
            table.add_column(short, justify="right", min_width=7)

    for idx, r in enumerate(results, start=1):
        name_short = r.name.replace(" ", "")

        if r.streak < 0:
            streak_text = Text(r.direction, style="bold green")
            # 显式负号:管道/重定向丢失颜色时方向仍可读
            cum_text = Text(f"-{abs(r.streak_pct):.2f}%", style="green")
        elif r.streak > 0:
            streak_text = Text(r.direction, style="bold red")
            cum_text = Text(f"+{abs(r.streak_pct):.2f}%", style="red")
        else:
            streak_text = Text("平", style="dim")
            cum_text = Text("0%", style="dim")

        row: list[str | Text] = [
            str(idx),
            name_short,
            f"{r.current_price:.2f}",
            streak_text,
            cum_text,
        ]
        if show_moneyflow:
            mf = getattr(r, "moneyflow_net", None)
            row.append(f"{mf:,.0f}" if mf is not None else "—")

        if latest:
            for _, chg in r.daily_changes[:latest]:
                abs_chg = abs(chg)
                if chg > 0:
                    row.append(Text(f"▲{abs_chg:.2f}%", style="red"))
                elif chg < 0:
                    row.append(Text(f"▼{abs_chg:.2f}%", style="green"))
                else:
                    row.append(Text("—", style="dim"))

        table.add_row(*row)

    return table

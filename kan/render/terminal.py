"""终端 rich.Table 构建层 · scan/low/high/info/compare/trend 共用。

设计:与 kan/export.py(md/json)对称 · 5 个纯函数 · 吃 model 吐 rich.Table。
命令侧只负责 filter / 网络 / console.print() · 表格结构集中在本模块。

复用 kan/render.py 的 format_pct / responsive_periods / max_trend_dates ·
不重新实现样式逻辑。

字符级一致约束:builder 不改任何 markup / column header / 行格式 ·
任何调整都会被 baseline diff 抓住(见 task 验证步骤)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from kan.cli.helpers import format_date_compact, format_fetched_at_compact
from kan.render.base import format_pct

if TYPE_CHECKING:
    from datetime import date

    from kan.core.models import (
        BoardMeta,
        HotMeta,
        PeriodResult,
        StockScanResult,
        ThemeMeta,
    )
    from kan.core.pipeline import DataCtx
    from kan.core.scanner import TrendResult


# ── 共用 reference label ──────────────────────────────────────────────


def _board_reference_label(
    name: str, meta: BoardMeta | HotMeta | ThemeMeta | None,
) -> str:
    """板块 / 题材指数 reference 行的名称单元格 · scan / low / high 共用。

    industry 模式 → 「🏛️ X 板块指数」 · theme 模式 → 「🎯 X 题材指数」
    单 SOT 化以前 scan_table 内硬编码 🏛️ 的写法,避免 scan 与 low/high 视觉漂移。
    """
    from kan.core.scan_targets import ThemeMeta

    if isinstance(meta, ThemeMeta):
        return f"🎯 {name} 题材指数"
    return f"🏛️ {name} 板块指数"


# ── scan ──────────────────────────────────────────────────────────────


def scan_title(
    ctx: DataCtx,
    *,
    high_mode: bool,
    signal_only: bool = False,
) -> str:
    """构造 scan 命令标题 · 给 terminal table.title + md export 共用 · 单 SOT。"""
    from kan.core.scan_targets import BoardMeta, HotMeta, ThemeMeta

    meta = ctx.meta
    data_cutoff = ctx.freshness.data_cutoff
    fetched_at = ctx.freshness.fetched_at

    if isinstance(meta, BoardMeta):
        return (
            f"慢慢看 · {meta.board.name} 行业位置扫描"
            f" · {'高点' if high_mode else '低点'}模式"
        )
    if isinstance(meta, HotMeta):
        return (
            f"慢慢看 · {meta.list_name} 位置扫描"
            f" · {'高点' if high_mode else '低点'}模式"
        )
    if isinstance(meta, ThemeMeta):
        return (
            f"慢慢看 · {meta.theme.name} 题材位置扫描"
            f" · {'高点' if high_mode else '低点'}模式"
        )
    title = (
        f"慢慢看 · 自选股位置扫描 · "
        f"{'高点' if high_mode else '低点'}模式"
    )
    if signal_only:
        title += " · 仅信号"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    return title


def scan_table(
    ctx: DataCtx,
    results: list[StockScanResult],
    *,
    display_periods: list[int],
    high_mode: bool,
    signal_only: bool = False,
    board_index_result: StockScanResult | None = None,
) -> Table:
    """kan scan 10-周期全景表 · 支持板块指数 row + 热榜名次 + 自选 ⭐ 高亮。

    title 由 ctx.meta(BoardMeta/HotMeta/ThemeMeta/None)+ ctx.freshness 决定 ·
    自选模式带 cutoff/fetched_at 后缀 · 行业/热榜/题材模式标题完全替换不带后缀
    (与 v0.0.5.0 原状一致 · 不改)。

    Args:
        ctx: 数据流水线产出快照 · 提供 meta + freshness。
        results: 已经过 exclude_st / --signal 过滤的展示行。
        display_periods: responsive_periods(console.width) 选出的周期子集。
        high_mode: True=高点模式 / False=低点模式 · 影响标题 + format_pct 色 + 共振取值。
        signal_only: True 时标题追加 " · 仅信号"(仅自选模式生效 · 板块模式忽略)。
        board_index_result: 板块指数 / 题材指数 K 线 scan 结果 · 不为 None 时作为
            第一行 + section 分隔(与 results 区分)。caller 提前算好(scan_stock 是
            重导入 · render 层不应自己调度)。
    """
    from kan.core.scan_targets import HotMeta

    meta = ctx.meta
    title = scan_title(ctx, high_mode=high_mode, signal_only=signal_only)
    is_hot = isinstance(meta, HotMeta)
    highlight = meta.highlight if meta else set()
    rank_map = meta.rank_map if is_hot else {}

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    for p in display_periods:
        table.add_column(f"{p}日", justify="right", min_width=6)
    table.add_column("共振", justify="center")

    if board_index_result is not None:
        brow: list[str | Text] = [
            _board_reference_label(board_index_result.name, meta),
        ]
        brow.append(f"{board_index_result.current_price:.2f}")
        for p in display_periods:
            pr = next(
                (x for x in board_index_result.periods if x.period == p), None,
            )
            brow.append(
                Text("-", style="dim") if pr is None
                else format_pct(pr, high_mode=high_mode),
            )
        brow.append("")
        table.add_row(*brow)
        table.add_section()

    for r in results:
        row: list[str | Text] = []
        if is_hot:
            rank = rank_map.get(r.symbol)
            row.append(str(rank) if rank is not None else "-")
        name_short = r.name.replace(" ", "")
        tag = ""
        if r.limit_up:
            tag = " 涨停"
        elif r.limit_down:
            tag = " 跌停"
        star = "⭐ " if r.symbol in highlight else ""
        row.append(f"{star}{name_short} {r.symbol}{tag}")
        row.append(f"{r.current_price:.2f}")

        for p in display_periods:
            pr = next((x for x in r.periods if x.period == p), None)
            if pr is None:
                row.append(Text("-", style="dim"))
            else:
                row.append(format_pct(pr, high_mode=high_mode))

        resonance = r.high_resonance if high_mode else r.low_resonance
        if resonance >= 3:
            row.append(Text(f"×{resonance}", style="bold yellow"))
        elif resonance > 0:
            row.append(Text(f"×{resonance}", style="yellow"))
        else:
            row.append("")

        table.add_row(*row)

    return table


# ── low / high ────────────────────────────────────────────────────────


def extreme_table(
    period: int,
    hits: list[tuple[StockScanResult, PeriodResult]],
    mode: str,
    *,
    is_hot: bool = False,
    rank_map: dict[str, int] | None = None,
    highlight: set[str] | None = None,
    data_cutoff: date | None = None,
    fetched_at: str | None = None,
    board_index_result: StockScanResult | None = None,
    board_meta: BoardMeta | HotMeta | ThemeMeta | None = None,
) -> Table:
    """kan low / high 单周期表 · 多周期时由 caller 循环逐张调用。

    title 含周期 + 触及数 + 累积 cutoff/fetched_at(caller 在跨周期循环里累积 ·
    与原行为一致 · 数据本身不变只是表头不同)。

    Args:
        period: 当前周期天数(2-360)。
        hits: filter_extreme 产出的 [(StockScanResult, PeriodResult), ...]。
        mode: "low" 或 "high" · 决定标签 + 位置百分比文字色。
        is_hot: True 时加 "榜" 名次列。
        rank_map: 热榜代码 → 名次。is_hot=False 时可 None。
        highlight: 自选股代码集合 · 用于 ⭐ 前缀。
        data_cutoff: 截至本周期累积的最大 cutoff · 影响 title。
        fetched_at: 截至本周期累积的最晚 cache_age · 影响 title。
        board_index_result: 板块 / 题材指数 K 线 scan 结果 · 不为 None 时
            作为首行 + add_section 与 hits 视觉分隔。caller 提前 scan_stock
            产出(传 periods=用户周期 list)· render 层不调度。
        board_meta: 用于选名称前缀(BoardMeta → 🏛️ 板块指数 · ThemeMeta →
            🎯 题材指数)· 当 board_index_result 非 None 时必须配套传入。
    """
    label = "低点" if mode == "low" else "高点"
    signal_style = "bold green" if mode == "low" else "bold yellow"
    rank_map = rank_map or {}
    highlight = highlight or set()

    title = f"慢慢看 · {period} 日{label} · {len(hits)} 只触及"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    table.add_column(f"{period}日最低", justify="right", style="dim", min_width=8)
    table.add_column(f"{period}日最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    if board_index_result is not None:
        # 找出当前 period 对应的 PeriodResult · caller 调 scan_stock 时
        # periods 应当含 period · 但 board K 线行数 < period 时会 insufficient。
        board_pr = next(
            (p for p in board_index_result.periods if p.period == period), None,
        )
        bref: list[str | Text] = []
        if is_hot:  # 兜底 · 当前 hot 无 index_kline · 此分支理论上走不到
            bref.append("-")
        bref.append(_board_reference_label(board_index_result.name, board_meta))
        bref.append(f"{board_index_result.current_price:.2f}")
        if board_pr is None or board_pr.insufficient:
            bref.append("-")
            bref.append("-")
            bref.append(Text("-", style="dim"))
        else:
            bref.append(f"{board_pr.n_low:.2f}")
            bref.append(f"{board_pr.n_high:.2f}")
            # reference 行用普通色不带 [%] · 与 hits 的 [pct%] bold 信号区分
            bref.append(f"{board_pr.position_pct:.1f}%")
        table.add_row(*bref)
        table.add_section()

    for result, pr in hits:
        name_short = result.name.replace(" ", "")
        star = "⭐ " if result.symbol in highlight else ""
        row: list[str | Text] = []
        if is_hot:
            rank = rank_map.get(result.symbol)
            row.append(str(rank) if rank is not None else "-")
        row.append(f"{star}{name_short} {result.symbol}")
        row.append(f"{result.current_price:.2f}")
        row.append(f"{pr.n_low:.2f}")
        row.append(f"{pr.n_high:.2f}")
        row.append(Text(f"[{pr.position_pct:.1f}%]", style=signal_style))
        table.add_row(*row)

    return table


# ── info(单股全周期 / 行业档案 / 题材档案 共用)─────────────────────────


def info_table(
    result: StockScanResult,
    *,
    is_industry: bool = False,
    board_meta: BoardMeta | ThemeMeta | None = None,
) -> Table:
    """4 列全周期位置表 · 周期 / 最低 / 最高 / 位置。

    info(单股) · _info_industry(行业档案) · _info_theme(题材档案)三处共用。
    有一个易错点:单股 info 的 insufficient 位置单元格用 Text("-", style="dim") ·
    industry/theme 档案用普通字符串 "-"。字符级一致约束下两条路径不能合并。

    Args:
        result: scan_stock 产出的 StockScanResult(单股 / 板块指数 / 题材指数)。
        is_industry: True → insufficient 位置单元格用 "-"(industry / theme)。
                     False → insufficient 位置单元格用 Text("-", style="dim")(info)。
        board_meta: 预留 · 当前不参与渲染(future-extension hook)。
    """
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("最低", justify="right", style="dim", min_width=8)
    table.add_column("最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    for pr in result.periods:
        if pr.insufficient:
            if is_industry:
                table.add_row(f"{pr.period}日", "-", "-", "-")
            else:
                table.add_row(
                    f"{pr.period}日", "-", "-", Text("-", style="dim"),
                )
        else:
            table.add_row(
                f"{pr.period}日",
                f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}",
                format_pct(pr),
            )

    return table


# ── compare ───────────────────────────────────────────────────────────


def compare_table(
    results: list[StockScanResult],
    *,
    periods: list[int],
) -> Table:
    """kan compare 转置表 · 指标为行 · 个股为列(最多 8 只)。

    title 硬编码 "慢慢看 · 多股对比" · 不随 cutoff/freshness 变化 · 与原行为一致。

    Args:
        results: 2-8 只 StockScanResult。
        periods: 用户指定的周期列表(已校验过在 PERIODS 内)。
    """
    table = Table(
        title="慢慢看 · 多股对比", show_lines=False, pad_edge=False, padding=(0, 1),
    )
    table.add_column("指标", style="cyan", no_wrap=True)
    for r in results:
        table.add_column(f"{r.name.replace(' ', '')} {r.symbol}", justify="right")

    table.add_row("现价", *[f"{r.current_price:.2f}" for r in results])
    for p in periods:
        cells: list[str | Text] = []
        for r in results:
            pr = next((x for x in r.periods if x.period == p), None)
            cells.append(Text("-", style="dim") if pr is None else format_pct(pr))
        table.add_row(f"{p}日位置", *cells)
    table.add_row("低点共振", *[f"×{r.low_resonance}" for r in results])
    table.add_row("高点共振", *[f"×{r.high_resonance}" for r in results])
    table.add_row("ST", *["是" if r.is_st else "—" for r in results])
    table.add_row(
        "涨跌停",
        *["涨停" if r.limit_up else ("跌停" if r.limit_down else "—") for r in results],
    )
    table.add_row("数据截止", *[format_date_compact(r.scan_date) for r in results])

    return table


# ── trend ─────────────────────────────────────────────────────────────


def trend_title(
    ctx: DataCtx,
    *,
    candle: bool,
    filter_label: str = "",
) -> str:
    """构造 trend 命令标题 · terminal + md export 共用。"""
    from kan.core.scan_targets import BoardMeta, HotMeta, ThemeMeta

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
    title = f"慢慢看 · 连续涨跌看板 · {mode_label}{filter_label}"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    return title


def trend_table(
    ctx: DataCtx,
    results: list[TrendResult],
    *,
    latest: int | None = None,
    candle: bool = False,
    filter_label: str = "",
) -> Table:
    """连续涨跌看板 · 行=股票 · 列=股票/现价/连续/累计(+ 可选近 N 天明细)。

    Args:
        ctx: 数据流水线产出快照 · 提供 meta(title 分支)+ freshness(cutoff/fetched_at)。
        results: trend_batch 产出后再经 --down/--up 过滤的 TrendResult 列表。
        latest: 已经过 max_trend_dates(console.width) 截断的有效日期列数 ·
                None 或 0 时不加日期列。原 --latest=N 由 caller 截断为窄屏 N′ 后传入。
        candle: 阳线阴线口径 · 影响 mode_label。
        filter_label: " · 连跌≥3天" / " · 连涨≥5天" / "" · caller 构造好传入。
    """
    from kan.core.scan_targets import HotMeta

    meta = ctx.meta
    title = trend_title(ctx, candle=candle, filter_label=filter_label)
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


# ── 题材榜 leaderboard(`kan theme trend`)· v0.0.5.7 ───────────────────


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

    if latest and results:
        ref = results[0]
        for date_str, _ in ref.daily_changes[:latest]:
            short = date_str[-5:]
            table.add_column(short, justify="right", min_width=7)

    for idx, r in enumerate(results, start=1):
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
            str(idx),
            name_short,
            f"{r.current_price:.2f}",
            streak_text,
            cum_text,
        ]

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


# ── 历史位置回溯(`kan history`)· v0.0.6.6 ─────────────────────────────


class _HistCell:
    """把快照里的裸 dict 适配成 format_pct 吃的 duck-typed 对象(insufficient=False)。"""

    __slots__ = ("at_high", "at_low", "insufficient", "position_pct")

    def __init__(self, cell: dict):
        self.insufficient = False
        self.at_low = bool(cell.get("at_low"))
        self.at_high = bool(cell.get("at_high"))
        self.position_pct = cell.get("pct", 0.0)


def history_table(
    symbol: str,
    name: str,
    entries: list,
    *,
    period: int,
) -> Table:
    """单只股票位置回溯 · 行=快照日(新→旧)· 列=日期/N日位置/共振/标记。

    纯离线渲染:entries 来自 scanner.load_symbol_history(只读 snapshots/)。
    位置单元格复用 render.base.format_pct(跟 scan 同配色)· 某日缺该周期 → dim 「-」。
    """
    from kan.core.scanner import history_mark

    name_short = name.replace(" ", "")
    title = f"慢慢看 · {name_short} {symbol} · {period}日位置回溯"

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("日期", justify="left", style="white", no_wrap=True)
    table.add_column(f"{period}日位置", justify="right", min_width=7)
    table.add_column("共振", justify="center")
    table.add_column("标记", justify="left")

    for e in entries:
        cell = e.periods.get(period)
        if cell is None:
            pct_text: Text = Text("-", style="dim")
        else:
            pct_text = format_pct(_HistCell(cell))

        res, direction = history_mark(e.periods)
        if res == 0:
            res_text = Text("—", style="dim")
            mark_text = Text("—", style="dim")
        else:
            res_text = Text(f"×{res}", style="bold yellow" if res >= 3 else "")
            arrow = "⬇" if direction == "low" else "⬆"
            color = "green" if direction == "low" else "red"
            if res >= 3:
                word = "多周期低位" if direction == "low" else "多周期高位"
                mark_text = Text(f"{arrow} {word}", style=color)
            else:
                mark_text = Text(arrow, style=color)

        table.add_row(format_date_compact(e.snapshot_date), pct_text, res_text, mark_text)

    return table

"""`kan theme` 子命令组 · 题材发现(list / search)+ 题材榜(trend)。

子命令:
- theme list [--all]    列题材清单(默认拼音前 30 · --all 全部 ~391 + 散户超载警告)
- theme search 关键词    模糊搜题材
- theme trend           题材连续涨跌榜 · K 线走 EM datacenter(不在反爬名单)·
                        并行拉 + 24h cache · streak 算法复用 calc_trend

注:反爬只针对 push2 路径的成分股接口;K 线接口 get_market_concept_east 走
datacenter HTTP · 不在反爬名单 · 并行 16 worker 安全。
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from kan.app import app
from kan.data import boards
from kan.storage import export

theme_app = typer.Typer(
    name="theme",
    help="题材板块管理(同花顺 ~391 个 · 一股归多个 · 标签型分类)",
    no_args_is_help=True,
)
app.add_typer(theme_app, name="theme")

_DEFAULT_LIST_TOP = 30
_DEFAULT_TREND_LIMIT = 30  # 跟 list 默认值对齐 · 散户单屏可读


class ThemeTrendSort(StrEnum):
    streak = "streak"
    latest = "latest"
    moneyflow = "moneyflow"


def _render_failure_diagnosis(diagnosis) -> list[str]:
    """把 LeaderboardDiagnosis 展开成多行用户可读的失败消息(每行一条)。

    设计:透传 TuShare server msg 当 ground truth · 不猜测失败原因
    (猜 "ths_daily 需 2000+ 积分" 被实测打脸 · 真实是频率限速)。
    """
    lines: list[str] = ["❌ 题材榜无数据 · 所有数据源失败", ""]
    lines.append("数据源链路:")

    if diagnosis.tushare_attempted:
        token_label = diagnosis.tushare_token_masked or "***"
        lines.append(f"  ① TuShare Pro (你配了 token {token_label}):")
        lines.append(f"     endpoint: {diagnosis.tushare_endpoint or '(未知)'}")
        if diagnosis.tushare_failed_at == "catalog":
            lines.append("     结果:     ❌ catalog (ths_index) 拉取失败")
        elif diagnosis.tushare_failed_at == "klines":
            lines.append("     结果:     ❌ K 线 (ths_daily) 拉取失败 (catalog 通了)")
        else:
            lines.append("     结果:     ⚠️  状态未知")
        # 透传 server msg · TuShare 官方原文比脑补更权威
        if diagnosis.tushare_error_msg:
            lines.append(f"     server:   code={diagnosis.tushare_error_code} · {diagnosis.tushare_error_msg}")
    else:
        lines.append("  ① TuShare Pro: 未尝试 (没配 token · 跳过)")

    if diagnosis.em_attempted:
        lines.append("  ② AkShare EM (兜底):")
        lines.append(
            f"     结果:     ❌ {diagnosis.em_failed_count}/{diagnosis.em_total} "
            "题材失败 (datacenter 不稳定 · 已知问题)"
        )
    else:
        lines.append("  ② AkShare EM (兜底): 未尝试")

    lines.append("")
    lines.append("可能修复:")
    if diagnosis.tushare_attempted and diagnosis.tushare_failed_at:
        from kan.data.tushare import DEFAULT_ENDPOINT

        code = diagnosis.tushare_error_code
        # 按 server 实际 code 给精准建议 · 替代之前的脑补文案
        if code == 40101:
            # token 不对
            lines.append("  · token 无效 · 检查 https://tushare.pro/user/token 重新复制完整 token")
        elif code == 40203:
            # 频率超限 · 让 server msg "频率超限(X次/小时)" 自解释具体频次
            lines.append("  · 频率超限 · 频次表见 https://tushare.pro/document/1?doc_id=290")
        elif code == 40004:
            lines.append("  · 积分不足 · 充值 https://tushare.pro/user/token")
        elif code is not None and code < 0:
            # -1/-2/-3 = 客户端层 (网络/HTTP/JSON) · 检查 endpoint
            if diagnosis.tushare_endpoint and diagnosis.tushare_endpoint != DEFAULT_ENDPOINT:
                lines.append(f"  · 客户端层失败 · 切回官方端点试试: kan config set tushare-endpoint {DEFAULT_ENDPOINT}")
            else:
                lines.append("  · 客户端层失败 · 检查本机网络 / TuShare 服务状态")
        elif diagnosis.tushare_endpoint and diagnosis.tushare_endpoint != DEFAULT_ENDPOINT:
            # 没拿到 code 但用了自部署代理 · 推切官方
            lines.append(f"  · 切回官方端点试试: kan config set tushare-endpoint {DEFAULT_ENDPOINT}")
        lines.append("  · 关闭 TuShare 走 EM: kan config unset tushare-token")
    elif not diagnosis.tushare_attempted:
        lines.append("  · 配 TuShare 走付费源: kan config set tushare-token <你的_token>")
    lines.append("  · 5-10 分钟后重试 (EM datacenter 通常自愈)")

    return lines


def _pinyin_key(name: str) -> str:
    """简易拼音首字母键 · 仅做排序用 · 中英混排兼容。

    实现:中文字符返回 'z' (排在 ASCII 后面),其他原样。
    完整拼音排序留作后续优化(本版用简易 fallback)。
    """
    if not name:
        return "z"
    first = name[0]
    if first.isascii():
        return first.lower()
    return "z" + name  # 中文统一压到 ASCII 后面 · 内部按中文 unicode 顺序


@theme_app.command("list")
def list_cmd(
    all_: bool = typer.Option(False, "--all", help="显示全部题材(~391 · 散户超载警告)"),
) -> None:
    """列题材清单(默认拼音前 30 · --all 全部)。"""
    try:
        catalog = boards.load_theme_catalog()
    except boards.ThemeDataUnavailableError as e:
        typer.echo(f"❌ 题材清单不可用: {e}", err=True)
        raise typer.Exit(1) from None

    total = len(catalog)
    sorted_catalog = sorted(catalog, key=lambda t: _pinyin_key(t.name))

    if all_:
        typer.echo(f"🎯 题材清单 · 全部 {total} 个(同花顺源)\n")
        display = sorted_catalog
    else:
        typer.echo(f"🎯 题材清单 · {total} 个(同花顺源 · 默认显示前 {_DEFAULT_LIST_TOP} 拼音序)\n")
        display = sorted_catalog[:_DEFAULT_LIST_TOP]

    for t in display:
        size_label = f"({t.size} 只成分股)" if t.size else ""
        typer.echo(f"  {t.code}  {t.name}  {size_label}".rstrip())

    typer.echo("")
    if not all_ and total > _DEFAULT_LIST_TOP:
        typer.echo(f"💡 共 {total} 个题材 · 看全部:kan theme list --all  ·  模糊搜:kan theme search 关键词")
    from kan.render.theme import THEME_CLASSIFICATION, THEME_RISK, THEME_VS_INDUSTRY
    typer.echo(f"💡 {THEME_VS_INDUSTRY}(科大讯飞同属 AI/教育/智慧城市等)")
    typer.echo(f"💡 {THEME_CLASSIFICATION}")
    typer.echo(f"⚠️  {THEME_RISK} · 用工具看位置不等于买卖建议")


@theme_app.command("search")
def search_cmd(
    keyword: str = typer.Argument(..., help="题材关键词(模糊匹配)"),
) -> None:
    """模糊搜题材 · 列所有命中候选。"""
    from kan.data.boards import normalize_theme_name

    if not keyword or not keyword.strip():
        typer.echo(
            "❌ 题材关键词不能为空 · 例: kan theme search AI · 看全部: kan theme list",
            err=True,
        )
        raise typer.Exit(2)

    try:
        catalog = boards.load_theme_catalog()
    except boards.ThemeDataUnavailableError as e:
        typer.echo(f"❌ 题材清单不可用: {e}", err=True)
        raise typer.Exit(1) from None

    k_norm = normalize_theme_name(keyword)
    matches = [t for t in catalog if k_norm in normalize_theme_name(t.name)]

    if not matches:
        typer.echo(f"未找到含「{keyword}」的题材 · 0 个候选")
        return

    typer.echo(f"🔍 搜「{keyword}」· 命中 {len(matches)} 个候选:\n")
    for t in matches[:30]:  # 最多展示 30 候选 · 防刷屏
        typer.echo(f"  {t.code}  {t.name}")
    if len(matches) > 30:
        typer.echo(f"\n  ... 还有 {len(matches) - 30} 个 · 用更具体关键词缩小范围")
    typer.echo("")
    typer.echo("💡 用完整题材名跑扫描:kan scan --theme=AI应用")


@theme_app.command("trend")
def trend_cmd(
    up: Annotated[
        int | None,
        typer.Option("--up", help="只看连涨≥N天的题材(1-30)"),
    ] = None,
    down: Annotated[
        int | None,
        typer.Option("--down", help="只看连跌≥N天的题材(1-30)"),
    ] = None,
    min_streak: Annotated[
        int | None,
        typer.Option("--min-streak", help="只看连续涨跌绝对天数 ≥ N 的题材(1-30)"),
    ] = None,
    sort: Annotated[
        ThemeTrendSort,
        typer.Option("--sort", help="排序口径: streak(连续天数) / latest(最新单日涨幅) / moneyflow(主力净额)"),
    ] = ThemeTrendSort.streak,
    latest: Annotated[
        int | None,
        typer.Option("--latest", "-l", help="展示近 N 天每日 ▲▼ 明细(1-30)", min=1, max=30),
    ] = None,
    candle: Annotated[
        bool,
        typer.Option("--candle", "-c", help="阳线阴线口径(默认收盘价口径)"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help=f"显示前 N(默认 {_DEFAULT_TREND_LIMIT} · --all 全部)", min=1, max=500),
    ] = _DEFAULT_TREND_LIMIT,
    all_: Annotated[
        bool,
        typer.Option("--all", help="显示全部题材(~391 · 无视 --limit)"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="强刷 K 线(忽略 24h cache · 重新拉 391 题材)"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式:terminal(默认)/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """题材连续涨跌榜 · 按 streak 绝对值降序排 · 连涨大的在最上 · 连跌大的在最下。

    示例:
      kan theme trend                # 默认前 30 题材 · 收盘价口径
      kan theme trend --min-streak 1 # 展示刚启动的 1 天连续题材
      kan theme trend --up 3         # 只看连涨 ≥ 3 天
      kan theme trend --sort latest  # 按最新单日涨幅排序
      kan theme trend --sort moneyflow  # 按题材成分股主力净额合计排序
      kan theme trend --down 3       # 只看连跌 ≥ 3 天
      kan theme trend --latest 5     # 近 5 天每日 ▲▼ 明细列
      kan theme trend --all          # 全部 ~391 题材
      kan theme trend --force        # 强刷 K 线 cache
      kan theme trend --format json  # JSON 输出(脚本化)

    数据流:
      load_theme_catalog (24h cache) → 并行 16 worker × fetch_theme_kline (24h cache) →
      calc_trend(close 或 candle 口径) → sort by abs(streak) → 排序后展示前 N。
    """
    from kan.cli.helpers import _print_err

    if up is not None and down is not None:
        _print_err("❌ --up 和 --down 不能同时使用")
        raise typer.Exit(1)
    for name, val in [("--up", up), ("--down", down)]:
        if val is not None and not (1 <= val <= 30):
            _print_err(f"❌ {name} 的值必须在 1-30 之间(当前:{val})")
            raise typer.Exit(1)
    if min_streak is not None and not (1 <= min_streak <= 30):
        _print_err(f"❌ --min-streak 的值必须在 1-30 之间(当前:{min_streak})")
        raise typer.Exit(1)

    from rich.console import Console

    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter

    reporter = operation_reporter()

    def _render() -> None:
        pass

    try:
        with operation("题材趋势榜", reporter=reporter) as lifecycle:
            lifecycle.phase("加载数据模块")
            from kan.data.theme_leaderboard import (
                load_theme_leaderboard,
                sort_leaderboard,
            )
            from kan.render import terminal as render_terminal
            from kan.render.theme import render_theme_trend_disclaimer

            try:
                all_results, errors, source, diagnosis = load_theme_leaderboard(
                    candle=candle,
                    force=force,
                    lifecycle=lifecycle,
                )
            except boards.ThemeDataUnavailableError as e:
                _print_err(f"❌ 题材榜不可用: {e}")
                raise typer.Exit(1) from None

            if not all_results:
                for line in _render_failure_diagnosis(diagnosis):
                    _print_err(line)
                raise typer.Exit(1)

            moneyflow_map = None
            if sort is ThemeTrendSort.moneyflow:
                from kan.core.models import Theme
                from kan.data.board_leaderboard import theme_moneyflow_map

                lifecycle.phase("聚合题材资金")
                moneyflow_map = theme_moneyflow_map(
                    [Theme(code=r.symbol, name=r.name, source="ths") for r in all_results],
                    force=force,
                    lifecycle=lifecycle,
                )

            lifecycle.phase("排序与过滤")
            sorted_results = sort_leaderboard(
                all_results,
                up_filter=up,
                down_filter=down,
                min_streak=min_streak,
                sort_by=sort.value,
                moneyflow=moneyflow_map,
            )

            if not sorted_results:
                def _render_empty() -> None:
                    if up is not None:
                        _print_err(f"没有连续涨 ≥{up} 天的题材")
                    elif down is not None:
                        _print_err(f"没有连续跌 ≥{down} 天的题材")
                    else:
                        _print_err("没有符合条件的题材")
                _render = _render_empty
            else:
                lifecycle.phase("准备输出")
                shown_results = sorted_results if all_ else sorted_results[:limit]
                total_themes = len(all_results) + len(errors)

                filter_label = ""
                if up is not None:
                    filter_label = f" · 连涨≥{up}天"
                elif down is not None:
                    filter_label = f" · 连跌≥{down}天"
                if min_streak is not None:
                    filter_label += f" · 连续≥{min_streak}天"
                if sort is not ThemeTrendSort.streak:
                    sort_label = "最新单日涨幅" if sort is ThemeTrendSort.latest else "主力净额"
                    filter_label += f" · 按{sort_label}排序"

                if fmt is export.OutputFormat.json:
                    payload = export.theme_leaderboard_payload(
                        shown_results,
                        candle=candle,
                        total_themes=total_themes,
                        errors_count=len(errors),
                        data_cutoff=None,
                        fetched_at=None,
                    )
                    json_str = export.to_json(payload)
                    def _render_json() -> None:
                        typer.echo(json_str)
                    _render = _render_json
                elif fmt is export.OutputFormat.md:
                    title = render_terminal.theme_leaderboard_title(
                        total_themes=total_themes,
                        shown=len(shown_results),
                        candle=candle,
                        filter_label=filter_label,
                        data_cutoff=None,
                        fetched_at=None,
                        errors_count=len(errors),
                    )
                    md_str = export.theme_leaderboard_markdown(
                        shown_results, title=title, latest=latest,
                    )
                    def _render_md() -> None:
                        typer.echo(md_str)
                    _render = _render_md
                else:
                    # terminal 渲染 —— 在 lifecycle 内构造，context 外输出
                    console = Console()
                    from kan.render.base import max_trend_dates
                    actual_latest: int | None = None
                    if latest and shown_results:
                        actual_latest = min(latest, max_trend_dates(console.width))

                    table = render_terminal.theme_leaderboard_table(
                        shown_results,
                        total_themes=total_themes,
                        latest=actual_latest,
                        candle=candle,
                        filter_label=filter_label,
                        errors_count=len(errors),
                    )

                    errors_names = ""
                    if errors and len(errors) <= 10:
                        errors_names = ", ".join(t.name for t, _ in errors[:10])

                    def _render_terminal() -> None:
                        console.print(table)

                        if latest and actual_latest is not None and actual_latest < latest:
                            console.print(
                                f"\n  [dim]窄屏模式 · 显示近 {actual_latest}/{latest} 天"
                                " · 加宽终端可见全部[/dim]"
                            )

                        if not all_ and len(sorted_results) > limit:
                            console.print(
                                f"\n  [dim]💡 显示前 {limit}/{len(sorted_results)}"
                                " · 看全部:kan theme trend --all[/dim]"
                            )

                        if errors and len(errors) <= 10:
                            console.print(
                                f"\n  [dim]ℹ️  {len(errors)} 题材数据不可用:{errors_names}[/dim]"
                            )
                        elif errors:
                            console.print(
                                f"\n  [dim]ℹ️  {len(errors)} 题材数据不可用 · 可 --force 重试[/dim]"
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

                        render_theme_trend_disclaimer(source=source)

                    _render = _render_terminal

    except typer.Exit:
        raise

    _render()

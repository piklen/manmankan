import os
import re as _re
from typing import Annotated

import typer

from kan import __version__
from kan.render import DISCLAIMER, format_pct, max_trend_dates, responsive_periods

# 错误消息脱敏 · 防 traceback 泄漏本地路径（home / 绝对路径）
_HOME_PREFIX = os.path.expanduser("~")
_ABS_PATH_PATTERN = _re.compile(r"/[\w/.\-]+/([\w.\-]+)")


def _safe_error_msg(e: Exception, max_len: int = 200) -> str:
    """脱敏异常消息：替换 home 路径为 ~ · 隐藏绝对路径前缀 · 截断超长消息。"""
    msg = str(e)
    if _HOME_PREFIX and _HOME_PREFIX != "/":
        msg = msg.replace(_HOME_PREFIX, "~")
    msg = _ABS_PATH_PATTERN.sub(r"<...>/\1", msg)
    if len(msg) > max_len:
        msg = msg[: max_len - 3] + "..."
    return msg


def _print_err(msg: str) -> None:
    """错误信号写到 stderr · 脚本调用者可 `kan ... 2>/dev/null` 过滤。

    用于 raise typer.Exit(1) 配套的 console 输出 · 与正常表格/数据输出区分。
    """
    from rich.console import Console
    Console(stderr=True).print(msg)


app = typer.Typer(
    name="kan",
    help="慢慢看 · A 股自选股位置感工具",
    invoke_without_command=True,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"kan {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True, help="显示版本号"),
    ] = None,
) -> None:
    """慢慢看 · 看清你的股票正站在历史价格的哪个位置"""
    import sys
    if len(sys.argv) == 1:
        help_cmd()
        raise typer.Exit()


@app.command(name="help")
def help_cmd() -> None:
    """查看命令帮助"""
    from rich.console import Console

    Console().print("""[bold]慢慢看 · 命令速记[/bold]

[bold cyan]自选股管理[/bold cyan]
  kan add 600519 000858     添加自选股（代码）
  kan add 茅台              添加自选股（名称搜索）
  kan remove 600519 茅台    移除自选股（支持多只 + 名称）
  kan list                  查看自选列表
  kan import stocks.csv     CSV 批量导入
  kan clear                 清空自选列表

[bold cyan]位置扫描[/bold cyan]
  kan scan                  全景扫描 10 周期（低点模式）
  kan scan --high           全景扫描 10 周期（高点模式）
  kan scan -S               仅显示有共振信号的股票（--signal）
  kan scan --diff           显示与上次扫描的变化

[bold cyan]低点/高点筛选[/bold cyan]
  kan low 60                谁在 60 日低点？
  kan low 30 60 120         多周期一次看
  kan high 30               谁在 30 日高点？

[bold cyan]单只详情[/bold cyan]
  kan info 600519           单只股票全周期位置 + 涨跌 + 共振

[bold cyan]连续涨跌[/bold cyan]
  kan trend                 连续涨跌看板（不筛选）
  kan trend --down          只看连跌 ≥ 3 天（默认值）
  kan trend --down 5        只看连跌 ≥ 5 天
  kan trend --up            只看连涨 ≥ 3 天（默认值）
  kan trend --up 5          只看连涨 ≥ 5 天
  kan trend --latest 7      展示近 7 天走势详情
  kan trend --candle        阳线阴线口径（默认收盘价口径）

  [dim]以上参数可任意组合：kan trend --down 5 --latest 7 --candle[/dim]
  [dim]N 范围：2-30[/dim]

[bold cyan]数据管理[/bold cyan]
  kan fetch                 拉取数据（通常不需要，scan 自动更新）
  kan fetch --force         强制刷新

[bold cyan]shell 命令补全[/bold cyan] (mac/linux/windows)
  kan completion install    安装补全脚本（自动检测 shell · 之后 kan s<Tab>=kan scan）
  kan completion install zsh  显式指定 shell（zsh/bash/fish/powershell）

[dim]涨跌停自动标记 · ST 默认显示，kan scan --exclude-st 可排除[/dim]
""")


def _load_names_with_optional_spinner(console) -> dict[str, str]:
    """加载 A 股代码表 · 缓存过期时 spinner 包住 watchlist 重 import + preload。

    设计要点：fresh 检查走极轻的 kan.paths（~370μs）· spinner 提前到 watchlist
    重模块（akshare lazy 后约 ~40ms 热启动 / ~1-2s 冷启动）import 之前显示，
    避免按回车后用户面对一段 silent 期。
    """
    import time as _time

    from kan.paths import is_stock_names_cache_fresh
    cache_fresh = is_stock_names_cache_fresh()

    if cache_fresh:
        from kan.watchlist import preload_stock_names
        return preload_stock_names()

    t_start = _time.monotonic()
    with console.status(
        "[yellow]⏳ 正在加载 A 股代码表 (首次约 5-15s · 后续 7 天内秒级)...[/yellow]",
        spinner="dots",
    ):
        from kan.watchlist import preload_stock_names
        names = preload_stock_names()
    elapsed = _time.monotonic() - t_start
    console.print(f"[green]✅ A 股代码表加载完成 · 用时 {elapsed:.1f}s[/green]")
    return names


@app.command()
def add(
    symbols: Annotated[list[str], typer.Argument(help="股票代码或名称（如 600519 茅台）")],
) -> None:
    """添加自选股（支持代码或名称搜索）"""
    import time as _time

    batch = len(symbols) > 1

    from rich.console import Console
    # spinner 写 stderr · 防被 baostock 内部 stdout/stderr 重定向干扰 ·
    # tqdm/login banner 抑制已下沉到 watchlist.py 各 _fetch_* 函数内部 self-suppress
    _console = Console(stderr=True)

    names = _load_names_with_optional_spinner(_console)

    # watchlist 已被 helper 加载到 sys.modules · 第二次 import 是 dict 查找
    from kan.watchlist import (
        add_stock,
        load_watchlist,
        save_watchlist,
        search_by_name,
    )

    wl = load_watchlist()
    changed = False
    success, skip, fail = 0, 0, 0
    failures: list[str] = []  # 失败累积到末尾打印 · 防止打断 spinner / 进度反馈

    # 大批量提示（≥ 20 只）· 单行 spinner 提示 · add 主循环本身极快（< 1s 处理 200 只）
    add_start = _time.monotonic()
    use_batch_spinner = len(symbols) >= 20

    if use_batch_spinner:
        spinner_ctx = _console.status(
            f"[cyan]正在添加 {len(symbols)} 只股票...[/cyan]",
            spinner="dots",
        )
    else:
        spinner_ctx = _NoopContext()

    with spinner_ctx:
        for sym in symbols:
            cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", sym.strip())
            if _re.match(r"^\d{6}$", cleaned):
                if wl.find(cleaned):
                    if not batch:
                        typer.echo(f"  {cleaned} 已在自选列表中")
                    skip += 1
                    continue
                name = names.get(cleaned)
                if not name:
                    failures.append(f"未找到股票: {cleaned}（不在 A 股代码表中）")
                    fail += 1
                    continue
                add_stock(wl, cleaned, name)
                changed = True
                if not use_batch_spinner:
                    typer.echo(f"  ✅ 已添加 {name.replace(' ', '')} ({cleaned})")
                success += 1
            else:
                matches = search_by_name(sym, _names_cache=names)
                if len(matches) == 1:
                    code, _name = matches[0]
                    if wl.find(code):
                        if not batch:
                            typer.echo(f"  {code} 已在自选列表中")
                        skip += 1
                    else:
                        add_stock(wl, code, _name)
                        changed = True
                        if not use_batch_spinner:
                            typer.echo(f"  ✅ 已添加 {_name.replace(' ', '')} ({code})")
                        success += 1
                elif len(matches) == 0:
                    failures.append(f"未找到包含「{sym}」的股票")
                    fail += 1
                else:
                    # 多匹配也累积末尾 · 不打断 spinner
                    failures.append(
                        f"「{sym}」匹配到 {len(matches)} 只 · 请用更精确名称或代码"
                    )
                    fail += 1

    add_elapsed = _time.monotonic() - add_start

    if changed:
        save_watchlist(wl)

    # 末尾汇总：先打失败列表（如果有）· 再打统计
    if batch:
        if failures:
            for f in failures:
                typer.echo(f"  ❌ {f}", err=True)
        parts = []
        if success:
            parts.append(f"成功 {success}")
        if skip:
            parts.append(f"跳过 {skip}")
        if fail:
            parts.append(f"失败 {fail}")
        time_part = f" · 用时 {add_elapsed:.1f}s" if add_elapsed >= 0.5 else ""
        typer.echo(f"  添加完成 · {' · '.join(parts)}{time_part}")


class _NoopContext:
    """No-op context manager · 跟 console.status 接口对齐 · 用于小量场景跳过 spinner。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@app.command()
def remove(
    symbols: Annotated[list[str], typer.Argument(help="股票代码或名称（支持多只）")],
) -> None:
    """移除自选股（支持代码或名称 · 多只批量删除）"""
    from kan import watchlist as wl

    for sym in symbols:
        cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", sym.strip())
        if _re.match(r"^\d{6}$", cleaned):
            try:
                _, msg = wl.remove(sym)
                typer.echo(f"  {msg}")
            except ValueError as e:
                typer.echo(f"  ❌ {e}", err=True)
        else:
            current = wl.load_watchlist()
            matches = [(s.symbol, s.name) for s in current.stocks if sym in s.name.replace(" ", "")]
            if len(matches) == 1:
                code, name = matches[0]
                _, msg = wl.remove(code)
                typer.echo(f"  已移除 {name.replace(' ', '')} ({code})")
            elif len(matches) == 0:
                typer.echo(f"  ❌ 自选列表中没有包含「{sym}」的股票", err=True)
            else:
                typer.echo(f"  「{sym}」匹配到 {len(matches)} 只自选股：")
                for code, name in matches:
                    typer.echo(f"    {code} {name.replace(' ', '')}")
                typer.echo("    请用代码精确移除")


@app.command(name="list")
def list_stocks() -> None:
    """查看自选列表"""
    from rich.console import Console
    from rich.table import Table

    from kan.watchlist import list_all

    stocks = list_all()
    if not stocks:
        typer.echo("自选列表为空 · 请先 `kan add <代码>` 添加")
        return

    table = Table(title=f"自选股列表 · 共 {len(stocks)} 只")
    table.add_column("代码", style="cyan")
    table.add_column("名称", style="white")
    table.add_column("添加日期", style="dim")

    for s in stocks:
        table.add_row(s.symbol, s.name.replace(" ", ""), str(s.added_at))

    Console().print(table)


@app.command(name="import")
def import_csv(
    path: Annotated[str, typer.Argument(help="CSV 文件路径")],
) -> None:
    """从 CSV 批量导入自选股"""
    from kan.watchlist import import_csv as do_import

    try:
        success, skipped, errors = do_import(path)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"  ❌ {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"导入完成：✅ 新增 {success} · ⏭ 跳过 {skipped} · ❌ 失败 {len(errors)}")
    for err in errors:
        typer.echo(f"  ❌ {err}", err=True)


@app.command()
def fetch(
    symbols: Annotated[list[str] | None, typer.Argument(help="股票代码（留空则拉取全部自选）")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="强制刷新（忽略缓存）")] = False,
) -> None:
    """拉取股票历史 K 线数据"""
    from kan.fetcher import fetch_kline, is_fresh

    if not symbols:
        from kan.watchlist import load_watchlist
        wl = load_watchlist()
        if not wl.stocks:
            typer.echo("自选列表为空 · 请先 `kan add <代码>` 添加", err=True)
            raise typer.Exit(1)
        symbols = [s.symbol for s in wl.stocks]

    success = 0
    for sym in symbols:
        if not force and is_fresh(sym):
            typer.echo(f"  {sym} 已是最新（今日已拉取）")
            success += 1
            continue
        try:
            df = fetch_kline(sym, force=force)
            typer.echo(f"  ✅ {sym} 拉取成功（{len(df)} 条 K 线）")
            success += 1
        except Exception as e:
            typer.echo(f"  ❌ {sym} 拉取失败：{_safe_error_msg(e)}", err=True)



def _get_watchlist_pairs() -> list[tuple[str, str]]:
    from kan.watchlist import load_watchlist
    wl = load_watchlist()
    if not wl.stocks:
        typer.echo("自选列表为空 · 请先 `kan add <代码>` 添加", err=True)
        raise typer.Exit(1)
    return [(s.symbol, s.name) for s in wl.stocks]


_NETWORK_ERR_KEYWORDS = (
    "Max retries",
    "Timeout",
    "HTTPSConnection",
    "HTTPConnection",
    "ConnectionError",
    "ConnectionResetError",
    "Read timed out",
    "URLError",
    "RemoteDisconnected",
    "Failed to establish",
)


def _network_error_msg(err: str) -> str:
    """把网络异常 traceback 简化为用户友好提示。

    避免暴露 host / port / query 参数等内部细节。
    """
    if any(k in err for k in _NETWORK_ERR_KEYWORDS):
        return "网络异常 · 请检查连接或稍后重试"
    if "无效股票代码或无数据" in err:
        return "无数据（可能停牌 / 退市）"
    return _safe_error_msg(ValueError(err), max_len=60)


def _auto_fetch_stale(pairs: list[tuple[str, str]]) -> None:
    """自动拉取缺失或过期（非今天）的自选股数据。

    并发 5 + rich.Progress 进度条 + 网络异常友好提示。
    避免串行 172 只可能阻塞 ≥ 9 分钟无反馈的体验问题。
    """
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from kan.fetcher import fetch_batch, is_fresh

    stale = [(sym, name) for sym, name in pairs if not is_fresh(sym)]
    if not stale:
        return

    console = Console()
    n = len(stale)

    # 大量股票时给出明确预期 · 避免用户以为卡死
    if n >= 30:
        est_low = max(1, n // 60)
        est_high = max(2, n // 20)
        console.print(
            f"[yellow]需更新 {n} 只股票数据 · 并发 5 · "
            f"预计 {est_low}-{est_high} 分钟[/yellow]"
        )
    elif n > 5:
        console.print(f"[yellow]更新 {n} 只股票数据...[/yellow]")

    name_map = dict(stale)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[dim]({task.completed}/{task.total})[/dim]"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("更新中", total=n)

        def _on_done(symbol: str, ok: bool, _err_msg: str | None) -> None:
            name = name_map.get(symbol, symbol).replace(" ", "")
            desc = f"更新中 · 最近: {name}" if ok else f"更新中 · 失败: {name}"
            progress.update(task_id, advance=1, description=desc)

        try:
            results, errors = fetch_batch(
                [s for s, _ in stale],
                force=True,
                max_workers=5,
                on_progress=_on_done,
            )
        except KeyboardInterrupt:
            progress.stop()
            console.print("\n  [yellow]已中断 · 已完成的数据已保存[/yellow]")
            import os as _os
            _os._exit(130)

    # 汇总输出
    success_count = len(results)
    if errors:
        console.print(
            f"  [green]✅ 成功 {success_count}[/green] · "
            f"[red]❌ 失败 {len(errors)}[/red]"
        )
        for i, (sym, raw_err) in enumerate(errors.items()):
            if i >= 5:
                console.print(
                    f"  [dim]...及 {len(errors) - 5} 只失败 · "
                    f"`kan fetch` 重试[/dim]"
                )
                break
            name = name_map.get(sym, sym).replace(" ", "")
            console.print(
                f"  [red]· {name} ({sym}) · {_network_error_msg(raw_err)}[/red]"
            )
    else:
        console.print(f"  [green]✅ {success_count} 只全部更新完成[/green]")
    console.print()




@app.command()
def scan(
    high: Annotated[bool, typer.Option("--high", help="高点模式（默认低点模式）")] = False,
    signal: Annotated[bool, typer.Option("--signal", "-S", "-s", help="仅显示有共振信号的股票")] = False,
    diff: Annotated[bool, typer.Option("--diff", "-d", help="增量模式：显示与上次扫描的变化")] = False,
    exclude_st: Annotated[bool, typer.Option("--exclude-st", help="排除 ST/*ST 股票")] = False,
) -> None:
    """扫描自选股多周期位置（10 周期全景模式）"""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from kan.fetcher import cache_age
    from kan.scanner import (
        PERIODS,
        compute_diff,
        load_snapshot,
        save_snapshot,
        scan_batch,
    )

    console = Console()
    watchlist_pairs = _get_watchlist_pairs()
    _auto_fetch_stale(watchlist_pairs)
    mode = "high" if high else "low"

    prev_snapshot = load_snapshot() if diff else None

    # P1-8: 单次 scan_batch · 后续 filter / diff / snapshot 都用 all_results · 避免重复调用
    all_results = scan_batch(watchlist_pairs, mode=mode)

    if not all_results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    results = all_results
    if exclude_st:
        results = [r for r in results if not r.is_st]

    if signal:
        if mode == "high":
            results = [r for r in results if r.high_resonance > 0]
        else:
            results = [r for r in results if r.low_resonance > 0]
        if not results:
            console.print("没有股票触及极值区 · 无共振信号")
            save_snapshot(all_results)
            return

    from datetime import date as date_cls
    latest_time = None
    data_is_today = True
    for r in results:
        t = cache_age(r.symbol)
        if t:
            latest_time = t
            if not t.startswith(str(date_cls.today())):
                data_is_today = False

    title = f"慢慢看 · 自选股位置扫描 · {'高点' if high else '低点'}模式"
    if signal:
        title += " · 仅信号"
    if latest_time:
        title += f" · {latest_time} 更新"

    display_periods = responsive_periods(console.width)
    is_compact = len(display_periods) < len(PERIODS)

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    for p in display_periods:
        table.add_column(f"{p}日", justify="right", min_width=6)
    table.add_column("共振", justify="center")

    for r in results:
        row: list[str | Text] = []
        name_short = r.name.replace(" ", "")
        tag = ""
        if r.limit_up:
            tag = " 涨停"
        elif r.limit_down:
            tag = " 跌停"
        row.append(f"{name_short} {r.symbol}{tag}")
        row.append(f"{r.current_price:.2f}")

        for p in display_periods:
            pr = next((x for x in r.periods if x.period == p), None)
            if pr is None:
                row.append(Text("-", style="dim"))
            else:
                row.append(format_pct(pr, high_mode=high))

        resonance = r.high_resonance if high else r.low_resonance
        if resonance >= 3:
            row.append(Text(f"×{resonance}", style="bold yellow"))
        elif resonance > 0:
            row.append(Text(f"×{resonance}", style="yellow"))
        else:
            row.append("")

        table.add_row(*row)

    console.print(table)

    if is_compact:
        shown = "/".join(str(p) for p in display_periods)
        n = len(display_periods)
        console.print(
            f"\n  [dim]窄屏模式 · 显示 {n}/10 周期"
            f"（{shown}日）· 加宽终端可见全部[/dim]"
        )

    if not data_is_today:
        console.print("\n  [bold yellow]⚠️ 数据非今日，建议 kan fetch --force 更新[/bold yellow]")

    # 增量对比 · 用上面 cache 的 all_results · 避免重复 scan (P1-8)
    if diff and prev_snapshot:
        changes = compute_diff(all_results, prev_snapshot)
        if changes:
            console.print()
            console.print("[bold]与上次扫描的变化：[/bold]")
            for sym, name, _, desc in changes:
                name_short = name.replace(" ", "")
                console.print(f"  {name_short} {sym} · {desc}")
        else:
            if data_is_today:
                console.print("\n  [dim]与上次扫描无变化（同日数据，次日再对比可见变化）[/dim]")
            else:
                console.print("\n  与上次扫描无变化")
    elif diff and not prev_snapshot:
        console.print("\n  [dim]首次扫描，无历史对比（下次 --diff 将显示变化）[/dim]")

    # 保存快照供下次 diff 用 · 始终保存 all_results 全量 (P1-8: 避免重复 scan)
    save_snapshot(all_results)

    console.print()
    if high:
        console.print("[dim]  \\[x%] = 触及高点(≥95%) · 100%=区间最高 · 越高=越接近 N 日最高价[/dim]")
    else:
        console.print("[dim]  \\[x%] = 触及低点(≤5%) · 0%=区间最低 · 越低=越接近 N 日最低价[/dim]")
    console.print(DISCLAIMER, style="dim")


def _filter_extreme_cmd(periods: list[int], mode: str) -> None:
    """low/high 共享实现"""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from kan.fetcher import cache_age
    from kan.scanner import filter_extreme

    console = Console()
    for p in periods:
        if p < 2 or p > 360:
            _print_err(f"❌ 周期 {p} 无效（范围 2-360）")
            raise typer.Exit(1)

    label = "低点" if mode == "low" else "高点"
    signal_style = "bold green" if mode == "low" else "bold yellow"

    watchlist_pairs = _get_watchlist_pairs()
    _auto_fetch_stale(watchlist_pairs)
    results_by_period = filter_extreme(watchlist_pairs, periods, mode=mode)

    if not results_by_period:
        console.print(f"自选股中没有触及 {'/'.join(map(str, periods))} 日{label}的股票")
        return

    latest_time = None

    for n, hits in results_by_period.items():
        for r, _ in hits:
            t = cache_age(r.symbol)
            if t:
                latest_time = t

        title = f"慢慢看 · {n} 日{label} · {len(hits)} 只触及"
        if latest_time:
            title += f" · {latest_time} 更新"

        table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
        table.add_column("股票", style="white", no_wrap=True)
        table.add_column("现价", justify="right", style="white", min_width=8)
        table.add_column(f"{n}日最低", justify="right", style="dim", min_width=8)
        table.add_column(f"{n}日最高", justify="right", style="dim", min_width=8)
        table.add_column("位置", justify="right", min_width=8)

        for result, pr in hits:
            name_short = result.name.replace(" ", "")
            table.add_row(
                f"{name_short} {result.symbol}",
                f"{result.current_price:.2f}",
                f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}",
                Text(f"[{pr.position_pct:.1f}%]", style=signal_style),
            )

        console.print(table)
        console.print()

    console.print(DISCLAIMER, style="dim")


@app.command()
def low(
    periods: Annotated[list[int], typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120）")],
) -> None:
    """筛选 N 日低点的自选股（支持多周期）"""
    _filter_extreme_cmd(periods, mode="low")


@app.command()
def high(
    periods: Annotated[list[int], typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120）")],
) -> None:
    """筛选 N 日高点的自选股（支持多周期）"""
    _filter_extreme_cmd(periods, mode="high")


@app.command()
def trend(
    latest: Annotated[int | None, typer.Option("--latest", "-l", help="展示近 N 天走势详情（1-180）", min=1, max=180)] = None,
    down: Annotated[int | None, typer.Option("--down", help="只看连跌≥N天（不带 N 默认 3）")] = None,
    up: Annotated[int | None, typer.Option("--up", help="只看连涨≥N天（不带 N 默认 3）")] = None,
    candle: Annotated[bool, typer.Option("--candle", "-c", help="阳线阴线口径（默认收盘价口径）")] = False,
) -> None:
    """连续涨跌看板"""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from kan.fetcher import cache_age
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


@app.command()
def info(
    symbol: Annotated[str, typer.Argument(help="股票代码（如 600519）")],
) -> None:
    """单只股票详情（全周期位置 + 涨跌信息）"""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from kan.fetcher import cache_age, fetch_kline, get_cached, is_fresh
    from kan.scanner import calc_trend, scan_stock
    from kan.watchlist import _lookup_name, _normalize_symbol

    console = Console()

    try:
        symbol = _normalize_symbol(symbol)
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(1) from e

    try:
        name = _lookup_name(symbol)
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(1) from e

    if not is_fresh(symbol):
        console.print(f"正在拉取 {name} ({symbol}) 数据...")
        try:
            fetch_kline(symbol, force=True)
        except Exception as e:
            from rich.console import Console as _ErrConsole
            _ErrConsole(stderr=True).print(f"❌ 拉取失败：{_safe_error_msg(e)}")
            raise typer.Exit(1) from e

    df = get_cached(symbol)
    if df is None:
        _print_err("无数据")
        raise typer.Exit(1)

    result = scan_stock(df, symbol, name)
    trend_result = calc_trend(df, symbol, name)
    name_short = name.replace(" ", "")

    latest_time = cache_age(symbol) or ""
    title = f"慢慢看 · {name_short} {symbol}"
    if latest_time:
        title += f" · {latest_time} 更新"

    # 基本信息
    tag = ""
    if result.is_st:
        tag = " [bold red]ST[/bold red]"
    if result.limit_up:
        tag += " [bold red]涨停[/bold red]"
    elif result.limit_down:
        tag += " [bold green]跌停[/bold green]"

    console.print(f"\n[bold]{title}[/bold]{tag}")
    console.print(f"  现价 {result.current_price:.2f} · {trend_result.direction} · 累计 {abs(trend_result.streak_pct):.2f}%")
    console.print()

    # 全周期位置表
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("最低", justify="right", style="dim", min_width=8)
    table.add_column("最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    for pr in result.periods:
        if pr.insufficient:
            table.add_row(f"{pr.period}日", "-", "-", Text("-", style="dim"))
            continue

        table.add_row(
            f"{pr.period}日",
            f"{pr.n_low:.2f}",
            f"{pr.n_high:.2f}",
            format_pct(pr),
        )

    console.print(table)
    console.print(f"\n  低点共振 ×{result.low_resonance} · 高点共振 ×{result.high_resonance}")
    console.print(DISCLAIMER, style="dim")


@app.command(name="clear")
def clear_watchlist() -> None:
    """清空自选列表"""
    from kan.watchlist import clear, load_watchlist

    wl = load_watchlist()
    if not wl.stocks:
        typer.echo("自选列表已经是空的")
        return

    confirm = typer.confirm(f"确定要清空 {len(wl.stocks)} 只自选股吗？")
    if not confirm:
        typer.echo("已取消")
        return

    count = clear()
    typer.echo(f"已清空 {count} 只自选股")


def _detect_install_method() -> dict[str, object]:
    """检测当前 kan 是怎么装的 · 返回对应卸载命令信息。

    用 sys.executable 路径模式判断:
      - uv tool: ~/.local/share/uv/tools/manmankan/bin/python
      - pipx: ~/.local/pipx/venvs/manmankan/bin/python
      - pip/venv: 含 site-packages 或 .venv
    """
    import sys

    exe = sys.executable
    if "uv/tools" in exe and "manmankan" in exe:
        return {
            "name": "uv tool",
            "cmd": "uv tool uninstall manmankan",
            "alts": ["pipx uninstall manmankan", "pip uninstall manmankan"],
        }
    if "pipx/venvs/manmankan" in exe:
        return {
            "name": "pipx",
            "cmd": "pipx uninstall manmankan",
            "alts": ["uv tool uninstall manmankan", "pip uninstall manmankan"],
        }
    if "site-packages" in exe or ".venv" in exe:
        return {
            "name": "pip / venv",
            "cmd": "pip uninstall manmankan",
            "alts": ["uv tool uninstall manmankan", "pipx uninstall manmankan"],
        }
    return {
        "name": "未知（无法自动检测）",
        "cmd": "uv tool uninstall manmankan",
        "alts": ["pipx uninstall manmankan", "pip uninstall manmankan"],
    }


def _human_size(size_bytes: int) -> str:
    """字节数转人类可读 (KB / MB)"""
    kb = size_bytes / 1024
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb:.1f} KB"


@app.command()
def update(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认 · 用于脚本 / CI")] = False,
    check_only: Annotated[bool, typer.Option("--check", help="仅检查 · 不升级")] = False,
) -> None:
    """检查并升级到最新版本

    工作流程:
      1. 实时查 PyPI 拿最新版本号 (force=True 跳过 daily cache)
      2. 跟当前版本对比
      3. 有新版 + 用户 confirm → 调对应包管理器 upgrade (uv tool / pipx / pip)
      4. 失败显示友好错误 + 退出码 1

    用法:
      kan update              检查并升级 (会 prompt 确认)
      kan update -y           跳过确认 · 用于脚本
      kan update --check      仅检查不升级
    """
    from rich.console import Console

    from kan import updater

    console = Console()

    info = updater.check_for_updates(force=True)

    if info.latest is None:
        _print_err("[yellow]⚠️ 无法连接 PyPI · 请检查网络后重试[/yellow]")
        raise typer.Exit(1)

    console.print(f"当前版本: [cyan]v{info.current}[/cyan]")
    console.print(f"最新版本: [cyan]v{info.latest}[/cyan]")

    if not info.has_update:
        console.print("[green]✅ 已是最新版本[/green]")
        return

    console.print(
        "更新说明: https://github.com/piklen/manmankan/blob/main/CHANGELOG.md"
    )

    if check_only:
        console.print(
            f"[dim]跑 [bold]kan update[/bold] 升级到 v{info.latest}[/dim]"
        )
        return

    if not yes and not typer.confirm(f"是否升级到 v{info.latest}?"):
        console.print("[dim]已取消[/dim]")
        return

    install = updater.detect_install_method()
    console.print(
        f"[dim]检测到安装方式: {install.name} · 升级中...[/dim]"
    )

    status, msg = updater.run_upgrade()
    if status == "success":
        console.print(
            f"[green]✅ 已升级到 v{info.latest}[/green] "
            f"[dim](方式: {msg} · 下次跑 kan 命令生效)[/dim]"
        )
    else:
        _print_err("[red]❌ 升级失败[/red]")
        _print_err(f"[dim]{msg}[/dim]")
        raise typer.Exit(1)


@app.command()
def uninstall(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认 · 用于脚本 / CI")] = False,
    keep_data: Annotated[bool, typer.Option("--keep-data", help="只输出包卸载提示 · 不删数据")] = False,
) -> None:
    """卸载 kan: 删除所有本地数据 + 输出软件包卸载命令。

    数据清理范围（除非 --keep-data）:
      - ~/.local/share/kan/ (XDG 数据)
      - ~/.kan/ (legacy 数据 · 如存在)

    软件包本身不会自动卸载（chicken-and-egg · kan 无法删自己运行的进程）。
    本命令会检测安装方式并打印对应卸载指令，请手动执行。
    """
    import shutil
    from pathlib import Path

    from rich.console import Console

    from kan.paths import BASE_DIR

    console = Console()
    legacy_dir = Path.home() / ".kan"

    # 1. 列出会删的路径 + 大小
    targets: list[tuple[str, Path, int]] = []
    for label, path in (("XDG 数据", BASE_DIR), ("Legacy 数据", legacy_dir)):
        if path.exists():
            try:
                size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            except OSError:
                size = 0
            targets.append((label, path, size))

    # 2. 检测安装方式
    install = _detect_install_method()

    # 3. 显示数据 + 安装方式
    if not keep_data:
        if targets:
            console.print("[bold]将删除以下数据目录:[/bold]")
            for label, path, size in targets:
                console.print(f"  · {path} ({label} · {_human_size(size)})")
        else:
            console.print("[dim]没有数据目录需要清理[/dim]")
        console.print()

    console.print(
        "[bold yellow]软件包本身不会自动卸载[/bold yellow]"
        "（chicken-and-egg · kan 无法删除正在运行自己的 Python 进程）"
    )
    console.print(f"检测到安装方式: [cyan]{install['name']}[/cyan]")
    console.print(f"请手动运行: [bold]{install['cmd']}[/bold]")
    alts = install.get("alts")
    if alts:
        console.print("[dim]或（如果上面命令不适用）:[/dim]")
        for alt in alts:
            console.print(f"  [dim]{alt}[/dim]")
    console.print()

    # 4. keep_data 模式 · 早返回
    if keep_data:
        return

    # 5. 无数据 · 无需确认
    if not targets:
        return

    # 6. 确认
    if not yes and not typer.confirm("确认删除上面所有数据吗?"):
        console.print("[dim]已取消[/dim]")
        return

    # 7. 删除
    deleted = 0
    for _label, path, _size in targets:
        try:
            shutil.rmtree(path)
            console.print(f"  ✅ 已删除 {path}")
            deleted += 1
        except Exception as e:
            _print_err(f"  ❌ 删除 {path} 失败: {_safe_error_msg(e)}")

    console.print()
    if deleted == len(targets):
        console.print(
            f"[green]✅ kan 数据已完全清理 ({deleted} 个目录)[/green] · "
            "软件包请按上面提示自卸"
        )
    else:
        console.print(
            f"[yellow]⚠️ 部分清理 ({deleted}/{len(targets)} 成功) · "
            "请检查权限或手动 rm[/yellow]"
        )


_VALID_SHELLS = ("zsh", "bash", "fish", "powershell", "pwsh")


def _detect_shell_fallback() -> str | None:
    """fallback shell 检测：先 shellingham · 失败回退 $SHELL · windows 回退 powershell。

    typer 0.25 + uv tool 环境下 shellingham 经常 fail（process tree 中间是 python wrapper），
    所以提供多层 fallback 让 mac/linux/windows 都能用。
    """
    import os

    # 1) shellingham (uv tool 环境下经常失败 · 但本地裸装可用)
    try:
        import shellingham
        name, _path = shellingham.detect_shell()
        if name in _VALID_SHELLS:
            return name
    except Exception:
        pass

    # 2) $SHELL env (mac/linux 通用)
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        shell_name = os.path.basename(shell_path)
        if shell_name in ("zsh", "bash", "fish"):
            return shell_name

    # 3) windows 兜底（PSModulePath 是 powershell 特征环境变量）
    if os.name == "nt" or "PSModulePath" in os.environ:
        return "powershell"

    return None


@app.command(name="completion")
def completion_cmd(
    action: Annotated[str, typer.Argument(help="install")],
    shell: Annotated[
        str | None,
        typer.Argument(help="zsh / bash / fish / powershell · 不传时自动检测"),
    ] = None,
) -> None:
    """安装 shell 命令补全脚本（mac/linux/windows 全平台）。

    支持的 shell:
      - mac/linux: zsh / bash / fish
      - windows: powershell / pwsh

    用法:
        kan completion install         # 自动检测 shell · 安装补全脚本
        kan completion install zsh     # 显式指定 shell

    安装后的效果:
        kan s<Tab>      → kan scan
        kan <Tab>       → 列出所有命令（add / scan / list / info / ...）
        kan trend --<Tab> → 列出所有 --down / --up / --latest / --candle 等

    安装后请重启终端或 source 配置文件让补全生效。
    脚本路径会显示在输出中 · 想自定义可 cat 该路径查看脚本内容。
    """
    if action != "install":
        typer.echo(f"❌ 未知动作: {action} · 当前只支持 install", err=True)
        raise typer.Exit(1)

    if shell is None:
        shell = _detect_shell_fallback()
        if shell is None:
            typer.echo(
                "❌ 无法自动检测 shell · 请显式指定: "
                "kan completion install [zsh|bash|fish|powershell]",
                err=True,
            )
            raise typer.Exit(1)

    if shell not in _VALID_SHELLS:
        typer.echo(
            f"❌ 不支持的 shell: {shell} · 支持: {', '.join(_VALID_SHELLS)}",
            err=True,
        )
        raise typer.Exit(1)

    try:
        from typer.completion import install
        installed_shell, path = install(shell=shell, prog_name="kan")
    except Exception as e:
        typer.echo(f"❌ 安装失败: {_safe_error_msg(e)}", err=True)
        raise typer.Exit(1) from None

    from rich.console import Console
    console = Console()
    console.print(
        f"[green]✅ {installed_shell} 补全脚本已安装到[/green] [cyan]{path}[/cyan]"
    )
    console.print()
    console.print("[yellow]让补全生效（任选其一）：[/yellow]")
    if installed_shell == "zsh":
        console.print("  1) 重启终端")
        console.print("  2) [cyan]source ~/.zshrc[/cyan]")
    elif installed_shell == "bash":
        console.print("  1) 重启终端")
        console.print("  2) [cyan]source ~/.bashrc[/cyan]")
    elif installed_shell == "fish":
        console.print("  1) 重启终端 (fish 自动加载 completions/)")
    elif installed_shell in ("powershell", "pwsh"):
        console.print("  1) 重启 PowerShell")
        console.print("  2) [cyan]. $PROFILE[/cyan]")
    console.print()
    console.print("[dim]之后试 [bold]kan s[/bold] + Tab 看效果[/dim]")


def _normalize_streak_args() -> None:
    """让 --down / --up 不带值时注入默认 3（typer 0.25 无法透传 click 的 flag_value）

    typer 把 ``--down`` 限定为「无值」(bool flag) 或「必带值」(Optional[int]) 二选一，
    无法表达 click 的 ``is_flag=False, flag_value=N`` 模式。
    本实现把语义合并到 ``--down N``，并在 entry 之前预处理 sys.argv，
    让 ``--down`` 不带数字时注入 ``"3"`` 作为默认连跌天数：

      kan trend --down              → 注入 3 → 等价 --down 3
      kan trend --down 5            → 不动
      kan trend --down --candle     → 注入 3 → --down 3 --candle
      kan trend --down 5 --candle   → 不动
    """
    import sys

    args = sys.argv
    for i in range(len(args) - 1, -1, -1):
        if args[i] not in ("--down", "--up"):
            continue
        next_is_value = (i + 1 < len(args)) and args[i + 1].lstrip("-").isdigit()
        if not next_is_value:
            args.insert(i + 1, "3")


def _normalize_help_args() -> None:
    """让 ``kan --help`` 等价 ``kan help`` · 走中文速记

    统一行为：
      kan          → 中文速记（main callback 检测 sys.argv 长度）
      kan help     → 中文速记（@app.command(name="help")）
      kan --help   → 转换为 ``help`` 子命令 · 走中文速记

    实现：root-level ``--help`` 替换为 ``help`` 子命令 · 三种调用统一中文速记。
    子命令的 ``--help`` 不影响（如 ``kan scan --help`` 仍走 typer 默认）。
    """
    import sys

    if len(sys.argv) == 2 and sys.argv[1] == "--help":
        sys.argv[1] = "help"


def _auto_install_completion() -> None:
    """首次启动自动启用 shell 命令补全 · 标记文件防重复 · 失败静默不影响主流程。

    用户视角："uv tool install manmankan" 后第一次跑任意 kan 命令 · 自动启用
    tab 补全 · 不需要再手动 `kan completion install`。

    跳过条件（防止 surprising behavior）：
      - 环境变量 KAN_NO_COMPLETION_AUTOINSTALL=1（power user 关闭）
      - 标记文件已存在（{BASE_DIR}/.completion_installed）
      - 非 TTY 环境（pipe / CI / docker · 不要在脚本场景改 shell rc）
      - 检测不到 shell（typer 装不了）

    第一次成功（或检测失败）后写标记文件 · 之后启动只 stat 一次（~ms）。
    """
    import os
    import sys

    if os.environ.get("KAN_NO_COMPLETION_AUTOINSTALL") == "1":
        return

    # 非 TTY (pipe / CI) 不自动改 shell rc 文件
    if not (sys.stdout.isatty() or sys.stderr.isatty()):
        return

    try:
        from kan.paths import BASE_DIR
        flag_path = BASE_DIR / ".completion_installed"
    except Exception:
        return

    if flag_path.exists():
        return

    # 即使下面失败 · 也标记一下不再尝试
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()
    except Exception:
        return

    shell = _detect_shell_fallback()
    if shell is None or shell not in _VALID_SHELLS:
        return

    try:
        from typer.completion import install
        installed_shell, _path = install(shell=shell, prog_name="kan")
    except Exception:
        return

    # 通知用户（小字 stderr · 不打扰主流程）
    try:
        from rich.console import Console
        Console(stderr=True).print(
            f"[dim]💡 已为你自动启用 {installed_shell} 命令补全 · "
            f"重启终端后 [bold]kan s[/bold] + Tab 即生效 · "
            f"不需要可设 KAN_NO_COMPLETION_AUTOINSTALL=1[/dim]"
        )
    except Exception:
        pass


def _check_updates_atexit() -> None:
    """主命令完成后异步检查更新 · 静默 fallback · 5 个交互场景对应。

    场景:
      A) auto_update is None + TTY  → prompt y/n/skip 询问偏好 · 选 y 立即升级
      B) auto_update is True         → 自动调包管理器 upgrade · 失败静默
      C) auto_update is False        → 仅 hint · 每周限流一次
      D) PyPI 不可达 / 网络失败       → 完全静默 · 不破坏主命令
      E) 非 TTY / KAN_NO_UPDATE_CHECK → 直接返回 · 不发请求

    所有异常都吞掉 · atexit hook 不能让主命令 exit code 改变。
    """
    import os
    import sys

    if os.environ.get("KAN_NO_UPDATE_CHECK") == "1":
        return
    # 用户已经在跑 kan update · atexit 不重复检查防双重升级 / 双重 prompt
    if len(sys.argv) >= 2 and sys.argv[1] == "update":
        return
    # 非 TTY (pipe / CI) 不弹 prompt 不打扰
    if not (sys.stdout.isatty() or sys.stderr.isatty()):
        return

    try:
        from datetime import date, timedelta

        from rich.console import Console

        from kan import config, updater

        info = updater.check_for_updates()
        if info.latest is None or not info.has_update:
            return

        cfg = config.load()
        auto_update = cfg.get("auto_update")
        console = Console(stderr=True)

        # 场景 B: 已选 True · 自动升级
        if auto_update is True:
            console.print(
                f"\n[dim]💡 检测到新版本 v{info.latest} · 自动升级中...[/dim]"
            )
            status, msg = updater.run_upgrade()
            if status == "success":
                console.print(
                    f"[dim]✅ 已升级到 v{info.latest} · 下次跑 kan 命令生效[/dim]"
                )
            # 升级失败 atexit 静默不打扰主命令
            return

        # 场景 C: 已选 False · 仅 hint · 每周限流
        if auto_update is False:
            should_hint = True
            last_hint = cfg.get("last_hint_date")
            if isinstance(last_hint, str):
                try:
                    last = date.fromisoformat(last_hint)
                    should_hint = (date.today() - last) >= timedelta(days=7)
                except ValueError:
                    pass
            if should_hint:
                console.print(
                    f"\n[dim]💡 当前 v{info.current} · 最新 v{info.latest} · "
                    f"跑 [bold]kan update[/bold] 升级 (本提示每周一次)[/dim]"
                )
                cfg["last_hint_date"] = date.today().isoformat()
                try:
                    config.save(cfg)
                except OSError:
                    pass
            return

        # 场景 A: 首次发现新版 (auto_update is None) · 阻塞 prompt
        console.print(
            f"\n[bold yellow]💡 发现新版本 v{info.latest}[/bold yellow] "
            f"[dim](当前 v{info.current})[/dim]"
        )
        try:
            choice = typer.prompt(
                "是否启用「以后自动升级」 [y/n/skip]",
                default="skip",
                show_default=True,
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if choice in ("y", "yes"):
            cfg["auto_update"] = True
            try:
                config.save(cfg)
            except OSError:
                pass
            console.print("[green]✅ 偏好已保存 · 立即升级中...[/green]")
            status, msg = updater.run_upgrade()
            if status == "success":
                console.print(
                    f"[green]✅ 已升级到 v{info.latest} · 下次跑 kan 命令生效[/green]"
                )
            else:
                console.print(
                    "[red]❌ 升级失败 (主命令不受影响 · 可手动 kan update 重试)[/red]"
                )
                console.print(f"[dim]{msg}[/dim]")
        elif choice in ("n", "no"):
            cfg["auto_update"] = False
            try:
                config.save(cfg)
            except OSError:
                pass
            console.print(
                "[dim]✅ 偏好已保存 · 不再自动升级 · "
                "以后跑 [bold]kan update[/bold] 手动升级[/dim]"
            )
        else:
            # skip / 其他 · 不写偏好 · 下次再问
            console.print(
                "[dim]跳过 · 跑 [bold]kan update[/bold] 升级 · 下次启动时再询问偏好[/dim]"
            )
    except Exception:
        # atexit hook 不能让主命令受影响 · 任何异常都吞掉
        pass


def cli_main() -> None:
    """CLI entry point · sys.argv 预处理后再交给 typer。

    实现细节：_auto_install_completion 推迟到命令完成后（atexit）执行，
    防止其 stderr 输出跟 add 命令的 Live Display spinner 共享 stderr 时
    buffer 竞争（用户可能看不到 spinner 动画的 corner case）。
    """
    import atexit

    from kan.paths import migrate_legacy
    migrate_legacy()
    _normalize_help_args()
    _normalize_streak_args()
    # 命令结束后才装补全 + 检查更新 · 不抢主流程 stderr
    # atexit LIFO 执行 · 后注册先跑 · update 检查先于 completion install
    atexit.register(_auto_install_completion)
    atexit.register(_check_updates_atexit)
    app()

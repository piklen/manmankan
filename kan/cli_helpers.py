"""CLI 共享 helper · 跨命令组复用的小工具。

按职责切分：
- 错误脱敏 / 网络异常友好化：_safe_error_msg / _print_err / _network_error_msg
- 安装检测：_detect_install_method
- shell 检测：_detect_shell_fallback / _VALID_SHELLS
- argv 预处理：_normalize_streak_args / _normalize_help_args
- 自选股 / 数据加载：_load_names_with_optional_spinner / _get_watchlist_pairs / _auto_fetch_stale
- 杂项：_NoopContext / _human_size

lazy import 模式保留 · 顶层只 import 极轻的 stdlib + typer · rich/akshare 等重模块函数体内 lazy。
"""
import contextlib
import os
import re as _re
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import typer

from kan._log import debug_log
from kan._time import today as _today

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


def confirm_destructive(summary: str, *, yes: bool) -> bool:
    """破坏性批量操作二次确认 · 打印影响摘要 · yes=True 跳过 · 返回是否继续。

    用于按行业批量增删自选股 —— 不可逆操作前让用户看清影响范围再决定。
    """
    typer.echo(summary)
    if yes:
        return True
    return typer.confirm("继续?")


class _NoopContext:
    """No-op context manager · 跟 console.status 接口对齐 · 用于小量场景跳过 spinner。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


# ── 日期格式化 helpers (散户友好压缩 · 同年隐藏年份) ────────────────
# v0.0.4.8: 今天的日期 helper 移到 kan/_time.py (防 trading_calendar 反向 circular import)
# 本 module 内通过 `_today()` local alias 调 `from kan._time import today as _today`
def format_date_compact(d: date) -> str:
    """同年时省 year (`05-12`) · 跨年才显示完整 ISO (`2025-12-31`)。

    v0.0.4.7: 80 列窄屏 title 不溢出 + 散户阅读减负。
    """
    today = _today()
    if d.year == today.year:
        return d.strftime("%m-%d")
    return d.isoformat()


def format_fetched_at_compact(fetched_str: str) -> str:
    """从 ISO datetime string 提取最 compact 表示。

    - 当天一般 (05:00-21:59): `16:05` (省日期 · 因为 user 知道今天)
    - 当天凌晨 (00:00-04:59): `今晨 01:00` (防深夜跑 scan 时误判为下午)
    - 昨天傍晚 (22:00-23:59): `昨晚 23:50` (对称提示 · 防早上 scan 时误判为今天)
    - 同年不同天: `05-12 16:05`
    - 跨年: `2025-12-31 16:05`
    - 不可解析: 原样返回

    v0.0.4.8: 凌晨日界提示防误判;v0.0.4.7: 80 列窄屏不溢出。
    """
    try:
        dt = datetime.fromisoformat(fetched_str)
    except (ValueError, TypeError):
        return fetched_str
    today = _today()
    if dt.date() == today:
        hour = dt.hour
        time_str = dt.strftime("%H:%M")
        if 0 <= hour < 5:
            return f"今晨 {time_str}"
        return time_str
    if dt.date() == today - timedelta(days=1) and dt.hour >= 22:
        return f"昨晚 {dt.strftime('%H:%M')}"
    if dt.year == today.year:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


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


def _load_names_with_optional_spinner(console) -> dict[str, str]:
    """加载 A 股代码表 · 缓存过期时 spinner 包住 watchlist 重 import + preload。

    设计要点：fresh 检查走极轻的 kan.paths（~370μs）· spinner 提前到 watchlist
    重模块（akshare lazy 后约 ~40ms 热启动 / ~1-2s 冷启动）import 之前显示，
    避免按回车后用户面对一段 启动反馈。
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


@contextmanager
def _with_heavy_imports_spinner(console, message: str):
    """在重模块 import 前先打开 spinner，避免 CLI 路由后出现 启动反馈。"""
    with console.status(f"[yellow]{message}[/yellow]", spinner="dots") as status:
        yield status


def _load_watchlist_pairs() -> list[tuple[str, str]]:
    """自选股 (代码, 名称) 列表;自选为空时返回 [] · 不报错。

    用于 --industry 模式 —— 扫的是板块成分股,自选股仅用于 ⭐ 高亮,
    自选为空只意味着没有高亮,不应阻止扫描。
    """
    from kan.watchlist import load_watchlist
    return [(s.symbol, s.name) for s in load_watchlist().stocks]


def _get_watchlist_pairs() -> list[tuple[str, str]]:
    """自选股 (代码, 名称) 列表;自选为空时友好报错 + 退出(自选模式命令用)。"""
    pairs = _load_watchlist_pairs()
    if not pairs:
        typer.echo("自选列表为空 · 请先 `kan add <代码>` 添加", err=True)
        raise typer.Exit(1)
    return pairs


def _auto_fetch_stale(pairs: list[tuple[str, str]]) -> None:
    """自动拉取缺失或过期（非今天）的自选股数据。

    并发自适应 (v0.0.4.7): resolve_max_workers() · cpu_count*2 cap 12.
    rich.Progress 进度条 + 网络异常友好提示.
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

    console = Console(stderr=True)
    n_total = len(pairs)

    # v0.0.4.7.1 hotfix: "检查缓存" 3 阶段 spinner (B+C 组合 · 真用户反馈触发)
    # 旧: 单句 "⏳ 检查缓存..." · 169 只 + akshare 冷启动可能 5-30s 沉默 · 真小白误判卡死
    # 新: import → trade_dates warm → ticking 数字进度 · 用户每秒看到工具在动
    with console.status(
        "[yellow]⏳ 加载数据模块...[/yellow]",
        spinner="dots",
    ) as status:
        from kan.fetcher import fetch_batch, is_fresh

        # Stage 2: explicit pre-warm trade_dates · 避免 ticking 阶段第 1 只时
        # latent 触发 akshare 5-15s 拉取 (用户看到 spinner 停在 1/169 会困惑)
        status.update(
            f"[yellow]⏳ 加载交易日历 · {n_total} 只自选股待检查...[/yellow]"
        )
        from kan.trading_calendar import latest_trade_date
        # latest_trade_date 现已 fail-soft (v0.0.4.7) · 不抛 RuntimeError ·
        # 但保险 contextlib.suppress · 任何 upstream regression 不应 break 检查缓存
        with contextlib.suppress(Exception):
            _ = latest_trade_date()

        # Stage 3: ticking 数字进度 (B+C · 每 5% update 一次 · 防闪烁)
        status.update(
            f"[yellow]⏳ 检查缓存 · 0/{n_total} 只 · "
            f"首次稍慢 · 后续秒级[/yellow]"
        )
        stale: list[tuple[str, str]] = []
        update_every = max(1, n_total // 20)
        for i, (sym, name) in enumerate(pairs):
            if not is_fresh(sym):
                stale.append((sym, name))
            if (i + 1) % update_every == 0 or i + 1 == n_total:
                status.update(
                    f"[yellow]⏳ 检查缓存 · {i + 1}/{n_total} 只 · "
                    f"已发现 {len(stale)} 只 stale[/yellow]"
                )
    if not stale:
        return

    n = len(stale)

    # 大量股票时给出明确预期 · 避免用户以为卡死
    # v0.0.4.7: 删除 v0.0.4.5 一次性迁移文案 (对老用户冗余)
    if n >= 30:
        est_low = max(1, n // 60)
        est_high = max(2, n // 20)
        # v0.0.4.7: 并发不再硬编码 5 · auto_max_workers 启发式 (cpu_count*2 cap 12)
        from kan.fetcher import resolve_max_workers
        workers = resolve_max_workers()
        console.print(
            f"[yellow]需更新 {n} 只股票数据 · 并发 {workers} · "
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
        task_id = progress.add_task("⏳ 拉取数据...", total=n)

        # v0.0.4.8: 累计失败 symbol · GIL 保护 list.append 原生 thread-safe
        # 避免 nonlocal int += 的 read-modify-write race condition
        fails: list[str] = []

        def _on_done(symbol: str, ok: bool, _err_msg: str | None) -> None:
            # v0.0.4.7: spinner 加 stale 总数
            # v0.0.4.8: ✅/❌ emoji + 累计失败数
            # v0.0.4.8 finalize: truncate name to 4 char + 紧凑 desc · 80 列不折行
            #   旧 "⏳ 补数据 · 169 只 stale · ❌ 失败: 中国铝业 · 失败 3" ≈ 99 列 (折行)
            #   新 "⏳ 补数据 169 只 · ❌ 中国铝… · 失败 3" ≈ 64 列 (80 列 OK)
            full_name = name_map.get(symbol, symbol).replace(" ", "")
            # truncate 到 4 char 防长名占用视觉宽 (e.g. "中国神华" / "贵州茅台" 都 4 char OK)
            name = full_name if len(full_name) <= 4 else full_name[:3] + "…"
            if not ok:
                fails.append(symbol)
            current_fail = len(fails)
            desc = (
                f"⏳ 补数据 {n} 只 · ✅ {name}" if ok
                else f"⏳ 补数据 {n} 只 · ❌ {name}"
            )
            if current_fail > 0:
                desc += f" · 失败 {current_fail}"
            progress.update(task_id, advance=1, description=desc)

        try:
            # v0.0.4.7: max_workers 不再硬编码 · 由 fetch_batch 内部 resolve_max_workers() 启发式
            results, errors = fetch_batch(
                [s for s, _ in stale],
                force=True,
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


def _human_size(size_bytes: int) -> str:
    """字节数转人类可读 (KB / MB)"""
    kb = size_bytes / 1024
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb:.1f} KB"


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


_VALID_SHELLS = ("zsh", "bash", "fish", "powershell", "pwsh")


def _detect_shell_fallback() -> str | None:
    """fallback shell 检测：先 shellingham · 失败回退 $SHELL · windows 回退 powershell。

    typer 0.25 + uv tool 环境下 shellingham 经常 fail（process tree 中间是 python wrapper），
    所以提供多层 fallback 让 mac/linux/windows 都能用。
    """
    # 1) shellingham (uv tool 环境下经常失败 · 但本地裸装可用)
    try:
        import shellingham
        name, _path = shellingham.detect_shell()
        if name in _VALID_SHELLS:
            return name
    except Exception as e:
        # v0.0.4.8 finalize: lazy import 改顶层一致 (zero-cost stdlib wrapper)
        debug_log(__name__, "shellingham detect_shell fallback", e)

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

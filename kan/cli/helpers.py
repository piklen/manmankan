"""CLI 共享 helper · 跨命令组复用的小工具。

按职责切分：
- 错误脱敏 / 网络异常友好化：_safe_error_msg / _print_err / _network_error_msg
- 安装检测：_detect_install_method
- shell 检测：_detect_shell_fallback / _VALID_SHELLS
- argv 预处理：_normalize_streak_args / _normalize_help_args
- 代码池解析：_parse_codes / _resolve_code_pairs
- 自选股 / 数据加载：_load_names_with_optional_spinner / _get_watchlist_pairs / _auto_fetch_stale
- 杂项：_NoopContext / _human_size

lazy import 模式保留 · 顶层只 import 极轻依赖 · rich/akshare 等重模块函数体内 lazy。

Helper 适用矩阵(防 6 命令使用漂移):
  helper                          scan trend low high info compare fetch
  _auto_fetch_stale                ✓   ✓    ✓   ✓   ✓    ✓       —
  _get_watchlist_pairs             ✓   ✓    ✓   ✓   —    —       ✓
  _load_watchlist_pairs            ✓   ✓    —   —   —    —       —
  _print_err / _safe_error_msg     ✓   ✓    ✓   ✓   ✓    ✓       ✓
  _with_heavy_imports_spinner      ✓   ✓    ✓   ✓   ✓    ✓       ✓
  _network_error_msg               —   ✓    —   —   ✓    ✓       ✓
  format_date_compact              ✓   ✓    ✓   ✓   ✓    ✓       —
  format_fetched_at_compact        ✓   ✓    ✓   ✓   ✓    ✓       —
  pipeline.render_freshness_warning ✓ ✓   —   —   —    —       —"""
import os
import re as _re
from contextlib import contextmanager

import typer

from kan.core.auto_fetch import auto_fetch_stale
from kan.infra.console import print_err
from kan.infra.errors import network_error_msg, safe_error_msg
from kan.infra.formatting import (
    format_date_compact as _format_date_compact,
)
from kan.infra.formatting import (
    format_fetched_at_compact as _format_fetched_at_compact,
)
from kan.infra.log import debug_log

_auto_fetch_stale = auto_fetch_stale
_print_err = print_err
_network_error_msg = network_error_msg
_safe_error_msg = safe_error_msg
format_date_compact = _format_date_compact
format_fetched_at_compact = _format_fetched_at_compact


def _parse_codes(raw: str) -> tuple[list[str], list[str]]:
    """解析逗号 / 空格 / 换行分隔代码 · 返回 (去重 codes, invalid tokens)。"""
    codes: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    prefix_re = _re.compile(r"^(SH|SZ|BJ)[.:]?", _re.I)
    suffix_re = _re.compile(r"[.:]?(SH|SZ|BJ)$", _re.I)
    for token in _re.split(r"[\s,，;；]+", raw.strip()):
        if not token:
            continue
        code = prefix_re.sub("", token.strip())
        code = suffix_re.sub("", code)
        if not _re.fullmatch(r"\d{6}", code):
            invalid.append(token)
            continue
        if code in seen:
            continue
        seen.add(code)
        if code not in codes:
            codes.append(code)
    return codes, invalid


def _resolve_code_pairs(raw: str, *, command: str) -> list[tuple[str, str]]:
    """CLI `--codes`/位置参数 → [(code, name)] · 名称表不可用时用代码兜底。"""
    import sys

    text = sys.stdin.read() if raw == "-" else raw
    codes, invalid = _parse_codes(text)
    if invalid:
        preview = ", ".join(invalid[:5])
        suffix = "..." if len(invalid) > 5 else ""
        _print_err(f"❌ --codes 含非法代码: {preview}{suffix} · 需 6 位 A 股代码")
        raise typer.Exit(2)
    if not codes:
        _print_err(f"❌ --codes 为空 · 例: {command} --codes 600519,000858")
        raise typer.Exit(2)
    try:
        from kan.storage.watchlist import preload_stock_names

        names = preload_stock_names()
    except Exception as e:
        debug_log(__name__, "preload stock names for --codes", e)
        names = {}
    return [(code, names.get(code, code)) for code in codes]


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


def _load_names_with_optional_spinner(console) -> dict[str, str]:
    """加载 A 股代码表 · cache 不新鲜时 spinner 包住初始化/刷新过程。

    设计要点：fresh 检查走极轻的 kan.storage.paths（~370μs）· spinner 提前到 watchlist
    重模块（akshare lazy 后约 ~40ms 热启动 / ~1-2s 冷启动）import 之前显示，
    避免按回车后用户面对一段 启动反馈。
    """
    import time

    from kan.storage.paths import is_stock_names_cache_fresh
    cache_fresh = is_stock_names_cache_fresh()

    if cache_fresh:
        from kan.storage.watchlist import preload_stock_names
        return preload_stock_names()

    t_start = time.monotonic()
    with console.status(
        "[yellow]⏳ 首次运行 · 初始化 A 股代码表...[/yellow]",
        spinner="dots",
    ):
        from kan.storage.watchlist import preload_stock_names
        names = preload_stock_names()
    elapsed = time.monotonic() - t_start
    console.print(f"[green]✅ A 股代码表加载完成 · 用时 {elapsed:.1f}s[/green]")
    return names


@contextmanager
def _with_heavy_imports_spinner(console, message: str):
    """在重模块 import 前先打开 spinner，避免 CLI 路由后出现 启动反馈。"""
    with console.status(f"[yellow]{message}[/yellow]", spinner="dots") as status:
        yield status


def _load_watchlist_pairs(group: str | None = None) -> list[tuple[str, str]]:
    """指定组的 (代码, 名称) 列表;组为空时返回 [] · 不报错(--group 不传走 default)。

    用于 --industry 模式 —— 扫的是板块成分股,自选股仅用于 ⭐ 高亮,
    自选为空只意味着没有高亮,不应阻止扫描。
    """
    from kan.storage.watchlist import GroupNotFoundError, load_watchlist
    try:
        return [(s.symbol, s.name) for s in load_watchlist(group).stocks]
    except GroupNotFoundError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(2) from None


def _get_watchlist_pairs(group: str | None = None) -> list[tuple[str, str]]:
    """指定组 (代码, 名称) 列表;为空时友好报错 + 退出(自选模式命令用)。"""
    pairs = _load_watchlist_pairs(group)
    if not pairs:
        label = "自选" if not group else f"「{group}」组"
        suffix = "" if not group else f" --group {group}"
        typer.echo(
            f"{label}列表为空 · 先加几只:`kan add 600519 茅台 000858{suffix}` (代码或名称都行)",
            err=True,
        )
        raise typer.Exit(1)
    return pairs


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
        # 背景: lazy import 改顶层一致 (zero-cost stdlib wrapper)
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

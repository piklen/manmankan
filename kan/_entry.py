"""Console-script entry point with import-time failure guard."""

from __future__ import annotations

import os
import sys

_BOOT_BANNER_COMMANDS = {
    "add", "scan", "fetch", "low", "high", "info", "trend", "find", "theme", "board",
    "index", "daily", "guide",
}
_FAST_ROOT_HELP_ARGS = {("help",), ("--help",), ("-h",)}
_FAST_START_HELP_ARGS = {()}
_FAST_SUBCOMMAND_HELP_ARGS: dict[tuple[str, ...], str] = {
    ("find", "--help"): "find",
    ("find", "-h"): "find",
}


def _is_shell_completion_run() -> bool:
    return bool(
        os.environ.get("_KAN_COMPLETE")
        or os.environ.get("_TYPER_COMPLETE_ARGS")
    )


def _should_print_fast_help(argv: list[str] | None = None) -> bool:
    """Return whether the console script can render root help without full CLI import."""
    if _is_shell_completion_run():
        return False
    args = tuple((argv or sys.argv)[1:])
    return args in _FAST_ROOT_HELP_ARGS


def _should_print_fast_start(argv: list[str] | None = None) -> bool:
    """Return whether an empty invocation should render the retail-first start page."""
    if _is_shell_completion_run():
        return False
    args = tuple((argv or sys.argv)[1:])
    return args in _FAST_START_HELP_ARGS


def _fast_subcommand_help_command(argv: list[str] | None = None) -> str | None:
    """返回可单独注册帮助页模块的子命令;当前仅 find 命中。"""
    if _is_shell_completion_run():
        return None
    args = tuple((argv if argv is not None else sys.argv)[1:])
    return _FAST_SUBCOMMAND_HELP_ARGS.get(args)


def _maybe_print_boot_banner() -> None:
    if os.environ.get("KAN_NO_BOOT_BANNER") == "1":
        return
    if not sys.stderr.isatty():
        return
    if len(sys.argv) < 2:
        return
    if sys.argv[1] not in _BOOT_BANNER_COMMANDS:
        return
    if "--help" in sys.argv[2:] or "-h" in sys.argv[2:]:
        return
    sys.stderr.write("⏳ 慢慢看启动中...\r")
    sys.stderr.flush()


def _write_install_error(e: ImportError | ModuleNotFoundError) -> None:
    sys.stderr.write(
        f"\n❌ kan 安装文件不完整 ({type(e).__name__}: {str(e)[:120]})\n"
        "\n这通常发生在 kan update 升级中途被打断 · 或上游 deps 版本错位。\n"
        "请运行以下命令之一手动 reinstall:\n\n"
        "  uv tool install manmankan --reinstall\n"
        "  pipx install manmankan --force\n"
        "  pip install --force-reinstall manmankan\n"
        "\n如问题持续 · 请到 https://github.com/piklen/manmankan/issues 报告。\n"
    )


def _print_fast_help() -> None:
    from kan.help_text import print_root_help

    print_root_help()


def _print_fast_start() -> None:
    from kan.help_text import print_start_help

    print_start_help()


def _install_doh_dns() -> None:
    """绕过 Clash fake-ip DNS 劫持 · 对 help/complete 等瞬时命令跳过。"""
    if _is_shell_completion_run():
        return
    try:
        from kan.infra.doh_dns import install as install_doh
        install_doh()
    except Exception:
        pass  # DoH 不可用不阻塞启动


def _patch_mini_racer() -> None:
    """修复 mini-racer 0.14+ 在 macOS 上缺少 __init__.py 的问题。"""
    try:
        from kan.infra.finalizer_guard import patch_mini_racer_import
        patch_mini_racer_import()
    except Exception:
        pass  # 补丁失败不阻塞启动


def main() -> None:
    _maybe_print_boot_banner()
    if _should_print_fast_start():
        _print_fast_start()
        return
    if _should_print_fast_help():
        _print_fast_help()
        return
    _patch_mini_racer()
    _install_doh_dns()
    try:
        from kan.cli import cli_main
    except (ImportError, ModuleNotFoundError) as e:
        _write_install_error(e)
        sys.exit(2)
    cli_main()

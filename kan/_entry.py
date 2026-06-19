"""Console-script entry point with import-time failure guard."""

from __future__ import annotations

import os
import sys

_BOOT_BANNER_COMMANDS = {
    "add", "scan", "fetch", "low", "high", "info", "trend", "find", "theme", "board",
    "index",
}
_FAST_ROOT_HELP_ARGS = {(), ("help",), ("--help",), ("-h",)}


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
    sys.stderr.write("⏳ 启动中...\r")
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


def main() -> None:
    _maybe_print_boot_banner()
    if _should_print_fast_help():
        _print_fast_help()
        return
    try:
        from kan.cli import cli_main
    except (ImportError, ModuleNotFoundError) as e:
        _write_install_error(e)
        sys.exit(2)
    cli_main()

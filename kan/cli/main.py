"""kan CLI entry point · 极薄入口 (只装 cli_main 函数 + boot banner)。

子命令装饰器触发 / app 单例 / 子模块 import 全由 kan/cli/__init__.py 接管。
本文件只负责:
  1. boot banner (启动 spinner · module top-level 执行)
  2. cli_main: argv 预处理 + atexit register + app() 调用 + ImportError 兜底
"""
import os as _os
import sys as _sys

_BOOT_BANNER_COMMANDS = {"add", "scan", "fetch", "low", "high", "info", "trend", "find"}


def _maybe_print_boot_banner() -> None:
    if _os.environ.get("KAN_NO_BOOT_BANNER") == "1":
        return
    if not _sys.stderr.isatty():
        return
    if len(_sys.argv) < 2:
        return
    if _sys.argv[1] not in _BOOT_BANNER_COMMANDS:
        return
    if "--help" in _sys.argv[2:] or "-h" in _sys.argv[2:]:
        return
    _sys.stderr.write("⏳ 启动中...\r")
    _sys.stderr.flush()


_maybe_print_boot_banner()

from kan.app import app  # noqa: E402


def cli_main() -> None:
    """CLI entry point · sys.argv 预处理后再交给 typer。

    实现细节：_auto_install_completion 推迟到命令完成后（atexit）执行，
    防止其 stderr 输出跟 add 命令的 Live Display spinner 共享 stderr 时
    buffer 竞争（用户可能看不到 spinner 动画的 corner case）。

    v0.0.4.4: 顶层 try/except (ImportError, ModuleNotFoundError) 兜底 ·
    防 v0.0.4.3 装机崩抛 60+ 行 traceback 地狱 · 给用户清晰 reinstall 引导。
    """
    import atexit

    try:
        from kan.cli.atexit import _auto_install_completion, _check_updates_atexit
        from kan.cli.helpers import _normalize_help_args, _normalize_streak_args
        from kan.storage.paths import migrate_legacy

        migrate_legacy()
        _normalize_help_args()
        _normalize_streak_args()
        # 命令结束后才装补全 + 检查更新 · 不抢主流程 stderr
        # atexit LIFO 执行 · 后注册先跑 · update 检查先于 completion install
        atexit.register(_auto_install_completion)
        atexit.register(_check_updates_atexit)
        try:
            app()
        except Exception as e:
            # 顶层 WatchlistCorruptError catch · 改架构后 load_watchlist 不再 sys.exit
            # 避免 list / scan / fetch 等命令在损坏场景下抛 traceback
            from kan.storage.watchlist import WatchlistCorruptError
            if isinstance(e, WatchlistCorruptError):
                _sys.stderr.write(
                    f"❌ {e}\n"
                    f"   跑 `kan clear --yes` 强制重置(会丢全部自选 · 不可恢复)\n"
                )
                _sys.exit(1)
            raise
    except (ImportError, ModuleNotFoundError) as e:
        # v0.0.4.4: 装机不完整时给清晰行动建议 · 不抛 traceback
        # 用 stdlib stderr write · 不依赖 rich (rich 可能正是 ImportError 来源)
        _sys.stderr.write(
            f"\n❌ kan 安装文件不完整 ({type(e).__name__}: {str(e)[:120]})\n"
            "\n这通常发生在 kan update 升级中途被打断 · 或上游 deps 版本错位。\n"
            "请运行以下命令之一手动 reinstall:\n\n"
            "  uv tool install manmankan --reinstall\n"
            "  pipx install manmankan --force\n"
            "  pip install --force-reinstall manmankan\n"
            "\n如问题持续 · 请到 https://github.com/piklen/manmankan/issues 报告。\n"
        )
        _sys.exit(2)

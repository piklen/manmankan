"""kan CLI runtime entry point.

console-script import-time guard lives in kan/_entry.py. This module keeps the
runtime wiring importable for tests and for Typer command registration.
"""
import sys as _sys

from kan.app import app


def cli_main() -> None:
    """CLI entry point · sys.argv 预处理后再交给 typer。

    背景: 顶层 try/except (ImportError, ModuleNotFoundError) 兜底 ·
    防安装不完整时抛 60+ 行 traceback · 给用户清晰 reinstall 引导。
    """
    import atexit

    try:
        from kan.cli.atexit import _check_updates_atexit
        from kan.cli.helpers import _normalize_help_args, _normalize_streak_args
        from kan.storage.stock_names_refresh import maybe_start_stock_names_refresh

        maybe_start_stock_names_refresh()
        _normalize_help_args()
        _normalize_streak_args()
        # 环境设置只由 kan setup / completion / mcp install 主动触发。
        atexit.register(_check_updates_atexit)
        try:
            app()
        except Exception as e:
            # 顶层兜底 WatchlistCorruptError · load_watchlist 用 raise 而非 sys.exit ·
            # 由顶层统一转友好提示 · 避免 list / scan / fetch 在损坏场景抛 traceback
            from kan.storage.watchlist import WatchlistCorruptError
            if isinstance(e, WatchlistCorruptError):
                _sys.stderr.write(
                    f"❌ {e}\n"
                    f"   跑 `kan clear --yes` 强制重置(会丢全部自选 · 不可恢复)\n"
                )
                _sys.exit(1)
            raise
    except (ImportError, ModuleNotFoundError) as e:
        # 背景: 装机不完整时给清晰行动建议 · 不抛 traceback
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

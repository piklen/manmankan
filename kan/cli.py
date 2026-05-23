"""kan CLI entry point · 极薄入口。

职责仅三件：
  1. re-export `app` (向后兼容旧 import path `from kan.cli import app`)
  2. cli_main: argv 预处理 + atexit register + app() 调用
  3. 文件末尾触发子模块 import 让 @app.command() 装饰器执行 · 注册所有 12 个命令

实际命令实现拆到 cli_*_cmds.py · 共享 helper 在 cli_helpers.py · atexit hook 在 cli_atexit.py。
拆分蓝图详见 docs/v0.0.3-cli-refactor-plan.md。
"""
import os as _os
import sys as _sys

_BOOT_BANNER_COMMANDS = {"add", "scan", "fetch", "low", "high", "info", "trend"}


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
        from kan.cli_atexit import _auto_install_completion, _check_updates_atexit
        from kan.cli_helpers import _normalize_help_args, _normalize_streak_args
        from kan.paths import migrate_legacy

        migrate_legacy()
        _normalize_help_args()
        _normalize_streak_args()
        # 命令结束后才装补全 + 检查更新 · 不抢主流程 stderr
        # atexit LIFO 执行 · 后注册先跑 · update 检查先于 completion install
        atexit.register(_auto_install_completion)
        atexit.register(_check_updates_atexit)
        app()
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


# 触发子模块装饰器执行 · MUST be at module top-level (不能在 cli_main 函数体内)
# 让 `from kan.cli import app` / `import kan.cli` 拿到完整命令列表 · 测试也依赖这点
from kan import (  # noqa: E402, F401
    cli_config_cmds,
    cli_meta_cmds,
    cli_scan_cmds,
    cli_theme_cmds,
    cli_trend_cmds,
    cli_watchlist_cmds,
)

"""kan CLI entry point · 极薄入口。

职责仅三件：
  1. re-export `app` (向后兼容旧 import path `from kan.cli import app`)
  2. cli_main: argv 预处理 + atexit register + app() 调用
  3. 文件末尾触发子模块 import 让 @app.command() 装饰器执行 · 注册所有 12 个命令

实际命令实现拆到 cli_*_cmds.py · 共享 helper 在 cli_helpers.py · atexit hook 在 cli_atexit.py。
拆分蓝图详见 docs/v0.0.3-cli-refactor-plan.md。
"""
from kan.app import app


def cli_main() -> None:
    """CLI entry point · sys.argv 预处理后再交给 typer。

    实现细节：_auto_install_completion 推迟到命令完成后（atexit）执行，
    防止其 stderr 输出跟 add 命令的 Live Display spinner 共享 stderr 时
    buffer 竞争（用户可能看不到 spinner 动画的 corner case）。
    """
    import atexit

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


# 触发子模块装饰器执行 · MUST be at module top-level (不能在 cli_main 函数体内)
# 让 `from kan.cli import app` / `import kan.cli` 拿到完整命令列表 · 测试也依赖这点
from kan import (  # noqa: E402, F401
    cli_meta_cmds,
    cli_scan_cmds,
    cli_trend_cmds,
    cli_watchlist_cmds,
)

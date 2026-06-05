"""atexit hooks · 主命令完成后跑：环境设置提示 + 更新检查。

这两个 hook 必须满足：
  1. 不影响主命令 exit code（任何异常都吞掉）
  2. 非 TTY 静默（pipe / CI 场景不弹 prompt）
  3. 失败不重试（避免每次启动都 retry 失败的网络 / shell 检测）
  4. shell completion 调用静默（typer 注入的脚本设置 _KAN_COMPLETE 时调
     kan 子进程拿候选项 · 任何 stdout 写入会被 zsh `eval $(...)` 抓走当
     _arguments spec 解析 · 曾报 `comparguments:327: invalid argument`）
"""
import contextlib
import os
import sys

import typer

from kan.infra.log import debug_log


def _is_shell_completion_run() -> bool:
    """当前进程是不是被 typer/click shell completion 触发的子调用。

    typer 注入到 shell rc 的脚本固定设置两个环境变量：
      - `_KAN_COMPLETE` = "complete_zsh" / "complete_bash" / "complete_fish" / ...
      - `_TYPER_COMPLETE_ARGS` = 用户当前已输入的命令片段

    任一存在即表明这次是 completion 调用，atexit hook 必须保持完全静默
    （包括 stdout 和 stderr · zsh `eval $(...)` 抓 stdout，但 stderr 在
    某些场景也会被前端工具解析）。检测两个 env var 是冗余护栏，覆盖未来
    typer 上游可能的命名变更。
    """
    return bool(
        os.environ.get("_KAN_COMPLETE")
        or os.environ.get("_TYPER_COMPLETE_ARGS")
    )


def _is_interactive_session() -> bool:
    """stdout 和 stderr 都是 tty 才算可交互。

    旧实现用 `stdout.isatty() or stderr.isatty()` —— 太宽松：completion 时
    stdout 被 pipe 抓走但 stderr 仍是 tty，导致 hook 误判为可交互、把 prompt
    文本灌进 stdout 污染上游捕获流。改成 AND 后只要任一被重定向就跳过。
    """
    return sys.stdout.isatty() and sys.stderr.isatty()


def _auto_install_completion() -> None:
    """首次交互启动提示用户配置 shell completion / MCP · 不静默改环境。

    用户视角："uv tool install manmankan" 后第一次跑任意 kan 命令，结束时给一次
    本机环境设置提示。用户确认后才写 shell rc / MCP 客户端配置。

    跳过条件（防止 surprising behavior）：
      - 环境变量 KAN_NO_ENV_SETUP_PROMPT=1 或 KAN_NO_COMPLETION_AUTOINSTALL=1
      - completion 与 MCP 都已安装 / 拒绝 / 无可检测目标
      - 非 TTY 环境（pipe / CI / docker · 不要在脚本场景改 shell rc）
    """
    # shell completion 子调用绝不能写 shell rc 文件（用户没主动跑 install）
    if _is_shell_completion_run():
        return

    if (
        os.environ.get("KAN_NO_ENV_SETUP_PROMPT") == "1"
        or os.environ.get("KAN_NO_COMPLETION_AUTOINSTALL") == "1"
    ):
        return

    # 非 TTY (pipe / CI) 不自动改 shell rc 文件
    if not _is_interactive_session():
        return

    try:
        from rich.console import Console

        from kan.cli.helpers import _detect_shell_fallback
        from kan.cli.setup_helpers import (
            completion_done,
            install_shell_completion,
            mark_completion_setup,
            mark_mcp_setup,
            mark_setup_skip,
            mcp_done,
            mcp_install_succeeded,
            setup_skip_recent,
        )
        from kan.mcp.install import detect_clients, install_clients
    except Exception as e:
        debug_log(__name__, "import environment setup helpers", e)
        return

    if setup_skip_recent():
        return

    shell = _detect_shell_fallback()
    completion_needed = shell is not None and not completion_done()
    detected_clients = detect_clients()
    mcp_needed = bool(detected_clients) and not mcp_done()

    if not completion_needed and not mcp_needed:
        return

    try:
        Console(stderr=True).print(
            "\n[bold]manmankan 可完成本机环境设置[/bold]\n"
            f"[dim]completion: {shell or '未检测到'} · "
            f"MCP clients: {', '.join(detected_clients) if detected_clients else '未检测到'}[/dim]\n"
            "[dim]选 y=全部安装，c=只装补全，m=只注册 MCP，n=不再提示，skip=稍后[/dim]"
        )
        choice = typer.prompt(
            "现在设置吗? [y/c/m/n/skip]",
            default="skip",
            show_default=True,
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    except Exception as e:
        debug_log(__name__, "environment setup prompt", e)
        return

    if choice in ("skip", "s", ""):
        mark_setup_skip()
        return

    if choice in ("n", "no"):
        if completion_needed:
            mark_completion_setup(False)
        if mcp_needed:
            mark_mcp_setup(False)
        return

    install_completion = choice in ("y", "yes", "c", "completion") and completion_needed
    install_mcp = choice in ("y", "yes", "m", "mcp") and mcp_needed
    console = Console(stderr=True)

    if install_completion:
        result = install_shell_completion(shell)
        if result.status == "failed":
            console.print(f"[dim]completion 安装失败: {result.detail}[/dim]")
            mark_completion_setup(False)
        else:
            console.print(f"[dim]completion 已安装: {result.target}[/dim]")

    if install_mcp:
        results = install_clients(detected_clients)
        statuses = [r.status for r in results]
        if mcp_install_succeeded(statuses):
            mark_mcp_setup(True)
            console.print(f"[dim]MCP 已注册: {', '.join(detected_clients)}[/dim]")
        else:
            failed = [r.client for r in results if r.status == "failed"]
            mark_mcp_setup(False)
            console.print(
                "[dim]MCP 部分注册失败: "
                + ", ".join(failed)
                + " · 可跑 `kan mcp install --dry-run` 查看[/dim]"
            )


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
    # shell completion 子调用必须完全静默 · 防 typer.prompt 污染 zsh eval 抓取流
    # (曾报 `_arguments:comparguments:327: invalid argument`)
    if _is_shell_completion_run():
        return

    if os.environ.get("KAN_NO_UPDATE_CHECK") == "1":
        return
    # 用户已经在跑 kan update · atexit 不重复检查防双重升级 / 双重 prompt
    if len(sys.argv) >= 2 and sys.argv[1] == "update":
        return
    # 非 TTY (pipe / CI) 不弹 prompt 不打扰
    if not _is_interactive_session():
        return

    try:
        from datetime import date, timedelta

        from rich.console import Console

        from kan.data import updater
        from kan.storage import config

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
            status, msg = updater.run_upgrade(console=console)
            if status == "success":
                console.print(
                    f"[dim]✅ 已升级到 v{info.latest} · 下次跑 kan 命令生效[/dim]"
                )
                console.print(
                    "[dim]   建议开新终端窗口跑下次命令 · 当前终端有旧进程缓存[/dim]"
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
                with contextlib.suppress(OSError):
                    config.save(cfg)
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
            with contextlib.suppress(OSError):
                config.save(cfg)
            console.print("[green]✅ 偏好已保存 · 立即升级中...[/green]")
            status, msg = updater.run_upgrade(console=console)
            if status == "success":
                console.print(
                    f"[green]✅ 已升级到 v{info.latest} · 下次跑 kan 命令生效[/green]"
                )
                console.print(
                    "[dim]   建议开新终端窗口跑下次命令 · 当前终端有旧进程缓存[/dim]"
                )
            else:
                console.print(
                    "[red]❌ 升级失败 (主命令不受影响 · 可手动 kan update 重试)[/red]"
                )
                console.print(f"[dim]{msg}[/dim]")
        elif choice in ("n", "no"):
            cfg["auto_update"] = False
            with contextlib.suppress(OSError):
                config.save(cfg)
            console.print(
                "[dim]✅ 偏好已保存 · 不再自动升级 · "
                "以后跑 [bold]kan update[/bold] 手动升级[/dim]"
            )
        else:
            # skip / 其他 · 不写偏好 · 下次再问
            console.print(
                "[dim]跳过 · 跑 [bold]kan update[/bold] 升级 · 下次启动时再询问偏好[/dim]"
            )
    except Exception as e:
        # atexit hook 不能让主命令受影响 · 任何异常都吞掉
        # 加 debug log 防完全无诊断
        debug_log(__name__, "update check atexit handler", e)

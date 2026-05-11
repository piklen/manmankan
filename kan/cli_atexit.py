"""atexit hooks · 主命令完成后跑：自动补全安装 + 更新检查。

这两个 hook 必须满足：
  1. 不影响主命令 exit code（任何异常都吞掉）
  2. 非 TTY 静默（pipe / CI 场景不弹 prompt）
  3. 失败不重试（避免每次启动都 retry 失败的网络 / shell 检测）
"""
import contextlib

import typer

from kan.cli_helpers import _VALID_SHELLS, _detect_shell_fallback


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
    except Exception:
        # atexit hook 不能让主命令受影响 · 任何异常都吞掉
        pass

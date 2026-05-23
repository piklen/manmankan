"""元命令：自身升级 / 卸载 / shell 补全。

这一组命令的特征：操作 kan 自身的安装 / 配置 / shell 集成 · 不涉及股票数据。
"""
from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _VALID_SHELLS,
    _detect_install_method,
    _detect_shell_fallback,
    _human_size,
    _print_err,
    _safe_error_msg,
)


@app.command()
def update(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认 · 用于脚本 / CI")] = False,
    check_only: Annotated[bool, typer.Option("--check", help="仅检查 · 不升级")] = False,
) -> None:
    """检查并升级到最新版本

    工作流程:
      1. 实时查 PyPI 拿最新版本号 (force=True 跳过 daily cache)
      2. 跟当前版本对比
      3. 有新版 + 用户 confirm → 调对应包管理器 upgrade (uv tool / pipx / pip)
      4. 失败显示友好错误 + 退出码 1

    用法:
      kan update              检查并升级 (会 prompt 确认)
      kan update -y           跳过确认 · 用于脚本
      kan update --check      仅检查不升级
    """
    from rich.console import Console

    from kan.data import updater

    console = Console()

    info = updater.check_for_updates(force=True)

    if info.latest is None:
        _print_err("[yellow]⚠️ 无法连接 PyPI · 请检查网络后重试[/yellow]")
        raise typer.Exit(1)

    console.print(f"当前版本: [cyan]v{info.current}[/cyan]")
    console.print(f"最新版本: [cyan]v{info.latest}[/cyan]")

    if not info.has_update:
        console.print("[green]✅ 已是最新版本[/green]")
        return

    console.print(
        "更新说明: https://github.com/piklen/manmankan/blob/main/CHANGELOG.md"
    )

    if check_only:
        console.print(
            f"[dim]跑 [bold]kan update[/bold] 升级到 v{info.latest}[/dim]"
        )
        return

    if not yes and not typer.confirm(f"是否升级到 v{info.latest}?"):
        console.print("[dim]已取消[/dim]")
        return

    install = updater.detect_install_method()
    console.print(
        f"[dim]检测到安装方式: {install.name} · 升级中...[/dim]"
    )

    status, msg = updater.run_upgrade(console=console)
    if status == "success":
        console.print(
            f"[green]✅ 已升级到 v{info.latest}[/green] "
            f"[dim](方式: {msg} · 下次跑 kan 命令生效)[/dim]"
        )
        console.print(
            "[dim]   建议开新终端窗口跑下次命令 · 当前终端有旧进程缓存[/dim]"
        )
    else:
        _print_err("[red]❌ 升级失败[/red]")
        _print_err(f"[dim]{msg}[/dim]")
        raise typer.Exit(1)


@app.command()
def uninstall(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认 · 用于脚本 / CI")] = False,
    keep_data: Annotated[bool, typer.Option("--keep-data", help="只输出包卸载提示 · 不删数据")] = False,
) -> None:
    """卸载 kan: 删除所有本地数据 + 输出软件包卸载命令。

    数据清理范围（除非 --keep-data）:
      - ~/.local/share/kan/ (XDG 数据)
      - ~/.kan/ (legacy 数据 · 如存在)

    软件包本身不会自动卸载（chicken-and-egg · kan 无法删自己运行的进程）。
    本命令会检测安装方式并打印对应卸载指令，请手动执行。
    """
    import shutil
    from pathlib import Path

    from rich.console import Console

    from kan.storage.paths import BASE_DIR

    console = Console()
    legacy_dir = Path.home() / ".kan"

    # 1. 列出会删的路径 + 大小
    targets: list[tuple[str, Path, int]] = []
    for label, path in (("XDG 数据", BASE_DIR), ("Legacy 数据", legacy_dir)):
        if path.exists():
            try:
                size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            except OSError:
                size = 0
            targets.append((label, path, size))

    # 2. 检测安装方式
    install = _detect_install_method()

    # 3. 显示数据 + 安装方式
    if not keep_data:
        if targets:
            console.print("[bold]将删除以下数据目录:[/bold]")
            for label, path, size in targets:
                console.print(f"  · {path} ({label} · {_human_size(size)})")
        else:
            console.print("[dim]没有数据目录需要清理[/dim]")
        console.print()

    console.print(
        "[bold yellow]软件包本身不会自动卸载[/bold yellow]"
        "（chicken-and-egg · kan 无法删除正在运行自己的 Python 进程）"
    )
    console.print(f"检测到安装方式: [cyan]{install['name']}[/cyan]")
    console.print(f"请手动运行: [bold]{install['cmd']}[/bold]")
    alts = install.get("alts")
    if alts:
        console.print("[dim]或（如果上面命令不适用）:[/dim]")
        for alt in alts:
            console.print(f"  [dim]{alt}[/dim]")
    console.print()

    # 4. keep_data 模式 · 早返回
    if keep_data:
        return

    # 5. 无数据 · 无需确认
    if not targets:
        return

    # 6. 确认
    if not yes and not typer.confirm("确认删除上面所有数据吗?"):
        console.print("[dim]已取消[/dim]")
        return

    # 7. 删除
    deleted = 0
    for _label, path, _size in targets:
        try:
            shutil.rmtree(path)
            console.print(f"  ✅ 已删除 {path}")
            deleted += 1
        except Exception as e:
            _print_err(f"  ❌ 删除 {path} 失败: {_safe_error_msg(e)}")

    console.print()
    if deleted == len(targets):
        console.print(
            f"[green]✅ kan 数据已完全清理 ({deleted} 个目录)[/green] · "
            "软件包请按上面提示自卸"
        )
    else:
        console.print(
            f"[yellow]⚠️ 部分清理 ({deleted}/{len(targets)} 成功) · "
            "请检查权限或手动 rm[/yellow]"
        )


@app.command(name="completion")
def completion_cmd(
    action: Annotated[str, typer.Argument(help="install")],
    shell: Annotated[
        str | None,
        typer.Argument(help="zsh / bash / fish / powershell · 不传时自动检测"),
    ] = None,
) -> None:
    """安装 shell 命令补全脚本（mac/linux/windows 全平台）。

    支持的 shell:
      - mac/linux: zsh / bash / fish
      - windows: powershell / pwsh

    用法:
        kan completion install         # 自动检测 shell · 安装补全脚本
        kan completion install zsh     # 显式指定 shell

    安装后的效果:
        kan s<Tab>      → kan scan
        kan <Tab>       → 列出所有命令（add / scan / list / info / ...）
        kan trend --<Tab> → 列出所有 --down / --up / --latest / --candle 等

    安装后请重启终端或 source 配置文件让补全生效。
    脚本路径会显示在输出中 · 想自定义可 cat 该路径查看脚本内容。
    """
    if action != "install":
        typer.echo(f"❌ 未知动作: {action} · 当前只支持 install", err=True)
        raise typer.Exit(1)

    if shell is None:
        shell = _detect_shell_fallback()
        if shell is None:
            typer.echo(
                "❌ 无法自动检测 shell · 请显式指定: "
                "kan completion install [zsh|bash|fish|powershell]",
                err=True,
            )
            raise typer.Exit(1)

    if shell not in _VALID_SHELLS:
        typer.echo(
            f"❌ 不支持的 shell: {shell} · 支持: {', '.join(_VALID_SHELLS)}",
            err=True,
        )
        raise typer.Exit(1)

    try:
        from typer.completion import install
        installed_shell, path = install(shell=shell, prog_name="kan")
    except Exception as e:
        typer.echo(f"❌ 安装失败: {_safe_error_msg(e)}", err=True)
        raise typer.Exit(1) from None

    from rich.console import Console
    console = Console()
    console.print(
        f"[green]✅ {installed_shell} 补全脚本已安装到[/green] [cyan]{path}[/cyan]"
    )
    console.print()
    console.print("[yellow]让补全生效（任选其一）：[/yellow]")
    if installed_shell == "zsh":
        console.print("  1) 重启终端")
        console.print("  2) [cyan]source ~/.zshrc[/cyan]")
    elif installed_shell == "bash":
        console.print("  1) 重启终端")
        console.print("  2) [cyan]source ~/.bashrc[/cyan]")
    elif installed_shell == "fish":
        console.print("  1) 重启终端 (fish 自动加载 completions/)")
    elif installed_shell in ("powershell", "pwsh"):
        console.print("  1) 重启 PowerShell")
        console.print("  2) [cyan]. $PROFILE[/cyan]")
    console.print()
    console.print("[dim]之后试 [bold]kan s[/bold] + Tab 看效果[/dim]")

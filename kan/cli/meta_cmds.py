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
from kan.cli.setup_helpers import install_shell_completion


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
        # 区分 "齐平 PyPI" 与 "本地超前(dev 安装 / 预发版)" · 不再让两者共享"已是最新"文案
        if updater.is_newer(info.current, info.latest):
            console.print(
                f"[green]✅ 当前 v{info.current} 已超前 PyPI 最新发布版 v{info.latest}"
                " · 通常是开发版 / editable install[/green]"
            )
        else:
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

    status, msg = updater.run_upgrade(console=console, target_version=info.latest)
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

    result = install_shell_completion(shell)
    if result.status == "failed":
        typer.echo(f"❌ 安装失败: {result.detail}", err=True)
        raise typer.Exit(1)

    from rich.console import Console
    console = Console()
    console.print(
        f"[green]✅ {result.shell} 补全脚本已安装到[/green] [cyan]{result.target}[/cyan]"
    )
    console.print()
    console.print("[yellow]让补全生效（任选其一）：[/yellow]")
    if result.shell == "zsh":
        console.print("  1) 重启终端")
        console.print("  2) [cyan]source ~/.zshrc[/cyan]")
    elif result.shell == "bash":
        console.print("  1) 重启终端")
        console.print("  2) [cyan]source ~/.bashrc[/cyan]")
    elif result.shell == "fish":
        console.print("  1) 重启终端 (fish 自动加载 completions/)")
    elif result.shell in ("powershell", "pwsh"):
        console.print("  1) 重启 PowerShell")
        console.print("  2) [cyan]. $PROFILE[/cyan]")
    console.print()
    console.print("[dim]之后试 [bold]kan s[/bold] + Tab 看效果[/dim]")


@app.command()
def setup(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="使用自动检测结果，跳过交互确认")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只预览，不写 shell/MCP 配置")] = False,
    mcp_clients: Annotated[
        str | None,
        typer.Option(
            "--mcp-clients",
            help="MCP 目标: auto / all / none / 逗号分隔 client 列表",
        ),
    ] = None,
    no_completion: Annotated[bool, typer.Option("--no-completion", help="跳过 shell 补全")] = False,
    no_mcp: Annotated[bool, typer.Option("--no-mcp", help="跳过 MCP 客户端注册")] = False,
) -> None:
    """交互式配置本机环境：shell 补全 + MCP 客户端。"""
    from rich.console import Console
    from rich.table import Table

    from kan.cli.setup_helpers import (
        mark_completion_setup,
        mark_mcp_setup,
        mcp_install_succeeded,
        parse_mcp_client_selection,
    )
    from kan.mcp.install import SUPPORTED_CLIENTS, detect_clients, install_clients

    console = Console()
    detected_shell = _detect_shell_fallback()
    detected_clients = detect_clients()

    console.print("[bold]manmankan 本机环境设置[/bold]")
    console.print(f"shell: [cyan]{detected_shell or '未检测到'}[/cyan]")
    console.print(
        "MCP clients: "
        + ("[cyan]" + ", ".join(detected_clients) + "[/cyan]" if detected_clients else "[dim]未检测到[/dim]")
    )

    install_completion_step = False
    if not no_completion and detected_shell is not None:
        install_completion_step = yes or typer.confirm(
            f"安装 {detected_shell} 命令补全?",
            default=True,
        )

    selected_clients: list[str] = []
    if not no_mcp:
        default_selection = mcp_clients or ("auto" if detected_clients else "none")
        if yes:
            selection = default_selection
        else:
            selection = typer.prompt(
                "MCP clients [auto/all/none/csv]",
                default=default_selection,
                show_default=True,
            )
        try:
            selected_clients = parse_mcp_client_selection(selection, detected_clients)
        except ValueError as e:
            _print_err(f"❌ {e}")
            raise typer.Exit(2) from None

    if install_completion_step:
        completion_result = install_shell_completion(detected_shell, dry_run=dry_run)
        if completion_result.status == "failed":
            _print_err(f"❌ completion 安装失败: {completion_result.detail}")
        else:
            console.print(
                f"[green]✅ completion[/green] {completion_result.status}: "
                f"[cyan]{completion_result.target}[/cyan]"
            )
            if not dry_run:
                mark_completion_setup(True)
    elif no_completion:
        console.print("[dim]跳过 completion[/dim]")
    else:
        if not dry_run:
            mark_completion_setup(False)
        console.print("[dim]已跳过 completion，之后仍可跑 `kan completion install`[/dim]")

    if selected_clients:
        results = install_clients(selected_clients, dry_run=dry_run)
        table = Table(title="MCP 注册结果")
        table.add_column("client", style="cyan")
        table.add_column("status")
        table.add_column("target", overflow="fold")
        table.add_column("detail", overflow="fold")
        for result in results:
            table.add_row(result.client, result.status, result.target, result.detail)
        console.print(table)
        if not dry_run and mcp_install_succeeded([r.status for r in results]):
            mark_mcp_setup(True)
    elif no_mcp:
        console.print("[dim]跳过 MCP[/dim]")
    else:
        if not dry_run:
            mark_mcp_setup(False)
        console.print(
            "[dim]未选择 MCP client，之后可跑 "
            f"`kan mcp install --client <client>`；支持: {', '.join(SUPPORTED_CLIENTS)}[/dim]"
        )

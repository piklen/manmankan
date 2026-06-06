"""`kan group` 子命令组 · 多分组管理。

6 子命令:
- create <name>          建组
- list                   列所有组 (含 default 标记 + 股数)
- rename <old> <new>     重命名 (default 指针同步)
- delete <name>          删除 (default 组保护 · 必须先 default 切换)
- default <name>         切换 default 组
- copy <src> <dst>       复制整组 (dst 必须不存在 · 防误覆盖)

跨组移动单股见 `kan move` (独立顶级命令 · 不在 group 子命令组里 · 跟 Unix mv 同形)。
"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err
from kan.storage.watchlist import (
    GroupExistsError,
    GroupNotFoundError,
    GroupProtectedError,
    copy_group,
    create_group,
    delete_group,
    list_groups,
    rename_group,
    set_default_group,
)

group_app = typer.Typer(
    name="group",
    help="多分组管理(自选 / 持仓 / 短线池 ... · 自定义组名)",
    no_args_is_help=True,
)
app.add_typer(group_app, name="group")


@group_app.command("list")
def list_cmd() -> None:
    """列出所有组(显示股数 + default 标记)。"""
    from rich.console import Console
    from rich.table import Table

    groups = list_groups()
    if not groups:
        # 理论不发生 (load_grouped_watchlist 保证至少有 default 组)
        typer.echo("没有任何组 · 跑 `kan add 600519` 自动创建 default 组")
        return

    table = Table(title=f"自选股分组 · 共 {len(groups)} 组")
    table.add_column("组名", style="cyan")
    table.add_column("股数", justify="right")
    table.add_column("标记", style="dim")
    for name, count, is_default in groups:
        mark = "默认" if is_default else ""
        table.add_row(name, str(count), mark)
    Console().print(table)


@group_app.command("create")
def create_cmd(
    name: Annotated[str, typer.Argument(help="新组名 (如 持仓 / 短线池 / 长线池)")],
) -> None:
    """新建一个组(空)。"""
    try:
        actual = create_group(name)
    except GroupExistsError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    typer.echo(
        f"✅ 已创建组「{actual}」· "
        f"加股票:`kan add 600519 --group {actual}`"
    )


@group_app.command("rename")
def rename_cmd(
    old: Annotated[str, typer.Argument(help="原组名")],
    new: Annotated[str, typer.Argument(help="新组名")],
) -> None:
    """重命名组(default 指针自动同步)。"""
    try:
        actual = rename_group(old, new)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except GroupExistsError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    typer.echo(f"✅ 已将组「{old}」重命名为「{actual}」")


@group_app.command("delete")
def delete_cmd(
    name: Annotated[str, typer.Argument(help="要删除的组名")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="跳过二次确认 · 用于脚本"),
    ] = False,
) -> None:
    """删除组(default 组保护 · 必须先 `kan group default <其他>` 切换)。"""
    try:
        # 先 peek 股数 + default 状态 (delete_group 自己会再校验 · 这里只为确认提示)
        peek = {n: (count, is_default) for n, count, is_default in list_groups()}
        if name not in peek:
            _print_err(f"❌ 组「{name}」不存在")
            raise typer.Exit(2)
        count, is_default = peek[name]
        if is_default:
            _print_err(
                f"❌ 组「{name}」是默认组 · 不能删除 · "
                f"先 `kan group default <其他组>` 切换"
            )
            raise typer.Exit(2)
        if count > 0 and not yes:
            confirm = typer.confirm(
                f"组「{name}」有 {count} 只股票 · 删除后不可恢复 · 确定?"
            )
            if not confirm:
                typer.echo("已取消")
                return
        removed = delete_group(name)
    except GroupProtectedError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    typer.echo(f"✅ 已删除组「{name}」(连带 {removed} 只股票)")


@group_app.command("default")
def default_cmd(
    name: Annotated[
        str | None,
        typer.Argument(help="要设为 default 的组名 (省略则显示当前 default)"),
    ] = None,
) -> None:
    """切换 default 组(不带参显示当前 default · 不带 --group 的命令都走 default)。"""
    if name is None:
        from kan.storage.watchlist import get_default_group

        typer.echo(f"当前 default 组:「{get_default_group()}」")
        return
    try:
        old = set_default_group(name)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    if old == name:
        typer.echo(f"ℹ️  「{name}」本来就是 default 组 · 无变化")
    else:
        typer.echo(f"✅ default 组:「{old}」→「{name}」")


@group_app.command("copy")
def copy_cmd(
    src: Annotated[str, typer.Argument(help="源组名")],
    dst: Annotated[str, typer.Argument(help="目标组名 (必须不存在 · 防误覆盖)")],
) -> None:
    """复制整组到新组(dst 必须不存在 · 想覆盖先 `kan group delete dst`)。"""
    try:
        count = copy_group(src, dst)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except GroupExistsError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    typer.echo(f"✅ 已复制「{src}」→「{dst}」({count} 只股票)")

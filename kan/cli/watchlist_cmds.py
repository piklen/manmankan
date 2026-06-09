"""自选股管理命令：add / remove / list / import / clear。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err
from kan.cli.watchlist_add import run_add
from kan.cli.watchlist_list import run_list_stocks
from kan.cli.watchlist_remove import run_remove


@app.command()
def add(
    symbols: Annotated[
        list[str] | None,
        typer.Argument(help="股票代码或名称（如 600519 茅台）", show_default=False),
    ] = None,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="按申万行业批量添加该行业全部成分股"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="按题材批量添加该题材全部成分股"),
    ] = None,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="加到指定组 (默认 default 组 · 跑 kan group list 查看)"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="跳过二次确认 · 慎用"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="预览批量添加结果，不写入自选股"),
    ] = False,
    fetch: Annotated[
        bool,
        typer.Option("--fetch", help="添加成功后立即拉取新增股票 K 线缓存"),
    ] = False,
) -> None:
    """添加自选股（支持代码或名称搜索 · --industry / --theme 批量加 · --group 加到指定组）"""
    run_add(
        symbols,
        industry=industry,
        theme=theme,
        group=group,
        yes=yes,
        dry_run=dry_run,
        fetch=fetch,
    )


@app.command()
def remove(
    symbols: Annotated[
        list[str] | None,
        typer.Argument(help="股票代码或名称（支持多只）", show_default=False),
    ] = None,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="按申万行业批量移除自选里属于该行业的股票"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="按题材批量移除自选里属于该题材的股票"),
    ] = None,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="从指定组移除 (默认 default 组)"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="跳过二次确认 · 慎用"),
    ] = False,
) -> None:
    """移除自选股（代码或名称 · --industry / --theme 批量 · --group 指定组）"""
    run_remove(symbols, industry=industry, theme=theme, group=group, yes=yes)


@app.command(name="list")
def list_stocks(
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="只列自选里属于该申万行业的股票"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="只列自选里属于该题材的股票"),
    ] = None,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="看指定组 (默认 default 组)"),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="列所有组拼起来 (按组分段显示)"),
    ] = False,
) -> None:
    """查看自选列表 (--group 看指定组 · --all 看所有组 · --industry/--theme 过滤行业/题材)"""
    run_list_stocks(industry=industry, theme=theme, group=group, show_all=show_all)


@app.command(name="import")
def import_csv(
    path: Annotated[str, typer.Argument(help="CSV 文件路径")],
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="导入到指定组 (默认 default 组)"),
    ] = None,
) -> None:
    """从 CSV 批量导入自选股 (--group 导入到指定组)"""
    from kan.storage.watchlist import GroupNotFoundError
    from kan.storage.watchlist import import_csv as do_import

    try:
        success, skipped, errors = do_import(path, group=group)
    except GroupNotFoundError as e:
        typer.echo(f"  ❌ {e}", err=True)
        raise typer.Exit(2) from None
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"  ❌ {e}", err=True)
        raise typer.Exit(1) from None
    suffix = "" if not group else f" → 「{group}」组"
    typer.echo(f"导入完成{suffix}：✅ 新增 {success} · ⏭ 跳过 {skipped} · ❌ 失败 {len(errors)}")
    for err in errors:
        typer.echo(f"  ❌ {err}", err=True)


@app.command(name="clear")
def clear_watchlist(
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="清空指定组 (默认 default 组 · 不影响其他组)"),
    ] = None,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="跳过二次确认 · 用于脚本 / CI"
    ),
) -> None:
    """清空自选列表 (--group 只清指定组 · 其他组保留)"""
    from kan.storage.paths import WATCHLIST_PATH
    from kan.storage.watchlist import (
        GroupNotFoundError,
        WatchlistCorruptError,
        clear,
        load_watchlist,
    )

    try:
        wl = load_watchlist(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except WatchlistCorruptError as e:
        if not yes:
            typer.echo(
                f"❌ {e}\n"
                f"   跑 `kan clear --yes` 强制重置(会丢全部分组 · 不可恢复)",
                err=True,
            )
            raise typer.Exit(1) from None
        import contextlib

        with contextlib.suppress(FileNotFoundError):
            WATCHLIST_PATH.unlink()
        typer.echo("⚠️  原 watchlist.json 已损坏 · 已删除并重置为空 (所有组清空)")
        return

    group_label = f"「{group}」" if group else "自选"
    if not wl.stocks:
        typer.echo(f"{group_label}组已经是空的")
        return

    if not yes:
        confirm = typer.confirm(f"确定要清空 {group_label}组 {len(wl.stocks)} 只股票吗？")
        if not confirm:
            typer.echo("已取消")
            return

    count = clear(group=group)
    typer.echo(f"已清空 {group_label}组 {count} 只股票")

"""`kan move` + `kan export` 顶级命令 · 多分组管理配套 · v0.0.6.1 引入。

- `kan move <symbol> <src> <dst>`:跨组移动单股(支持代码或名称模糊搜)。
  - src/dst 必须存在(不自动建组 · 防 typo 灾难)
  - 同股已在 dst 时只从 src 删除 · 不重复添加

- `kan export [--group X | --all]`:导出 CSV 到 stdout(重定向 `>pos.csv`)。
  - --group X:导出指定组 · 列 = 代码,名称,添加日期
  - --all:导出所有组 · 列 = 组名,代码,名称,添加日期
  - 不带 flag:导出 default 组
"""
from __future__ import annotations

import csv
import sys
from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err


@app.command()
def move(
    symbol: Annotated[
        str,
        typer.Argument(help="股票代码或名称 (如 600519 / 茅台)"),
    ],
    src: Annotated[str, typer.Argument(help="源组名")],
    dst: Annotated[str, typer.Argument(help="目标组名 (必须已存在 · 防 typo)")],
) -> None:
    """跨组移动单股(src/dst 必须都存在)。"""
    from kan.storage.watchlist import (
        GroupNotFoundError,
        load_grouped_watchlist,
        move_stock,
        resolve_symbol_or_name,
    )

    # 接受名称模糊搜:先 resolve_symbol_or_name (跟 add 同入口)
    try:
        code, name = resolve_symbol_or_name(symbol)
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None

    # src 组不存在时 · 单股 6 位代码也可能因 group missing 报错 · 校验一次
    gw = load_grouped_watchlist()
    if src not in gw.groups:
        _print_err(f"❌ 源组「{src}」不存在 · 跑 `kan group list` 查看所有组")
        raise typer.Exit(2)
    if dst not in gw.groups:
        _print_err(
            f"❌ 目标组「{dst}」不存在 · 跑 `kan group create {dst}` 新建 · "
            f"不自动建组防 typo"
        )
        raise typer.Exit(2)

    try:
        _stock, dst_existed = move_stock(code, src, dst)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    except ValueError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(1) from None

    name_short = name.replace(" ", "")
    if dst_existed:
        typer.echo(
            f"✅ {name_short} ({code}) 已从「{src}」移除 · "
            f"「{dst}」已有该股 · 未重复添加"
        )
    else:
        typer.echo(f"✅ 已移动 {name_short} ({code}) ·「{src}」→「{dst}」")


@app.command()
def export(
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="导出指定组 (默认 default 组)"),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="导出所有组 (列前缀加 group)"),
    ] = False,
) -> None:
    """导出 CSV 到 stdout(重定向 `>pos.csv`)。

    --all:输出列 = group,symbol,name,added_at
    --group X / 默认:输出列 = symbol,name,added_at
    """
    from kan.storage.watchlist import (
        GroupNotFoundError,
        list_all,
        load_grouped_watchlist,
    )

    if show_all and group is not None:
        _print_err("❌ --all 与 --group 不能同时使用")
        raise typer.Exit(2)

    writer = csv.writer(sys.stdout, lineterminator="\n")

    if show_all:
        gw = load_grouped_watchlist()
        writer.writerow(["group", "symbol", "name", "added_at"])
        for gname, stocks in gw.groups.items():
            for s in stocks:
                writer.writerow([
                    gname, s.symbol, s.name.replace(" ", ""), s.added_at.isoformat(),
                ])
        return

    try:
        stocks = list_all(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None

    writer.writerow(["symbol", "name", "added_at"])
    for s in stocks:
        writer.writerow([
            s.symbol, s.name.replace(" ", ""), s.added_at.isoformat(),
        ])

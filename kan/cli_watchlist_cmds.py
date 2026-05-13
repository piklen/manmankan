"""自选股管理命令：help / add / remove / list / import / clear。

这一组命令的共同特征：操作 kan.watchlist 模块的持久化状态 · 不涉及 K 线数据拉取。
"""
import re as _re
from typing import Annotated

import typer

from kan.app import app
from kan.cli_helpers import _load_names_with_optional_spinner, _NoopContext


@app.command(name="help")
def help_cmd() -> None:
    """查看命令帮助"""
    from rich.console import Console

    Console().print("""[bold]慢慢看 · 命令速记[/bold]

[bold cyan]自选股管理[/bold cyan]
  kan add 600519 000858     添加自选股（代码）
  kan add 茅台              添加自选股（名称搜索）
  kan remove 600519 茅台    移除自选股（支持多只 + 名称）
  kan list                  查看自选列表
  kan import stocks.csv     CSV 批量导入
  kan clear                 清空自选列表

[bold cyan]位置扫描[/bold cyan]
  kan scan                  全景扫描 10 周期（低点模式）
  kan scan --high           全景扫描 10 周期（高点模式）
  kan scan -S               仅显示有共振信号的股票（--signal）
  kan scan --diff           显示与上次扫描的变化

[bold cyan]低点/高点筛选[/bold cyan]
  kan low 60                谁在 60 日低点？
  kan low 30 60 120         多周期一次看
  kan high 30               谁在 30 日高点？

[bold cyan]单只详情[/bold cyan]
  kan info 600519           单只股票全周期位置 + 涨跌 + 共振

[bold cyan]连续涨跌[/bold cyan]
  kan trend                 连续涨跌看板（不筛选）
  kan trend --down          只看连跌 ≥ 3 天（默认值）
  kan trend --down 5        只看连跌 ≥ 5 天
  kan trend --up            只看连涨 ≥ 3 天（默认值）
  kan trend --up 5          只看连涨 ≥ 5 天
  kan trend --latest 7      展示近 7 天走势详情
  kan trend --candle        阳线阴线口径（默认收盘价口径）

  [dim]以上参数可任意组合：kan trend --down 5 --latest 7 --candle[/dim]
  [dim]N 范围：2-30[/dim]

[bold cyan]数据管理[/bold cyan]
  kan fetch                 拉取数据（通常不需要，scan 自动更新）
  kan fetch --force         强制刷新

[bold cyan]shell 命令补全[/bold cyan] (mac/linux/windows)
  kan completion install    安装补全脚本（自动检测 shell · 之后 kan s<Tab>=kan scan）
  kan completion install zsh  显式指定 shell（zsh/bash/fish/powershell）

[dim]涨跌停自动标记 · ST 默认显示，kan scan --exclude-st 可排除[/dim]
""")


@app.command()
def add(
    symbols: Annotated[list[str], typer.Argument(help="股票代码或名称（如 600519 茅台）")],
) -> None:
    """添加自选股（支持代码或名称搜索）"""
    import time as _time

    batch = len(symbols) > 1

    from rich.console import Console
    # spinner 写 stderr · 防被 baostock 内部 stdout/stderr 重定向干扰 ·
    # tqdm/login banner 抑制已下沉到 watchlist.py 各 _fetch_* 函数内部 self-suppress
    _console = Console(stderr=True)

    names = _load_names_with_optional_spinner(_console)

    # watchlist 已被 helper 加载到 sys.modules · 第二次 import 是 dict 查找
    from kan.watchlist import (
        add_stock,
        load_watchlist,
        save_watchlist,
        search_by_name,
    )

    wl = load_watchlist()
    changed = False
    success, skip, fail = 0, 0, 0
    failures: list[str] = []  # 失败累积到末尾打印 · 防止打断 spinner / 进度反馈

    # 大批量提示（≥ 20 只）· 单行 spinner 提示 · add 主循环本身极快（< 1s 处理 200 只）
    add_start = _time.monotonic()
    use_batch_spinner = len(symbols) >= 20

    if use_batch_spinner:
        spinner_ctx = _console.status(
            f"[cyan]正在添加 {len(symbols)} 只股票...[/cyan]",
            spinner="dots",
        )
    else:
        spinner_ctx = _NoopContext()

    with spinner_ctx:
        for sym in symbols:
            cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", sym.strip())
            if _re.match(r"^\d{6}$", cleaned):
                if wl.find(cleaned):
                    if not batch:
                        typer.echo(f"  {cleaned} 已在自选列表中")
                    skip += 1
                    continue
                name = names.get(cleaned)
                if not name:
                    failures.append(f"未找到股票: {cleaned}（不在 A 股代码表中）")
                    fail += 1
                    continue
                add_stock(wl, cleaned, name)
                changed = True
                if not use_batch_spinner:
                    typer.echo(f"  ✅ 已添加 {name.replace(' ', '')} ({cleaned})")
                success += 1
            else:
                matches = search_by_name(sym, _names_cache=names)
                if len(matches) == 1:
                    code, _name = matches[0]
                    if wl.find(code):
                        if not batch:
                            typer.echo(f"  {code} 已在自选列表中")
                        skip += 1
                    else:
                        add_stock(wl, code, _name)
                        changed = True
                        if not use_batch_spinner:
                            typer.echo(f"  ✅ 已添加 {_name.replace(' ', '')} ({code})")
                        success += 1
                elif len(matches) == 0:
                    failures.append(f"未找到包含「{sym}」的股票")
                    fail += 1
                else:
                    # U-1 (v0.0.4.7 P0): 多匹配列出候选 · 与 kan remove 一致
                    # 旧: 只说"匹配到 N 只 · 请用更精确名称或代码" → dead-end
                    # 新: 列出全部候选 · 用户能直接 copy 代码再 add
                    matches_preview = "; ".join(
                        f"{code} {name.replace(' ', '')}" for code, name in matches[:8]
                    )
                    if len(matches) > 8:
                        matches_preview += f"; …等 {len(matches)} 只"
                    failures.append(
                        f"「{sym}」匹配到 {len(matches)} 只 · 候选: {matches_preview} · 请用代码精确添加"
                    )
                    fail += 1

    add_elapsed = _time.monotonic() - add_start

    if changed:
        save_watchlist(wl)

    # 末尾汇总：先打失败列表（如果有）· 再打统计
    if batch:
        if failures:
            for f in failures:
                typer.echo(f"  ❌ {f}", err=True)
        parts = []
        if success:
            parts.append(f"成功 {success}")
        if skip:
            parts.append(f"跳过 {skip}")
        if fail:
            parts.append(f"失败 {fail}")
        time_part = f" · 用时 {add_elapsed:.1f}s" if add_elapsed >= 0.5 else ""
        typer.echo(f"  添加完成 · {' · '.join(parts)}{time_part}")
    elif failures:
        # v0.0.4.4: 单只模式下错误必须打 + exit 1
        # 修复 v0.0.4.3 用户报告："kan add 999999" / "kan add 不存在的名字" / "kan add 科技"(多匹配)
        # 三种错误输入全静默 + Exit 0 · 用户认为工具坏了
        for f in failures:
            typer.echo(f"  ❌ {f}", err=True)
        raise typer.Exit(1)


@app.command()
def remove(
    symbols: Annotated[list[str], typer.Argument(help="股票代码或名称（支持多只）")],
) -> None:
    """移除自选股（支持代码或名称 · 多只批量删除）"""
    from kan import watchlist as wl

    for sym in symbols:
        cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", sym.strip())
        if _re.match(r"^\d{6}$", cleaned):
            try:
                _, msg = wl.remove(sym)
                typer.echo(f"  {msg}")
            except ValueError as e:
                typer.echo(f"  ❌ {e}", err=True)
        else:
            current = wl.load_watchlist()
            matches = [(s.symbol, s.name) for s in current.stocks if sym in s.name.replace(" ", "")]
            if len(matches) == 1:
                code, name = matches[0]
                _, msg = wl.remove(code)
                typer.echo(f"  已移除 {name.replace(' ', '')} ({code})")
            elif len(matches) == 0:
                typer.echo(f"  ❌ 自选列表中没有包含「{sym}」的股票", err=True)
            else:
                typer.echo(f"  「{sym}」匹配到 {len(matches)} 只自选股：")
                for code, name in matches:
                    typer.echo(f"    {code} {name.replace(' ', '')}")
                typer.echo("    请用代码精确移除")


@app.command(name="list")
def list_stocks() -> None:
    """查看自选列表"""
    from rich.console import Console
    from rich.table import Table

    from kan.watchlist import list_all

    stocks = list_all()
    if not stocks:
        typer.echo("自选列表为空 · 请先 `kan add <代码>` 添加")
        return

    table = Table(title=f"自选股列表 · 共 {len(stocks)} 只")
    table.add_column("代码", style="cyan")
    table.add_column("名称", style="white")
    table.add_column("添加日期", style="dim")

    for s in stocks:
        table.add_row(s.symbol, s.name.replace(" ", ""), str(s.added_at))

    Console().print(table)


@app.command(name="import")
def import_csv(
    path: Annotated[str, typer.Argument(help="CSV 文件路径")],
) -> None:
    """从 CSV 批量导入自选股"""
    from kan.watchlist import import_csv as do_import

    try:
        success, skipped, errors = do_import(path)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"  ❌ {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"导入完成：✅ 新增 {success} · ⏭ 跳过 {skipped} · ❌ 失败 {len(errors)}")
    for err in errors:
        typer.echo(f"  ❌ {err}", err=True)


@app.command(name="clear")
def clear_watchlist() -> None:
    """清空自选列表"""
    from kan.watchlist import clear, load_watchlist

    wl = load_watchlist()
    if not wl.stocks:
        typer.echo("自选列表已经是空的")
        return

    confirm = typer.confirm(f"确定要清空 {len(wl.stocks)} 只自选股吗？")
    if not confirm:
        typer.echo("已取消")
        return

    count = clear()
    typer.echo(f"已清空 {count} 只自选股")

"""自选股管理命令：add / remove / list / import / clear。

这一组命令的共同特征：操作 kan.watchlist 模块的持久化状态 · 不涉及 K 线数据拉取。

help 命令拆到 kan.cli_help（v0.0.5.0 起）· 减少本文件行数 ·
help 文案变更不再触发 watchlist 编辑冲突。
"""
import re as _re
from typing import Annotated

import typer

from kan.app import app
from kan.cli_helpers import (
    _load_names_with_optional_spinner,
    _NoopContext,
    _print_err,
    confirm_destructive,
)


def _add_by_industry(industry: str, yes: bool) -> None:
    """按申万行业批量添加成分股进自选 · 二次确认 + 影响摘要。"""
    from kan import boards
    from kan.watchlist import add_stock, load_watchlist, save_watchlist

    try:
        board = boards.search_industry(industry)
        cons = boards.get_industry_constituents(board)
    except boards.BoardNotFoundError:
        _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词")
        raise typer.Exit(1) from None
    except boards.BoardDataUnavailableError:
        _print_err("❌ 行业数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None

    wl = load_watchlist()
    existing = {s.symbol for s in wl.stocks}
    new = [(c, n) for c, n in cons if c not in existing]
    already = len(cons) - len(new)
    old_total = len(wl.stocks)

    if not new:
        typer.echo(f"「{board.name}」全部 {len(cons)} 只成分股已在自选 · 无需添加")
        return

    summary = (
        f"⚠️ 将加 {len(cons)} 只{board.name}股进自选\n"
        f"   其中 {already} 只已在自选 · 实际新增 {len(new)} 只\n"
        f"   自选股 {old_total} → {old_total + len(new)} 只\n"
        f"   kan scan 耗时会明显变长"
    )
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    for code, name in new:
        add_stock(wl, code, name)
    save_watchlist(wl)
    typer.echo(
        f"✅ 已加 {len(new)} 只{board.name}股 · "
        f"自选股 {old_total} → {len(wl.stocks)} 只"
    )


def _add_by_theme(theme_query: str, yes: bool) -> None:
    """按题材批量添加成分股进自选 · 二次确认 + 影响摘要。"""
    from kan import boards
    from kan.watchlist import add_stock, load_watchlist, save_watchlist

    try:
        themed = boards.search_theme(theme_query)
        cons = boards.get_theme_constituents(themed)
    except boards.ThemeNotFoundError:
        _print_err(f"❌ 未找到题材「{theme_query}」· 试更短关键词 · 或跑 kan theme search")
        raise typer.Exit(2) from None
    except boards.ThemeDataUnavailableError:
        _print_err("❌ 题材数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None

    wl = load_watchlist()
    existing = {s.symbol for s in wl.stocks}
    new = [(c, n) for c, n in cons if c not in existing]
    already = len(cons) - len(new)
    old_total = len(wl.stocks)

    if not new:
        typer.echo(f"「{themed.name}」全部 {len(cons)} 只成分股已在自选 · 无需添加")
        return

    from kan.render_theme import THEME_CLASSIFICATION, THEME_RISK
    summary = (
        f"⚠️ 将加 {len(cons)} 只{themed.name}股进自选\n"
        f"   其中 {already} 只已在自选 · 实际新增 {len(new)} 只\n"
        f"   自选股 {old_total} → {old_total + len(new)} 只\n"
        f"   ⚠️ {THEME_CLASSIFICATION}\n"
        f"   ⚠️ {THEME_RISK}"
    )
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    for code, name in new:
        add_stock(wl, code, name)
    save_watchlist(wl)
    typer.echo(
        f"✅ 已加 {len(new)} 只{themed.name}股 · "
        f"自选股 {old_total} → {len(wl.stocks)} 只"
    )


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
    yes: Annotated[
        bool,
        typer.Option("--yes", help="跳过二次确认 · 慎用"),
    ] = False,
) -> None:
    """添加自选股（支持代码或名称搜索 · --industry / --theme 批量加）"""
    if industry is not None and theme is not None:
        _print_err("不能同时指定 --industry 和 --theme · 二选一")
        raise typer.Exit(2)
    if (industry is not None or theme is not None) and symbols:
        _print_err("不能同时指定股票代码和 --industry / --theme · 二选一")
        raise typer.Exit(2)
    if industry is not None:
        _add_by_industry(industry, yes)
        return
    if theme is not None:
        _add_by_theme(theme, yes)
        return

    import time as _time

    # 无参 Typer 默认英文 "Missing argument 'SYMBOLS...'"
    # 改散户中文友好提示 + 例子 (replace argument-not-provided default)
    if not symbols:
        typer.echo(
            "请告诉我要加哪只股票 · 例: kan add 600519 茅台 (代码或名称都行)",
            err=True,
        )
        raise typer.Exit(2)

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
    skips: list[str] = []     # 跳过明细 · batch 模式末尾打印 · 修 F6 "跳过 N 不知所云"

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
            # F41: 空字符串 / 纯空白拒绝 · 不进入"匹配 5207 只"逻辑
            if not sym or not sym.strip():
                failures.append(
                    "空字符串不是有效股票名 / 代码 · 例: kan add 600519 茅台"
                )
                fail += 1
                continue
            cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", sym.strip())
            if _re.match(r"^\d{6}$", cleaned):
                if wl.find(cleaned):
                    if not batch:
                        typer.echo(f"  {cleaned} 已在自选列表中")
                    else:
                        skips.append(f"{cleaned} → 跳过(已在自选)")
                    skip += 1
                    continue
                name = names.get(cleaned)
                if not name:
                    # 加下一步引导 · 不留 dead-end
                    failures.append(
                        f"未找到股票: {cleaned}（不在 A 股代码表中）· "
                        f"试 `kan add 茅台` 用名称搜索"
                    )
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
                        else:
                            skips.append(
                                f"「{sym}」→ 跳过(匹配 {code} {_name.replace(' ', '')} · 已在自选)"
                            )
                        skip += 1
                    else:
                        add_stock(wl, code, _name)
                        changed = True
                        if not use_batch_spinner:
                            typer.echo(f"  ✅ 已添加 {_name.replace(' ', '')} ({code})")
                        success += 1
                elif len(matches) == 0:
                    # 加下一步引导
                    failures.append(
                        f"未找到包含「{sym}」的股票 · "
                        f"试 `kan theme search` 找题材 / 用代码精确加 `kan add 600519`"
                    )
                    fail += 1
                else:
                    # 多匹配列出候选 · 与 kan remove 一致
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

    # 末尾汇总：先打跳过 + 失败明细 · 再打统计
    if batch:
        # F6: batch 模式下逐条说明 skip 原因 · 防 "跳过 N" 不知所云
        if skips:
            for s in skips:
                typer.echo(f"  ⚠️  {s}")
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
        # F7: batch 模式下 fail > 0 也要 exit 1 · 旧版只在单只模式 exit 1
        if fail:
            raise typer.Exit(1)
    elif failures:
        # v0.0.4.4: 单只模式下错误必须打 + exit 1
        # 修复 v0.0.4.3 用户报告："kan add 999999" / "kan add 不存在的名字" / "kan add 科技"(多匹配)
        # 三种错误输入全静默 + Exit 0 · 用户认为工具坏了
        for f in failures:
            typer.echo(f"  ❌ {f}", err=True)
        raise typer.Exit(1)


def _remove_by_industry(industry: str, yes: bool) -> None:
    """按申万行业批量移除自选里属于该行业的股票 · 二次确认。"""
    from kan import boards
    from kan.watchlist import load_watchlist, save_watchlist

    try:
        board = boards.search_industry(industry)
        cons = boards.get_industry_constituents(board)
    except boards.BoardNotFoundError:
        _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词")
        raise typer.Exit(1) from None
    except boards.BoardDataUnavailableError:
        _print_err("❌ 行业数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None

    cons_codes = {c for c, _ in cons}
    wl = load_watchlist()
    old_total = len(wl.stocks)
    to_remove = [s for s in wl.stocks if s.symbol in cons_codes]

    if not to_remove:
        typer.echo(f"你的自选里没有「{board.name}」行业的股票")
        return

    summary = (
        f"⚠️ 将从自选删除 {len(to_remove)} 只{board.name}股"
        f"（你的自选 ∩ {board.name}成分）\n"
        f"   自选股 {old_total} → {old_total - len(to_remove)} 只\n"
        f"   删除不可恢复（除非重新 kan add）"
    )
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    wl.stocks = [s for s in wl.stocks if s.symbol not in cons_codes]
    save_watchlist(wl)
    typer.echo(
        f"✅ 已从自选删除 {len(to_remove)} 只{board.name}股 · "
        f"自选股 {old_total} → {len(wl.stocks)} 只"
    )


def _remove_by_theme(theme_query: str, yes: bool) -> None:
    """按题材批量移除自选里属于该题材的股票 · 二次确认。"""
    from kan import boards
    from kan.watchlist import load_watchlist, save_watchlist

    try:
        themed = boards.search_theme(theme_query)
        cons = boards.get_theme_constituents(themed)
    except boards.ThemeNotFoundError:
        _print_err(f"❌ 未找到题材「{theme_query}」· 试更短关键词")
        raise typer.Exit(2) from None
    except boards.ThemeDataUnavailableError:
        _print_err("❌ 题材数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None

    cons_codes = {c for c, _ in cons}
    wl = load_watchlist()
    old_total = len(wl.stocks)
    to_remove = [s for s in wl.stocks if s.symbol in cons_codes]

    if not to_remove:
        typer.echo(f"你的自选里没有「{themed.name}」题材的股票")
        return

    summary = (
        f"⚠️ 将从自选删除 {len(to_remove)} 只{themed.name}股"
        f"（你的自选 ∩ {themed.name}成分）\n"
        f"   自选股 {old_total} → {old_total - len(to_remove)} 只\n"
        f"   删除不可恢复（除非重新 kan add）"
    )
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    wl.stocks = [s for s in wl.stocks if s.symbol not in cons_codes]
    save_watchlist(wl)
    typer.echo(
        f"✅ 已从自选删除 {len(to_remove)} 只{themed.name}股 · "
        f"自选股 {old_total} → {len(wl.stocks)} 只"
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
    yes: Annotated[
        bool,
        typer.Option("--yes", help="跳过二次确认 · 慎用"),
    ] = False,
) -> None:
    """移除自选股（支持代码或名称 · 多只批量删除 · --industry / --theme 批量移除）"""
    if industry is not None and theme is not None:
        _print_err("不能同时指定 --industry 和 --theme · 二选一")
        raise typer.Exit(2)
    if (industry is not None or theme is not None) and symbols:
        _print_err("不能同时指定股票代码和 --industry / --theme · 二选一")
        raise typer.Exit(2)
    if industry is not None:
        _remove_by_industry(industry, yes)
        return
    if theme is not None:
        _remove_by_theme(theme, yes)
        return

    # 跟 kan add 同款散户中文 · 兑现承诺到 remove 命令
    if not symbols:
        typer.echo(
            "请告诉我要移除哪只股票 · 例: kan remove 600519 (代码或名称都行)",
            err=True,
        )
        raise typer.Exit(2)

    from kan import watchlist as wl

    fail_count = 0
    for sym in symbols:
        # F41: 空字符串拒绝(对齐 add)
        if not sym or not sym.strip():
            typer.echo(
                "  ❌ 空字符串不是有效股票名 / 代码 · 例: kan remove 600519",
                err=True,
            )
            fail_count += 1
            continue
        cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", sym.strip())
        if _re.match(r"^\d{6}$", cleaned):
            try:
                _, msg = wl.remove(sym)
                typer.echo(f"  {msg}")
            except ValueError as e:
                typer.echo(f"  ❌ {e}", err=True)
                fail_count += 1
        else:
            current = wl.load_watchlist()
            matches = [(s.symbol, s.name) for s in current.stocks if sym in s.name.replace(" ", "")]
            if len(matches) == 1:
                code, name = matches[0]
                _, msg = wl.remove(code)
                typer.echo(f"  已移除 {name.replace(' ', '')} ({code})")
            elif len(matches) == 0:
                typer.echo(
                    f"  ❌ 自选列表中没有包含「{sym}」的股票",
                    err=True,
                )
                fail_count += 1
            else:
                typer.echo(f"  「{sym}」匹配到 {len(matches)} 只自选股：", err=True)
                for code, name in matches:
                    typer.echo(f"    {code} {name.replace(' ', '')}", err=True)
                typer.echo("    请用代码精确移除", err=True)
                fail_count += 1

    # F7: 任一只失败 → exit 1 · 对齐 add 行为
    if fail_count:
        raise typer.Exit(1)


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
) -> None:
    """查看自选列表(--industry / --theme 只看某行业/题材的)"""
    from rich.console import Console
    from rich.table import Table

    from kan.cli_helpers import _print_err
    from kan.watchlist import list_all

    if industry is not None and theme is not None:
        _print_err("❌ --industry 与 --theme 不能同时使用")
        raise typer.Exit(2)

    stocks = list_all()
    if not stocks:
        typer.echo("自选列表为空 · 请先 `kan add <代码>` 添加")
        return

    title = f"自选股列表 · 共 {len(stocks)} 只"
    if industry is not None:
        from kan import boards
        try:
            board = boards.search_industry(industry)
            cons_codes = {c for c, _ in boards.get_industry_constituents(board)}
        except boards.BoardNotFoundError:
            _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词")
            raise typer.Exit(1) from None
        except boards.BoardDataUnavailableError:
            _print_err("❌ 行业数据源暂时不可用,稍后再试")
            raise typer.Exit(1) from None
        stocks = [s for s in stocks if s.symbol in cons_codes]
        if not stocks:
            typer.echo(f"自选股里没有属于「{board.name}」行业的")
            return
        title = f"自选股 · {board.name} 行业 · {len(stocks)} 只"
    elif theme is not None:
        from kan import boards
        try:
            themed = boards.search_theme(theme)
            cons_codes = {c for c, _ in boards.get_theme_constituents(themed)}
        except boards.ThemeNotFoundError:
            _print_err(f"❌ 未找到题材「{theme}」· 试更短关键词")
            raise typer.Exit(2) from None
        except boards.ThemeDataUnavailableError:
            _print_err("❌ 题材数据源暂时不可用,稍后再试")
            raise typer.Exit(1) from None
        stocks = [s for s in stocks if s.symbol in cons_codes]
        if not stocks:
            typer.echo(f"自选股里没有属于「{themed.name}」题材的")
            return
        title = f"自选股 · {themed.name} 题材 · {len(stocks)} 只"

    table = Table(title=title)
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
def clear_watchlist(
    yes: bool = typer.Option(
        False, "--yes", "-y", help="跳过二次确认 · 用于脚本 / CI"
    ),
) -> None:
    """清空自选列表"""
    from kan.paths import WATCHLIST_PATH
    from kan.watchlist import (
        WatchlistCorruptError,
        clear,
        load_watchlist,
    )

    try:
        wl = load_watchlist()
    except WatchlistCorruptError as e:
        # 文件损坏 fallback · --yes 直接 unlink 重建 · 否则给清晰 hint
        if not yes:
            typer.echo(
                f"❌ {e}\n"
                f"   跑 `kan clear --yes` 强制重置(会丢全部自选 · 不可恢复)",
                err=True,
            )
            raise typer.Exit(1) from None
        # --yes 模式 · 直接 unlink 重建空文件 · 不再调 clear() (clear 会再读)
        import contextlib
        with contextlib.suppress(FileNotFoundError):
            WATCHLIST_PATH.unlink()
        typer.echo("⚠️  原 watchlist.json 已损坏 · 已删除并重置为空")
        return

    if not wl.stocks:
        typer.echo("自选列表已经是空的")
        return

    if not yes:
        confirm = typer.confirm(f"确定要清空 {len(wl.stocks)} 只自选股吗？")
        if not confirm:
            typer.echo("已取消")
            return

    count = clear()
    typer.echo(f"已清空 {count} 只自选股")

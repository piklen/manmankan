"""`kan remove` 执行逻辑。"""
from __future__ import annotations

import re as _re

import typer

from kan.cli.helpers import _print_err, confirm_destructive


def _remove_by_industry(industry: str, yes: bool, group: str | None = None) -> None:
    """按申万行业批量移除指定组里属于该行业的股票。"""
    from kan.data import boards
    from kan.storage.watchlist import (
        GroupNotFoundError,
        load_watchlist,
        save_watchlist,
    )

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
    try:
        wl = load_watchlist(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    is_default = group is None
    target_label = "自选" if is_default else f"「{group}」组"
    state_label = "自选股" if is_default else f"「{group}」组"
    old_total = len(wl.stocks)
    to_remove = [s for s in wl.stocks if s.symbol in cons_codes]

    if not to_remove:
        typer.echo(f"你的{target_label}里没有「{board.name}」行业的股票")
        return

    summary = (
        f"⚠️ 将从{target_label}删除 {len(to_remove)} 只{board.name}股"
        f"（你的{target_label} ∩ {board.name}成分）\n"
        f"   {state_label} {old_total} → {old_total - len(to_remove)} 只\n"
        f"   删除不可恢复（除非重新 kan add）"
    )
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    wl.stocks = [s for s in wl.stocks if s.symbol not in cons_codes]
    save_watchlist(wl, group=group)
    typer.echo(
        f"✅ 已从{target_label}删除 {len(to_remove)} 只{board.name}股 · "
        f"{state_label} {old_total} → {len(wl.stocks)} 只"
    )


def _remove_by_theme(theme_query: str, yes: bool, group: str | None = None) -> None:
    """按题材批量移除指定组里属于该题材的股票。"""
    from kan.data import boards
    from kan.storage.watchlist import (
        GroupNotFoundError,
        load_watchlist,
        save_watchlist,
    )

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
    try:
        wl = load_watchlist(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    is_default = group is None
    target_label = "自选" if is_default else f"「{group}」组"
    state_label = "自选股" if is_default else f"「{group}」组"
    old_total = len(wl.stocks)
    to_remove = [s for s in wl.stocks if s.symbol in cons_codes]

    if not to_remove:
        typer.echo(f"你的{target_label}里没有「{themed.name}」题材的股票")
        return

    summary = (
        f"⚠️ 将从{target_label}删除 {len(to_remove)} 只{themed.name}股"
        f"（你的{target_label} ∩ {themed.name}成分）\n"
        f"   {state_label} {old_total} → {old_total - len(to_remove)} 只\n"
        f"   删除不可恢复（除非重新 kan add）"
    )
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    wl.stocks = [s for s in wl.stocks if s.symbol not in cons_codes]
    save_watchlist(wl, group=group)
    typer.echo(
        f"✅ 已从{target_label}删除 {len(to_remove)} 只{themed.name}股 · "
        f"{state_label} {old_total} → {len(wl.stocks)} 只"
    )


def run_remove(
    symbols: list[str] | None,
    *,
    industry: str | None,
    theme: str | None,
    group: str | None,
    yes: bool,
) -> None:
    """执行 `kan remove`。"""
    if industry is not None and theme is not None:
        _print_err("不能同时指定 --industry 和 --theme · 二选一")
        raise typer.Exit(2)
    if (industry is not None or theme is not None) and symbols:
        _print_err("不能同时指定股票代码和 --industry / --theme · 二选一")
        raise typer.Exit(2)
    if industry is not None:
        _remove_by_industry(industry, yes, group=group)
        return
    if theme is not None:
        _remove_by_theme(theme, yes, group=group)
        return

    if not symbols:
        typer.echo(
            "请告诉我要移除哪只股票 · 例: kan remove 600519 (代码或名称都行)",
            err=True,
        )
        raise typer.Exit(2)

    from kan.storage import watchlist as wl
    from kan.storage.watchlist import GroupNotFoundError

    in_label = "自选" if not group else f"「{group}」组"
    fail_count = 0
    for sym in symbols:
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
                removed, msg = wl.remove(cleaned, group=group)
                typer.echo(f"  {msg}")
                if not removed:
                    fail_count += 1
            except GroupNotFoundError as e:
                _print_err(f"❌ {e}")
                raise typer.Exit(2) from None
            except ValueError as e:
                typer.echo(f"  ❌ {e}", err=True)
                fail_count += 1
        else:
            try:
                current = wl.load_watchlist(group)
            except GroupNotFoundError as e:
                _print_err(f"❌ {e}")
                raise typer.Exit(2) from None
            matches = [
                (s.symbol, s.name) for s in current.stocks if sym in s.name.replace(" ", "")
            ]
            if len(matches) == 1:
                code, name = matches[0]
                removed, msg = wl.remove(code, group=group)
                if removed:
                    typer.echo(f"  已移除 {name.replace(' ', '')} ({code})")
                else:
                    typer.echo(f"  ❌ {msg}", err=True)
                    fail_count += 1
            elif len(matches) == 0:
                typer.echo(
                    f"  ❌ {in_label}中没有包含「{sym}」的股票",
                    err=True,
                )
                fail_count += 1
            else:
                typer.echo(f"  「{sym}」匹配到 {len(matches)} 只{in_label}股：", err=True)
                for code, name in matches:
                    typer.echo(f"    {code} {name.replace(' ', '')}", err=True)
                typer.echo("    请用代码精确移除", err=True)
                fail_count += 1

    if fail_count:
        raise typer.Exit(1)

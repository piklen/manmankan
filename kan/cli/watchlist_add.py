"""`kan add` 执行逻辑。"""
from __future__ import annotations

import re as _re
import time
from datetime import date

import typer
from rich.console import Console

from kan.cli.helpers import (
    _load_names_with_optional_spinner,
    _NoopContext,
    _print_err,
    confirm_destructive,
)
from kan.core.models import Stock

_A_SHARE_CODE_PREFIXES = (
    "000",
    "001",
    "002",
    "003",
    "300",
    "301",
    "302",
    "600",
    "601",
    "603",
    "605",
    "688",
    "689",
)


def _clean_code_token(raw: str) -> str | None:
    """把代码形输入归一化为 6 位数字；非代码返回 None。"""
    cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    return cleaned if _re.match(r"^\d{6}$", cleaned) else None


def _looks_like_a_share_code(code: str) -> bool:
    """仅用于无缓存数字代码添加路径的低成本语法判断。"""
    return code.startswith(_A_SHARE_CODE_PREFIXES)


def _expand_stdin_symbols(symbols: list[str] | None) -> list[str] | None:
    """展开 add 参数里的 `-`，从 stdin 读取逗号或空白分隔的代码池。"""
    if not symbols or "-" not in symbols:
        return symbols
    import sys

    expanded: list[str] = []
    for sym in symbols:
        if sym == "-":
            text = sys.stdin.read()
            expanded.extend(part for part in _re.split(r"[\s,]+", text.strip()) if part)
        else:
            expanded.append(sym)
    return expanded


def _fetch_added(symbols: list[str]) -> None:
    """用户显式传入 --fetch 时，为新增股票拉取 K 线缓存。"""
    if not symbols:
        return
    from kan.data.fetcher import DEFAULT_KLINE_DAYS, fetch_batch

    results, errors = fetch_batch(symbols, days=DEFAULT_KLINE_DAYS)
    ok = sum(1 for df in results.values() if df is not None)
    fail = len(errors)
    if fail:
        typer.echo(f"  ⚠️  --fetch 完成: 成功 {ok} · 失败 {fail}", err=True)
        for sym, err in list(errors.items())[:5]:
            typer.echo(f"    {sym}: {err}", err=True)
        return
    typer.echo(f"  ✅ --fetch 已拉取 {ok} 只")


def _add_by_industry(
    industry: str,
    yes: bool,
    group: str | None = None,
    dry_run: bool = False,
    fetch: bool = False,
) -> None:
    """按申万行业批量添加成分股进指定组。"""
    from kan.data import boards
    from kan.storage.watchlist import (
        GroupNotFoundError,
        add_many,
        load_watchlist,
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

    try:
        wl = load_watchlist(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    is_default = group is None
    target_label = "自选" if is_default else f"「{group}」组"
    state_label = "自选股" if is_default else f"「{group}」组"
    existing = {s.symbol for s in wl.stocks}
    new = [(c, n) for c, n in cons if c not in existing]
    already = len(cons) - len(new)
    old_total = len(wl.stocks)

    if not new:
        typer.echo(f"「{board.name}」全部 {len(cons)} 只成分股已在{target_label} · 无需添加")
        return

    summary = (
        f"⚠️ 将添加 {len(new)} 只{board.name}股进{target_label}\n"
        f"   其中 {already} 只已在{target_label} · 实际新增 {len(new)} 只\n"
        f"   {state_label} {old_total} → {old_total + len(new)} 只\n"
        f"   kan scan 耗时会明显变长"
    )
    if dry_run:
        typer.echo(summary)
        typer.echo("dry-run: 未写入自选股")
        return
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    added, actual_old, actual_new = add_many(
        [Stock(symbol=code, name=name, added_at=date.today()) for code, name in new],
        group=group,
    )
    typer.echo(
        f"✅ 已加 {len(added)} 只{board.name}股 · "
        f"{state_label} {actual_old} → {actual_new} 只"
    )
    if fetch:
        _fetch_added([stock.symbol for stock in added])


def _add_by_theme(
    theme_query: str,
    yes: bool,
    group: str | None = None,
    dry_run: bool = False,
    fetch: bool = False,
) -> None:
    """按题材批量添加成分股进指定组。"""
    from kan.data import boards
    from kan.storage.watchlist import (
        GroupNotFoundError,
        add_many,
        load_watchlist,
    )

    try:
        themed = boards.search_theme(theme_query)
        cons = boards.get_theme_constituents(themed)
    except boards.ThemeNotFoundError:
        _print_err(f"❌ 未找到题材「{theme_query}」· 试更短关键词 · 或跑 kan theme search")
        raise typer.Exit(2) from None
    except boards.ThemeDataUnavailableError:
        _print_err("❌ 题材数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None

    try:
        wl = load_watchlist(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    is_default = group is None
    target_label = "自选" if is_default else f"「{group}」组"
    state_label = "自选股" if is_default else f"「{group}」组"
    existing = {s.symbol for s in wl.stocks}
    new = [(c, n) for c, n in cons if c not in existing]
    already = len(cons) - len(new)
    old_total = len(wl.stocks)

    if not new:
        typer.echo(f"「{themed.name}」全部 {len(cons)} 只成分股已在{target_label} · 无需添加")
        return

    from kan.render.theme import THEME_CLASSIFICATION, THEME_RISK

    summary = (
        f"⚠️ 将添加 {len(new)} 只{themed.name}股进{target_label}\n"
        f"   其中 {already} 只已在{target_label} · 实际新增 {len(new)} 只\n"
        f"   {state_label} {old_total} → {old_total + len(new)} 只\n"
        f"   ⚠️ {THEME_CLASSIFICATION}\n"
        f"   ⚠️ {THEME_RISK}"
    )
    if dry_run:
        typer.echo(summary)
        typer.echo("dry-run: 未写入自选股")
        return
    if not confirm_destructive(summary, yes=yes):
        typer.echo("已取消")
        return

    added, actual_old, actual_new = add_many(
        [Stock(symbol=code, name=name, added_at=date.today()) for code, name in new],
        group=group,
    )
    typer.echo(
        f"✅ 已加 {len(added)} 只{themed.name}股 · "
        f"{state_label} {actual_old} → {actual_new} 只"
    )
    if fetch:
        _fetch_added([stock.symbol for stock in added])


def run_add(
    symbols: list[str] | None,
    *,
    industry: str | None,
    theme: str | None,
    group: str | None,
    yes: bool,
    dry_run: bool,
    fetch: bool,
) -> None:
    """执行 `kan add`。"""
    symbols = _expand_stdin_symbols(symbols)
    if industry is not None and theme is not None:
        _print_err("不能同时指定 --industry 和 --theme · 二选一")
        raise typer.Exit(2)
    if (industry is not None or theme is not None) and symbols:
        _print_err("不能同时指定股票代码和 --industry / --theme · 二选一")
        raise typer.Exit(2)
    if industry is not None:
        _add_by_industry(industry, yes, group=group, dry_run=dry_run, fetch=fetch)
        return
    if theme is not None:
        _add_by_theme(theme, yes, group=group, dry_run=dry_run, fetch=fetch)
        return
    if dry_run:
        _print_err("❌ --dry-run 仅支持 --industry / --theme 批量添加")
        raise typer.Exit(2)

    if not symbols:
        typer.echo(
            "请告诉我要加哪只股票 · 例: kan add 600519 茅台 (代码或名称都行)",
            err=True,
        )
        raise typer.Exit(2)

    invalid_numeric = [
        sym.strip()
        for sym in symbols
        if _re.fullmatch(r"(?:sh|sz|SH|SZ)?\d+", sym.strip())
        and _clean_code_token(sym) is None
    ]
    if invalid_numeric:
        shown = "、".join(invalid_numeric[:3])
        suffix = " 等" if len(invalid_numeric) > 3 else ""
        _print_err(f"❌ {shown}{suffix} 不是 6 位股票代码 · 例: kan add 600519")
        raise typer.Exit(2)

    batch = len(symbols) > 1
    console = Console(stderr=True)

    from kan.storage.watchlist import (
        GroupNotFoundError,
        add_many,
        add_stock,
        load_stock_names_cache,
        load_watchlist,
        search_by_name,
    )

    code_only_input = all(_clean_code_token(sym) is not None for sym in symbols)
    if code_only_input:
        names = load_stock_names_cache(allow_stale=True) or {}
    else:
        names = _load_names_with_optional_spinner(console)

    try:
        wl = load_watchlist(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    changed = False
    added_codes: list[str] = []
    pending_stocks: list[Stock] = []
    success, skip, fail = 0, 0, 0
    unresolved_names = 0
    failures: list[str] = []
    skips: list[str] = []

    add_start = time.monotonic()
    use_batch_spinner = len(symbols) >= 20

    if use_batch_spinner:
        spinner_ctx = console.status(
            f"[cyan]正在添加 {len(symbols)} 只股票...[/cyan]",
            spinner="dots",
        )
    else:
        spinner_ctx = _NoopContext()

    in_label = "自选" if not group else f"「{group}」组"
    success_suffix = "" if not group else f" → 「{group}」"
    with spinner_ctx:
        for sym in symbols:
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
                        typer.echo(f"  {cleaned} 已在{in_label}列表中")
                    else:
                        skips.append(f"{cleaned} → 跳过(已在{in_label})")
                    skip += 1
                    continue
                name = names.get(cleaned)
                if not name:
                    if code_only_input and _looks_like_a_share_code(cleaned):
                        name = cleaned
                        unresolved_names += 1
                    else:
                        failures.append(
                            f"未找到股票: {cleaned}（不在 A 股代码表中）· "
                            f"试 `kan add 茅台` 用名称搜索"
                        )
                        fail += 1
                        continue
                add_stock(wl, cleaned, name)
                pending_stocks.append(
                    Stock(symbol=cleaned, name=name, added_at=date.today())
                )
                added_codes.append(cleaned)
                changed = True
                if not use_batch_spinner:
                    typer.echo(
                        f"  ✅ 已添加 {name.replace(' ', '')} ({cleaned}){success_suffix}"
                    )
                success += 1
            else:
                matches = search_by_name(sym, _names_cache=names)
                if len(matches) == 1:
                    code, name = matches[0]
                    if wl.find(code):
                        if not batch:
                            typer.echo(f"  {code} 已在{in_label}列表中")
                        else:
                            skips.append(
                                f"「{sym}」→ 跳过(匹配 {code} "
                                f"{name.replace(' ', '')} · 已在{in_label})"
                            )
                        skip += 1
                    else:
                        add_stock(wl, code, name)
                        pending_stocks.append(
                            Stock(symbol=code, name=name, added_at=date.today())
                        )
                        added_codes.append(code)
                        changed = True
                        if not use_batch_spinner:
                            typer.echo(
                                f"  ✅ 已添加 {name.replace(' ', '')} ({code}){success_suffix}"
                            )
                        success += 1
                elif len(matches) == 0:
                    failures.append(
                        f"未找到包含「{sym}」的股票 · "
                        f"试 `kan theme search` 找题材 / 用代码精确加 `kan add 600519`"
                    )
                    fail += 1
                else:
                    matches_preview = "; ".join(
                        f"{code} {name.replace(' ', '')}" for code, name in matches[:8]
                    )
                    if len(matches) > 8:
                        matches_preview += f"; …等 {len(matches)} 只"
                    failures.append(
                        f"「{sym}」匹配到 {len(matches)} 只 · 候选: "
                        f"{matches_preview} · 请用代码精确添加"
                    )
                    fail += 1

    add_elapsed = time.monotonic() - add_start

    if changed:
        added, _actual_old, _actual_new = add_many(pending_stocks, group=group)
        concurrent_skips = len(pending_stocks) - len(added)
        if concurrent_skips:
            success -= concurrent_skips
            skip += concurrent_skips
            skips.append(f"并发期间已有 {concurrent_skips} 只被其他窗口加入")
        added_codes = [stock.symbol for stock in added]

    if batch:
        if skips:
            for s in skips:
                typer.echo(f"  ⚠️  {s}")
        if failures:
            for f in failures:
                typer.echo(f"  ❌ {f}", err=True)
        if unresolved_names:
            typer.echo(
                f"  ⚠️  {unresolved_names} 只未命中本地名称表,已先按代码加入"
            )
        parts = []
        if success:
            parts.append(f"成功 {success}")
        if skip:
            parts.append(f"跳过 {skip}")
        if fail:
            parts.append(f"失败 {fail}")
        time_part = f" · 用时 {add_elapsed:.1f}s" if add_elapsed >= 0.5 else ""
        typer.echo(f"  添加完成 · {' · '.join(parts)}{time_part}")
        if fetch and added_codes:
            _fetch_added(added_codes)
        if fail:
            raise typer.Exit(1)
    elif failures:
        for f in failures:
            typer.echo(f"  ❌ {f}", err=True)
        raise typer.Exit(1)
    elif fetch and added_codes:
        _fetch_added(added_codes)

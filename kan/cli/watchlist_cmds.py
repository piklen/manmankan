"""自选股管理命令：add / remove / list / import / clear。

共同特征:操作 kan.storage.watchlist 的持久化状态 · 不涉及 K 线数据拉取。
help 命令在独立的 kan.cli.help 模块(help 文案变更不触发本文件编辑冲突)。
"""
import re as _re
from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _load_names_with_optional_spinner,
    _NoopContext,
    _print_err,
    confirm_destructive,
)

_A_SHARE_CODE_PREFIXES = (
    "000", "001", "002", "003",
    "300", "301", "302",
    "600", "601", "603", "605",
    "688", "689",
)


def _clean_code_token(raw: str) -> str | None:
    """Return normalized 6-digit code for code-like input, else None."""
    cleaned = _re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    return cleaned if _re.match(r"^\d{6}$", cleaned) else None


def _looks_like_a_share_code(code: str) -> bool:
    """Cheap syntax gate for no-cache numeric add fast path."""
    return code.startswith(_A_SHARE_CODE_PREFIXES)


def _expand_stdin_symbols(symbols: list[str] | None) -> list[str] | None:
    """Expand '-' in add arguments from stdin (comma/whitespace separated)."""
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
    """Fetch K-line cache for newly added symbols when user opts in."""
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
    """按申万行业批量添加成分股进指定组 (group=None 走 default) · 二次确认 + 影响摘要。"""
    from kan.data import boards
    from kan.storage.watchlist import (
        GroupNotFoundError,
        add_stock,
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

    for code, name in new:
        add_stock(wl, code, name)
    save_watchlist(wl, group=group)
    typer.echo(
        f"✅ 已加 {len(new)} 只{board.name}股 · "
        f"{state_label} {old_total} → {len(wl.stocks)} 只"
    )
    if fetch:
        _fetch_added([code for code, _name in new])


def _add_by_theme(
    theme_query: str,
    yes: bool,
    group: str | None = None,
    dry_run: bool = False,
    fetch: bool = False,
) -> None:
    """按题材批量添加成分股进指定组 (group=None 走 default) · 二次确认 + 影响摘要。"""
    from kan.data import boards
    from kan.storage.watchlist import (
        GroupNotFoundError,
        add_stock,
        load_watchlist,
        save_watchlist,
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

    for code, name in new:
        add_stock(wl, code, name)
    save_watchlist(wl, group=group)
    typer.echo(
        f"✅ 已加 {len(new)} 只{themed.name}股 · "
        f"{state_label} {old_total} → {len(wl.stocks)} 只"
    )
    if fetch:
        _fetch_added([code for code, _name in new])


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

    import time

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

    # watchlist 已被 helper 加载到 sys.modules · 第二次 import 是 dict 查找
    from kan.storage.watchlist import (
        GroupNotFoundError,
        add_stock,
        load_stock_names_cache,
        load_watchlist,
        save_watchlist,
        search_by_name,
    )

    code_only_input = all(_clean_code_token(sym) is not None for sym in symbols)
    if code_only_input:
        # 只读本地 cache,不触发网络刷新。批量数字代码 add 的主诉是"快加入",
        # 不该为了显示名称同步拉全市场代码表。
        names = load_stock_names_cache(allow_stale=True) or {}
    else:
        names = _load_names_with_optional_spinner(_console)

    try:
        wl = load_watchlist(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None
    changed = False
    added_codes: list[str] = []
    success, skip, fail = 0, 0, 0
    unresolved_names = 0
    failures: list[str] = []  # 失败累积到末尾打印 · 防止打断 spinner / 进度反馈
    skips: list[str] = []     # 跳过明细 · batch 模式末尾打印 · 修 F6 "跳过 N 不知所云"

    # 大批量提示（≥ 20 只）· 单行 spinner 提示 · add 主循环本身极快（< 1s 处理 200 只）
    add_start = time.monotonic()
    use_batch_spinner = len(symbols) >= 20

    if use_batch_spinner:
        spinner_ctx = _console.status(
            f"[cyan]正在添加 {len(symbols)} 只股票...[/cyan]",
            spinner="dots",
        )
    else:
        spinner_ctx = _NoopContext()

    in_label = "自选" if not group else f"「{group}」组"
    success_suffix = "" if not group else f" → 「{group}」"
    with spinner_ctx:
        for sym in symbols:
            # 空字符串 / 纯空白拒绝 · 不进入名称模糊匹配(否则空串会匹配全市场)
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
                        # 加下一步引导 · 不留 dead-end
                        failures.append(
                            f"未找到股票: {cleaned}（不在 A 股代码表中）· "
                            f"试 `kan add 茅台` 用名称搜索"
                        )
                        fail += 1
                        continue
                add_stock(wl, cleaned, name)
                added_codes.append(cleaned)
                changed = True
                if not use_batch_spinner:
                    typer.echo(f"  ✅ 已添加 {name.replace(' ', '')} ({cleaned}){success_suffix}")
                success += 1
            else:
                matches = search_by_name(sym, _names_cache=names)
                if len(matches) == 1:
                    code, _name = matches[0]
                    if wl.find(code):
                        if not batch:
                            typer.echo(f"  {code} 已在{in_label}列表中")
                        else:
                            skips.append(
                                f"「{sym}」→ 跳过(匹配 {code} {_name.replace(' ', '')} · 已在{in_label})"
                            )
                        skip += 1
                    else:
                        add_stock(wl, code, _name)
                        added_codes.append(code)
                        changed = True
                        if not use_batch_spinner:
                            typer.echo(f"  ✅ 已添加 {_name.replace(' ', '')} ({code}){success_suffix}")
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

    add_elapsed = time.monotonic() - add_start

    if changed:
        save_watchlist(wl, group=group)

    # 末尾汇总：先打跳过 + 失败明细 · 再打统计
    if batch:
        # batch 模式逐条说明 skip 原因 · 防"跳过 N 只"用户不知所云
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
        # batch 模式只要有失败就 exit 1 · 与单只模式行为一致 · 便于脚本判断
        if fail:
            raise typer.Exit(1)
    elif failures:
        # 背景: 单只模式下错误必须打 + exit 1
        # 修复 早期用户报告："kan add 999999" / "kan add 不存在的名字" / "kan add 科技"(多匹配)
        # 三种错误输入全静默 + Exit 0 · 用户认为工具坏了
        for f in failures:
            typer.echo(f"  ❌ {f}", err=True)
        raise typer.Exit(1)
    elif fetch and added_codes:
        _fetch_added(added_codes)


def _remove_by_industry(industry: str, yes: bool, group: str | None = None) -> None:
    """按申万行业批量移除指定组里属于该行业的股票 (group=None 走 default) · 二次确认。"""
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
    """按题材批量移除指定组里属于该题材的股票 (group=None 走 default) · 二次确认。"""
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

    # 跟 kan add 同款散户中文 · 兑现承诺到 remove 命令
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
        # 空字符串拒绝 · 与 add 一致
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
            matches = [(s.symbol, s.name) for s in current.stocks if sym in s.name.replace(" ", "")]
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

    # 任一只失败 → exit 1 · 与 add 一致
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
    from rich.console import Console
    from rich.table import Table

    from kan.cli.helpers import _print_err
    from kan.storage.watchlist import (
        GroupNotFoundError,
        list_all,
        load_grouped_watchlist,
    )

    if industry is not None and theme is not None:
        _print_err("❌ --industry 与 --theme 不能同时使用")
        raise typer.Exit(2)
    if show_all and group is not None:
        _print_err("❌ --all 与 --group 不能同时使用 (--all 已列所有组)")
        raise typer.Exit(2)

    # --all 模式 · 列所有组 (industry/theme filter 仍适用)
    if show_all:
        gw = load_grouped_watchlist()
        if not any(gw.groups.values()):
            typer.echo("所有组都是空的 · 先加几只: `kan add 600519 茅台 000858`")
            return
        console = Console()
        for gname, stocks in gw.groups.items():
            tag = " (默认)" if gname == gw.default else ""
            if not stocks:
                console.print(f"\n[dim]📋 {gname}{tag} · 空[/dim]")
                continue
            t = Table(title=f"📋 {gname}{tag} · {len(stocks)} 只")
            t.add_column("代码", style="cyan")
            t.add_column("名称", style="white")
            t.add_column("添加日期", style="dim")
            for s in stocks:
                t.add_row(s.symbol, s.name.replace(" ", ""), str(s.added_at))
            console.print(t)
        return

    try:
        stocks = list_all(group)
    except GroupNotFoundError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from None

    group_label = f"「{group}」" if group else "自选"
    empty_hint = (
        "自选列表为空 · 先加几只:`kan add 600519 茅台 000858` (代码或名称都行)"
        if not group
        else f"「{group}」组为空 · `kan add 600519 --group {group}` 添加"
    )
    if not stocks:
        typer.echo(empty_hint)
        return

    title = f"{group_label}股列表 · 共 {len(stocks)} 只"
    if industry is not None:
        from kan.data import boards
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
            typer.echo(f"{group_label}组里没有属于「{board.name}」行业的")
            return
        title = f"{group_label}组 · {board.name} 行业 · {len(stocks)} 只"
    elif theme is not None:
        from kan.data import boards
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
            typer.echo(f"{group_label}组里没有属于「{themed.name}」题材的")
            return
        title = f"{group_label}组 · {themed.name} 题材 · {len(stocks)} 只"

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
        # 文件损坏 fallback · --yes 直接 unlink 重建 · 否则给清晰 hint
        if not yes:
            typer.echo(
                f"❌ {e}\n"
                f"   跑 `kan clear --yes` 强制重置(会丢全部分组 · 不可恢复)",
                err=True,
            )
            raise typer.Exit(1) from None
        # --yes 模式 · 直接 unlink 重建空文件 · 不再调 clear() (clear 会再读)
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

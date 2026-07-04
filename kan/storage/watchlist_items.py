"""watchlist 单组股票 CRUD 与 CSV 导入。"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from kan.core.models import Stock
from kan.storage.watchlist_models import (
    MAX_CSV_SIZE,
    GroupNotFoundError,
    Watchlist,
    _normalize_symbol,
)
from kan.storage.watchlist_names import _lookup_name
from kan.storage.watchlist_store import (
    _save_grouped_watchlist,
    load_grouped_watchlist,
    load_watchlist,
    with_watchlist_lock,
)


def add_stock(wl: Watchlist, symbol: str, name: str) -> bool:
    """向已加载的 Watchlist 追加一只（不做 IO）。返回是否新增。"""
    if wl.find(symbol):
        return False
    wl.stocks.append(Stock(symbol=symbol, name=name, added_at=date.today()))
    return True


@with_watchlist_lock
def add(symbol: str, group: str | None = None) -> tuple[bool, str]:
    """添加股票到指定组 (不传走 default 组)。返回 (是否新增, 消息)。"""
    symbol = _normalize_symbol(symbol)
    gw = load_grouped_watchlist()
    target = group or gw.default
    if target not in gw.groups:
        raise GroupNotFoundError(
            f"组「{target}」不存在 · 跑 `kan group create {target}` 新建"
        )

    stocks = gw.groups[target]
    is_default = target == gw.default
    if any(s.symbol == symbol for s in stocks):
        msg = (
            f"{symbol} 已在自选列表中"
            if is_default
            else f"{symbol} 已在「{target}」组中"
        )
        return False, msg

    name = _lookup_name(symbol)
    stocks.append(Stock(symbol=symbol, name=name, added_at=date.today()))
    _save_grouped_watchlist(gw)
    suffix = "" if is_default else f" → 「{target}」"
    return True, f"✅ 已添加 {name} ({symbol}){suffix}"


@with_watchlist_lock
def remove(symbol: str, group: str | None = None) -> tuple[bool, str]:
    """从指定组移除股票 (不传走 default 组)。返回 (是否移除, 消息)。"""
    symbol = _normalize_symbol(symbol)
    gw = load_grouped_watchlist()
    target = group or gw.default
    if target not in gw.groups:
        raise GroupNotFoundError(
            f"组「{target}」不存在 · 跑 `kan group list` 查看"
        )

    stocks = gw.groups[target]
    is_default = target == gw.default
    new_stocks = [s for s in stocks if s.symbol != symbol]
    if len(new_stocks) == len(stocks):
        msg = (
            f"{symbol} 不在自选列表中"
            if is_default
            else f"{symbol} 不在「{target}」组中"
        )
        return False, msg

    gw.groups[target] = new_stocks
    _save_grouped_watchlist(gw)
    suffix = "" if is_default else f"(自「{target}」)"
    return True, f"已移除 {symbol}{suffix}"


def list_all(group: str | None = None) -> list[Stock]:
    """列指定组股票 (不传走 default 组)。"""
    return load_watchlist(group).stocks


def import_csv(
    path: str | Path, group: str | None = None,
) -> tuple[int, int, list[str]]:
    """CSV 导入到指定组 (不传走 default 组)。返回 (成功数, 跳过数, 错误列表)。

    CSV 格式：每行一个代码，或 代码,名称。

    入口三道校验：
      1. 必须 .csv 后缀（防意外读取 ~/.ssh/id_rsa 之类）
      2. 必须存在且是文件（防误传目录）
      3. 大小 ≤ MAX_CSV_SIZE（防巨型文件 OOM）
    """
    p = Path(path).resolve()

    if p.suffix.lower() != ".csv":
        raise ValueError(f"文件必须是 .csv 后缀: {p.name}")

    if not p.is_file():
        raise FileNotFoundError(f"文件不存在或不是普通文件: {p.name}")

    if p.stat().st_size > MAX_CSV_SIZE:
        size_mb = p.stat().st_size / (1024 * 1024)
        raise ValueError(
            f"文件过大（{size_mb:.1f} MB · 上限 "
            f"{MAX_CSV_SIZE // (1024 * 1024)} MB）: {p.name}"
        )

    success, skipped = 0, 0
    errors: list[str] = []

    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    # CSV header 自动 detect 跳过
    # 第一行第一列不是 6 位数字 → 当成 header skip
    # (典型 header: symbol,name / code,name / 代码,名称)
    start_idx = 0
    if rows:
        first_cell = rows[0][0].strip() if rows[0] and rows[0][0] else ""
        if first_cell and not first_cell.isdigit():
            start_idx = 1

    for row in rows[start_idx:]:
        if not row or not row[0].strip():
            continue
        raw = row[0].strip()
        try:
            ok, _msg = add(raw, group=group)
            if ok:
                success += 1
            else:
                skipped += 1
        except ValueError as e:
            errors.append(str(e))

    return success, skipped, errors


@with_watchlist_lock
def clear(group: str | None = None) -> int:
    """清空指定组 (不传走 default 组) · 不影响其他组 · 返回被清除的股数。"""
    gw = load_grouped_watchlist()
    target = group or gw.default
    if target not in gw.groups:
        raise GroupNotFoundError(
            f"组「{target}」不存在 · 跑 `kan group list` 查看"
        )
    count = len(gw.groups[target])
    gw.groups[target] = []
    _save_grouped_watchlist(gw)
    return count

"""真实持仓存储 · XDG positions.json。

只持久化用户录入的事实：现金、持仓均价、股数、首次录入日。
盈亏、市值、仓位和位置全部在查询时实时计算。
"""
from __future__ import annotations

import csv
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from kan.storage.paths import POSITIONS_PATH, ensure_dirs

SCHEMA_VERSION = 1
MAX_IMPORT_SIZE = 5 * 1024 * 1024
_SYMBOL_RE = re.compile(r"^\d{6}$")


class Position(BaseModel):
    symbol: str
    name: str
    cost: float
    shares: int
    added_at: date

    @field_validator("symbol")
    @classmethod
    def _valid_symbol(cls, value: str) -> str:
        symbol = normalize_symbol(value)
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError("股票代码必须是 6 位数字")
        return symbol

    @field_validator("cost")
    @classmethod
    def _valid_cost(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("成本必须大于 0")
        return round(float(value), 4)

    @field_validator("shares")
    @classmethod
    def _valid_shares(cls, value: int) -> int:
        if int(value) != value or value <= 0:
            raise ValueError("股数必须是正整数")
        return int(value)


class PositionsBook(BaseModel):
    version: int = SCHEMA_VERSION
    cash: float = 0.0
    positions: list[Position] = Field(default_factory=list)

    @field_validator("cash")
    @classmethod
    def _valid_cash(cls, value: float) -> float:
        if value < 0:
            raise ValueError("现金不能为负数")
        return round(float(value), 2)

    def find(self, symbol: str) -> Position | None:
        symbol = normalize_symbol(symbol)
        return next((p for p in self.positions if p.symbol == symbol), None)


class PositionsCorruptError(Exception):
    """positions.json 解析失败。"""


@dataclass(frozen=True)
class ImportRow:
    symbol: str
    cost: float
    shares: int
    name: str | None = None


@dataclass(frozen=True)
class ImportSummary:
    count: int
    total_cost: float
    positions: list[Position]


def normalize_symbol(raw: str) -> str:
    """统一为 6 位 A 股代码，支持 sh/sz/bj 前后缀。"""
    text = raw.strip()
    text = re.sub(r"^(SH|SZ|BJ)[.:]?", "", text, flags=re.I)
    text = re.sub(r"[.:]?(SH|SZ|BJ)$", "", text, flags=re.I)
    if not _SYMBOL_RE.fullmatch(text):
        raise ValueError(f"「{raw}」不是 6 位股票代码")
    return text


def _atomic_write_json(path: Path, payload: object) -> None:
    """原子写 JSON + 0600；父目录按 XDG 用户数据目录收紧到 0700。"""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(path.parent, 0o700)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    with suppress(OSError):
        os.chmod(path, 0o600)


def _load_cached_names() -> dict[str, str]:
    try:
        from kan.storage.watchlist import load_stock_names_cache

        return load_stock_names_cache(allow_stale=True) or {}
    except Exception:
        return {}


def _resolve_name(symbol: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return _load_cached_names().get(symbol, symbol)


def _apply_cached_names(book: PositionsBook) -> PositionsBook:
    names = _load_cached_names()
    if not names:
        return book
    positions = [
        p.model_copy(update={"name": names[p.symbol]})
        if p.name == p.symbol and names.get(p.symbol) else p
        for p in book.positions
    ]
    return book.model_copy(update={"positions": positions})


def load_positions() -> PositionsBook:
    """读取 positions.json；不存在时返回空账本。"""
    if not POSITIONS_PATH.exists():
        return PositionsBook()
    try:
        raw = json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PositionsCorruptError(
            f"持仓文件损坏（{POSITIONS_PATH.name}）· 错误: {e.msg} (行 {e.lineno} 列 {e.colno})"
        ) from e
    try:
        payload = {
            "version": raw.get("version", SCHEMA_VERSION),
            "cash": raw.get("cash", 0.0),
            "positions": raw.get("positions", []),
        }
        return _apply_cached_names(PositionsBook(**payload))
    except Exception as e:
        raise PositionsCorruptError(f"持仓文件结构无效（{POSITIONS_PATH.name}）") from e


def save_positions(book: PositionsBook) -> None:
    ensure_dirs()
    payload = {
        "version": SCHEMA_VERSION,
        "cash": round(book.cash, 2),
        "positions": [p.model_dump(mode="json") for p in book.positions],
    }
    _atomic_write_json(POSITIONS_PATH, payload)


def list_positions() -> list[Position]:
    return list(load_positions().positions)


def set_cash(amount: float) -> PositionsBook:
    book = PositionsBook(**load_positions().model_copy(update={"cash": amount}).model_dump())
    save_positions(book)
    return book


def add_position(
    symbol: str,
    *,
    cost: float,
    shares: int,
    name: str | None = None,
    merge: bool = False,
) -> Position:
    """新增持仓；merge=True 时按成交成本加权到旧持仓。"""
    symbol = normalize_symbol(symbol)
    book = load_positions()
    existing = book.find(symbol)
    if existing is not None and not merge:
        raise ValueError(f"{symbol} 已有持仓 · 若是追加录入请加 --add")

    if existing is None:
        pos = Position(
            symbol=symbol,
            name=_resolve_name(symbol, name),
            cost=cost,
            shares=shares,
            added_at=date.today(),
        )
        book.positions.append(pos)
    else:
        new_shares = existing.shares + int(shares)
        new_cost = (
            existing.cost * existing.shares + float(cost) * int(shares)
        ) / new_shares
        pos = existing.model_copy(update={
            "cost": round(new_cost, 4),
            "shares": new_shares,
            "name": _resolve_name(symbol, name or existing.name),
        })
        book.positions = [pos if p.symbol == symbol else p for p in book.positions]
    save_positions(book)
    return pos


def update_position(
    symbol: str,
    *,
    cost: float | None = None,
    shares: int | None = None,
    name: str | None = None,
) -> Position:
    symbol = normalize_symbol(symbol)
    if cost is None and shares is None and name is None:
        raise ValueError("至少提供 --cost / --shares / --name 之一")
    book = load_positions()
    existing = book.find(symbol)
    if existing is None:
        raise ValueError(f"{symbol} 没有持仓")
    payload: dict[str, Any] = {}
    if cost is not None:
        payload["cost"] = cost
    if shares is not None:
        payload["shares"] = shares
    if name is not None:
        payload["name"] = _resolve_name(symbol, name)
    pos = Position(**existing.model_copy(update=payload).model_dump())
    book.positions = [pos if p.symbol == symbol else p for p in book.positions]
    save_positions(book)
    return pos


def reduce_position(symbol: str, *, shares: int) -> tuple[Position, bool]:
    """减少持股数；减到 0 时删除该持仓。返回 (原/新持仓, 是否清仓)。"""
    symbol = normalize_symbol(symbol)
    if shares <= 0:
        raise ValueError("股数必须是正整数")
    book = load_positions()
    existing = book.find(symbol)
    if existing is None:
        raise ValueError(f"{symbol} 没有持仓")
    if shares > existing.shares:
        raise ValueError(f"减少股数 {shares} 超过当前持股 {existing.shares}")
    if shares == existing.shares:
        book.positions = [p for p in book.positions if p.symbol != symbol]
        save_positions(book)
        return existing, True
    pos = existing.model_copy(update={"shares": existing.shares - shares})
    book.positions = [pos if p.symbol == symbol else p for p in book.positions]
    save_positions(book)
    return pos, False


def remove_position(symbol: str) -> Position:
    symbol = normalize_symbol(symbol)
    book = load_positions()
    existing = book.find(symbol)
    if existing is None:
        raise ValueError(f"{symbol} 没有持仓")
    book.positions = [p for p in book.positions if p.symbol != symbol]
    save_positions(book)
    return existing


def clear_positions() -> int:
    book = load_positions()
    count = len(book.positions)
    save_positions(book.model_copy(update={"positions": []}))
    return count


def add_positions(rows: list[ImportRow]) -> ImportSummary:
    """批量建仓；已有持仓不覆盖，避免误解析静默污染。"""
    book = load_positions()
    existing_symbols = {p.symbol for p in book.positions}
    seen: set[str] = set()
    added: list[Position] = []
    today = date.today()
    for row in rows:
        if row.symbol in seen:
            raise ValueError(f"{row.symbol} 在本次录入中重复")
        if row.symbol in existing_symbols:
            raise ValueError(f"{row.symbol} 已有持仓 · 若是追加录入请用结构化 --add")
        seen.add(row.symbol)
        added.append(Position(
            symbol=row.symbol,
            name=_resolve_name(row.symbol, row.name),
            cost=row.cost,
            shares=row.shares,
            added_at=today,
        ))
    book.positions.extend(added)
    save_positions(book)
    return ImportSummary(
        count=len(added),
        total_cost=sum(p.cost * p.shares for p in added),
        positions=added,
    )


def parse_compact_token(token: str) -> ImportRow:
    parts = [p.strip() for p in token.split(":")]
    if len(parts) not in (3, 4):
        raise ValueError(f"紧凑格式应为 code:cost:shares · 实际: {token}")
    symbol = normalize_symbol(parts[0])
    try:
        cost = float(parts[1])
        shares = int(parts[2])
    except ValueError as e:
        raise ValueError(f"成本/股数格式错误: {token}") from e
    name = parts[3] if len(parts) == 4 and parts[3] else None
    _ = Position(
        symbol=symbol,
        name=_resolve_name(symbol, name),
        cost=cost,
        shares=shares,
        added_at=date.today(),
    )
    return ImportRow(symbol=symbol, cost=cost, shares=shares, name=name)


def parse_import_text(text: str) -> list[ImportRow]:
    """解析 CSV/stdin；支持 header 或无 header，也兼容 code:cost:shares 行。"""
    if len(text.encode("utf-8")) > MAX_IMPORT_SIZE:
        raise ValueError("导入内容超过 5 MB")
    stripped = text.strip()
    if not stripped:
        return []
    rows: list[ImportRow] = []
    reader = csv.reader(StringIO(stripped))
    raw_rows = [[cell.strip() for cell in row] for row in reader if any(c.strip() for c in row)]
    if not raw_rows:
        return []
    header = [c.lower() for c in raw_rows[0]]
    has_header = any(
        c in header
        for c in (
            "symbol", "code", "代码", "股票代码", "成本", "cost", "shares", "股数", "数量",
        )
    )
    data_rows = raw_rows[1:] if has_header else raw_rows
    index = {name: i for i, name in enumerate(header)} if has_header else {}

    for row in data_rows:
        if len(row) == 1 and ":" in row[0]:
            rows.append(parse_compact_token(row[0]))
            continue
        try:
            if has_header:
                symbol = row[_pick_index(index, ("symbol", "code", "代码", "股票代码"), 0)]
                cost = row[_pick_index(index, ("cost", "成本"), 1)]
                shares = row[_pick_index(index, ("shares", "股数", "数量"), 2)]
                name_idx = _pick_index(index, ("name", "名称"), -1)
                name = row[name_idx] if 0 <= name_idx < len(row) else None
            else:
                symbol, cost, shares = row[:3]
                name = row[3] if len(row) >= 4 else None
        except (IndexError, KeyError) as e:
            raise ValueError(f"导入行缺少 symbol/cost/shares: {row}") from e
        rows.append(ImportRow(
            symbol=normalize_symbol(symbol),
            cost=float(cost),
            shares=int(shares),
            name=name or None,
        ))
    return rows


def _pick_index(index: dict[str, int], keys: tuple[str, ...], default: int) -> int:
    for key in keys:
        if key in index:
            return index[key]
    return default


def import_positions(rows: list[ImportRow]) -> ImportSummary:
    """批量导入按纠错覆盖处理：同代码覆盖成本/股数，避免重复污染。"""
    book = load_positions()
    by_symbol = {p.symbol: p for p in book.positions}
    imported: list[Position] = []
    today = date.today()
    for row in rows:
        existing = by_symbol.get(row.symbol)
        pos = Position(
            symbol=row.symbol,
            name=_resolve_name(row.symbol, row.name or (existing.name if existing else None)),
            cost=row.cost,
            shares=row.shares,
            added_at=existing.added_at if existing else today,
        )
        by_symbol[row.symbol] = pos
        imported.append(pos)
    kept_order = [p.symbol for p in book.positions if p.symbol in by_symbol]
    new_symbols = [p.symbol for p in imported if p.symbol not in kept_order]
    ordered = kept_order + new_symbols
    book.positions = [by_symbol[s] for s in ordered]
    save_positions(book)
    return ImportSummary(
        count=len(imported),
        total_cost=sum(p.cost * p.shares for p in imported),
        positions=imported,
    )


def import_positions_text(text: str) -> ImportSummary:
    return import_positions(parse_import_text(text))

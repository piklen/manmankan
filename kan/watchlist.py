"""自选股管理"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import typer

from kan.models import Stock
from kan.paths import (
    NAMES_CACHE_MAX_AGE_DAYS,
    STOCK_NAMES_CACHE,
    WATCHLIST_PATH,
    ensure_dirs,
    is_stock_names_cache_fresh,
)

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB · CSV 导入文件大小上限

__all__ = [  # 显式 re-export · is_stock_names_cache_fresh / NAMES_CACHE_MAX_AGE_DAYS 来自 paths
    "NAMES_CACHE_MAX_AGE_DAYS",
    "STOCK_NAMES_CACHE",
    "is_stock_names_cache_fresh",
]


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写：先写 .tmp 同目录文件，再 os.replace 替换目标。

    避免半截写入导致 JSON 损坏（断电/Ctrl-C/磁盘满）。

    v0.0.4.4: 父目录 mkdir mode=0o700 + 写完 chmod 0o600 ·
    保护用户金融持仓数据（防同机其他用户读取持仓画像）。
    """
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    # 收紧权限到 0o600 (umask 默认 022 会留 0644 · 同机其他用户能读)
    os.chmod(path, 0o600)


class Watchlist:
    def __init__(self, stocks: list[Stock] | None = None) -> None:
        self.stocks: list[Stock] = stocks or []

    def find(self, symbol: str) -> Stock | None:
        for s in self.stocks:
            if s.symbol == symbol:
                return s
        return None


def _normalize_symbol(raw: str) -> str:
    """统一为 6 位纯数字代码。支持 sh600519 / sz000858 / 600519 格式。"""
    cleaned = re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    if not re.match(r"^\d{6}$", cleaned):
        raise ValueError(f"无效股票代码格式: {raw}")
    return cleaned


def _load_stock_names() -> dict[str, str]:
    """加载 A 股代码-名称映射，带本地缓存。

    主用 baostock query_stock_basic (5s · ~3 倍快) ·
    akshare stock_info_a_code_name (~16s) 作为 fallback。
    """
    ensure_dirs()
    if STOCK_NAMES_CACHE.exists():
        mtime = datetime.fromtimestamp(STOCK_NAMES_CACHE.stat().st_mtime)
        if (datetime.now() - mtime).days < NAMES_CACHE_MAX_AGE_DAYS:
            try:
                with open(STOCK_NAMES_CACHE, encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                # 缓存损坏 · 静默重新拉取（不致命，下面会兜底）
                pass

    mapping = _fetch_names_baostock() or _fetch_names_akshare()
    if mapping is None:
        raise RuntimeError(
            "无法获取 A 股代码表 · baostock 和 akshare 均失败 · 请检查网络"
        )
    _atomic_write_json(STOCK_NAMES_CACHE, mapping)
    return mapping


def _fetch_names_baostock() -> dict[str, str] | None:
    """baostock query_stock_basic · 主路径 · 实测 5s · 比 akshare 快 3 倍。

    返回字段: code/code_name/ipoDate/outDate/type/status
      · type='1' = 股票 (排除指数/ETF)
      · status='1' = 上市 (排除退市)
      · code 格式 'sh.600519' → 取后 6 位
    """
    try:
        import io
        import sys

        import baostock as bs

        _stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            bs.login()
        finally:
            sys.stdout = _stdout

        rs = bs.query_stock_basic()
        if rs.error_code != "0":
            return None

        mapping: dict[str, str] = {}
        while rs.next():
            row = rs.get_row_data()
            if len(row) < 6:
                continue
            code, name, _ipo, _out, type_, status = row[:6]
            if type_ != "1" or status != "1":
                continue
            short_code = code.split(".")[-1]
            if len(short_code) == 6 and short_code.isdigit():
                mapping[short_code] = name

        return mapping if mapping else None
    except Exception:
        from rich.console import Console

        Console(stderr=True).print(
            "[yellow]⚠️ baostock 失败 · 切换 akshare 备用源（约 16s）[/yellow]"
        )
        return None


def _fetch_names_akshare() -> dict[str, str] | None:
    """akshare stock_info_a_code_name · fallback · 实测 ~16s · baostock 失败时兜底。

    Lazy import akshare · 不在 watchlist 顶层 import：akshare 拖 pandas/numpy/bs4/requests
    整窝进启动路径，单个就占 watchlist 冷启动成本 85%（~8s 冷启动 ***REMOVED***）。
    本函数仅在 baostock 主路径失败时调用，95%+ 的常规启动不该付这个成本。

    内部 self-suppress akshare 的 tqdm 'n/16' 误导进度条（写到 stderr）。
    不依赖 cli.py 外层重定向 stderr · 避免干扰 cli 的 spinner Live Display。
    """
    import io
    import sys

    import akshare as ak  # lazy: 见 docstring

    _real_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        df = ak.stock_info_a_code_name()
        return dict(zip(df["code"], df["name"], strict=True))
    except Exception:
        return None
    finally:
        sys.stderr = _real_stderr


def _lookup_name(symbol: str) -> str:
    """查询股票名称，未找到则抛异常。"""
    names = _load_stock_names()
    name = names.get(symbol)
    if not name:
        raise ValueError(f"未找到股票: {symbol}（不在 A 股代码表中）")
    return name


def search_by_name(query: str, _names_cache: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """按名称模糊搜索股票 · 返回 [(代码, 名称), ...]"""
    names = _names_cache if _names_cache is not None else _load_stock_names()
    query = query.strip()
    return [(code, name) for code, name in names.items() if query in name]


def preload_stock_names() -> dict[str, str]:
    """Pre-load A-share stock name mapping. Triggers HTTP fetch if cache is stale."""
    return _load_stock_names()


def add_stock(wl: Watchlist, symbol: str, name: str) -> bool:
    """向已加载的 Watchlist 追加一只（不做 IO）。返回是否新增。"""
    if wl.find(symbol):
        return False
    wl.stocks.append(Stock(symbol=symbol, name=name, added_at=date.today()))
    return True


def save_watchlist(wl: Watchlist) -> None:
    """Save watchlist to disk."""
    _save_watchlist(wl)


def load_watchlist() -> Watchlist:
    if not WATCHLIST_PATH.exists():
        return Watchlist()
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        typer.echo(
            f"自选股文件损坏（{WATCHLIST_PATH.name}）· "
            f"请备份后跑 `kan clear` 重置 · 错误: {e.msg} (行 {e.lineno} 列 {e.colno})",
            err=True,
        )
        sys.exit(1)
    stocks = [Stock(**s) for s in data.get("stocks", [])]
    return Watchlist(stocks)


def _save_watchlist(wl: Watchlist) -> None:
    ensure_dirs()
    data = {"stocks": [s.model_dump(mode="json") for s in wl.stocks]}
    _atomic_write_json(WATCHLIST_PATH, data)


def add(symbol: str) -> tuple[bool, str]:
    """添加股票。返回 (是否新增, 消息)。"""
    symbol = _normalize_symbol(symbol)
    wl = load_watchlist()

    if wl.find(symbol):
        return False, f"{symbol} 已在自选列表中"

    name = _lookup_name(symbol)
    stock = Stock(symbol=symbol, name=name, added_at=date.today())
    wl.stocks.append(stock)
    _save_watchlist(wl)
    return True, f"✅ 已添加 {name} ({symbol})"


def remove(symbol: str) -> tuple[bool, str]:
    """移除股票。返回 (是否移除, 消息)。"""
    symbol = _normalize_symbol(symbol)
    wl = load_watchlist()
    original_len = len(wl.stocks)
    wl.stocks = [s for s in wl.stocks if s.symbol != symbol]

    if len(wl.stocks) == original_len:
        return False, f"{symbol} 不在自选列表中"

    _save_watchlist(wl)
    return True, f"已移除 {symbol}"


def list_all() -> list[Stock]:
    return load_watchlist().stocks


def import_csv(path: str | Path) -> tuple[int, int, list[str]]:
    """CSV 导入。返回 (成功数, 跳过数, 错误列表)。

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
        for row in reader:
            if not row or not row[0].strip():
                continue
            raw = row[0].strip()
            try:
                ok, _msg = add(raw)
                if ok:
                    success += 1
                else:
                    skipped += 1
            except ValueError as e:
                errors.append(str(e))

    return success, skipped, errors


def clear() -> int:
    """清空自选列表，返回被清除的数量。"""
    wl = load_watchlist()
    count = len(wl.stocks)
    _save_watchlist(Watchlist())
    return count

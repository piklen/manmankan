"""自选股管理 · v0.0.6.1 起支持多分组 (GroupedWatchlist)。

storage schema v2:
    {
        "version": 2,
        "default": "自选",
        "groups": {
            "自选": {"stocks": [Stock, ...]},
            "持仓": {"stocks": [Stock, ...]}
        }
    }

老 v1 schema {"stocks": [...]} 加载时自动迁移为 v2 (包成 default 组「自选」) ·
迁移即时写回磁盘 · 用户零感知。老 API load_watchlist() / _save_watchlist(wl) /
add / remove / clear / list_all 行为不变 (默认走 default 组) · 新 group 参数
让 CLI 直接操作指定组。
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from kan.core.models import Stock
from kan.infra.log import debug_log
from kan.storage.paths import (
    NAMES_CACHE_MAX_AGE_DAYS,
    STOCK_NAMES_CACHE,
    WATCHLIST_PATH,
    ensure_dirs,
    is_stock_names_cache_fresh,
)

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB · CSV 导入文件大小上限
SCHEMA_VERSION = 2
DEFAULT_GROUP_NAME = "自选"
MAX_GROUP_NAME_LEN = 32

__all__ = [  # 显式 re-export · is_stock_names_cache_fresh / NAMES_CACHE_MAX_AGE_DAYS 来自 paths
    "DEFAULT_GROUP_NAME",
    "NAMES_CACHE_MAX_AGE_DAYS",
    "SCHEMA_VERSION",
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


class GroupedWatchlist:
    """多分组自选股 · v2 schema 包多个 named groups。

    每个 group 拥有独立的 stock list (含独立 added_at) · 同一只股票可同时属于
    多个组 (例如「自选」盯所有 ·「持仓」只看实买) · 各 added_at 反映"加到该组
    的日期"而非"全局首次添加日期"。

    delete_group / rename_group / set_default 都内置 default 组保护 ·
    防误删唯一可用组留下"无 default"的损坏状态。
    """

    def __init__(
        self,
        *,
        groups: dict[str, list[Stock]] | None = None,
        default: str = DEFAULT_GROUP_NAME,
    ) -> None:
        if groups is None:
            groups = {default: []}
        if default not in groups:
            # 防御性 · 理论不发生 (load 时已校正)
            groups[default] = []
        self.groups: dict[str, list[Stock]] = groups
        self.default: str = default

    @property
    def group_names(self) -> list[str]:
        """按插入顺序返回所有组名 (Python 3.7+ dict 保插入序)。"""
        return list(self.groups.keys())

    def get_group(self, name: str | None = None) -> list[Stock]:
        g = name or self.default
        if g not in self.groups:
            raise GroupNotFoundError(
                f"组「{g}」不存在 · 跑 `kan group list` 查看所有组"
            )
        return self.groups[g]

    def has_group(self, name: str) -> bool:
        return name in self.groups

    def find(self, symbol: str, group: str | None = None) -> Stock | None:
        for s in self.get_group(group):
            if s.symbol == symbol:
                return s
        return None


class GroupNotFoundError(Exception):
    """指定组不存在 · CLI 层 catch 后给散户友好引导。"""


class GroupExistsError(Exception):
    """组名冲突 (create / rename / copy 目标已存在)。"""


class GroupProtectedError(Exception):
    """default 组保护 · 不允许删除 / 重命名到合并状态。"""


def _validate_group_name(name: str) -> str:
    """组名规范化 + 校验 · 防特殊字符 / 过长 / 空。"""
    name = name.strip() if name else ""
    if not name:
        raise ValueError("组名不能为空 · 例: kan group create 持仓")
    if len(name) > MAX_GROUP_NAME_LEN:
        raise ValueError(
            f"组名过长 (上限 {MAX_GROUP_NAME_LEN} 字符 · 当前 {len(name)})"
        )
    for ch in "/\\\0\n\r\t":
        if ch in name:
            raise ValueError("组名不能包含 / \\ 换行符 制表符 等特殊字符")
    return name


def _normalize_symbol(raw: str) -> str:
    """统一为 6 位纯数字代码。支持 sh600519 / sz000858 / 600519 格式。

    名称(中文)输入会 raise ValueError + 散户友好引导。
    add 命令内部 catch 后走 fuzzy match · info/compare 显示该消息引导用户。
    """
    cleaned = re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    if not re.match(r"^\d{6}$", cleaned):
        raise ValueError(
            f"「{raw}」不是 6 位股票代码 · "
            f"试 `kan add {raw}` 搜名称查代码 · 或直接用代码如 `kan info 600519`"
        )
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
    except Exception as e:
        # baostock fallback · user-facing warn + debug log
        debug_log(__name__, "baostock stock name fetch", e)
        from rich.console import Console

        Console(stderr=True).print(
            "[yellow]⚠️ baostock 失败 · 切换 akshare 备用源（约 16s）[/yellow]"
        )
        return None


def _fetch_names_akshare() -> dict[str, str] | None:
    """akshare stock_info_a_code_name · fallback · 实测 ~16s · baostock 失败时兜底。

    Lazy import akshare · 不在 watchlist 顶层 import：akshare 拖 pandas/numpy/bs4/requests
    整窝进启动路径，单个就占 watchlist 冷启动成本 85%（~8s 冷启动 启动反馈）。
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
    except Exception as e:
        # akshare fallback · 静默返 None · debug log 供排查
        debug_log(__name__, "akshare stock_info_a_code_name fallback", e)
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
    if not query:
        return []
    return [(code, name) for code, name in names.items() if query in name]


def resolve_symbol_or_name(raw: str) -> tuple[str, str]:
    """6 位代码 → 精确查名;非 6 位 → 名称模糊搜.返回 (code, name).

    多匹配 / 零匹配 / 空输入抛 ValueError + 散户引导.info / compare 共用 ·
    跟 add 的内联流程一致(单匹配通过 · 多匹配列候选 · 零匹配引导).
    """
    cleaned = re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    if re.match(r"^\d{6}$", cleaned):
        return cleaned, _lookup_name(cleaned)
    if not cleaned:
        raise ValueError(
            "空字符串不是有效股票名 / 代码 · 例: kan info 600519 或 kan info 茅台"
        )
    matches = search_by_name(cleaned)
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise ValueError(
            f"未找到包含「{raw}」的股票 · 试更短关键词或用 6 位代码"
        )
    preview = "; ".join(
        f"{code} {name.replace(' ', '')}" for code, name in matches[:8]
    )
    if len(matches) > 8:
        preview += f"; …等 {len(matches)} 只"
    raise ValueError(
        f"「{raw}」匹配到 {len(matches)} 只 · 候选: {preview} · 请用代码精确指定"
    )


def preload_stock_names() -> dict[str, str]:
    """Pre-load A-share stock name mapping. Triggers HTTP fetch if cache is stale."""
    return _load_stock_names()


def add_stock(wl: Watchlist, symbol: str, name: str) -> bool:
    """向已加载的 Watchlist 追加一只（不做 IO）。返回是否新增。"""
    if wl.find(symbol):
        return False
    wl.stocks.append(Stock(symbol=symbol, name=name, added_at=date.today()))
    return True


def save_watchlist(wl: Watchlist, group: str | None = None) -> None:
    """Save watchlist to disk · group=None 走 default 组 (向后兼容)。"""
    _save_watchlist(wl, group=group)


class WatchlistCorruptError(Exception):
    """自选股文件解析失败 · 由 caller (clear --yes / list / scan) 决定 fallback。

    旧实现 sys.exit(1) 在 load 内部 · 剥夺 caller 处理能力 · 导致
    `kan clear --yes` 损坏场景永远死循环 (clear 永远 load 失败 exit 1)。
    改用 raise 让 cli_watchlist_cmds.clear --yes 能跳过 load 直接重置。
    """


def load_watchlist(group: str | None = None) -> Watchlist:
    """加载指定组的自选股 (默认 default 组) · 返回老 Watchlist 对象向后兼容。

    旧调用 `load_watchlist()` 不带参 → 返回 default 组 stocks (跟 v0.0.6 行为一致) ·
    现有测试 / WatchlistSet / cli_*_cmds 零改动仍 work。
    """
    gw = load_grouped_watchlist()
    return Watchlist(stocks=list(gw.get_group(group)))


def _save_watchlist(wl: Watchlist, group: str | None = None) -> None:
    """保存 wl 到指定组 (默认 default 组) · 老调用 _save_watchlist(wl) 不变。

    实现:加载 GroupedWatchlist · 替换目标组的 stocks · 写回。这保留 v2 schema
    完整性 (不擦掉其他组)。
    """
    gw = load_grouped_watchlist()
    target = group or gw.default
    if target not in gw.groups:
        raise GroupNotFoundError(
            f"组「{target}」不存在 · 跑 `kan group create {target}` 新建"
        )
    gw.groups[target] = list(wl.stocks)
    _save_grouped_watchlist(gw)


def load_grouped_watchlist() -> GroupedWatchlist:
    """加载完整多分组 storage · v1 schema 自动迁移到 v2 + 持久化。

    迁移路径:
      v1 {"stocks": [...]} → v2 {"version":2, "default":"自选", "groups":{"自选":{"stocks":[...]}}}
    迁移即时写回磁盘 (一次性) · 之后所有读都直走 v2 fast path。
    """
    if not WATCHLIST_PATH.exists():
        return GroupedWatchlist()
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise WatchlistCorruptError(
            f"自选股文件损坏（{WATCHLIST_PATH.name}）· "
            f"错误: {e.msg} (行 {e.lineno} 列 {e.colno})"
        ) from e

    # v1 → v2 在线迁移 · 检测条件: 顶层有 stocks 但没 groups
    if "stocks" in data and "groups" not in data:
        stocks = [Stock(**s) for s in data.get("stocks", [])]
        gw = GroupedWatchlist(
            groups={DEFAULT_GROUP_NAME: stocks},
            default=DEFAULT_GROUP_NAME,
        )
        _save_grouped_watchlist(gw)
        return gw

    # v2 fast path
    raw_groups = data.get("groups", {})
    groups: dict[str, list[Stock]] = {}
    for name, payload in raw_groups.items():
        stock_list = payload.get("stocks", []) if isinstance(payload, dict) else []
        groups[name] = [Stock(**s) for s in stock_list]

    default = data.get("default", DEFAULT_GROUP_NAME)
    # default 指向不存在组时降级 (理论不发生 · 防御性):
    # 1. 有任意组 → 取第一个为 default 并写回
    # 2. 完全空 → 重建 default 组
    if default not in groups:
        if groups:
            default = next(iter(groups.keys()))
        else:
            groups[DEFAULT_GROUP_NAME] = []
            default = DEFAULT_GROUP_NAME

    return GroupedWatchlist(groups=groups, default=default)


def _save_grouped_watchlist(gw: GroupedWatchlist) -> None:
    """原子写 v2 schema · 保 0o600 持仓画像隐私底线。"""
    ensure_dirs()
    data = {
        "version": SCHEMA_VERSION,
        "default": gw.default,
        "groups": {
            name: {"stocks": [s.model_dump(mode="json") for s in stocks]}
            for name, stocks in gw.groups.items()
        },
    }
    _atomic_write_json(WATCHLIST_PATH, data)


def save_grouped_watchlist(gw: GroupedWatchlist) -> None:
    """公开 wrapper · cli/group_cmds 直接 import 调用 · 跟 save_watchlist 同形。"""
    _save_grouped_watchlist(gw)


# ───────────────────── group CRUD API ─────────────────────


def list_groups() -> list[tuple[str, int, bool]]:
    """返回 [(组名, 股数, 是否 default), ...] 按插入顺序。"""
    gw = load_grouped_watchlist()
    return [
        (name, len(stocks), name == gw.default)
        for name, stocks in gw.groups.items()
    ]


def create_group(name: str) -> str:
    """创建新组 · 返回规范化后的组名。重名抛 GroupExistsError。"""
    name = _validate_group_name(name)
    gw = load_grouped_watchlist()
    if name in gw.groups:
        raise GroupExistsError(f"组「{name}」已存在 · 跑 `kan group list` 查看")
    gw.groups[name] = []
    _save_grouped_watchlist(gw)
    return name


def rename_group(old: str, new: str) -> str:
    """重命名组 · 同时更新 default 指针 (如指向 old)。返回新组名。"""
    new = _validate_group_name(new)
    gw = load_grouped_watchlist()
    if old not in gw.groups:
        raise GroupNotFoundError(f"组「{old}」不存在")
    if new == old:
        return new  # noop
    if new in gw.groups:
        raise GroupExistsError(
            f"组「{new}」已存在 · 拒绝合并 · 想合并跑 `kan group copy {old} {new}` 再 `kan group delete {old}`"
        )
    # 保插入顺序:重建 dict (Python 3.7+ insertion-ordered)
    gw.groups = {(new if k == old else k): v for k, v in gw.groups.items()}
    if gw.default == old:
        gw.default = new
    _save_grouped_watchlist(gw)
    return new


def delete_group(name: str) -> int:
    """删除组 · 不能删 default (先切换 default 再删) · 返回被删股数。"""
    gw = load_grouped_watchlist()
    if name not in gw.groups:
        raise GroupNotFoundError(f"组「{name}」不存在")
    if name == gw.default:
        raise GroupProtectedError(
            f"组「{name}」是默认组 · 不能删除 · 先 `kan group default <其他组>` 切换"
        )
    count = len(gw.groups[name])
    del gw.groups[name]
    _save_grouped_watchlist(gw)
    return count


def set_default_group(name: str) -> str:
    """切换 default 组 · 返回旧 default 组名。"""
    gw = load_grouped_watchlist()
    if name not in gw.groups:
        raise GroupNotFoundError(f"组「{name}」不存在")
    old = gw.default
    gw.default = name
    _save_grouped_watchlist(gw)
    return old


def get_default_group() -> str:
    """获取当前 default 组名。"""
    return load_grouped_watchlist().default


def copy_group(src: str, dst: str) -> int:
    """复制 src 整组到 dst (dst 必须不存在 · 防误覆盖) · 返回复制的股数。"""
    dst = _validate_group_name(dst)
    gw = load_grouped_watchlist()
    if src not in gw.groups:
        raise GroupNotFoundError(f"源组「{src}」不存在")
    if dst in gw.groups:
        raise GroupExistsError(
            f"目标组「{dst}」已存在 · 拒绝覆盖 · 想覆盖先 `kan group delete {dst}`"
        )
    gw.groups[dst] = [s.model_copy() for s in gw.groups[src]]
    _save_grouped_watchlist(gw)
    return len(gw.groups[dst])


def move_stock(symbol: str, src: str, dst: str) -> tuple[Stock, bool]:
    """跨组移动单股 · src/dst 都必须存在 (不自动建组 · 防 typo 灾难)。

    返回 (移动的 Stock, dst_already_had) ·
    dst_already_had=True 表示目标组已有该股 (只从 src 删除 · 不重复添加)。
    """
    symbol = _normalize_symbol(symbol)
    gw = load_grouped_watchlist()
    if src not in gw.groups:
        raise GroupNotFoundError(f"源组「{src}」不存在")
    if dst not in gw.groups:
        raise GroupNotFoundError(
            f"目标组「{dst}」不存在 · 跑 `kan group create {dst}` 新建 · 不自动建组防 typo"
        )
    src_stocks = gw.groups[src]
    found = next((s for s in src_stocks if s.symbol == symbol), None)
    if found is None:
        raise ValueError(f"{symbol} 不在「{src}」组中")
    dst_existed = any(s.symbol == symbol for s in gw.groups[dst])
    gw.groups[src] = [s for s in src_stocks if s.symbol != symbol]
    if not dst_existed:
        gw.groups[dst].append(found)
    _save_grouped_watchlist(gw)
    return found, dst_existed


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
    """列指定组股票 (不传走 default 组) · 老调用 list_all() 不变。"""
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

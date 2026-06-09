"""自选股 storage 数据模型与通用校验。"""
from __future__ import annotations

import re

from kan.core.models import Stock

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB · CSV 导入文件大小上限
SCHEMA_VERSION = 2
DEFAULT_GROUP_NAME = "自选"
MAX_GROUP_NAME_LEN = 32


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


class WatchlistCorruptError(Exception):
    """自选股文件解析失败 · 由 caller (clear --yes / list / scan) 决定 fallback。

    旧实现 sys.exit(1) 在 load 内部 · 剥夺 caller 处理能力 · 导致
    `kan clear --yes` 损坏场景永远死循环 (clear 永远 load 失败 exit 1)。
    改用 raise 让 cli_watchlist_cmds.clear --yes 能跳过 load 直接重置。
    """


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

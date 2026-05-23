"""StockSet · 股票集合抽象 (OOP 视角的 manmankan)。

把"一组股票"抽象成对象 · 让 verb (scan / trend / low / high / ...) 接受
任何 StockSet 实例统一处理 · 而不是各命令 if industry / elif hot / elif theme /
else watchlist 分支分发。

四类基础实现:
- WatchlistSet:  自选股 (本地 storage)
- HotRankSet:    东方财富热榜 (人气榜 / 飙升榜)
- ThemeSet:      题材股 (同花顺概念板块成分股)
- IndustrySet:   行业股 (东财行业分类)

设计选择:
- Protocol-based · 任何带 name / codes() / pairs() 的对象都可扮演 StockSet
  (无需继承 · 鸭子类型 · 利于用户扩展自定义集合)
- lazy resolution · 调 .codes() / .pairs() 时才真正拉数据 (不阻塞 import)
- 构造器只接 identifier (theme 名 / hot mode) · 数据获取沉淀到 .pairs()

CLI 层 (kan/cli/*_cmds.py) 暂未迁移 · 仍走 resolve_scan_targets。OOP 层是
为"Python API 使用 + 渐进迁移 CLI"打地基。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class StockSet(Protocol):
    """股票集合抽象 · 任何"一组股票"对象都可以扮演这个 role。

    必需:
    - `name` (property 或 attr): 集合显示名 (CLI 输出 / 日志 / 错误提示)
    - `codes()`: 6 位纯数字代码列表
    - `pairs()`: (代码, 名称) 元组列表 (名称缺失时可为空字符串)

    可选:
    - `__len__`: 元素个数 (默认走 len(codes()))
    """

    name: str

    def codes(self) -> list[str]: ...
    def pairs(self) -> list[tuple[str, str]]: ...


# ───────────────────── 4 个具体实现 ─────────────────────


@dataclass
class WatchlistSet:
    """自选股集合 · 从本地 storage 加载 (kan add / kan remove 管理的列表)。"""

    name: str = "自选股"
    _pairs: list[tuple[str, str]] | None = None

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.storage.watchlist import load_watchlist

            wl = load_watchlist()
            self._pairs = [(s.symbol, s.name) for s in wl.stocks]
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class HotRankSet:
    """东方财富热榜 / 涨速榜集合。

    mode = "rank" → 人气榜 (HotList.RANK)
    mode = "surge" → 飙升榜 (HotList.SURGE)
    """

    mode: str = "rank"
    _pairs: list[tuple[str, str]] | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return "东财人气榜" if self.mode == "rank" else "东财飙升榜"

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.data.hot import HotList, fetch_hot_list

            which = HotList.RANK if self.mode == "rank" else HotList.SURGE
            entries = fetch_hot_list(which)
            self._pairs = [(e.symbol, e.name) for e in entries]
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class ThemeSet:
    """题材股集合 · 同花顺概念板块成分股。

    构造时传题材名 (如 "AI" / "国产软件" / "新能源")。
    .pairs() 触发 catalog 查找 + 拉成分股。
    """

    theme: str
    _pairs: list[tuple[str, str]] | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return f"题材「{self.theme}」"

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.data import boards

            themed = boards.search_theme(self.theme)
            self._pairs = boards.get_theme_constituents(themed)
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class IndustrySet:
    """行业股集合 · 东财行业分类 (申万 / 中信类似行业体系)。

    构造时传行业名 (如 "银行" / "白酒" / "半导体")。
    .pairs() 触发 catalog 查找 + 拉成分股。
    """

    industry: str
    _pairs: list[tuple[str, str]] | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return f"行业「{self.industry}」"

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.data import boards

            board = boards.search_industry(self.industry)
            self._pairs = boards.get_industry_constituents(board)
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())


# ───────────────────── factory ─────────────────────


def from_flags(
    *,
    industry: str | None = None,
    hot: str | None = None,
    theme: str | None = None,
) -> StockSet:
    """从 CLI flags 构造对应 StockSet (一类 factory)。

    - 三者全 None → WatchlistSet (默认走自选股)
    - 任一非 None → 对应 Set
    - 任意两个或三个同时非 None → ValueError (互斥)
    """
    given = sum(1 for x in (industry, hot, theme) if x is not None)
    if given > 1:
        raise ValueError(
            "industry / hot / theme 三者互斥 · 同时只能指定一个"
        )
    if industry is not None:
        return IndustrySet(industry)
    if hot is not None:
        return HotRankSet(hot)
    if theme is not None:
        return ThemeSet(theme)
    return WatchlistSet()


__all__ = [
    "HotRankSet",
    "IndustrySet",
    "StockSet",
    "ThemeSet",
    "WatchlistSet",
    "from_flags",
]

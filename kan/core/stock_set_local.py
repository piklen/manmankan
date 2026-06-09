"""本地和显式股票集合实现。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WatchlistSet:
    """自选股集合 · 从本地 storage 加载指定组 (kan add/remove --group 管理)。

    group=None → 走 default 组 (kan group default 切换) · 跟 当前行为完全一致 ·
    group="持仓" → 走该具名组 · 触发 lazy resolve 时调 load_watchlist("持仓")。
    """

    name: str = "自选股"
    group: str | None = None
    _pairs: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        # group 指定时 name 自动加组名后缀 (CLI 输出 / 日志识别) · 默认不变
        if self.group and self.name == "自选股":
            self.name = f"自选股·{self.group}"

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.storage.watchlist import load_watchlist

            wl = load_watchlist(self.group)
            self._pairs = [(s.symbol, s.name) for s in wl.stocks]
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def meta(self) -> None:
        """自选股集合无 meta (highlight/index_kline/rank_map 仅对 industry/hot/theme 有意义)。"""
        return None

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class HoldingsSet:
    """真实持仓集合 · 从 positions.json 加载。"""

    name: str = "真实持仓"
    _pairs: list[tuple[str, str]] | None = None

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.storage.positions import load_positions

            book = load_positions()
            self._pairs = [(p.symbol, p.name) for p in book.positions]
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def meta(self) -> None:
        return None

    def membership(self, symbol: str) -> tuple[bool, bool]:
        holding = {c for c, _ in self._resolve()}
        return False, symbol in holding

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class WatchlistHoldingsSet:
    """默认池 · 自选 ∪ 真实持仓，保留成员来源用于渲染标记。"""

    name: str = "自选股+真实持仓"
    _pairs: list[tuple[str, str]] | None = None
    _watchlist_codes: set[str] = field(default_factory=set, repr=False)
    _holding_codes: set[str] = field(default_factory=set, repr=False)

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.storage.positions import load_positions
            from kan.storage.watchlist import load_watchlist

            watchlist_pairs = [(s.symbol, s.name) for s in load_watchlist().stocks]
            holding_pairs = [(p.symbol, p.name) for p in load_positions().positions]
            self._watchlist_codes = {c for c, _ in watchlist_pairs}
            self._holding_codes = {c for c, _ in holding_pairs}
            merged: dict[str, str] = {}
            for code, name in [*watchlist_pairs, *holding_pairs]:
                if code not in merged:
                    merged[code] = name
            self._pairs = list(merged.items())
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def meta(self) -> None:
        return None

    def membership(self, symbol: str) -> tuple[bool, bool]:
        self._resolve()
        return symbol in self._watchlist_codes, symbol in self._holding_codes

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class AllStocksSet:
    """A 股全市场集合 · tushare stock_basic 全部上市股 (排北交所 · 含 ST)。"""

    name: str = "A股全市场"
    _pairs: list[tuple[str, str]] | None = None

    def _resolve(self) -> list[tuple[str, str]]:
        if self._pairs is None:
            from kan.data.universe import fetch_all_stocks

            self._pairs = fetch_all_stocks()
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self._resolve()]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self._resolve())

    def meta(self) -> None:
        """全市场集合无 meta (highlight/index_kline/rank_map 仅对 industry/hot/theme 有意义)。"""
        return None

    def __len__(self) -> int:
        return len(self._resolve())


@dataclass
class CodeListSet:
    """用户显式传入的代码池 · 给 `kan find --codes` / stdin 管线复用。"""

    pairs_input: list[tuple[str, str]]
    label: str = "自定义代码池"

    @property
    def name(self) -> str:
        return f"{self.label}({len(self.pairs_input)}只)"

    def codes(self) -> list[str]:
        return [c for c, _ in self.pairs_input]

    def pairs(self) -> list[tuple[str, str]]:
        return list(self.pairs_input)

    def meta(self) -> None:
        return None

    def __len__(self) -> int:
        return len(self.pairs_input)

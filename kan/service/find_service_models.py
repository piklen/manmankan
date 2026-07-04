"""Render-neutral find service request/result models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from kan.data.relative_strength import DEFAULT_RS_INDEX

if TYPE_CHECKING:
    from kan.core.cross_section import CrossSectionCtx, CrossSectionRow
    from kan.core.find_dsl import ConditionSet
    from kan.core.find_filter import FindMatch, TriggeredFilter
    from kan.core.pipeline import DataCtx
    from kan.core.stock_set import StockSet
    from kan.data.hot import HotList

FindOutputMode = Literal["terminal", "md", "json"]


class FindServiceError(Exception):
    """Domain-level find error, rendered by CLI/API adapters."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        hint: str | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


@dataclass(frozen=True)
class FindOutputProfile:
    """Requested result shape without depending on CLI OutputFormat."""

    mode: FindOutputMode
    compact: bool = False
    compact_context: bool = True
    field_paths: tuple[str, ...] = ()
    field_dimensions: frozenset[str] = frozenset()
    agent_summary: bool = False

    @property
    def is_export(self) -> bool:
        return self.mode != "terminal"


@dataclass(frozen=True)
class FindKlineRequest:
    conditions: ConditionSet
    output: FindOutputProfile
    code_pairs: list[tuple[str, str]] | None = None
    industry: str | None = None
    hot: HotList | None = None
    theme: str | None = None
    only_watchlist: bool = False
    only_holdings: bool = False
    exclude_star: bool = False
    exclude_bj: bool = False
    allow_auto_fetch: bool = True
    group: str | None = None
    limit: int | None = None
    offset: int = 0
    sort: tuple[str, str] | None = None
    rs_index_code: str = DEFAULT_RS_INDEX


@dataclass(frozen=True)
class FindCodePoolResult:
    stock_set: StockSet
    code_pairs: list[tuple[str, str]]
    pools: list[str]
    query_time: str


@dataclass(frozen=True)
class FindKlineResult:
    stock_set: StockSet
    ctx: DataCtx
    pool_results: list[Any]
    matches: list[FindMatch]
    matches_limited: list[FindMatch]
    effective_limit: int
    pools: list[str]
    filters: list[dict]
    query_time: str
    included_dimensions: set[str]
    compact_dimensions: set[str]

    @property
    def entries(self) -> list[tuple[FindMatch, Any]]:
        return [(m, m.result) for m in self.matches_limited]


@dataclass(frozen=True)
class FindCrossSectionRequest:
    conditions: ConditionSet
    output: FindOutputProfile
    source_mode: bool = False
    limit: int | None = None
    offset: int = 0
    sort: tuple[str, str] | None = None
    rs_index_code: str = DEFAULT_RS_INDEX


@dataclass(frozen=True)
class FindCrossSectionResult:
    ctx: CrossSectionCtx
    matched: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]]
    limited: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]]
    query_time: str
    filters: list[dict]
    included_dimensions: set[str]
    compact_dimensions: set[str]

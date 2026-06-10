"""`kan find` filter 匹配模型。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.models import StockScanResult


@dataclass(frozen=True)
class TriggeredFilter:
    """命中的单个 filter · 用于 find 结果审计轨迹。"""

    filter_type: str
    param: str
    value: float


@dataclass(frozen=True)
class FindMatch:
    """命中全部 filter 的单只股票 · 附带审计轨迹。"""

    result: StockScanResult
    triggered: tuple[TriggeredFilter, ...]


@dataclass(frozen=True)
class MatchSegmentSpec:
    """ConditionSet 字段、目标对象和 matcher 的绑定。"""

    filter_type: str
    condition_attr: str
    target_attr: str
    matcher: Callable[..., TriggeredFilter | None]
    supports_cross_section: bool = True

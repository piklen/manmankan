"""DSL parser for `kan find` · v0.0.6.4 MVP

按用户输入条件 · 解析成结构化 Filter 对象。

支持 filter (MVP v0.0.6.4):
- --pos PERIOD:OP:VAL    位置百分位 (例 180:lt:5 = 180 日位置 < 5%)
- --resonance LEVEL:OP:VAL  共振信号 (例 low:gte:3 = 低点共振 ≥ 3 周期)
- --exclude-st           排 ST/*ST

Future (v0.0.6.5+ candidates):
- --vol-ratio OP:VAL     量比 filter (需要 calc_volume_state)
- --streak up|down:OP:VAL  连涨连跌 (需要 calc_trend)
- --exclude-newshare DAYS  新股排除 (需要上市日期)

合规边界(manmankan/docs/compliance.md §7):
- 用户显式指定 filter · 不内置 preset
- 输出 "符合条件的股票" · 不"推荐 / 评级"
- 严格 grammar 校验 + 错误信息引导用户
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ALLOWED_OPS = ("lt", "lte", "gt", "gte", "eq", "ne")
ALLOWED_PERIODS = (3, 5, 7, 10, 15, 30, 60, 90, 120, 180)
RESONANCE_LEVELS = ("low", "high")


class FilterParseError(ValueError):
    """DSL parse error · raised when user input violates grammar."""


@dataclass(frozen=True)
class PosFilter:
    """位置百分位 filter · 例 PERIOD=180 OP=lt VALUE=5.0 = 180 日位置 < 5%."""

    period: int
    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> PosFilter:
        """Parse 'PERIOD:OP:VAL' string · 例 '180:lt:5'."""
        parts = raw.split(":")
        if len(parts) != 3:
            raise FilterParseError(
                f"--pos 格式错误 '{raw}' · 需要 PERIOD:OP:VAL 例 180:lt:5"
            )
        try:
            period = int(parts[0])
        except ValueError as e:
            raise FilterParseError(
                f"--pos 周期非整数 '{parts[0]}' · 例: --pos 180:lt:5"
            ) from e
        if period not in ALLOWED_PERIODS:
            raise FilterParseError(
                f"--pos 周期 {period} 不支持 · 仅 {list(ALLOWED_PERIODS)} · 例: --pos 180:lt:5"
            )
        op = parts[1].lower()
        if op not in ALLOWED_OPS:
            raise FilterParseError(
                f"--pos 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · 例: --pos 180:lt:5"
            )
        try:
            value = float(parts[2])
        except ValueError as e:
            raise FilterParseError(
                f"--pos 数值非数字 '{parts[2]}' · 例: --pos 180:lt:5"
            ) from e
        if not 0 <= value <= 100:
            raise FilterParseError(
                f"--pos 数值 {value} 越界 · 需 [0, 100] · 例: --pos 180:lt:5"
            )
        return cls(period=period, op=op, value=value)


@dataclass(frozen=True)
class ResonanceFilter:
    """共振 filter · 例 LEVEL=low OP=gte VALUE=3 = 低点共振 ≥ 3 周期."""

    level: Literal["low", "high"]
    op: str
    value: int

    @classmethod
    def parse(cls, raw: str) -> ResonanceFilter:
        """Parse 'LEVEL:OP:VAL' string · 例 'low:gte:3'."""
        parts = raw.split(":")
        if len(parts) != 3:
            raise FilterParseError(
                f"--resonance 格式错误 '{raw}' · 需要 LEVEL:OP:VAL 例 low:gte:3"
            )
        level = parts[0].lower()
        if level not in RESONANCE_LEVELS:
            raise FilterParseError(
                f"--resonance 级别 '{level}' 不支持 · 仅 low/high · 例: --resonance low:gte:3"
            )
        op = parts[1].lower()
        if op not in ALLOWED_OPS:
            raise FilterParseError(
                f"--resonance 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · 例: --resonance low:gte:3"
            )
        try:
            value = int(parts[2])
        except ValueError as e:
            raise FilterParseError(
                f"--resonance 数值非整数 '{parts[2]}' · 例: --resonance low:gte:3"
            ) from e
        if not 0 <= value <= 10:
            raise FilterParseError(
                f"--resonance 数值 {value} 越界 · 需 [0, 10] · 例: --resonance low:gte:3"
            )
        return cls(level=level, op=op, value=value)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ConditionSet:
    """DSL 解析后的完整 filter 集合 · 多 filter 间 AND 语义.

    MVP (v0.0.6.4):
    - pos_filters: tuple[PosFilter, ...]
    - resonance_filters: tuple[ResonanceFilter, ...]
    - exclude_st: bool
    """

    pos_filters: tuple[PosFilter, ...] = ()
    resonance_filters: tuple[ResonanceFilter, ...] = ()
    exclude_st: bool = False

    @classmethod
    def from_flags(
        cls,
        *,
        pos: list[str] | None = None,
        resonance: list[str] | None = None,
        exclude_st: bool = False,
    ) -> ConditionSet:
        """Build ConditionSet from CLI flag strings (raw user input)."""
        pos_parsed = tuple(PosFilter.parse(p) for p in (pos or []))
        res_parsed = tuple(ResonanceFilter.parse(r) for r in (resonance or []))
        return cls(
            pos_filters=pos_parsed,
            resonance_filters=res_parsed,
            exclude_st=exclude_st,
        )

    def is_empty(self) -> bool:
        return (
            not self.pos_filters
            and not self.resonance_filters
            and not self.exclude_st
        )


_OP_FUNCS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def apply_op(op: str, lhs: float, rhs: float) -> bool:
    """Apply comparison op · case-insensitive · raises if unknown."""
    if op not in _OP_FUNCS:
        raise ValueError(f"unsupported op '{op}'")
    return _OP_FUNCS[op](lhs, rhs)


__all__ = [
    "ALLOWED_OPS",
    "ALLOWED_PERIODS",
    "RESONANCE_LEVELS",
    "ConditionSet",
    "FilterParseError",
    "PosFilter",
    "ResonanceFilter",
    "apply_op",
]

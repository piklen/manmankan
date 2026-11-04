"""趋势因子的展示名称；不把结构枚举作为数值强弱评分。"""
from __future__ import annotations

from kan.domain.market_study import StudyField

_LABELS: dict[str, dict[float, str]] = {
    "swing_structure": {-1: "下降结构", 0: "混合结构", 1: "上升结构"},
    "swing_direction": {-1: "当前下行", 0: "尚未形成", 1: "当前上行"},
}


def factor_value(field: StudyField, value: float | None, unit: str = "") -> str:
    if value is None:
        return "未知"
    if field in _LABELS:
        return _LABELS[field].get(value, f"{value:g}")
    return f"{value:g}{unit}"


def swing_phase(values: dict[str, float | None], window: int) -> str:
    structure = values.get(f"swing_structure.{window}")
    direction = values.get(f"swing_direction.{window}")
    relation = factor_value("swing_structure", structure) if structure is not None else "结构不足"
    return f"{window}日 已确认点关系：{relation} · {factor_value('swing_direction', direction)}"

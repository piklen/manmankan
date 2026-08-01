"""find service sorting and pagination helpers."""
from __future__ import annotations

from typing import Any


def _nested(obj: object, attr: str, sub: str) -> float | None:
    """安全取 obj.<attr>.<sub> 数值(子对象/字段缺失 → None)· sort getter 共用。"""
    holder = getattr(obj, attr, None)
    val = getattr(holder, sub, None) if holder is not None else None
    return val if isinstance(val, (int, float)) else None


SORT_FIELD_GETTERS = {
    "pe": lambda o: _nested(o, "valuation", "pe_ttm"),
    "pb": lambda o: _nested(o, "valuation", "pb"),
    "dv": lambda o: _nested(o, "valuation", "dv_ttm"),
    "turnover": lambda o: _nested(o, "valuation", "turnover_rate"),
    "market_cap": lambda o: _nested(o, "valuation", "total_mv"),
    "volume_ratio": lambda o: _nested(o, "valuation", "volume_ratio"),
    "moneyflow": lambda o: _nested(o, "moneyflow", "net_amount"),
    "moneyflow_daily": lambda o: _nested(o, "moneyflow", "net_amount"),
    "moneyflow_days": lambda o: _nested(o, "moneyflow", "inflow_days"),
}
"""--sort 支持字段 · key=用户输入名 · value=从 match.result / 截面 row 取裸值。"""


def _sorted_offset_limit(
    items: list,
    key_obj: Any,
    sort: tuple[str, str] | None,
    offset: int,
    limit: int | None,
) -> list:
    """按 sort 排序(None 值恒排末尾)后做 offset/limit 切片 · K 线池 + 截面两路径共用。

    sort: (field, "asc"|"desc") · field 必在 SORT_FIELD_GETTERS(cmds 已校验)。
    key_obj: item → 取字段的对象(K 线池=FindMatch.result · 截面=row tuple[0])。
    """
    out = items
    if sort is not None:
        field, direction = sort
        getter = SORT_FIELD_GETTERS.get(field)
        if getter is not None:
            reverse = direction == "desc"

            def _key(it: Any) -> tuple:
                v = getter(key_obj(it))
                if v is None:
                    return (1, 0.0)  # None 恒排末尾(不论 asc/desc)
                return (0, -v if reverse else v)

            out = sorted(items, key=_key)
    start = max(0, offset)
    end = None if limit is None else start + limit
    return out[start:end]

"""Web 持仓事实序列化；AI JSON 契约由 storage/export.py 负责。"""
from __future__ import annotations

import math
from typing import Any

from kan.core.positions import PositionsSummary


def _date_text(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _round(value: float | None, digits: int = 2) -> float | None:
    # NaN/Inf 必须归一成 None:Starlette JSONResponse 用 allow_nan=False,
    # 任何非法浮点会在路由 return 之后的渲染阶段抛 ValueError → 500,
    # 且路由内 try/except 兜不住(渲染发生在路由作用域之外)。
    if value is None:
        return None
    f = float(value)
    return None if math.isnan(f) or math.isinf(f) else round(f, digits)


def serialize_hold(result: PositionsSummary) -> dict[str, Any]:
    """持仓页数据。"""
    rows = []
    for row in result.results:
        p180 = row.positions.get(180)
        # 盈亏速算：回本价和距回本距离
        breakeven_price = None
        distance_to_breakeven = None
        if row.cost and row.price and row.price > 0:
            breakeven_price = round(row.cost, 2)
            distance_to_breakeven = round((row.cost - row.price) / row.price * 100, 1)
        rows.append({
            "code": row.symbol,
            "name": row.name.replace(" ", ""),
            "cost": _round(row.cost, 4),
            "shares": row.shares,
            "price": _round(row.price),
            "prev_close": _round(row.prev_close),
            "market_value": _round(row.market_value),
            "daily_pnl": _round(row.daily_pnl),
            "daily_pnl_pct": _round(row.daily_pnl_pct),
            "total_pnl": _round(row.total_pnl),
            "total_pnl_pct": _round(row.total_pnl_pct),
            "weight_pct": _round(row.weight_pct),
            "p30_pct": _round(row.positions.get(30), 1),
            "p60_pct": _round(row.positions.get(60), 1),
            "p180_pct": _round(p180, 1),
            "price_source": row.price_source,
            "price_status": row.price_status,
            "breakeven_price": breakeven_price,
            "distance_to_breakeven": distance_to_breakeven,
        })
    return {
        "ok": True,
        "price_mode": result.price_mode,
        "data_cutoff": _date_text(result.data_cutoff),
        "account": {
            "cash": _round(result.account.cash),
            "total_market_value": _round(result.account.total_market_value),
            "total_assets": _round(result.account.total_assets),
            "total_position_pct": _round(result.account.total_position_pct),
            "daily_pnl": _round(result.account.daily_pnl),
            "total_pnl": _round(result.account.total_pnl),
        },
        "rows": rows,
        "notes": list(result.notes),
    }


def empty_hold_payload(*, error: str | None = None) -> dict[str, Any]:
    """持仓不可用时的中性降级 payload。"""
    return {
        "ok": error is None,
        "error": error,
        "price_mode": None,
        "data_cutoff": None,
        "account": {
            "cash": None,
            "total_market_value": None,
            "total_assets": None,
            "total_position_pct": None,
            "daily_pnl": None,
            "total_pnl": None,
        },
        "rows": [],
        "notes": [],
    }

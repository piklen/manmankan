"""Web 出口序列化。

Web 只输出页面友好的扁平结构;AI JSON 契约继续由 kan/storage/export.py 负责。
"""
from __future__ import annotations

import math
from typing import Any

from kan.core.models import StockScanResult
from kan.core.positions import PositionsSummary
from kan.service.daily_service import DailyOverview
from kan.service.history_service import HistoryServiceResult
from kan.service.index_service import IndexServiceResult
from kan.service.info_service import InfoServiceResult
from kan.service.scan_service import ScanServiceResult


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


def serialize_scan(result: ScanServiceResult) -> dict[str, Any]:
    """scan 表格与热力图数据。"""
    periods = sorted({
        period.period
        for row in result.results
        for period in row.periods
    })
    rows: list[dict[str, Any]] = []
    heatmap: list[dict[str, Any]] = []
    for row in result.results:
        item: dict[str, Any] = {
            "code": row.symbol,
            "name": row.name.replace(" ", ""),
            "price": _round(row.current_price),
            "scan_date": _date_text(row.scan_date),
            "low_resonance": row.low_resonance,
            "high_resonance": row.high_resonance,
            "in_watchlist": row.in_watchlist,
            "in_holding": row.in_holding,
        }
        for period in row.periods:
            key = f"p{period.period}"
            item[f"{key}_pct"] = None if period.insufficient else _round(period.position_pct, 1)
            item[f"{key}_at_low"] = False if period.insufficient else period.at_low
            item[f"{key}_at_high"] = False if period.insufficient else period.at_high
            heatmap.append({
                "code": row.symbol,
                "name": row.name.replace(" ", ""),
                "period": period.period,
                "position_pct": None if period.insufficient else _round(period.position_pct, 1),
                "at_low": False if period.insufficient else period.at_low,
                "at_high": False if period.insufficient else period.at_high,
            })
        rows.append(item)
    return {
        "ok": True,
        "source_name": result.ctx.source_name,
        "mode": result.mode,
        "periods": periods,
        "stats": {
            "targets": len(result.ctx.targets),
            "shown": len(rows),
            "data_cutoff": _date_text(result.ctx.freshness.data_cutoff),
            "expected_cutoff": _date_text(result.ctx.freshness.expected_cutoff),
            "fetched_at": result.ctx.freshness.fetched_at,
            "stale": result.ctx.freshness.is_stale,
        },
        "freshness": _freshness_payload(result),
        "rows": rows,
        "heatmap": heatmap,
    }


def serialize_daily_overview(result: DailyOverview) -> dict[str, Any]:
    """散户首页摘要，保留客观事实，不生成交易结论。"""
    return {
        "data_cutoff": _date_text(result.data_cutoff),
        "expected_cutoff": _date_text(result.expected_cutoff),
        "stale": result.stale,
        "scanned_count": result.scanned_count,
        "low_180_count": len(result.low_180),
        "high_180_count": len(result.high_180),
        "low_resonance_count": result.low_resonance_count,
        "high_resonance_count": result.high_resonance_count,
        "low_180": [_overview_row(row) for row in result.low_180[:6]],
        "high_180": [_overview_row(row) for row in result.high_180[:6]],
        "comparison_date": _date_text(result.comparison_date),
        "changes": [
            {
                "code": change.code,
                "name": change.name,
                "period": change.period,
                "description": change.description,
            }
            for change in result.changes[:12]
        ],
        "change_count": len(result.changes),
    }


def _overview_row(row: StockScanResult) -> dict[str, Any]:
    p180 = next(
        (period for period in row.periods if period.period == 180 and not period.insufficient),
        None,
    )
    return {
        "code": row.symbol,
        "name": row.name.replace(" ", ""),
        "price": _round(row.current_price),
        "position_180": _round(p180.position_pct, 1) if p180 else None,
        "low_resonance": row.low_resonance,
        "high_resonance": row.high_resonance,
        "in_holding": row.in_holding,
    }


def _freshness_payload(result: ScanServiceResult) -> dict[str, Any]:
    freshness = result.ctx.freshness
    cutoff = _date_text(freshness.data_cutoff)
    expected = _date_text(freshness.expected_cutoff)
    target_count = len(result.ctx.targets)
    missing_count = getattr(freshness, "missing_count", 0)
    current_count = getattr(freshness, "current_count", 0)
    min_cutoff = _date_text(getattr(freshness, "min_cutoff", None))
    history_incomplete_count = getattr(freshness, "history_incomplete_count", 0)
    required_rows = getattr(freshness, "required_rows", None)
    if target_count == 0:
        return {
            "status": "missing",
            "title": "先添加一只自己的股票",
            "detail": "在下方输入 6 位股票代码；添加后会自动更新本地行情。",
            "action_label": "先添加自选",
        }
    if freshness.data_cutoff is None:
        return {
            "status": "missing",
            "title": "还没有可用行情数据",
            "detail": "点击更新数据；如果失败，请检查网络后重试。",
            "action_label": "更新数据",
        }
    if freshness.is_stale:
        expected_text = f"，正常应至少到 {expected}" if expected else ""
        coverage = ""
        if missing_count:
            coverage = f"；{missing_count} 只没有可用缓存"
        elif current_count < target_count and min_cutoff:
            coverage = f"；最早一只只到 {min_cutoff}"
        elif history_incomplete_count and required_rows:
            coverage = (
                f"；{history_incomplete_count} 只历史数据不足 {required_rows} 个交易日"
            )
        return {
            "status": "stale",
            "title": "行情数据需要更新",
            "detail": f"最新一只到 {cutoff}{expected_text}{coverage}。更新前，位置和变化对比可能不完整。",
            "action_label": "立即更新",
        }
    fetched_text = f" · 本机拉取 {freshness.fetched_at}" if freshness.fetched_at else ""
    return {
        "status": "current",
        "title": f"行情已更新至 {cutoff}",
        "detail": f"以下概览均按该交易日收盘数据计算{fetched_text}。",
        "action_label": "重新检查",
    }


def serialize_info(result: InfoServiceResult) -> dict[str, Any]:
    """单股 info 数据。"""
    periods = []
    for period in result.result.periods:
        periods.append({
            "period": period.period,
            "position_pct": None if period.insufficient else _round(period.position_pct, 1),
            "at_low": False if period.insufficient else period.at_low,
            "at_high": False if period.insufficient else period.at_high,
            "n_low": None if period.insufficient else _round(period.n_low),
            "n_high": None if period.insufficient else _round(period.n_high),
            "gain_pct": _round(period.gain_pct),
            "distance_to_low_pct": _round(period.distance_to_low_pct),
            "distance_to_high_pct": _round(period.distance_to_high_pct),
        })
    volume = None
    if result.volume is not None:
        volume = {
            "window": result.volume.window,
            "ratio": _round(result.volume.ratio),
            "label": result.volume.label,
            "state": result.volume.state,
        }
    valuation = {
        "trade_date": _date_text(result.result.valuation_trade_date),
        "pe_ttm": _round(result.result.pe_ttm),
        "pb": _round(result.result.pb),
        "ps_ttm": _round(result.result.ps_ttm),
        "dv_ttm": _round(result.result.dv_ttm),
        "turnover_rate": _round(result.result.turnover_rate),
        "volume_ratio": _round(result.result.volume_ratio),
        "total_mv": _round(result.result.total_mv),
        "circ_mv": _round(result.result.circ_mv),
    }
    if result.valuation is not None:
        valuation.update({
            "trade_date": _date_text(result.valuation.trade_date),
            "pe_ttm": _round(result.valuation.pe_ttm),
            "pb": _round(result.valuation.pb),
            "ps_ttm": _round(result.valuation.ps_ttm),
            "dv_ttm": _round(result.valuation.dv_ttm),
            "turnover_rate": _round(result.valuation.turnover_rate),
            "volume_ratio": _round(result.valuation.volume_ratio),
            "total_mv": _round(result.valuation.total_mv),
            "circ_mv": _round(result.valuation.circ_mv),
        })
    change_pct = None
    if result.trend.daily_changes:
        change_pct = _round(result.trend.daily_changes[0][1])
    return {
        "ok": True,
        "code": result.symbol,
        "name": result.name.replace(" ", ""),
        "price": _round(result.result.current_price),
        "change_pct": change_pct,
        "scan_date": _date_text(result.result.scan_date),
        "data_cutoff": _date_text(result.data_cutoff),
        "fetched_at": result.fetched_at,
        "stale": result.stale,
        "low_resonance": result.result.low_resonance,
        "high_resonance": result.result.high_resonance,
        "trend": {
            "streak": result.trend.streak,
            "streak_pct": _round(result.trend.streak_pct),
            "direction": result.trend.direction,
        },
        "volume": volume,
        "volume_price_state": result.result.volume_price_state,
        "valuation": valuation,
        "periods": periods,
    }


def serialize_history(result: HistoryServiceResult) -> dict[str, Any]:
    """history 曲线数据。"""
    from kan.core.scanner import history_mark, history_resonance

    series = []
    for entry in result.entries:
        cell = entry.periods.get(result.period)
        low_res, high_res = history_resonance(entry.periods)
        resonance, direction = history_mark(entry.periods)
        series.append({
            "date": entry.snapshot_date.isoformat(),
            "position_pct": _round(cell["pct"], 1) if cell else None,
            "at_low": bool(cell["at_low"]) if cell else None,
            "at_high": bool(cell["at_high"]) if cell else None,
            "low_resonance": low_res,
            "high_resonance": high_res,
            "resonance": resonance,
            "direction": direction or None,
        })
    return {
        "ok": True,
        "code": result.symbol,
        "name": result.name.replace(" ", ""),
        "period": result.period,
        "series": series,
        "stats": {"shown": len(series)},
    }


def serialize_hold(result: PositionsSummary) -> dict[str, Any]:
    """持仓页数据。"""
    rows = []
    for row in result.results:
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
            "p180_pct": _round(row.positions.get(180), 1),
            "price_source": row.price_source,
            "price_status": row.price_status,
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


def serialize_index(result: IndexServiceResult) -> dict[str, Any]:
    """首页指数对照条。"""
    rows = []
    for row in result.rows:
        periods = {
            str(period.period): {
                "position_pct": _round(period.position_pct, 1),
                "gain_pct": _round(period.gain_pct),
            }
            for period in row.periods
        }
        rows.append({
            "code": row.code,
            "name": row.name,
            "data_available": row.data_available,
            "data_date": _date_text(row.data_date),
            "close": _round(row.close),
            "periods": periods,
        })
    available = sum(1 for row in result.rows if row.data_available)
    return {
        "ok": available > 0,
        "periods": result.periods,
        "rows": rows,
        "stats": {
            "shown": len(rows),
            "available": available,
            "missing": len(rows) - available,
        },
    }

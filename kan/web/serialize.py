"""Web 出口序列化。

Web 只输出页面友好的扁平结构;AI JSON 契约继续由 kan/storage/export.py 负责。
"""
from __future__ import annotations

from typing import Any

from kan.core.positions import PositionsSummary
from kan.service.history_service import HistoryServiceResult
from kan.service.index_service import IndexServiceResult
from kan.service.info_service import InfoServiceResult
from kan.service.scan_service import ScanServiceResult


def _date_text(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


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
            "stale": result.ctx.freshness.is_stale,
        },
        "rows": rows,
        "heatmap": heatmap,
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
            "ratio": result.volume.ratio,
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
            "streak_pct": result.trend.streak_pct,
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
            "position_pct": cell["pct"] if cell else None,
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

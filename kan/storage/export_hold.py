"""`kan hold --format md|json` 导出实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kan.storage.export_base import HOLD_SCHEMA_VERSION, _hold_disclaimer_text, md_table

if TYPE_CHECKING:
    from kan.core.positions import PositionsSummary

def _maybe_mask(value, *, mask: bool):
    return None if mask else value


def _hold_position_dict(row, *, mask: bool) -> dict:
    return {
        "symbol": row.symbol,
        "name": row.name,
        "cost": _maybe_mask(row.cost, mask=mask),
        "shares": _maybe_mask(row.shares, mask=mask),
        "price": row.price,
        "prev_close": row.prev_close,
        "daily_pnl": _maybe_mask(row.daily_pnl, mask=mask),
        "daily_pnl_pct": _maybe_mask(row.daily_pnl_pct, mask=mask),
        "total_pnl": _maybe_mask(row.total_pnl, mask=mask),
        "total_pnl_pct": _maybe_mask(row.total_pnl_pct, mask=mask),
        "market_value": _maybe_mask(row.market_value, mask=mask),
        "cost_value": _maybe_mask(row.cost_value, mask=mask),
        "weight_pct": _maybe_mask(row.weight_pct, mask=mask),
        "positions": {str(k): v for k, v in row.positions.items()},
        "price_source": row.price_source,
        "price_status": row.price_status,
        "corporate_action_warning": row.corporate_action_warning,
    }


def hold_payload(summary: PositionsSummary, *, mask: bool = False) -> dict:
    """kan hold --format json 的结构化 payload。"""
    return {
        "ok": True,
        "command": "hold",
        "schema_version": HOLD_SCHEMA_VERSION,
        "price_mode": summary.price_mode,
        "data_cutoff": summary.data_cutoff.isoformat() if summary.data_cutoff else None,
        "masked": mask,
        "results": [_hold_position_dict(row, mask=mask) for row in summary.results],
        "account": {
            "cash": _maybe_mask(summary.account.cash, mask=mask),
            "total_market_value": _maybe_mask(summary.account.total_market_value, mask=mask),
            "total_assets": _maybe_mask(summary.account.total_assets, mask=mask),
            "total_position_pct": _maybe_mask(summary.account.total_position_pct, mask=mask),
            "daily_pnl": _maybe_mask(summary.account.daily_pnl, mask=mask),
            "total_pnl": _maybe_mask(summary.account.total_pnl, mask=mask),
        },
        "health": {
            "high_count": summary.health.high_count,
            "low_count": summary.health.low_count,
            "middle_count": summary.health.middle_count,
            "profit_count": summary.health.profit_count,
            "loss_count": summary.health.loss_count,
            "flat_count": summary.health.flat_count,
        },
        "notes": list(summary.notes),
        "disclaimer": _hold_disclaimer_text(),
    }


def _hold_cell(value, *, digits: int = 2, mask: bool = False) -> str:
    if mask:
        return "***"
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def hold_markdown(summary: PositionsSummary, *, mask: bool = False) -> str:
    headers = [
        "股票", "现价", "成本", "今日盈亏%", "累计盈亏%", "累计盈亏额",
        "市值", "仓位%", "30日", "60日", "180日",
    ]
    rows: list[list[str]] = []
    for row in summary.results:
        rows.append([
            f"{row.name.replace(' ', '')} {row.symbol}",
            _hold_cell(row.price),
            _hold_cell(row.cost, digits=4, mask=mask),
            _hold_cell(row.daily_pnl_pct, mask=mask),
            _hold_cell(row.total_pnl_pct, mask=mask),
            _hold_cell(row.total_pnl, mask=mask),
            _hold_cell(row.market_value, mask=mask),
            _hold_cell(row.weight_pct, mask=mask),
            _hold_cell(row.positions.get(30), digits=1),
            _hold_cell(row.positions.get(60), digits=1),
            _hold_cell(row.positions.get(180), digits=1),
        ])
    account = summary.account
    sections = [
        "# 慢慢看 · 持仓总览",
        md_table(headers, rows),
        (
            "账户 · "
            f"总市值 {_hold_cell(account.total_market_value, mask=mask)} · "
            f"现金 {_hold_cell(account.cash, mask=mask)} · "
            f"总资产 {_hold_cell(account.total_assets, mask=mask)} · "
            f"总仓位 {_hold_cell(account.total_position_pct, mask=mask)}%"
        ),
        (
            "体检 · "
            f"高位 {summary.health.high_count} 只 · "
            f"低位 {summary.health.low_count} 只 · "
            f"浮盈 {summary.health.profit_count} 只 · "
            f"浮亏 {summary.health.loss_count} 只"
        ),
        f"现价口径: {summary.price_mode} · 数据截止: {summary.data_cutoff or '-'}",
        *summary.notes,
        "> " + _hold_disclaimer_text(),
    ]
    return "\n\n".join(sections)

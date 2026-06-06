"""持仓盈亏、仓位和体检计算。

本模块只做事实计算，不输出操作结论。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from kan.core.models import StockScanResult
from kan.storage.positions import Position, PositionsBook

HOLD_PERIODS = (30, 60, 180)


@dataclass(frozen=True)
class PriceSnapshot:
    symbol: str
    price: float | None
    prev_close: float | None
    source: str
    data_cutoff: date | None = None
    trade_time: str | None = None
    status: str = "ok"


@dataclass(frozen=True)
class PositionView:
    symbol: str
    name: str
    cost: float
    shares: int
    price: float | None
    prev_close: float | None
    market_value: float | None
    cost_value: float
    weight_pct: float | None
    daily_pnl: float | None
    daily_pnl_pct: float | None
    total_pnl: float | None
    total_pnl_pct: float | None
    positions: dict[int, float | None]
    price_source: str
    price_status: str
    corporate_action_warning: str | None = None


@dataclass(frozen=True)
class PositionHealth:
    high_count: int
    low_count: int
    middle_count: int
    profit_count: int
    loss_count: int
    flat_count: int


@dataclass(frozen=True)
class AccountView:
    cash: float
    total_market_value: float
    total_assets: float
    total_position_pct: float | None
    daily_pnl: float | None
    total_pnl: float | None


@dataclass(frozen=True)
class PositionsSummary:
    results: list[PositionView]
    account: AccountView
    health: PositionHealth
    price_mode: str
    data_cutoff: date | None
    notes: list[str] = field(default_factory=list)


def price_from_kline(symbol: str, df) -> PriceSnapshot:
    """从日 K 缓存构造收盘价口径快照。"""
    if df is None or getattr(df, "empty", True):
        return PriceSnapshot(
            symbol=symbol,
            price=None,
            prev_close=None,
            source="close_cache",
            status="missing",
        )
    import pandas as pd

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None
    scan_date = latest["date"]
    if not isinstance(scan_date, date):
        scan_date = pd.Timestamp(scan_date).date()
    price = round(float(latest["close"]), 2)
    prev_close = round(float(prev["close"]), 2) if prev is not None else None
    return PriceSnapshot(
        symbol=symbol,
        price=price,
        prev_close=prev_close,
        source="close_cache",
        data_cutoff=scan_date,
        status="ok",
    )


def _period_positions(scan: StockScanResult | None) -> dict[int, float | None]:
    out = dict.fromkeys(HOLD_PERIODS, None)
    if scan is None:
        return out
    for period in scan.periods:
        if period.period in out and not period.insufficient:
            out[period.period] = period.position_pct
    return out


def _corporate_action_warning(position: Position, as_of: date) -> str | None:
    try:
        from kan.data.dividend import latest_event_between

        event = latest_event_between(position.symbol, position.added_at, as_of)
    except Exception:
        return None
    if not event:
        return None
    return f"⚠️  {position.symbol} 建仓后有除权除息，请核对成本/股数（用券商当前显示值）"


def evaluate_positions(
    book: PositionsBook,
    *,
    prices: dict[str, PriceSnapshot],
    scans: dict[str, StockScanResult],
    price_mode: str,
    as_of: date,
    check_corporate_actions: bool = True,
) -> PositionsSummary:
    """计算持仓视图和账户汇总。"""
    rows: list[PositionView] = []
    total_market = 0.0
    total_cost = 0.0

    for pos in book.positions:
        quote = prices.get(pos.symbol) or PriceSnapshot(
            symbol=pos.symbol,
            price=None,
            prev_close=None,
            source="missing",
            status="missing",
        )
        market_value = round(quote.price * pos.shares, 2) if quote.price is not None else None
        cost_value = round(pos.cost * pos.shares, 2)
        total_market += market_value or 0.0
        total_cost += cost_value
        daily_pnl = None
        daily_pnl_pct = None
        if (
            quote.price is not None
            and quote.prev_close is not None
            and quote.prev_close > 0
            and pos.added_at < as_of
        ):
            daily_pnl = round((quote.price - quote.prev_close) * pos.shares, 2)
            daily_pnl_pct = round((quote.price - quote.prev_close) / quote.prev_close * 100, 2)
        total_pnl = None
        total_pnl_pct = None
        if quote.price is not None and pos.cost > 0:
            total_pnl = round((quote.price - pos.cost) * pos.shares, 2)
            total_pnl_pct = round((quote.price - pos.cost) / pos.cost * 100, 2)
        warning = _corporate_action_warning(pos, as_of) if check_corporate_actions else None
        rows.append(PositionView(
            symbol=pos.symbol,
            name=pos.name,
            cost=round(pos.cost, 4),
            shares=pos.shares,
            price=quote.price,
            prev_close=quote.prev_close,
            market_value=market_value,
            cost_value=cost_value,
            weight_pct=None,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            positions=_period_positions(scans.get(pos.symbol)),
            price_source=quote.source,
            price_status=quote.status,
            corporate_action_warning=warning,
        ))

    total_assets = round(book.cash + total_market, 2)
    weighted_rows: list[PositionView] = []
    for row in rows:
        weight = (
            round((row.market_value or 0.0) / total_assets * 100, 2)
            if total_assets > 0 and row.market_value is not None else None
        )
        weighted_rows.append(replace(row, weight_pct=weight))

    daily_values = [r.daily_pnl for r in weighted_rows if r.daily_pnl is not None]
    total_values = [r.total_pnl for r in weighted_rows if r.total_pnl is not None]
    account = AccountView(
        cash=round(book.cash, 2),
        total_market_value=round(total_market, 2),
        total_assets=total_assets,
        total_position_pct=round(total_market / total_assets * 100, 2) if total_assets > 0 else None,
        daily_pnl=round(sum(daily_values), 2) if daily_values else None,
        total_pnl=round(sum(total_values), 2) if total_values else None,
    )
    health = health_of(weighted_rows)
    data_cutoff = None
    for quote in prices.values():
        if quote.data_cutoff and (data_cutoff is None or quote.data_cutoff > data_cutoff):
            data_cutoff = quote.data_cutoff
    notes = [
        "盈亏按裸价差计算，未计佣金/印花税。",
        *[r.corporate_action_warning for r in weighted_rows if r.corporate_action_warning],
    ]
    return PositionsSummary(
        results=weighted_rows,
        account=account,
        health=health,
        price_mode=price_mode,
        data_cutoff=data_cutoff,
        notes=notes,
    )


def health_of(rows: list[PositionView]) -> PositionHealth:
    high = low = middle = profit = loss = flat = 0
    for row in rows:
        pos_180 = row.positions.get(180)
        if pos_180 is not None and pos_180 >= 80:
            high += 1
        elif pos_180 is not None and pos_180 <= 20:
            low += 1
        else:
            middle += 1
        if row.total_pnl is None or row.total_pnl == 0:
            flat += 1
        elif row.total_pnl > 0:
            profit += 1
        else:
            loss += 1
    return PositionHealth(
        high_count=high,
        low_count=low,
        middle_count=middle,
        profit_count=profit,
        loss_count=loss,
        flat_count=flat,
    )

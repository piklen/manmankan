"""真实持仓盈亏和体检计算测试。"""
from __future__ import annotations

from datetime import date

from kan.core.models import PeriodResult, StockScanResult
from kan.core.positions import PriceSnapshot, evaluate_positions
from kan.storage.positions import Position, PositionsBook


def _scan(symbol: str, name: str, pos_180: float) -> StockScanResult:
    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=12.0,
        scan_date=date(2026, 6, 6),
        periods=[
            PeriodResult(
                period=30,
                n_low=10.0,
                n_high=20.0,
                position_pct=30.0,
                at_low=False,
                at_high=False,
            ),
            PeriodResult(
                period=60,
                n_low=9.0,
                n_high=21.0,
                position_pct=60.0,
                at_low=False,
                at_high=False,
            ),
            PeriodResult(
                period=180,
                n_low=8.0,
                n_high=22.0,
                position_pct=pos_180,
                at_low=pos_180 <= 20,
                at_high=pos_180 >= 80,
            ),
        ],
        low_resonance=0,
        high_resonance=0,
    )


def test_evaluate_positions_calculates_daily_total_weight_and_health(monkeypatch) -> None:
    book = PositionsBook(
        cash=1000.0,
        positions=[
            Position(
                symbol="600519",
                name="贵州茅台",
                cost=10.0,
                shares=100,
                added_at=date(2026, 6, 1),
            ),
            Position(
                symbol="000858",
                name="五粮液",
                cost=20.0,
                shares=50,
                added_at=date(2026, 6, 6),
            ),
        ],
    )
    prices = {
        "600519": PriceSnapshot(
            symbol="600519",
            price=12.0,
            prev_close=11.0,
            source="realtime",
            data_cutoff=date(2026, 6, 5),
        ),
        "000858": PriceSnapshot(
            symbol="000858",
            price=18.0,
            prev_close=17.0,
            source="close_cache",
            data_cutoff=date(2026, 6, 5),
        ),
    }
    scans = {
        "600519": _scan("600519", "贵州茅台", 85.0),
        "000858": _scan("000858", "五粮液", 10.0),
    }

    monkeypatch.setattr("kan.data.dividend.latest_event_between", lambda *_args: object())

    summary = evaluate_positions(
        book,
        prices=prices,
        scans=scans,
        price_mode="realtime",
        as_of=date(2026, 6, 6),
    )

    first, second = summary.results
    assert first.daily_pnl == 100.0
    assert first.daily_pnl_pct == 9.09
    assert first.total_pnl == 200.0
    assert first.total_pnl_pct == 20.0
    assert first.weight_pct == 38.71
    assert first.positions[180] == 85.0
    assert "除权除息" in (first.corporate_action_warning or "")

    assert second.daily_pnl is None
    assert second.total_pnl == -100.0
    assert summary.account.total_market_value == 2100.0
    assert summary.account.total_assets == 3100.0
    assert summary.account.daily_pnl == 100.0
    assert summary.account.total_pnl == 100.0
    assert summary.health.high_count == 1
    assert summary.health.low_count == 1
    assert summary.health.profit_count == 1
    assert summary.health.loss_count == 1
    assert summary.price_mode == "realtime"
    assert summary.data_cutoff == date(2026, 6, 5)
    assert "未计佣金/印花税" in summary.notes[0]

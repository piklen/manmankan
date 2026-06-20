from __future__ import annotations

from kan.core.retail_facts import (
    cash_usage_pct,
    exclude_by_permission,
    lot_cost,
    market_board,
    permission_note,
    volume_price_state,
)


def test_lot_cost_and_cash_usage_are_plain_facts() -> None:
    assert lot_cost(12.34) == 1234.0
    assert cash_usage_pct(12.34, 10000) == 12.34
    assert cash_usage_pct(12.34, 0) is None


def test_market_board_and_permission_note() -> None:
    assert market_board("600519") == "主板"
    assert market_board("300750") == "创业板"
    assert market_board("688981") == "科创板"
    assert market_board("920184") == "北交所"
    assert permission_note("688981") == "需科创板权限"
    assert permission_note("600519") is None


def test_exclude_by_permission_filters_star_and_bj() -> None:
    pairs = [("600519", "主板"), ("688981", "科创"), ("920184", "北交")]
    assert exclude_by_permission(pairs, exclude_star=True, exclude_bj=True) == [
        ("600519", "主板")
    ]


def test_volume_price_state_combines_volume_and_close_direction() -> None:
    assert volume_price_state(volume_ratio=1.8, close=11, prev_close=10) == (
        "收涨", "量增·收涨",
    )
    assert volume_price_state(volume_ratio=0.5, close=9, prev_close=10) == (
        "收跌", "量缩·收跌",
    )
    assert volume_price_state(volume_ratio=None, close=10, prev_close=10) == (
        "收平", None,
    )

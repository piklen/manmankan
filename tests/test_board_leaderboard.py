"""kan.data.board_leaderboard tests."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from kan.core.models import Theme
from kan.data import board_leaderboard
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, operation


def _theme_df(days: int = 5) -> pd.DataFrame:
    base = date(2026, 5, 25)
    return pd.DataFrame({
        "date": [base + timedelta(days=i) for i in range(days)],
        "open": [100.0 + i for i in range(days)],
        "high": [102.0 + i for i in range(days)],
        "low": [99.0 + i for i in range(days)],
        "close": [101.0 + i for i in range(days)],
        "volume": [float("nan")] * days,
        "amount": [float("nan")] * days,
    })


def test_theme_moneyflow_uses_constituent_batch(monkeypatch):
    themes = [
        Theme(code="886001", name="题材一", source="ths"),
        Theme(code="886002", name="题材二", source="ths"),
    ]
    monkeypatch.setattr(
        "kan.data.moneyflow.fetch_moneyflow",
        lambda: pd.DataFrame([
            {"symbol": "600519", "net_amount": 100.0},
            {"symbol": "000858", "net_amount": -30.0},
        ]),
    )
    monkeypatch.setattr(
        "kan.data.boards.get_theme_constituents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected serial constituent fetch")
        ),
    )
    monkeypatch.setattr(
        "kan.data.boards.get_theme_constituents_batch",
        lambda requested, **_kwargs: {
            requested[0].code: [("600519", "贵州茅台")],
            requested[1].code: [("600519", "贵州茅台"), ("000858", "五粮液")],
        },
    )
    reporter = CollectingReporter()

    with operation("题材资金", reporter=reporter) as lifecycle:
        result = board_leaderboard.theme_moneyflow_map(themes, lifecycle=lifecycle)

    assert result == {"886001": 100.0, "886002": 70.0}
    progress = [
        event for event in reporter.events
        if event.kind is LifecycleKind.PROGRESS and event.message == "聚合题材资金"
    ]
    assert progress[-1].completed == 2
    assert progress[-1].total == 2


def test_theme_pos_uses_tushare_batch_klines(monkeypatch):
    themes = [Theme(code="886108", name="AI应用", source="tushare", size=None)]
    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_load_theme_catalog",
        lambda: (themes, None),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_load_theme_klines",
        lambda catalog, n_trading_days: ({"886108": _theme_df(n_trading_days)}, None),
    )
    monkeypatch.setattr(
        "kan.data.boards.load_theme_catalog",
        lambda force=False: (_ for _ in ()).throw(AssertionError("unexpected fallback")),
    )

    rows, errors = board_leaderboard.load_board_leaderboard(
        kind="theme",
        metric="pos",
        period=3,
        limit=1,
        parallel=1,
    )

    assert errors == []
    assert rows[0].code == "886108"
    assert rows[0].position_pct is not None
    assert rows[0].gain_pct is not None

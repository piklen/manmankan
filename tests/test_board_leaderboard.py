"""kan.data.board_leaderboard tests."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from kan.core.models import Theme
from kan.data import board_leaderboard


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

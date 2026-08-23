"""板块趋势应用服务契约测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from kan.core.models import Board, Theme
from kan.core.scanner import TrendResult
from kan.data import boards
from kan.domain.board import (
    BoardKind,
    BoardPulseQuery,
    BoardTrendMode,
    BoardTrendQuery,
    BoardTrendSort,
)
from kan.service import board_service


def _trend(code: str, name: str, streak: int, latest: float) -> TrendResult:
    return TrendResult(
        code,
        name,
        100.0,
        streak,
        round(streak * latest, 2),
        [("2026-08-21", latest), ("2026-08-20", latest)],
    )


def test_query_board_trends_returns_typed_snapshot(monkeypatch):
    rows = [
        _trend("801080", "电子", 3, 1.2),
        _trend("801120", "食品饮料", -2, -0.8),
    ]
    monkeypatch.setattr(
        "kan.data.board_trend.load_board_trends",
        lambda **kwargs: (rows, [], "sw", None),
    )

    snapshot = board_service.query_board_trends(
        BoardTrendQuery(kind=BoardKind.INDUSTRY, up=2, limit=10)
    )

    assert snapshot.source == "sw"
    assert snapshot.data_cutoff == "2026-08-21"
    assert snapshot.partial is False
    assert snapshot.coverage.model_dump() == {
        "total": 2,
        "evaluated": 2,
        "matched": 1,
        "returned": 1,
        "errors": 0,
    }
    assert snapshot.rows[0].code == "801080"
    assert snapshot.rows[0].symbol == "801080"
    assert snapshot.rows[0].latest_change_pct == 1.2
    assert snapshot.rows[0].daily_changes[0].date == "2026-08-21"


def test_query_board_trends_preserves_partial_failures(monkeypatch):
    failure = Board(code="801120", name="食品饮料", level=1, size=50)
    monkeypatch.setattr(
        "kan.data.board_trend.load_board_trends",
        lambda **kwargs: (
            [_trend("801080", "电子", 3, 1.2)],
            [(failure, RuntimeError("K 线为空"))],
            "sw",
            None,
        ),
    )

    snapshot = board_service.query_board_trends(BoardTrendQuery())

    assert snapshot.partial is True
    assert snapshot.coverage.total == 2
    assert snapshot.coverage.errors == 1
    assert snapshot.failures[0].code == "801120"
    assert snapshot.failures[0].message == "K 线为空"
    assert snapshot.warnings == ["1 个板块指数数据不可用"]


def test_query_board_trends_applies_moneyflow_before_sort(monkeypatch):
    rows = [
        _trend("801080", "电子", 3, 1.2),
        _trend("801120", "食品饮料", 2, 0.8),
    ]
    monkeypatch.setattr(
        "kan.data.board_trend.load_board_trends",
        lambda **kwargs: (rows, [], "sw", None),
    )
    monkeypatch.setattr(
        "kan.data.board_trend.board_trend_moneyflow_map",
        lambda *args, **kwargs: {"801080": 10.0, "801120": 20.0},
    )

    snapshot = board_service.query_board_trends(
        BoardTrendQuery(sort=BoardTrendSort.MONEYFLOW)
    )

    assert [row.code for row in snapshot.rows] == ["801120", "801080"]
    assert snapshot.rows[0].moneyflow_net == 20.0


def test_query_board_trends_rejects_empty_source(monkeypatch):
    monkeypatch.setattr(
        "kan.data.board_trend.load_board_trends",
        lambda **kwargs: ([], [], "sw", None),
    )

    with pytest.raises(board_service.BoardTrendServiceError) as exc_info:
        board_service.query_board_trends(BoardTrendQuery())

    assert exc_info.value.code == "data_unavailable"


def test_board_query_validates_conflicting_and_unsupported_filters():
    with pytest.raises(ValueError, match="不能同时"):
        BoardTrendQuery(up=3, down=3)
    with pytest.raises(ValueError, match="只支持一级"):
        BoardTrendQuery(
            kind=BoardKind.INDUSTRY,
            level=2,
            sort=BoardTrendSort.MONEYFLOW,
        )


def test_board_query_carries_candle_mode():
    query = BoardTrendQuery(kind=BoardKind.THEME, mode=BoardTrendMode.CANDLE)

    assert query.mode is BoardTrendMode.CANDLE


def _pulse_panel(*rows: tuple[str, str, float]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["symbol", "date", "close"])


def test_query_board_pulse_calculates_same_day_member_breadth(monkeypatch):
    board = Board(code="801080", name="电子", level=1, size=3)
    constituents = [("000001", "甲"), ("000002", "乙"), ("000003", "丙")]
    panel = _pulse_panel(
        ("000001", "2026-08-20", 10.0),
        ("000001", "2026-08-21", 11.0),
        ("000002", "2026-08-20", 20.0),
        ("000002", "2026-08-21", 19.0),
        ("000003", "2026-08-20", 30.0),
        ("000003", "2026-08-21", 30.0),
    )
    monkeypatch.setattr("kan.data.boards.search_industry", lambda _value: board)
    monkeypatch.setattr(
        "kan.data.boards.get_industry_constituents",
        lambda _board, force=False: constituents,
    )
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: panel,
    )

    snapshot = board_service.query_board_pulse(
        BoardPulseQuery(kind=BoardKind.INDUSTRY, value="电子", limit=3)
    )

    assert snapshot.board_code == "801080"
    assert snapshot.data_cutoff == "2026-08-21"
    assert snapshot.previous_date == "2026-08-20"
    assert snapshot.source == "tushare_daily_bars"
    assert snapshot.coverage.model_dump() == {
        "total": 3,
        "evaluated": 3,
        "up": 1,
        "down": 1,
        "flat": 1,
        "missing": 0,
    }
    assert snapshot.up_ratio_pct == 33.3
    assert snapshot.down_ratio_pct == 33.3
    assert snapshot.median_change_pct == 0.0
    assert snapshot.top_up[0].model_dump() == {
        "rank": 1,
        "code": "000001",
        "name": "甲",
        "close": 11.0,
        "change_pct": 10.0,
    }
    assert snapshot.top_down[0].code == "000002"


def test_query_board_pulse_keeps_missing_members_out_of_denominator(monkeypatch):
    board = Board(code="801080", name="电子", level=1, size=2)
    constituents = [("000001", "甲"), ("000002", "停牌成员")]
    panel = _pulse_panel(
        ("000001", "2026-08-20", 10.0),
        ("000001", "2026-08-21", 11.0),
        ("000002", "2026-08-20", 20.0),
    )
    monkeypatch.setattr("kan.data.boards.search_industry", lambda _value: board)
    monkeypatch.setattr(
        "kan.data.boards.get_industry_constituents",
        lambda _board, force=False: constituents,
    )
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: panel,
    )

    snapshot = board_service.query_board_pulse(
        BoardPulseQuery(kind=BoardKind.INDUSTRY, value="电子")
    )

    assert snapshot.partial is True
    assert snapshot.coverage.evaluated == 1
    assert snapshot.coverage.missing == 1
    assert snapshot.up_ratio_pct == 100.0
    assert snapshot.warnings == ["1 个成分股在同一截止日缺少两日行情"]


def test_query_board_pulse_falls_back_to_individual_cache(monkeypatch):
    theme = Theme(code="885001", name="AI应用", source="ths", size=1)
    monkeypatch.setattr("kan.data.boards.search_theme", lambda _value: theme)
    monkeypatch.setattr(
        "kan.data.boards.get_theme_constituents",
        lambda _theme, force=False: [("000001", "甲")],
    )
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no panel")),
    )
    monkeypatch.setattr(
        "kan.data.fetcher.get_cached",
        lambda _code: pd.DataFrame(
            {
                "date": ["2026-08-20", "2026-08-21"],
                "close": [10.0, 10.5],
            }
        ),
    )

    snapshot = board_service.query_board_pulse(
        BoardPulseQuery(kind=BoardKind.THEME, value="AI应用")
    )

    assert snapshot.source == "individual_cache"
    assert snapshot.top_up[0].change_pct == 5.0
    assert snapshot.warnings == ["全市场日线截面不可用，已降级读取本地个股缓存"]


def test_query_board_pulse_bridges_tushare_theme_code(monkeypatch):
    trend_theme = Theme(code="885781", name="石墨电极", source="tushare", size=1)
    constituent_theme = Theme(code="307512", name="石墨电极", source="ths", size=1)
    searched: list[str] = []

    def search_theme(value: str):
        searched.append(value)
        if value == "石墨电极":
            return constituent_theme
        raise boards.ThemeNotFoundError(value)

    monkeypatch.setattr("kan.data.boards.search_theme", search_theme)
    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_load_theme_catalog",
        lambda: ([trend_theme], None),
    )
    monkeypatch.setattr(
        "kan.data.boards.get_theme_constituents",
        lambda _theme, force=False: [("000001", "甲")],
    )
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: _pulse_panel(
            ("000001", "2026-08-20", 10.0),
            ("000001", "2026-08-21", 10.5),
        ),
    )

    snapshot = board_service.query_board_pulse(
        BoardPulseQuery(kind=BoardKind.THEME, value="885781")
    )

    assert searched == ["885781", "石墨电极"]
    assert snapshot.query.value == "885781"
    assert snapshot.board_code == "307512"
    assert snapshot.board_name == "石墨电极"


def test_query_board_pulse_rejects_wrong_industry_level(monkeypatch):
    monkeypatch.setattr(
        "kan.data.boards.search_industry",
        lambda _value: Board(code="801080", name="电子", level=1, size=3),
    )

    with pytest.raises(board_service.BoardPulseServiceError) as exc_info:
        board_service.query_board_pulse(
            BoardPulseQuery(kind=BoardKind.INDUSTRY, value="电子", level=2)
        )

    assert exc_info.value.code == "board_not_found"


def test_query_board_pulse_rejects_single_day_data(monkeypatch):
    board = Board(code="801080", name="电子", level=1, size=1)
    monkeypatch.setattr("kan.data.boards.search_industry", lambda _value: board)
    monkeypatch.setattr(
        "kan.data.boards.get_industry_constituents",
        lambda _board, force=False: [("000001", "甲")],
    )
    monkeypatch.setattr(
        "kan.data.kline_snapshot.fetch_recent_daily_bars",
        lambda *_args, **_kwargs: _pulse_panel(("000001", "2026-08-21", 10.0)),
    )

    with pytest.raises(board_service.BoardPulseServiceError) as exc_info:
        board_service.query_board_pulse(
            BoardPulseQuery(kind=BoardKind.INDUSTRY, value="电子")
        )

    assert exc_info.value.code == "data_unavailable"

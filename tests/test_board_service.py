"""板块趋势应用服务契约测试。"""

from __future__ import annotations

import pytest

from kan.core.models import Board
from kan.core.scanner import TrendResult
from kan.domain.board import (
    BoardKind,
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

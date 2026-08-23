"""行业 / 题材指数连续涨跌数据层测试。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from kan.core.models import Board, Theme
from kan.core.scanner import TrendResult
from kan.data import board_trend
from kan.data.provider_contracts import FetchFailureKind
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, operation


def _kline(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    start = date(2026, 8, 17)
    opens = opens or closes
    return pd.DataFrame({
        "date": [start + timedelta(days=index) for index in range(len(closes))],
        "open": opens,
        "high": [value + 1 for value in closes],
        "low": [value - 1 for value in closes],
        "close": closes,
        "volume": [1000.0] * len(closes),
        "amount": [10000.0] * len(closes),
    })


def test_load_industry_trends_reuses_stock_close_streak(monkeypatch):
    industries = [
        Board(code="801080", name="电子", level=1, size=100),
        Board(code="801120", name="食品饮料", level=1, size=50),
        Board(code="801081", name="半导体", level=2, size=30),
    ]
    frames = {
        "801080": _kline([100.0, 101.0, 102.0, 103.0]),
        "801120": _kline([100.0, 99.0, 98.0, 97.0]),
    }
    monkeypatch.setattr(
        "kan.data.boards.load_industry_catalog",
        lambda force=False: industries,
    )
    monkeypatch.setattr(
        "kan.data.boards.fetch_industry_kline",
        lambda board, force=False: frames[board.code],
    )

    results, errors = board_trend.load_industry_trends(level=1, parallel=1)

    assert errors == []
    by_code = {result.symbol: result for result in results}
    assert set(by_code) == {"801080", "801120"}
    assert by_code["801080"].streak == 3
    assert by_code["801120"].streak == -3


def test_load_industry_trends_supports_candle_streak(monkeypatch):
    industry = Board(code="801080", name="电子", level=1, size=100)
    monkeypatch.setattr(
        "kan.data.boards.load_industry_catalog",
        lambda force=False: [industry],
    )
    # 收盘逐日下降，但连续三天 close > open；--candle 必须按阳线而不是前收计算。
    monkeypatch.setattr(
        "kan.data.boards.fetch_industry_kline",
        lambda board, force=False: _kline(
            [103.0, 102.0, 101.0, 100.0],
            [104.0, 101.0, 100.0, 99.0],
        ),
    )

    results, errors = board_trend.load_industry_trends(
        level=1,
        candle=True,
        parallel=1,
    )

    assert errors == []
    assert results[0].streak == 3


def test_load_board_trends_delegates_theme_source(monkeypatch):
    theme = Theme(code="885881", name="云办公", source="tushare")
    result = TrendResult("885881", "云办公", 100.0, 3, 4.5, [])
    diagnosis = object()
    monkeypatch.setattr(
        "kan.data.theme_leaderboard.load_theme_leaderboard",
        lambda **kwargs: ([result], [(theme, RuntimeError("partial"))], "tushare", diagnosis),
    )

    results, errors, source, actual_diagnosis = board_trend.load_board_trends(
        kind="theme",
        candle=True,
    )

    assert results == [result]
    assert errors[0][0] == theme
    assert source == "tushare"
    assert actual_diagnosis is diagnosis


def test_sort_board_trends_filters_up_days():
    rows = [
        TrendResult("1", "涨三天", 100.0, 3, 4.0, [("2026-08-21", 1.0)]),
        TrendResult("2", "涨两天", 100.0, 2, 5.0, [("2026-08-21", 2.0)]),
        TrendResult("3", "跌四天", 100.0, -4, -6.0, [("2026-08-21", -1.0)]),
    ]

    filtered = board_trend.sort_board_trends(rows, up_filter=3)

    assert [row.symbol for row in filtered] == ["1"]


@pytest.mark.parametrize(
    ("failure", "expected_kind"),
    [
        ("empty", FetchFailureKind.EMPTY),
        ("transport", FetchFailureKind.TRANSPORT),
        ("unexpected", FetchFailureKind.TRANSPORT),
        ("empty_frame", FetchFailureKind.EMPTY),
    ],
)
def test_fetch_industry_kline_job_classifies_failures(monkeypatch, failure, expected_kind):
    from kan.data import boards

    industry = Board(code="801080", name="电子", level=1, size=100)

    def fake_fetch(_board, force=False):
        if failure == "empty":
            raise boards.BoardDataUnavailableError("申万指数 K 线为空")
        if failure == "transport":
            raise boards.BoardDataUnavailableError("申万指数 K 线暂不可用")
        if failure == "unexpected":
            raise ValueError("boom")
        return pd.DataFrame()

    monkeypatch.setattr(boards, "fetch_industry_kline", fake_fetch)

    result = board_trend._fetch_industry_kline_job(industry, force=True)

    assert result.data is None
    assert result.failure is not None
    assert result.failure.kind is expected_kind


def test_load_industry_trends_rejects_empty_level(monkeypatch):
    from kan.data import boards

    monkeypatch.setattr(boards, "load_industry_catalog", lambda force=False: [])

    with pytest.raises(boards.BoardDataUnavailableError, match="清单为空"):
        board_trend.load_industry_trends(level=3, parallel=1)


def test_load_industry_trends_reports_partial_failure_lifecycle(monkeypatch):
    from kan.data import boards

    industries = [
        Board(code="801080", name="电子", level=1, size=100),
        Board(code="801120", name="食品饮料", level=1, size=50),
    ]
    monkeypatch.setattr(boards, "load_industry_catalog", lambda force=False: industries)

    def fake_fetch(industry, force=False):
        if industry.code == "801120":
            raise boards.BoardDataUnavailableError("申万指数 K 线暂不可用")
        return _kline([100.0, 101.0, 102.0])

    monkeypatch.setattr(boards, "fetch_industry_kline", fake_fetch)
    reporter = CollectingReporter()

    with operation("行业趋势测试", reporter=reporter) as lifecycle:
        results, errors = board_trend.load_industry_trends(
            level=1,
            parallel=1,
            lifecycle=lifecycle,
        )

    assert [result.symbol for result in results] == ["801080"]
    assert [industry.code for industry, _ in errors] == ["801120"]
    assert any(event.kind is LifecycleKind.WAIT for event in reporter.events)
    assert any(event.kind is LifecycleKind.DEGRADED for event in reporter.events)
    assert any(event.kind is LifecycleKind.PROGRESS for event in reporter.events)


def test_load_industry_trends_collects_calculation_error(monkeypatch):
    from kan.data import boards

    industry = Board(code="801080", name="电子", level=1, size=100)
    monkeypatch.setattr(boards, "load_industry_catalog", lambda force=False: [industry])
    monkeypatch.setattr(
        boards,
        "fetch_industry_kline",
        lambda board, force=False: _kline([100.0, 101.0]),
    )
    monkeypatch.setattr(
        board_trend,
        "calc_trend",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad kline")),
    )

    results, errors = board_trend.load_industry_trends(level=1, parallel=1)

    assert results == []
    assert isinstance(errors[0][1], ValueError)


def test_load_board_trends_delegates_industry(monkeypatch):
    result = TrendResult("801080", "电子", 100.0, 2, 3.0, [])
    industry = Board(code="801080", name="电子", level=1, size=100)
    monkeypatch.setattr(
        board_trend,
        "load_industry_trends",
        lambda **kwargs: ([result], [(industry, RuntimeError("partial"))]),
    )

    results, errors, source, diagnosis = board_trend.load_board_trends(
        kind="industry",
        level=2,
        candle=True,
        force=True,
        parallel=3,
    )

    assert results == [result]
    assert errors[0][0] == industry
    assert source == "sw"
    assert diagnosis is None


def test_board_trend_moneyflow_maps_industry_names(monkeypatch):
    rows = [
        TrendResult("801080", "电子", 100.0, 2, 3.0, []),
        TrendResult("801120", "食品饮料", 100.0, 1, 1.0, []),
    ]
    monkeypatch.setattr(
        "kan.data.board_leaderboard.industry_moneyflow_map",
        lambda: {"电子": 123.0},
    )

    assert board_trend.board_trend_moneyflow_map("industry", rows) == {"801080": 123.0}


def test_board_trend_moneyflow_builds_theme_requests(monkeypatch):
    rows = [TrendResult("885881", "云办公", 100.0, 2, 3.0, [])]
    captured = {}

    def fake_moneyflow(themes, **kwargs):
        captured["themes"] = themes
        captured.update(kwargs)
        return {"885881": 456.0}

    monkeypatch.setattr(
        "kan.data.board_leaderboard.theme_moneyflow_map",
        fake_moneyflow,
    )

    result = board_trend.board_trend_moneyflow_map("theme", rows, force=True)

    assert result == {"885881": 456.0}
    assert captured["themes"][0].source == "ths"
    assert captured["force"] is True

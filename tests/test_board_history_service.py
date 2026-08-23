"""板块指数历史事件复核算法与服务测试。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from kan.core.scanner import calc_trend
from kan.domain.board import BoardKind, BoardTrendMode
from kan.domain.board_history import (
    BoardHistoryStudyQuery,
    BoardStudyDirection,
    BoardStudySamplePolicy,
)
from kan.service import board_history_service


def _frame(closes: list[float], *, opens: list[float] | None = None) -> pd.DataFrame:
    start = date(2026, 1, 1)
    actual_opens = opens or [closes[0], *closes[:-1]]
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=index) for index in range(len(closes))],
            "open": actual_opens,
            "close": closes,
        }
    )


def _query(**updates) -> BoardHistoryStudyQuery:
    values = {
        "kind": BoardKind.INDUSTRY,
        "value": "电子",
        "level": 1,
        "mode": BoardTrendMode.CLOSE,
        "direction": BoardStudyDirection.UP,
        "min_streak": 3,
        "forward_days": 5,
        "lookback_years": 15,
        "sample_policy": BoardStudySamplePolicy.FIRST_HIT,
        "benchmark_code": "000300.SH",
    }
    values.update(updates)
    return BoardHistoryStudyQuery(**values)


def test_historical_streaks_match_calc_trend_and_flat_penetration() -> None:
    frame = _frame([100, 101, 102, 102, 103, 102, 101, 100, 101, 102, 103, 104])

    streaks = board_history_service._historical_streaks(
        frame,
        mode=BoardTrendMode.CLOSE,
    )

    assert streaks[1:8] == [1, 2, 3, 4, -1, -2, -3]
    for index in range(1, len(frame)):
        expected = calc_trend(
            frame.iloc[: index + 1].reset_index(drop=True),
            "board",
            "板块",
        ).streak
        assert streaks[index] == expected


def test_candle_streaks_match_calc_trend() -> None:
    frame = _frame(
        [100, 101, 102, 100, 99, 98, 100],
        opens=[100, 100, 100, 100, 100, 100, 100],
    )
    streaks = board_history_service._historical_streaks(
        frame,
        mode=BoardTrendMode.CANDLE,
    )

    for index in range(1, len(frame)):
        expected = calc_trend(
            frame.iloc[: index + 1].reset_index(drop=True),
            "board",
            "板块",
            candle=True,
        ).streak
        assert streaks[index] == expected


def test_first_hit_and_non_overlapping_sample_policies() -> None:
    streaks = [0, 1, 2, 3, 4, -1, -2, -3, 1, 2, 3, 4]
    first_hits = board_history_service._first_hit_indices(
        streaks,
        direction=BoardStudyDirection.UP,
        min_streak=3,
    )

    assert first_hits == [3, 10]
    assert board_history_service._select_indices(
        first_hits,
        forward_days=2,
        policy=BoardStudySamplePolicy.FIRST_HIT,
    ) == [3, 10]
    assert board_history_service._select_indices(
        first_hits,
        forward_days=7,
        policy=BoardStudySamplePolicy.NON_OVERLAPPING,
    ) == [3]


def test_study_reports_censored_events_exact_benchmark_and_audit(monkeypatch) -> None:
    frame = _frame([100, 101, 102, 102, 103, 102, 101, 100, 101, 102, 103, 104, 103])
    monkeypatch.setattr(
        board_history_service,
        "_load_board_history",
        lambda _query: ("801080", "电子", "sw_index_history", frame),
    )
    benchmark = dict.fromkeys(frame["date"], 200.0)
    monkeypatch.setattr(
        board_history_service,
        "_benchmark_history",
        lambda _query: ("沪深300", "fixture", benchmark, []),
    )

    study = board_history_service.study_board_history(_query())

    assert study.coverage.first_hits == 2
    assert study.coverage.selected == 2
    assert study.coverage.completed == 1
    assert study.coverage.censored == 1
    assert study.coverage.benchmark_aligned == 1
    assert study.events[0].event_date == frame.iloc[3]["date"].isoformat()
    assert study.events[0].forward_date == frame.iloc[8]["date"].isoformat()
    assert study.events[0].return_pct == pytest.approx(-0.9804)
    assert study.events[0].benchmark_return_pct == 0.0
    assert study.events[0].relative_return_pct == study.events[0].return_pct
    assert study.raw_distribution.count == 1
    assert study.raw_distribution.positive_ratio_pct == 0.0
    assert study.audit.uses_current_constituents is False
    assert study.audit.reconstructs_historical_stock_pool is False
    assert study.audit.provider_vintage_archive is False


def test_missing_benchmark_dates_never_become_zero(monkeypatch) -> None:
    frame = _frame([100, 101, 102, 103, 104, 105, 106])
    monkeypatch.setattr(
        board_history_service,
        "_load_board_history",
        lambda _query: ("801080", "电子", "sw_index_history", frame),
    )
    monkeypatch.setattr(
        board_history_service,
        "_benchmark_history",
        lambda _query: ("沪深300", "fixture", {frame.iloc[3]["date"]: 200.0}, []),
    )

    study = board_history_service.study_board_history(
        _query(forward_days=2)
    )

    assert study.events[0].benchmark_return_pct is None
    assert study.events[0].relative_return_pct is None
    assert study.benchmark_distribution.count == 0
    assert study.relative_distribution.mean_pct is None
    assert study.coverage.benchmark_aligned == 0
    assert study.warnings == ["1 个事件缺少精确同日基准"]


def test_empty_sample_has_no_fabricated_statistics(monkeypatch) -> None:
    frame = _frame([100, 99, 98, 97, 96])
    monkeypatch.setattr(
        board_history_service,
        "_load_board_history",
        lambda _query: ("801080", "电子", "sw_index_history", frame),
    )
    monkeypatch.setattr(
        board_history_service,
        "_benchmark_history",
        lambda _query: (None, None, {}, []),
    )

    study = board_history_service.study_board_history(_query())

    assert study.events == []
    assert study.raw_distribution.count == 0
    assert study.raw_distribution.positive_ratio_pct is None
    assert study.raw_distribution.mean_pct is None


def test_distribution_uses_interpolated_quartiles() -> None:
    distribution = board_history_service._distribution([1.0, 2.0, 3.0, 4.0])

    assert distribution.count == 4
    assert distribution.positive_ratio_pct == 100.0
    assert distribution.mean_pct == 2.5
    assert distribution.median_pct == 2.5
    assert distribution.p25_pct == 1.75
    assert distribution.p75_pct == 3.25


def test_benchmark_history_handles_disabled_invalid_empty_and_exact_dates(monkeypatch) -> None:
    from kan.data import index

    disabled = board_history_service._benchmark_history(
        _query(benchmark_code=None)
    )
    assert disabled == (None, None, {}, [])

    with pytest.raises(board_history_service.BoardHistoryServiceError) as invalid:
        board_history_service._benchmark_history(_query(benchmark_code="not-an-index"))
    assert invalid.value.code == "invalid_benchmark"

    monkeypatch.setattr(index, "fetch_index_daily", lambda code, *, days: pd.DataFrame())
    name, source, values, warnings = board_history_service._benchmark_history(_query())
    assert name == "沪深300"
    assert source is None
    assert values == {}
    assert warnings == ["基准指数历史不可用，相对收益留空"]

    benchmark = _frame([200, 202, 201])
    monkeypatch.setattr(index, "fetch_index_daily", lambda code, *, days: benchmark)
    name, source, values, warnings = board_history_service._benchmark_history(_query())
    assert name == "沪深300"
    assert source == "tushare_or_akshare_index_daily"
    assert values[benchmark.iloc[1]["date"]] == 202
    assert warnings == []


def test_history_service_stable_errors_cover_missing_board_data_and_shape(monkeypatch) -> None:
    from kan.data import boards

    monkeypatch.setattr(
        boards,
        "search_industry",
        lambda value: (_ for _ in ()).throw(boards.BoardNotFoundError(value)),
    )
    with pytest.raises(board_history_service.BoardHistoryServiceError) as missing:
        board_history_service._load_board_history(_query())
    assert missing.value.code == "board_not_found"

    class ExistingBoard:
        code = "801080"
        name = "电子"
        level = 1

    monkeypatch.setattr(boards, "search_industry", lambda value: ExistingBoard())
    monkeypatch.setattr(
        boards,
        "fetch_industry_kline",
        lambda board, force=False: (_ for _ in ()).throw(
            boards.BoardDataUnavailableError("provider down")
        ),
    )
    with pytest.raises(board_history_service.BoardHistoryServiceError) as unavailable:
        board_history_service._load_board_history(_query())
    assert unavailable.value.code == "data_unavailable"

    with pytest.raises(board_history_service.BoardHistoryServiceError) as invalid:
        board_history_service._normalize_history(pd.DataFrame({"date": []}))
    assert invalid.value.code == "invalid_data"

    with pytest.raises(board_history_service.BoardHistoryServiceError) as short:
        board_history_service._normalize_history(_frame([100]))
    assert short.value.code == "insufficient_history"


def test_all_flat_history_has_zero_streaks() -> None:
    frame = _frame([100, 100, 100, 100])

    assert board_history_service._historical_streaks(
        frame,
        mode=BoardTrendMode.CLOSE,
    ) == [0, 0, 0, 0]


def test_theme_history_prefers_native_tushare_series(monkeypatch) -> None:
    from kan.core.models import Theme
    from kan.data import boards, tushare_themes

    frame = _frame([100, 101, 102])
    theme = Theme(code="885781", name="石墨电极", source="tushare")
    monkeypatch.setattr(
        tushare_themes,
        "tushare_load_theme_catalog",
        lambda: ([theme], None),
    )
    monkeypatch.setattr(
        tushare_themes,
        "tushare_load_theme_history",
        lambda selected, *, lookback_years, force: (frame, None),
    )
    monkeypatch.setattr(
        boards,
        "fetch_theme_kline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应走 EM")),
    )

    code, name, source, loaded = board_history_service._load_board_history(
        _query(kind=BoardKind.THEME, value="885781")
    )

    assert (code, name, source) == (
        "885781",
        "石墨电极",
        "tushare_ths_index_history",
    )
    assert loaded is frame


def test_theme_history_falls_back_to_em_when_tushare_is_unavailable(monkeypatch) -> None:
    from kan.core.models import Theme
    from kan.data import boards, tushare_themes
    from kan.data.tushare import TushareApiError

    frame = _frame([100, 101, 102])
    native_theme = Theme(code="885781", name="石墨电极", source="tushare")
    em_theme = Theme(code="BK1234", name="石墨电极", source="em")
    monkeypatch.setattr(
        tushare_themes,
        "tushare_load_theme_catalog",
        lambda: ([native_theme], None),
    )
    monkeypatch.setattr(
        tushare_themes,
        "tushare_load_theme_history",
        lambda selected, *, lookback_years, force: (
            None,
            TushareApiError(code=40203, msg="频率超限", api_name="ths_daily"),
        ),
    )
    monkeypatch.setattr(boards, "search_theme", lambda value: em_theme)
    monkeypatch.setattr(boards, "fetch_theme_kline", lambda theme, force=False: frame)

    code, name, source, loaded = board_history_service._load_board_history(
        _query(kind=BoardKind.THEME, value="石墨电极")
    )

    assert (code, name, source) == ("BK1234", "石墨电极", "em_concept_history")
    assert loaded is frame

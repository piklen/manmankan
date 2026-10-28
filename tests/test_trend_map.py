"""地图与条件研究必须描述同一份行情，而非两套筛选计算。"""


import numpy as np
import pandas as pd
import pytest

from kan.domain.market_study import StudyCondition, StudyQuery
from kan.service import trend_map
from kan.service.market_study import evaluate_study


@pytest.fixture
def market(monkeypatch):
    sessions = pd.bdate_range("2025-01-01", periods=210).date.tolist()

    def history(start, end):
        close = np.linspace(start, end, len(sessions))
        return pd.DataFrame({
            "date": sessions, "open": close - .1, "high": close + 1,
            "low": close - 1, "close": close, "volume": 1000., "_source": "fixture",
        })

    frames = {
        "600001": history(10, 20),
        "600002": history(20, 10),
        "600003": history(10, 20).iloc[:-1],
        "600004": None,
    }
    members = [(symbol, f"样本 {symbol}") for symbol in frames]
    monkeypatch.setattr(trend_map, "resolve_market_calendar", lambda as_of=None: (sessions, as_of or sessions[-1]))
    monkeypatch.setattr(trend_map, "resolve_study_members", lambda universe, codes: members if universe != "codes" else [(s, s) for s in codes])
    monkeypatch.setattr(trend_map, "_industry_map", lambda: dict.fromkeys(frames, "行业样本"))
    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda symbol: frames[symbol])
    return sessions, frames, members


def test_uniform_date_missing_coverage_and_industry_breadth(market):
    sessions, _, _ = market
    snapshot = trend_map.build_trend_map(trend_map.TrendMapQuery())
    assert (snapshot.total, snapshot.plotted, snapshot.missing) == (4, 2, 2)
    rising, falling, stale, missing = snapshot.rows
    assert rising.y > 0 > falling.y
    assert rising.x > falling.x
    assert stale.data_cutoff == sessions[-2] and stale.x is None and stale.y is None
    assert not missing.available and missing.close is None
    industry = snapshot.industries[0]
    assert (industry.total, industry.available, industry.up, industry.down) == (4, 2, 1, 1)
    assert len(rising.trail) == 6 and rising.trail[-1].date == sessions[-1]
    assert rising.trail[-1].x == rising.x


def test_rectangle_and_study_share_exact_metrics(market):
    sessions, frames, members = market
    snapshot = trend_map.build_trend_map(trend_map.TrendMapQuery(position_window=60, momentum_window=20))
    query = StudyQuery(
        universe="all", lookback_days=30, forward_days=5,
        conditions=[
            StudyCondition(field="position", window=60, operator="gte", value=50),
            StudyCondition(field="return_pct", window=20, operator="gt", value=0),
        ],
    )
    result, _, _ = evaluate_study(
        query, ((symbol, name, frames[symbol]) for symbol, name in members),
        sessions, sessions[-1],
    )
    brushed = {row.symbol for row in snapshot.rows if row.available and row.x >= 50 and row.y > 0}
    assert {row.symbol for row in result.current_matches} == brushed == {"600001"}
    hit = result.current_matches[0]
    assert hit.values["position.60"] == snapshot.rows[0].x
    assert hit.values["return_pct.20"] == snapshot.rows[0].y


def test_stock_evidence_and_map_do_not_read_after_selected_date(market):
    sessions, _, _ = market
    cutoff = sessions[-10]
    snapshot = trend_map.build_trend_map(trend_map.TrendMapQuery(as_of=cutoff))
    evidence = trend_map.get_trend_stock(trend_map.TrendStockQuery(symbol="600001", as_of=cutoff, days=60))
    assert evidence.as_of == cutoff
    assert len(evidence.bars) == 60
    assert all(bar.date <= cutoff for bar in evidence.bars)
    assert evidence.bars[-1].close == snapshot.rows[0].close
    assert evidence.positions == snapshot.rows[0].positions
    assert evidence.returns == snapshot.rows[0].returns


def test_explicit_pool_input_is_validated():
    with pytest.raises(ValueError):
        trend_map.TrendMapQuery(universe="codes", codes=[])
    with pytest.raises(ValueError):
        trend_map.TrendMapQuery(universe="all", codes=["600001"])
    assert trend_map.TrendMapQuery(universe="codes", codes=["600001", "600001"]).codes == ["600001"]

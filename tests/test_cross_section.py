"""kan/core/cross_section.py · run_cross_section 截面编排 (地基-3)。

mock fetch_metrics + fetch_sw_l1_map + stock_set.pairs · 验证编排不触网 ·
全市场跳历史分位只算行业内分位 + 中位 · 顺序跟随 pairs。
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from kan.core import cross_section


class _FakeSet:
    """最小 StockSet stub · 只暴露 pairs() (截面编排只用 pairs)。"""

    name = "测试池"

    def __init__(self, pairs):
        self._pairs = pairs

    def pairs(self):
        return list(self._pairs)


@pytest.fixture(autouse=True)
def _fixed_latest(monkeypatch):
    """钉死 latest_trade_date · 截面 stale 计算确定性 (不触交易日历)。"""
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date",
        lambda: datetime.date(2026, 5, 29),
    )


@pytest.fixture(autouse=True)
def _empty_optional_dimensions(monkeypatch):
    """默认不让可选截面维度触网;需要断言调用的测试单独覆盖。"""
    empty = lambda **_kw: pd.DataFrame()  # noqa: E731
    monkeypatch.setattr("kan.data.moneyflow.fetch_moneyflow", empty)
    monkeypatch.setattr("kan.data.technical.fetch_technical", empty)
    monkeypatch.setattr("kan.data.sentiment.fetch_sentiment", empty)
    monkeypatch.setattr("kan.data.chip.fetch_chip", empty)


def _cross_df(rows):
    return pd.DataFrame(rows)


def test_empty_pairs_no_fetch(monkeypatch):
    called = {"n": 0}

    def _fake(**_kw):
        called["n"] += 1
        return pd.DataFrame()
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", _fake)
    ctx = cross_section.run_cross_section(_FakeSet([]))
    assert ctx.rows == []
    assert ctx.pool_size == 0
    assert called["n"] == 0  # 空池不触网


def test_empty_metrics_rows_empty(monkeypatch):
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: pd.DataFrame())
    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: {})
    ctx = cross_section.run_cross_section(_FakeSet([("600519", "贵州茅台")]))
    assert ctx.rows == []  # 无 token / 空截面 → rows 空 (caller 报错)
    assert ctx.pool_size == 1


def test_builds_rows_with_valuation(monkeypatch):
    df = _cross_df([{
        "symbol": "600519", "trade_date": datetime.date(2026, 5, 29),
        "close": 1326.0, "pe_ttm": 20.0, "pb": 6.0,
        "turnover_rate": 0.61, "volume_ratio": 1.42,
        "total_mv": 1.0e8, "circ_mv": 1.0e8, "_source": "tushare_metrics",
    }])
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df.copy())
    monkeypatch.setattr(
        "kan.data.industry_map.fetch_sw_l1_map", lambda: {"600519": "食品饮料"},
    )
    ctx = cross_section.run_cross_section(_FakeSet([("600519", "贵州茅台")]))
    assert len(ctx.rows) == 1
    row = ctx.rows[0]
    assert row.code == "600519"
    assert row.name == "贵州茅台"
    assert row.valuation is not None
    assert row.valuation.turnover_rate == 0.61
    # 数据层存原始 pe (裸值过滤在 export 层 · 同 enrich 决策)
    assert row.valuation.pe_ttm == 20.0
    assert ctx.data_cutoff == datetime.date(2026, 5, 29)


def test_history_pct_rank_skipped(monkeypatch):
    """全市场截面跳历史分位 (*_pct_rank 恒 None) · 只行业内分位 + 中位。"""
    rows = [
        {"symbol": f"60000{i}", "trade_date": datetime.date(2026, 5, 29),
         "pe_ttm": 10.0 + i, "pb": 1.0 + i}
        for i in range(6)  # 6 只同行业 ≥ _MIN_INDUSTRY=5
    ]
    df = _cross_df(rows)
    l1 = {f"60000{i}": "银行" for i in range(6)}
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df.copy())
    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: l1)
    pairs = [(f"60000{i}", f"股{i}") for i in range(6)]
    ctx = cross_section.run_cross_section(_FakeSet(pairs))
    vc = ctx.rows[0].valuation_context
    assert vc is not None
    assert vc.pe_pct_rank is None, "历史分位全市场跳过"
    assert vc.pb_pct_rank is None
    assert vc.pe_industry_pct is not None, "行业内分位应算"
    assert vc.pe_industry_median is not None, "行业中位应算"
    assert vc.industry == "银行"


def test_small_industry_context_none(monkeypatch):
    """行业样本不足 (< _MIN_INDUSTRY) → valuation_context None (优雅降级)。"""
    df = _cross_df([{
        "symbol": "600519", "trade_date": datetime.date(2026, 5, 29), "pe_ttm": 20.0,
    }])
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df.copy())
    monkeypatch.setattr(
        "kan.data.industry_map.fetch_sw_l1_map", lambda: {"600519": "食品饮料"},
    )
    ctx = cross_section.run_cross_section(_FakeSet([("600519", "贵州茅台")]))
    assert ctx.rows[0].valuation_context is None  # 单只行业 · 样本不足


def test_preserves_pairs_order(monkeypatch):
    df = _cross_df([
        {"symbol": "000001", "trade_date": datetime.date(2026, 5, 29), "pe_ttm": 5.0},
        {"symbol": "600519", "trade_date": datetime.date(2026, 5, 29), "pe_ttm": 20.0},
    ])
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df.copy())
    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: {})
    ctx = cross_section.run_cross_section(
        _FakeSet([("600519", "茅台"), ("000001", "平安")]),
    )
    # 输出顺序跟随 pairs · 不被 df 行顺序打乱
    assert [r.code for r in ctx.rows] == ["600519", "000001"]


def test_selective_dimensions_skip_unrequested_fetches(monkeypatch):
    df = _cross_df([{
        "symbol": "600519", "trade_date": datetime.date(2026, 5, 29),
        "close": 1326.0, "pe_ttm": 20.0,
    }])
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df.copy())

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("unrequested dimension fetch should not run")

    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", _unexpected)
    monkeypatch.setattr("kan.data.moneyflow.fetch_moneyflow", _unexpected)
    monkeypatch.setattr("kan.data.technical.fetch_technical", _unexpected)
    monkeypatch.setattr("kan.data.sentiment.fetch_sentiment", _unexpected)
    monkeypatch.setattr("kan.data.chip.fetch_chip", _unexpected)

    ctx = cross_section.run_cross_section(
        _FakeSet([("600519", "贵州茅台")]),
        included_dimensions={"valuation"},
        need_valuation_context=False,
    )
    assert len(ctx.rows) == 1
    row = ctx.rows[0]
    assert row.valuation is not None
    assert row.valuation_context is None
    assert row.moneyflow is None
    assert row.technical is None
    assert row.sentiment is None
    assert row.chip is None


def test_selective_dimensions_fetch_only_requested_dimension(monkeypatch):
    df = _cross_df([{
        "symbol": "600519", "trade_date": datetime.date(2026, 5, 29),
        "close": 1326.0, "pe_ttm": 20.0,
    }])
    mf = _cross_df([{
        "symbol": "600519", "trade_date": datetime.date(2026, 5, 29),
        "net_amount": 5000.0, "buy_elg_amount": 3000.0,
        "buy_lg_amount": 2000.0, "_source": "tushare_moneyflow",
    }])
    calls = {"moneyflow": 0}
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **_kw: df.copy())
    monkeypatch.setattr("kan.data.industry_map.fetch_sw_l1_map", lambda: {})

    def _moneyflow(**_kw):
        calls["moneyflow"] += 1
        return mf.copy()

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("unrequested dimension fetch should not run")

    monkeypatch.setattr("kan.data.moneyflow.fetch_moneyflow", _moneyflow)
    monkeypatch.setattr("kan.data.technical.fetch_technical", _unexpected)
    monkeypatch.setattr("kan.data.sentiment.fetch_sentiment", _unexpected)
    monkeypatch.setattr("kan.data.chip.fetch_chip", _unexpected)

    ctx = cross_section.run_cross_section(
        _FakeSet([("600519", "贵州茅台")]),
        included_dimensions={"valuation", "moneyflow"},
        need_valuation_context=False,
    )
    assert calls["moneyflow"] == 1
    assert ctx.rows[0].moneyflow is not None
    assert ctx.rows[0].moneyflow.net_amount == 5000.0
    assert ctx.rows[0].technical is None

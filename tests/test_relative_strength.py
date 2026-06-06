"""kan/data/relative_strength.py · 对照 gain 计算 (mock 数据源 · 不触网)。

index_gains / industry_gains 的数据源 (fetch_index_daily / boards) 用 monkeypatch
替换,scan_stock 用真实计算喂构造 K 线。验证 gain 算法 + 缺数据降级 + level 过滤 +
空周期不触网。
"""
from __future__ import annotations

import datetime

import pandas as pd

from kan.data import relative_strength as rs


def _kline(rows: int, *, base: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """构造单调上涨 K 线 df (scan_stock 可直接读)。"""
    dates = [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(rows)]
    closes = [base + step * i for i in range(rows)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "close": closes,
    })


class TestGainsFromKline:
    def test_computes_gain_for_period(self):
        # 31 根单调涨 step=1 · close[-1]=130 / close[-31]=100 → 30 日涨幅 30%
        out = rs._gains_from_kline(_kline(31), "X", "测试", {30})
        assert out[30] == 30.0

    def test_insufficient_period_skipped(self):
        # 只 10 根 · 30 周期不足 → 不入 dict (不静默当 0)
        assert rs._gains_from_kline(_kline(10), "X", "测试", {30}) == {}

    def test_empty_or_none_df(self):
        assert rs._gains_from_kline(None, "X", "n", {30}) == {}
        assert rs._gains_from_kline(pd.DataFrame(), "X", "n", {30}) == {}

    def test_empty_periods(self):
        assert rs._gains_from_kline(_kline(31), "X", "n", set()) == {}

    def test_multi_period(self):
        out = rs._gains_from_kline(_kline(61), "X", "n", {30, 60})
        assert set(out) == {30, 60}
        assert out[30] > 0 and out[60] > 0


class TestIndexGains:
    def test_returns_gains_code_name(self, monkeypatch):
        monkeypatch.setattr(
            "kan.data.index.fetch_index_daily",
            lambda code, days: _kline(40, base=200.0, step=2.0),
        )
        gains, code, name = rs.index_gains({30}, index_code="沪深300")
        assert code == "000300.SH"
        assert name == "沪深300"
        assert gains[30] > 0  # 单调涨 → 正涨幅

    def test_empty_periods_no_fetch(self, monkeypatch):
        called = {"n": 0}

        def _f(code, days):
            called["n"] += 1
            return None

        monkeypatch.setattr("kan.data.index.fetch_index_daily", _f)
        gains, code, name = rs.index_gains(set())
        assert gains == {}
        assert called["n"] == 0  # 空周期不触网
        assert (code, name) == ("000300.SH", "沪深300")  # 默认沪深300

    def test_fetch_none_graceful(self, monkeypatch):
        monkeypatch.setattr("kan.data.index.fetch_index_daily", lambda code, days: None)
        gains, _code, _name = rs.index_gains({30})
        assert gains == {}  # 无数据优雅降级


class TestIndustryGains:
    @staticmethod
    def _catalog():
        from kan.core.models import Board

        return [
            Board(code="801080", name="电子", level=1, size=100),
            Board(code="801120", name="食品饮料", level=1, size=50),
            Board(code="850001", name="某二级", level=2, size=10),
        ]

    def test_aggregates_by_industry_name_level1_only(self, monkeypatch):
        monkeypatch.setattr(
            "kan.data.boards.load_industry_catalog", lambda force=False: self._catalog()
        )
        monkeypatch.setattr(
            "kan.data.boards.fetch_industry_kline",
            lambda board, force=False: _kline(40, base=300.0, step=1.5),
        )
        out = rs.industry_gains({30}, parallel=1)
        assert "电子" in out
        assert "食品饮料" in out
        assert "某二级" not in out  # level != 1 过滤
        assert out["电子"][30] > 0

    def test_empty_periods(self):
        assert rs.industry_gains(set()) == {}

    def test_no_catalog_graceful(self, monkeypatch):
        monkeypatch.setattr("kan.data.boards.load_industry_catalog", lambda force=False: [])
        assert rs.industry_gains({30}) == {}

    def test_kline_failure_skips_industry(self, monkeypatch):
        monkeypatch.setattr(
            "kan.data.boards.load_industry_catalog", lambda force=False: self._catalog()
        )

        def _boom(board, force=False):
            raise RuntimeError("kline down")

        monkeypatch.setattr("kan.data.boards.fetch_industry_kline", _boom)
        # K 线全失败 → 空 dict (优雅降级 · 不抛)
        assert rs.industry_gains({30}, parallel=1) == {}

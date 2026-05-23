"""kan.core.verbs · facade 路由验证 (不调真底层)。

verbs 是 thin facade · 只验证:
- 调对 underlying 函数
- 传对参数 (pairs / codes / mode / periods / etc)
- 返回值原样透传
真实数据流由 scanner / fetcher 各自测试覆盖。
"""
from __future__ import annotations

import pytest

from kan.core import verbs
from kan.core.stock_set import WatchlistSet


@pytest.fixture
def stock_set():
    """固定 4 只股票的 fake StockSet (绕过 storage IO)。"""
    return WatchlistSet(_pairs=[
        ("600519", "贵州茅台"),
        ("000858", "五粮液"),
        ("300750", "宁德时代"),
        ("002230", "科大讯飞"),
    ])


def test_scan_delegates_to_scan_batch(stock_set, monkeypatch):
    captured = {}

    def fake_scan_batch(pairs, mode="low"):
        captured["pairs"] = pairs
        captured["mode"] = mode
        return ["fake_result"]

    monkeypatch.setattr("kan.core.scanner.scan_batch", fake_scan_batch)
    result = verbs.scan(stock_set, mode="high")
    assert result == ["fake_result"]
    assert captured["pairs"] == stock_set.pairs()
    assert captured["mode"] == "high"


def test_scan_default_mode_is_low(stock_set, monkeypatch):
    captured = {}

    def fake_scan_batch(pairs, mode="low"):
        captured["mode"] = mode
        return []

    monkeypatch.setattr("kan.core.scanner.scan_batch", fake_scan_batch)
    verbs.scan(stock_set)
    assert captured["mode"] == "low"


def test_low_delegates_to_filter_extreme(stock_set, monkeypatch):
    captured = {}

    def fake_filter(pairs, periods, mode="low"):
        captured["pairs"] = pairs
        captured["periods"] = periods
        captured["mode"] = mode
        return {30: []}

    monkeypatch.setattr("kan.core.scanner.filter_extreme", fake_filter)
    result = verbs.low(stock_set, periods=[60])
    assert result == {30: []}
    assert captured["pairs"] == stock_set.pairs()
    assert captured["periods"] == [60]
    assert captured["mode"] == "low"


def test_low_default_periods(stock_set, monkeypatch):
    captured = {}

    def fake_filter(pairs, periods, mode="low"):
        captured["periods"] = periods
        return {}

    monkeypatch.setattr("kan.core.scanner.filter_extreme", fake_filter)
    verbs.low(stock_set)
    assert captured["periods"] == [30, 60, 120], "默认 periods 必须跟 CLI 对齐"


def test_high_delegates_to_filter_extreme_with_mode_high(stock_set, monkeypatch):
    captured = {}

    def fake_filter(pairs, periods, mode="low"):
        captured["mode"] = mode
        captured["periods"] = periods
        return {}

    monkeypatch.setattr("kan.core.scanner.filter_extreme", fake_filter)
    verbs.high(stock_set, periods=[180])
    assert captured["mode"] == "high"
    assert captured["periods"] == [180]


def test_trend_delegates_to_trend_batch(stock_set, monkeypatch):
    captured = {}

    def fake_trend_batch(pairs, candle=False):
        captured["pairs"] = pairs
        captured["candle"] = candle
        return ["fake_trend"]

    monkeypatch.setattr("kan.core.scanner.trend_batch", fake_trend_batch)
    result = verbs.trend(stock_set, candle=True)
    assert result == ["fake_trend"]
    assert captured["pairs"] == stock_set.pairs()
    assert captured["candle"] is True


def test_fetch_delegates_to_fetch_batch(stock_set, monkeypatch):
    captured = {}

    def fake_fetch_batch(symbols, days=180, force=False, max_workers=None, on_progress=None):
        captured["symbols"] = symbols
        captured["days"] = days
        captured["force"] = force
        return ({"600519": "df"}, {})

    monkeypatch.setattr("kan.data.fetcher.fetch_batch", fake_fetch_batch)
    results, errors = verbs.fetch(stock_set, days=30, force=True)
    assert results == {"600519": "df"}
    assert errors == {}
    assert captured["symbols"] == stock_set.codes(), "fetch 用 codes (不带名称)"
    assert captured["days"] == 30
    assert captured["force"] is True


def test_verbs_accept_any_stockset_via_protocol(monkeypatch):
    """duck-typing · 自定义类只要有 pairs/codes/name 就能被 verbs 接受。"""

    class CustomBasket:
        name = "自制篮子"

        def codes(self) -> list[str]:
            return ["600000"]

        def pairs(self) -> list[tuple[str, str]]:
            return [("600000", "浦发银行")]

    captured = {}

    def fake_scan_batch(pairs, mode="low"):
        captured["pairs"] = pairs
        return []

    monkeypatch.setattr("kan.core.scanner.scan_batch", fake_scan_batch)
    verbs.scan(CustomBasket())
    assert captured["pairs"] == [("600000", "浦发银行")]

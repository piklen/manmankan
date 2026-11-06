"""用可手算行情验证群体分母、窗口与多入口事实。"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kan.domain.discovery import DiscoveryQuery
from kan.service import discovery, trend_search


@pytest.fixture
def observed_market(monkeypatch):
    days = pd.bdate_range("2026-01-05", periods=6).date.tolist()

    def bars(prices):
        return pd.DataFrame({
            "date": days[:len(prices)], "open": prices, "close": prices,
            "high": prices, "low": prices, "volume": 1000, "_source": "synthetic",
        })

    frames = {
        # 截止第5天，两个相邻两日窗口：+10%→+20%，−10%→−20%，−10%→+10%，0→0。
        "000001": bars([100, 105, 110, 120, 132, 150]),
        "000002": bars([100, 95, 90, 80, 72, 60]),
        "000003": bars([100, 95, 90, 95, 99, 110]),
        "000004": bars([100, 100, 100, 100, 100, 100]),
        # 当前窗口已完整，前窗口不完整；不能混入跨窗口的同组对照。
        "000005": bars([100, 100, 100, 110, 120, 130]).iloc[2:],
        # 缺口不压缩成相邻交易日。
        "000006": bars([100, 100, 100, 100, 100, 100]).drop(index=3),
        "000007": None,
    }
    names = [(symbol, symbol) for symbol in frames]
    monkeypatch.setattr(discovery, "resolve_market_calendar", lambda as_of=None: (days, as_of or days[4]))
    monkeypatch.setattr(trend_search, "resolve_study_members", lambda universe, codes: [(code, code) for code in codes] if universe == "codes" else names)
    monkeypatch.setattr(trend_search, "_industries", lambda: {code: "甲" if code <= "000004" else "乙" for code in frames})
    monkeypatch.setattr("kan.data.fetcher.get_cached", frames.get)
    return days, frames


def test_distribution_paired_windows_fixed_history_and_drilldown(observed_market):
    days, _frames = observed_market
    result = discovery.discover_market(DiscoveryQuery(window=2))
    assert (result.previous_start, result.previous_as_of, result.as_of) == (days[0], days[2], days[4])
    stats = result.market.current
    assert (stats.total, stats.available, stats.missing, stats.up, stats.down, stats.flat) == (7, 5, 2, 3, 1, 1)
    assert stats.positive_share == 60
    assert (stats.median_return, stats.q25, stats.q75) == pytest.approx((10, 0, 20))
    paired = result.market.comparison
    assert (paired.available, paired.missing) == (4, 3)
    assert (paired.current_positive_share, paired.previous_positive_share, paired.breadth_delta_pp) == (50, 25, 25)
    assert (paired.current_median, paired.previous_median) == pytest.approx((5, -5))
    assert result.market.history_available == 4
    assert all(point.available == 4 for point in result.market.history)
    # 当前分布多出一只资料较短的股票，轨迹仍保持同一四只，不伪造广度变化。
    assert result.market.history[-1].positive_share == 50
    counts = {item.key: item.count for item in result.market.transitions}
    assert counts == {"up_up": 1, "down_up": 1, "up_down": 0, "down_down": 1, "flat": 1, "unknown": 3}
    assert sum(counts.values()) == stats.total
    for group in [result.market, *result.industries]:
        members = result.members if group is result.market else [item for item in result.members if item.industry == group.name]
        assert len(members) == group.total
        for bucket in group.distribution:
            assert bucket.count == sum(item.distribution_bin == bucket.key for item in members)
        for transition in group.transitions:
            assert transition.count == sum(item.transition == transition.key for item in members)
        assert sum(bucket.count for bucket in group.distribution) == group.current.available


def test_missing_future_and_explicit_scope_do_not_change_the_facts(observed_market):
    days, frames = observed_market
    query = DiscoveryQuery(window=2, as_of=days[4], industries=["甲"])
    before = discovery.discover_market(query)
    frames["000001"].loc[5, ["open", "high", "low", "close"]] = 9999
    assert discovery.discover_market(query) == before
    assert [member.symbol for member in before.members] == ["000001", "000002", "000003", "000004"]
    assert before.market.current.total == 4
    for symbol in frames:
        if frames[symbol] is not None:
            frames[symbol] = frames[symbol].iloc[:2]
    stale = discovery.discover_market(DiscoveryQuery(window=2, as_of=days[4]))
    assert stale.as_of == days[4] and stale.common_data_date < stale.as_of
    assert stale.market.current.available == 0 and stale.market.current.missing == 7
    assert stale.market.current.median_return is None
    assert all(point.positive_share is None for point in stale.market.history)
    assert all(item.transition == "unknown" for item in stale.members)
    empty = discovery.discover_market(DiscoveryQuery(window=2, industries=["不存在的行业"]))
    assert empty.market.total == 0 and empty.members == []


def test_exact_bucket_edges_and_single_corrupt_cache(observed_market):
    _days, frames = observed_market
    for price, expected in ((90, "m10_m5"), (95, "m5_0"), (105, "0_5"), (110, "5_10")):
        assert discovery._distribution_bin((price / 100 - 1) * 100) == expected
    assert discovery._distribution_bin(-10 - 1e-8) == "below_m10"
    frames["000001"] = frames["000001"].drop(columns="date")
    result = discovery.discover_market(DiscoveryQuery(window=2, universe="codes", codes=["000001", "000002"]))
    assert result.market.current.available == 1 and result.market.current.missing == 1
    assert "日期列" in result.members[0].reason
    assert result.members[1].return_pct == pytest.approx(-20)


def test_shared_gap_warning_counts_observed_history_without_pre_listing_days(observed_market):
    days, frames = observed_market
    # 两只已交易成员在同日缺行情；较晚上市与完全无缓存者不增加日期缺口数。
    frames["000001"] = frames["000001"].drop(index=3)
    result = discovery.discover_market(DiscoveryQuery(window=2))
    warning = next(text for text in result.warnings if "共同缺口" in text)
    assert f"{days[3]} 有 2 只股票缺少有效日线" in warning
    assert str(days[0]) not in warning and str(days[1]) not in warning
    assert "不推断停牌或涨跌" in warning
    assert (result.market.current.total, result.market.current.missing) == (7, 3)


def test_http_cli_python_and_mcp_return_one_result(observed_market):
    from kan.api import discover_market
    from kan.cli import app
    from kan.mcp.server import TOOLS
    from kan.web.app import create_app

    query = DiscoveryQuery(window=2, universe="codes", codes=["000001", "000006"])
    expected = discover_market(query).model_dump(mode="json")
    client = TestClient(create_app(session_required=False, recover_jobs=False), base_url="http://127.0.0.1", headers={"X-Kan-Web": "1"})
    response = client.post("/api/v1/discovery", json=query.model_dump(mode="json"))
    assert response.status_code == 200 and response.json() == expected
    run = CliRunner().invoke(app, ["discover", "--codes", "000001,000006", "--window", "2", "--format", "json"])
    assert run.exit_code == 0, run.output
    assert json.loads(run.stdout) == expected
    assert json.loads(TOOLS["kan_discover"].handler(query.model_dump(mode="json"))["stdout"]) == expected
    invalid = client.post("/api/v1/discovery", json={"window": 0})
    assert invalid.status_code == 422
    invalid_cli = CliRunner().invoke(app, ["discover", "--as-of", "not-a-date", "--format", "json"])
    assert invalid_cli.exit_code == 1 and json.loads(invalid_cli.stdout)["error"]["message"]

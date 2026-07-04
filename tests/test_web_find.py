"""kan web find 页面与自选管理测试。"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from kan.core.find_filter import FindMatch, TriggeredFilter
from kan.core.models import (
    EnrichedResult,
    MoneyflowMetrics,
    PeriodResult,
    StockScanResult,
    ValuationMetrics,
)
from kan.render.base import FIND_DISCLAIMER_TEXT
from kan.service.find_service import FindKlineResult
from kan.web.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_find_page_contains_disclaimer_and_cli_area() -> None:
    response = _client().get("/find")

    assert response.status_code == 200
    assert FIND_DISCLAIMER_TEXT in response.text
    assert "等价 CLI 命令" in response.text
    assert "符合条件的股票" in response.text
    assert "筛选" in response.text


def test_api_find_returns_web_shape(monkeypatch) -> None:
    captured = {}

    def fake_run(request):
        captured["request"] = request
        return _find_result()

    monkeypatch.setattr("kan.web.find_adapter.run_find_kline", fake_run)
    response = _client().post(
        "/api/find",
        headers={"X-Kan-Web": "1"},
        json={
            "pool": {"type": "codes", "value": "600519,000858"},
            "filters": [
                {"type": "pos", "period": "180", "op": "lt", "value": "20"},
                {"type": "pe", "op": "lt", "value": "30"},
            ],
            "exclude_st": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "符合条件的股票"
    assert payload["rows"][0]["code"] == "600519"
    assert payload["rows"][0]["metrics"][0]["label"] == "PE TTM"
    assert payload["stats"]["skipped_no_cache"] == 1
    assert "无本地缓存" in payload["message"]
    assert "--all" not in payload["command"]
    assert captured["request"].allow_auto_fetch is False


def test_api_find_rejects_empty_conditions() -> None:
    response = _client().post(
        "/api/find",
        headers={"X-Kan-Web": "1"},
        json={"pool": {"type": "watchlist"}, "filters": [], "exclude_st": False},
    )

    assert response.status_code == 400
    assert "请至少填写一个 filter" in response.text


def test_api_find_requires_csrf_header() -> None:
    response = _client().post(
        "/api/find",
        json={"pool": {"type": "watchlist"}, "filters": [], "exclude_st": True},
    )

    assert response.status_code == 403


def test_api_find_industry_cold_cache_hint(monkeypatch) -> None:
    from kan.service.find_service import FindServiceError

    def fake_run(_request):
        raise FindServiceError(code="data_unavailable", message="候选池无可用 K 线数据")

    monkeypatch.setattr("kan.web.find_adapter.run_find_kline", fake_run)
    response = _client().post(
        "/api/find",
        headers={"X-Kan-Web": "1"},
        json={
            "pool": {"type": "industry", "value": "半导体"},
            "filters": [{"type": "pos", "period": "180", "op": "lt", "value": "20"}],
        },
    )

    assert response.status_code == 400
    assert "该池大部分股票无本地缓存" in response.text


def test_watchlist_post_and_delete(monkeypatch) -> None:
    calls = []

    def fake_add(code):
        calls.append(("add", code))
        return True, f"已添加 {code}"

    def fake_remove(code):
        calls.append(("remove", code))
        return True, f"已移除 {code}"

    monkeypatch.setattr("kan.web.routes_api.watchlist.add", fake_add)
    monkeypatch.setattr("kan.web.routes_api.watchlist.remove", fake_remove)
    client = _client()

    post = client.post(
        "/api/watchlist",
        headers={"X-Kan-Web": "1"},
        json={"codes": "600519,000858"},
    )
    delete = client.delete("/api/watchlist/600519", headers={"X-Kan-Web": "1"})

    assert post.status_code == 200
    assert delete.status_code == 200
    assert calls == [("add", "600519"), ("add", "000858"), ("remove", "600519")]


def test_watchlist_post_invalid_code() -> None:
    response = _client().post(
        "/api/watchlist",
        headers={"X-Kan-Web": "1"},
        json={"codes": "bad-code"},
    )

    assert response.status_code == 400
    assert "不是 6 位股票代码" in response.text


def test_watchlist_delete_invalid_code() -> None:
    response = _client().delete("/api/watchlist/bad-code", headers={"X-Kan-Web": "1"})

    assert response.status_code == 400
    assert "不是 6 位股票代码" in response.text


def _find_result():
    row = EnrichedResult.from_scan(
        StockScanResult(
            symbol="600519",
            name="贵州茅台",
            current_price=100.0,
            scan_date=date(2026, 5, 23),
            periods=[
                PeriodResult(
                    period=180,
                    n_low=90.0,
                    n_high=110.0,
                    position_pct=10.0,
                    at_low=False,
                    at_high=False,
                ),
            ],
            low_resonance=1,
            high_resonance=0,
        ),
        valuation=ValuationMetrics(
            trade_date=date(2026, 5, 23),
            pe_ttm=20.0,
        ),
        moneyflow=MoneyflowMetrics(
            trade_date=date(2026, 5, 23),
            net_amount=100.0,
            net_amount_5d=500.0,
        ),
    )
    match = FindMatch(
        result=row,
        triggered=(TriggeredFilter("pos", "180:lt:20", 10.0),),
    )
    freshness = SimpleNamespace(
        data_cutoff=date(2026, 5, 23),
        is_stale=False,
    )
    ctx = SimpleNamespace(
        targets=[("600519", "贵州茅台"), ("000858", "五粮液")],
        results=[row],
        freshness=freshness,
    )
    return FindKlineResult(
        stock_set=SimpleNamespace(name="自定义代码池"),
        ctx=ctx,
        pool_results=[row],
        matches=[match],
        matches_limited=[match],
        effective_limit=50,
        filters=[{"name": "--pos", "param": "180:lt:20"}],
        pools=["codes:2"],
        query_time="2026-05-23T15:00:00+08:00",
        included_dimensions={"valuation", "moneyflow"},
        compact_dimensions={"valuation", "moneyflow"},
    )

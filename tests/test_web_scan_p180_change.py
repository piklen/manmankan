"""kan web /api/scan · 与上一份 Web 日快照对比的 180 日位置变化测试。

覆盖 routes_api.default_scan_payload 的 p180_change 计算分支:
- 有上一份快照 + 周期 dict → p180_change = 当前 - 之前
- 上一份周期值不是 dict → p180_change = None
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kan.core.models import PeriodResult, StockScanResult
from kan.core.pipeline import Freshness
from kan.web.app import create_app
from kan.web.security import SESSION_HEADER_NAME

_TEST_SESSION_TOKEN = "test-session-token"


def _client() -> TestClient:
    return TestClient(
        create_app(session_token=_TEST_SESSION_TOKEN),
        base_url="http://127.0.0.1",
        headers={SESSION_HEADER_NAME: _TEST_SESSION_TOKEN},
    )


def _row(symbol: str, name: str, pct_180: float) -> StockScanResult:
    return StockScanResult(
        symbol=symbol, name=name, current_price=10.0,
        scan_date=date(2026, 6, 18),
        periods=[
            PeriodResult(
                period=180, n_low=8.0, n_high=12.0, position_pct=pct_180,
                at_low=pct_180 <= 5, at_high=pct_180 >= 95,
            ),
        ],
        low_resonance=0, high_resonance=0,
    )


def _stub_scan(
    monkeypatch: pytest.MonkeyPatch,
    previous_snapshot: dict | None,
) -> list:
    rows = [_row("600519", "贵州茅台", 20.0), _row("000858", "五粮液", 60.0)]
    freshness = Freshness(
        data_cutoff=date(2026, 6, 18), fetched_at="2026-06-18 23:41",
        expected_cutoff=date(2026, 6, 18), is_stale=False, phase="post",
    )
    fake_result = SimpleNamespace(
        results=rows,
        all_results=rows,
        mode="low",
        ctx=SimpleNamespace(
            source_name="自选股+真实持仓",
            targets=[("600519", "贵州茅台"), ("000858", "五粮液")],
            freshness=freshness,
        ),
    )
    monkeypatch.setattr(
        "kan.web.routes_api.run_scan", lambda _request: fake_result,
    )
    previous = (
        (date(2026, 6, 17), previous_snapshot) if previous_snapshot is not None else None
    )
    monkeypatch.setattr(
        "kan.web.routes_api.load_previous_web_daily_snapshot", lambda _before: previous,
    )
    saved: list = []
    monkeypatch.setattr(
        "kan.web.routes_api.save_web_daily_snapshot",
        lambda results, *, data_cutoff: saved.append((results, data_cutoff)),
    )
    return saved


def test_scan_payload_p180_change_from_previous_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = _stub_scan(
        monkeypatch,
        {"600519": {"180": {"pct": 50.0}}, "000858": {"180": None}},
    )

    response = _client().get("/api/scan")

    assert response.status_code == 200
    rows = {row["code"]: row for row in response.json()["rows"]}
    # 有有效前值 → 变化 = 20.0 - 50.0
    assert rows["600519"]["p180_change"] == -30.0
    # 前值不是 dict → None
    assert rows["000858"]["p180_change"] is None
    # 非 stale 且已落新快照
    assert len(saved) == 1
    assert saved[0][1] == date(2026, 6, 18)


def test_scan_payload_no_previous_snapshot_no_p180_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_scan(monkeypatch, None)

    response = _client().get("/api/scan")

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert all("p180_change" not in row for row in rows)

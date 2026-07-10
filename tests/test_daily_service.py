"""散户每日概览服务测试。"""
from __future__ import annotations

from datetime import date

import pytest

from kan.core.models import PeriodResult, StockScanResult
from kan.core.pipeline import DataCtx, Freshness
from kan.service.daily_service import _period_matches, build_daily_overview
from kan.service.scan_service import ScanServiceResult
from kan.web.serialize import serialize_daily_overview, serialize_scan


def _row(symbol: str, name: str, position: float) -> StockScanResult:
    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=100.0,
        scan_date=date(2026, 7, 9),
        periods=[
            PeriodResult(
                period=180,
                n_low=80.0,
                n_high=120.0,
                position_pct=position,
                at_low=position <= 5,
                at_high=position >= 95,
            ),
        ],
        low_resonance=1 if position <= 5 else 0,
        high_resonance=1 if position >= 95 else 0,
    )


def _result(*, stale: bool = False) -> ScanServiceResult:
    rows = [_row("600519", "贵州 茅台", 3.0), _row("000858", "五粮液", 96.0)]
    return ScanServiceResult(
        ctx=DataCtx(
            targets=[(row.symbol, row.name) for row in rows],
            meta=None,
            results=rows,
            freshness=Freshness(
                data_cutoff=date(2026, 7, 9),
                fetched_at="2026-07-09 16:05",
                expected_cutoff=date(2026, 7, 10) if stale else date(2026, 7, 9),
                is_stale=stale,
                phase="post",
            ),
            source_name="自选股+真实持仓",
        ),
        mode="low",
        all_results=rows,
        results=rows,
    )


def test_daily_overview_counts_extremes_and_previous_day_changes() -> None:
    previous = {
        "600519": {"180": {"pct": 20.0, "at_low": False, "at_high": False}},
        "000858": {"180": {"pct": 96.0, "at_low": False, "at_high": True}},
    }

    overview = build_daily_overview(
        _result(),
        previous_snapshot=previous,
        comparison_date=date(2026, 7, 8),
    )
    payload = serialize_daily_overview(overview)

    assert payload["low_180_count"] == 1
    assert payload["high_180_count"] == 1
    assert payload["low_resonance_count"] == 1
    assert payload["high_resonance_count"] == 1
    assert payload["comparison_date"] == "2026-07-08"
    assert payload["change_count"] == 1
    assert payload["changes"][0]["description"] == "新进入 180 日接近低位 [3%]"
    assert payload["low_180"][0]["name"] == "贵州茅台"


def test_scan_freshness_explains_current_and_stale_data() -> None:
    current = serialize_scan(_result())
    stale = serialize_scan(_result(stale=True))

    assert current["freshness"]["status"] == "current"
    assert "2026-07-09" in current["freshness"]["title"]
    assert stale["freshness"]["status"] == "stale"
    assert "正常应至少到 2026-07-10" in stale["freshness"]["detail"]
    assert stale["freshness"]["action_label"] == "立即更新"


def test_period_matches_applies_both_bounds() -> None:
    rows = [_row("600519", "低", 3.0), _row("000858", "中", 50.0), _row("300750", "高", 96.0)]

    matches = _period_matches(rows, period=180, minimum=10, maximum=90)

    assert [row.symbol for row in matches] == ["000858"]
    with pytest.raises(ValueError, match="至少提供一个"):
        _period_matches(rows, period=180)


def test_web_daily_snapshot_failure_does_not_hide_scan(monkeypatch) -> None:
    from kan.web.routes_api import default_scan_payload

    monkeypatch.setattr("kan.web.routes_api.run_scan", lambda _request: _result())
    monkeypatch.setattr(
        "kan.web.routes_api.load_previous_web_daily_snapshot", lambda _before: None
    )
    monkeypatch.setattr(
        "kan.web.routes_api.save_web_daily_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    payload = default_scan_payload()

    assert payload["ok"] is True
    assert payload["overview"]["scanned_count"] == 2

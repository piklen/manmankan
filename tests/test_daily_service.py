"""散户每日概览服务测试。"""
from __future__ import annotations

from datetime import date

import pytest

from kan.core.models import PeriodResult, StockScanResult
from kan.core.pipeline import DataCtx, Freshness
from kan.service.daily_service import _period_matches, build_daily_overview
from kan.service.scan_service import ScanServiceResult


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
    assert len(overview.low_180) == 1
    assert len(overview.high_180) == 1
    assert overview.low_resonance_count == 1
    assert overview.high_resonance_count == 1
    assert overview.comparison_date == date(2026, 7, 8)
    assert len(overview.changes) == 1
    assert overview.changes[0].description == "新进入 180 日接近低位 [3%]"
    assert overview.changes[0].name == "贵州茅台"


def test_period_matches_applies_both_bounds() -> None:
    rows = [_row("600519", "低", 3.0), _row("000858", "中", 50.0), _row("300750", "高", 96.0)]

    matches = _period_matches(rows, period=180, minimum=10, maximum=90)

    assert [row.symbol for row in matches] == ["000858"]
    with pytest.raises(ValueError, match="至少提供一个"):
        _period_matches(rows, period=180)

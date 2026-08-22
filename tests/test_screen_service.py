"""vNext 选股 application service 测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from kan.core.find_filter_models import TriggeredFilter
from kan.core.models import EnrichedResult, PeriodResult, ValuationMetrics
from kan.domain.screen import (
    ComparisonOperator,
    DataCoverage,
    ScreenCondition,
    ScreenFilterType,
    ScreenSort,
    ScreenSpec,
    SortDirection,
)
from kan.service import screen_service
from kan.storage import paths


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))


def _result(symbol: str, name: str, *, pe: float, position: float) -> EnrichedResult:
    return EnrichedResult(
        symbol=symbol,
        name=name,
        current_price=100,
        scan_date=date(2026, 8, 21),
        periods=[
            PeriodResult(
                period=180,
                n_low=80,
                n_high=120,
                position_pct=position,
                at_low=False,
                at_high=False,
                gain_pct=5,
            )
        ],
        low_resonance=1,
        high_resonance=0,
        valuation=ValuationMetrics(
            trade_date=date(2026, 8, 21),
            pe_ttm=pe,
            close=100,
            source="fixture",
        ),
    )


def _match(
    symbol: str, name: str, *, pe: float, position: float
) -> tuple[object, tuple[TriggeredFilter, ...]]:
    return (
        _result(symbol, name, pe=pe, position=position),
        (
            TriggeredFilter("pos", "180:lt:50", position),
            TriggeredFilter("pe", "lt:40", pe),
        ),
    )


def _coverage(size: int) -> DataCoverage:
    return DataCoverage(
        universe_size=size,
        evaluated=size,
        matched=size,
        ratio=1,
        data_cutoff=date(2026, 8, 21),
    )


def _spec() -> ScreenSpec:
    return ScreenSpec(
        name="低位且估值可见",
        conditions=[
            ScreenCondition(
                type=ScreenFilterType.POS,
                operator=ComparisonOperator.LT,
                value=50,
                period=180,
            ),
            ScreenCondition(
                type=ScreenFilterType.PE,
                operator=ComparisonOperator.LT,
                value=40,
            ),
        ],
        sort=[ScreenSort(field_id="pe", direction=SortDirection.ASC)],
    )


def test_run_is_auditable_sorted_and_content_hash_stable(
    isolated_workspace: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    matches = [
        _match("600519", "贵州茅台", pe=28, position=35),
        _match("000858", "五粮液", pe=20, position=25),
    ]
    monkeypatch.setattr(
        screen_service, "_run_engine", lambda _spec: (matches, _coverage(2))
    )
    saved = screen_service.save_screen(_spec())

    first = screen_service.run_saved_screen(saved.screen_id)
    second = screen_service.run_saved_screen(saved.screen_id)

    assert [row.symbol for row in first.rows] == ["000858", "600519"]
    assert first.rows[0].evidence[0].evidence_ref.startswith(f"run:{first.run_id}:")
    assert first.rows[0].evidence[0].data_date == date(2026, 8, 21)
    assert first.result_hash == second.result_hash
    assert first.snapshot_id == second.snapshot_id
    assert second.diff.added == []
    assert second.diff.removed == []


def test_next_run_records_added_removed_and_rank_changes(
    isolated_workspace: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = [
        _match("600519", "贵州茅台", pe=28, position=35),
        _match("000858", "五粮液", pe=20, position=25),
    ]
    current = [
        _match("600519", "贵州茅台", pe=18, position=20),
        _match("000568", "泸州老窖", pe=25, position=30),
    ]
    batches = iter([(initial, _coverage(2)), (current, _coverage(2))])
    monkeypatch.setattr(screen_service, "_run_engine", lambda _spec: next(batches))
    saved = screen_service.save_screen(_spec())

    first = screen_service.run_saved_screen(saved.screen_id)
    second = screen_service.run_saved_screen(saved.screen_id)

    assert second.diff.previous_run_id == first.run_id
    assert second.diff.added == ["000568"]
    assert second.diff.removed == ["000858"]
    assert [(item.symbol, item.delta) for item in second.diff.rank_changes] == [
        ("600519", 1)
    ]

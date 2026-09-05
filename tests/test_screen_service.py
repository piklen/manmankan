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
    NullPolicy,
    ScreenCondition,
    ScreenFilterType,
    ScreenSort,
    ScreenSpec,
    SortDirection,
)
from kan.service import screen_service
from kan.storage import paths


@pytest.mark.parametrize("policy", ["exclude", "fail"])
def test_coverage_uses_enriched_pool_before_filtering(monkeypatch, policy):
    from types import SimpleNamespace

    from kan.core.models import StockScanResult
    from kan.core.pipeline import DataCtx, Freshness
    from kan.service import find_service

    day = date(2026, 9, 4)
    bases = [StockScanResult(
        symbol=symbol, name="合成股份", current_price=100, scan_date=day,
        periods=[], low_resonance=0, high_resonance=0,
    ) for symbol in ("600001", "600002")]
    enriched = [EnrichedResult(**base.model_dump(), valuation=ValuationMetrics(
        trade_date=day, pe_ttm=pe, source="fixture",
    )) for base, pe in zip(bases, (10, 30), strict=True)]
    ctx = DataCtx(targets=[(base.symbol, base.name) for base in bases], meta=None, results=bases,
                  freshness=Freshness(data_cutoff=day, fetched_at="2026-09-04", expected_cutoff=day, is_stale=False, phase="closed"))
    monkeypatch.setattr(find_service, "run_data_pipeline", lambda *args, **kwargs: ctx)
    monkeypatch.setattr("kan.core.enrich.enrich_results", lambda *args, **kwargs: enriched)
    monkeypatch.setattr("kan.storage.positions.load_positions", lambda: SimpleNamespace(cash=None))
    monkeypatch.setattr(screen_service, "_normalize_codes", lambda codes: ctx.targets)
    spec = ScreenSpec.model_validate({
        "universe": {"kind": "codes", "codes": ["600001", "600002"]},
        "conditions": [{"type": "pe", "operator": "lt", "value": 20, "null_policy": policy}],
    })
    run = screen_service.run_screen(spec, persist=False)
    assert len(run.rows) == 1 and run.coverage.evaluated == 2
    assert run.coverage.missing_by_field == {}
    enriched[1] = EnrichedResult(**bases[1].model_dump())
    if policy == "fail":
        with pytest.raises(screen_service.ScreenServiceError, match="pe 缺 1"):
            screen_service.run_screen(spec, persist=False)
    else:
        run = screen_service.run_screen(spec, persist=False)
        assert len(run.rows) == 1 and run.coverage.missing_by_field == {"pe": 1}


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


def test_fail_null_policy_rejects_partial_dimension_gaps(
    isolated_workspace: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    conditions = [
        item.model_copy(update={"null_policy": NullPolicy.FAIL})
        if item.type is ScreenFilterType.PE
        else item
        for item in spec.conditions
    ]
    spec = spec.model_copy(update={"conditions": conditions})
    coverage = _coverage(2).model_copy(
        update={"missing_by_field": {"pe": 1}}
    )
    monkeypatch.setattr(
        screen_service,
        "_run_engine",
        lambda _spec: ([_match("600519", "贵州茅台", pe=20, position=25)], coverage),
    )

    with pytest.raises(screen_service.ScreenServiceError) as exc_info:
        screen_service.run_screen(spec, persist=False)

    assert exc_info.value.code == "incomplete_data"
    assert "pe 缺 1" in exc_info.value.message

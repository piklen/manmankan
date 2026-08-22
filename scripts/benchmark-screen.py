#!/usr/bin/env python3
"""测量已缓存数据进入 ScreenRun 后的应用层 p95，不触发网络。"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import date

from kan.core.find_filter_models import TriggeredFilter
from kan.core.models import EnrichedResult, PeriodResult, ValuationMetrics
from kan.domain.screen import (
    ComparisonOperator,
    DataCoverage,
    ScreenCondition,
    ScreenFilterType,
    ScreenSort,
    ScreenSpec,
)
from kan.service import screen_service


def _fixture(index: int) -> tuple[object, tuple[TriggeredFilter, ...]]:
    symbol = f"{index % 700000:06d}"
    pe = 8.0 + (index % 200) / 10
    position = float(index % 45)
    result = EnrichedResult(
        symbol=symbol,
        name=f"合成样本{index}",
        current_price=10 + index / 100,
        scan_date=date(2026, 8, 21),
        periods=[
            PeriodResult(
                period=180,
                n_low=8,
                n_high=15,
                position_pct=position,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=1,
        high_resonance=0,
        valuation=ValuationMetrics(
            trade_date=date(2026, 8, 21),
            pe_ttm=pe,
            source="synthetic-cache",
        ),
    )
    return (
        result,
        (
            TriggeredFilter("pos", "180:lt:45", position),
            TriggeredFilter("pe", "lt:30", pe),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--assert-p95", type=float, default=None)
    args = parser.parse_args()
    matches = [_fixture(index) for index in range(args.rows)]
    coverage = DataCoverage(
        universe_size=args.rows,
        evaluated=args.rows,
        matched=args.rows,
        ratio=1,
        data_cutoff=date(2026, 8, 21),
    )
    spec = ScreenSpec(
        name="合成缓存基准",
        conditions=[
            ScreenCondition(
                type=ScreenFilterType.POS,
                operator=ComparisonOperator.LT,
                value=45,
                period=180,
            ),
            ScreenCondition(
                type=ScreenFilterType.PE,
                operator=ComparisonOperator.LT,
                value=30,
            ),
        ],
        sort=[ScreenSort(field_id="pe")],
        limit=args.rows,
    )
    original = screen_service._run_engine
    elapsed: list[float] = []

    def cached_engine(
        spec: ScreenSpec,
    ) -> tuple[list[tuple[object, tuple[TriggeredFilter, ...]]], DataCoverage]:
        del spec
        return matches, coverage

    try:
        screen_service._run_engine = cached_engine
        screen_service.run_screen(spec, persist=False)
        for _ in range(args.samples):
            started = time.perf_counter()
            screen_service.run_screen(spec, persist=False)
            elapsed.append((time.perf_counter() - started) * 1000)
    finally:
        screen_service._run_engine = original
    ordered = sorted(elapsed)
    p95_index = max(0, min(len(ordered) - 1, round(len(ordered) * 0.95) - 1))
    p95 = ordered[p95_index]
    payload = {
        "mode": "cached_application_path",
        "rows": args.rows,
        "samples": args.samples,
        "p50_ms": round(statistics.median(elapsed), 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(max(elapsed), 2),
        "target_ms": args.assert_p95,
        "passed": args.assert_p95 is None or p95 <= args.assert_p95,
    }
    print(json.dumps(payload, ensure_ascii=False))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

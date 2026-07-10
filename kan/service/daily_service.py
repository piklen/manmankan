"""散户每日概览服务。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kan.core.models import StockScanResult
from kan.service.scan_service import ScanServiceResult

_LOW_THRESHOLD = 10.0
_HIGH_THRESHOLD = 90.0


@dataclass(frozen=True)
class DailyChange:
    """相对上一份日快照的一条客观变化。"""

    code: str
    name: str
    period: int
    description: str


@dataclass(frozen=True)
class DailyOverview:
    """Web/CLI 共用的一日事实摘要。"""

    data_cutoff: date | None
    expected_cutoff: date | None
    fetched_at: str | None
    stale: bool
    scanned_count: int
    low_180: tuple[StockScanResult, ...]
    high_180: tuple[StockScanResult, ...]
    low_resonance_count: int
    high_resonance_count: int
    comparison_date: date | None
    changes: tuple[DailyChange, ...]


def build_daily_overview(
    result: ScanServiceResult,
    *,
    previous_snapshot: dict[str, dict[str, dict]] | None = None,
    comparison_date: date | None = None,
) -> DailyOverview:
    """从同一份 scan 领域结果提炼散户首屏摘要，不重复取数。"""
    rows = result.results
    low_180 = tuple(_period_matches(rows, period=180, maximum=10))
    high_180 = tuple(_period_matches(rows, period=180, minimum=90))
    raw_changes = _daily_changes(result.all_results, previous_snapshot) if previous_snapshot else []
    changes = tuple(
        DailyChange(
            code=code,
            name=name.replace(" ", ""),
            period=period,
            description=description,
        )
        for code, name, period, description in raw_changes
    )
    freshness = result.ctx.freshness
    return DailyOverview(
        data_cutoff=freshness.data_cutoff,
        expected_cutoff=freshness.expected_cutoff,
        fetched_at=freshness.fetched_at,
        stale=freshness.is_stale,
        scanned_count=len(rows),
        low_180=low_180,
        high_180=high_180,
        low_resonance_count=sum(row.low_resonance > 0 for row in rows),
        high_resonance_count=sum(row.high_resonance > 0 for row in rows),
        comparison_date=comparison_date,
        changes=changes,
    )


def _period_matches(
    rows: list[StockScanResult],
    *,
    period: int,
    minimum: float | None = None,
    maximum: float | None = None,
) -> list[StockScanResult]:
    if minimum is None and maximum is None:
        raise ValueError("minimum 和 maximum 至少提供一个")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("minimum 不能大于 maximum")
    matches: list[StockScanResult] = []
    for row in rows:
        value = next(
            (
                item.position_pct
                for item in row.periods
                if item.period == period and not item.insufficient
            ),
            None,
        )
        if value is None:
            continue
        if minimum is not None and value < minimum:
            continue
        if maximum is not None and value > maximum:
            continue
        matches.append(row)
    return matches


def _daily_changes(
    current: list[StockScanResult],
    previous: dict[str, dict[str, dict]],
) -> list[tuple[str, str, int, str]]:
    """按首页公开的 10% / 90% 阈值比较两份不同交易日快照。"""
    changes: list[tuple[str, str, int, str]] = []
    for row in current:
        previous_periods = previous.get(row.symbol, {})
        for period in row.periods:
            if period.insufficient:
                continue
            old = previous_periods.get(str(period.period))
            old_pct = old.get("pct") if isinstance(old, dict) else None
            if not isinstance(old_pct, int | float):
                continue
            new_pct = period.position_pct
            if new_pct <= _LOW_THRESHOLD < old_pct:
                description = f"新进入 {period.period} 日接近低位 [{new_pct:.0f}%]"
                changes.append((row.symbol, row.name, period.period, description))
            elif old_pct <= _LOW_THRESHOLD < new_pct:
                description = f"离开 {period.period} 日接近低位 → {new_pct:.0f}%"
                changes.append((row.symbol, row.name, period.period, description))
            if new_pct >= _HIGH_THRESHOLD > old_pct:
                description = f"新进入 {period.period} 日接近高位 [{new_pct:.0f}%]"
                changes.append((row.symbol, row.name, period.period, description))
            elif old_pct >= _HIGH_THRESHOLD > new_pct:
                description = f"离开 {period.period} 日接近高位 → {new_pct:.0f}%"
                changes.append((row.symbol, row.name, period.period, description))
    return changes

"""A 股指数位置参照用例服务。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


class IndexServiceError(RuntimeError):
    """index 领域错误,由 CLI/API 边界映射。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        hint: str | None = None,
        exit_code: int = 1,
    ) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code
        super().__init__(message)


@dataclass(frozen=True)
class IndexPeriodView:
    period: int
    position_pct: float | None
    gain_pct: float | None


@dataclass(frozen=True)
class IndexRow:
    code: str
    name: str
    data_available: bool
    data_date: date | None
    close: float | None
    periods: list[IndexPeriodView] = field(default_factory=list)

    @property
    def position_pct(self) -> float | None:
        return self.periods[0].position_pct if self.periods else None

    @property
    def gain_pct(self) -> float | None:
        return self.periods[0].gain_pct if self.periods else None


@dataclass(frozen=True)
class IndexRequest:
    codes: list[str] | None = None
    periods: list[int] | None = None
    days: int = 420


@dataclass(frozen=True)
class IndexServiceResult:
    periods: list[int]
    rows: list[IndexRow]


def get_index_reference(request: IndexRequest | None = None) -> IndexServiceResult:
    """返回常用指数多周期位置参照。"""
    if request is None:
        request = IndexRequest()
    from kan.core.scanner import MAX_PERIOD, MIN_PERIOD, scan_stock
    from kan.data.index import DEFAULT_INDEXES, fetch_index_daily, index_name, normalize_index_code

    periods = _normalize_periods(request.periods or [60])
    for period in periods:
        if period < MIN_PERIOD or period > MAX_PERIOD:
            raise IndexServiceError(
                code="invalid_period",
                message=f"周期 {period} 无效（范围 {MIN_PERIOD}-{MAX_PERIOD}）",
                hint="例: kan index sh --period 60 --format json",
                exit_code=2,
            )
    raw_codes = request.codes or [spec.code for spec in DEFAULT_INDEXES]
    rows: list[IndexRow] = []
    for raw in raw_codes:
        try:
            code = normalize_index_code(raw)
        except ValueError as e:
            raise IndexServiceError(
                code="invalid_index",
                message=str(e),
                hint="支持: sh / sz / cyb / hs300 · 例: kan index sh --format json",
                exit_code=2,
            ) from e
        name = index_name(code)
        df = fetch_index_daily(code, days=max(request.days, max(periods) + 40))
        if df is None or len(df) < min(periods):
            rows.append(IndexRow(
                code=code,
                name=name,
                data_available=False,
                data_date=None,
                close=None,
            ))
            continue
        scan = scan_stock(df, code, name, periods=periods)
        rows.append(IndexRow(
            code=code,
            name=name,
            data_available=True,
            data_date=scan.scan_date,
            close=scan.current_price,
            periods=[
                IndexPeriodView(
                    period=period.period,
                    position_pct=None if period.insufficient else period.position_pct,
                    gain_pct=period.gain_pct,
                )
                for period in scan.periods
            ],
        ))
    return IndexServiceResult(periods=periods, rows=rows)


def _normalize_periods(periods: list[int]) -> list[int]:
    return sorted(dict.fromkeys(int(p) for p in periods))


def index_row_payload(row: IndexRow) -> dict[str, Any]:
    """兼容 `kan index --format json` 的单行结构。"""
    return {
        "code": row.code,
        "name": row.name,
        "data_available": row.data_available,
        "data_date": row.data_date.isoformat() if row.data_date else None,
        "close": row.close,
        "position_pct": row.position_pct,
        "gain_pct": row.gain_pct,
    }

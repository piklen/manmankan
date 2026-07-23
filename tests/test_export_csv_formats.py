"""export 层 csv 序列化函数单元测试。

覆盖合并引入的 --format csv 输出路径:
- export_cross_section.history_csv / info_csv
- export_trend.trend_csv / compare_csv
- export_scan.extreme_csv
- export_hold.hold_csv
- export_find_results.find_payload 的 180 日位置分布摘要

统一断言:BOM 头(Excel 兼容) + header + 关键字段值。
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

from kan.core.find_filter import FindMatch, TriggeredFilter
from kan.core.models import (
    EnrichedResult,
    MoneyflowMetrics,
    PeriodResult,
    StockScanResult,
    VolumeState,
)
from kan.core.pipeline import Freshness
from kan.core.positions import (
    AccountView,
    PositionHealth,
    PositionsSummary,
    PositionView,
)
from kan.core.scanner import TrendResult
from kan.storage import export

BOM = "\ufeff"


def _scan_result(
    symbol: str = "600519",
    name: str = "贵州茅台",
    pct_180: float = 38.7,
    *,
    with_180: bool = True,
) -> StockScanResult:
    periods = [
        PeriodResult(
            period=60, n_low=1000.0, n_high=1400.0,
            position_pct=81.5, at_low=False, at_high=False,
        ),
    ]
    if with_180:
        periods.append(
            PeriodResult(
                period=180, n_low=900.0, n_high=2000.0,
                position_pct=pct_180, at_low=pct_180 <= 5, at_high=pct_180 >= 95,
            )
        )
    return StockScanResult(
        symbol=symbol, name=name, current_price=1326.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=periods, low_resonance=1, high_resonance=0,
    )


# ── history_csv (export_cross_section) ────────────────────────────────


def _history_entry(date_str: str, pct: float | None) -> SimpleNamespace:
    periods = {}
    if pct is not None:
        periods[30] = {"pct": pct, "at_low": pct <= 5, "at_high": pct >= 95}
    return SimpleNamespace(
        snapshot_date=datetime.date.fromisoformat(date_str),
        periods=periods,
    )


def test_history_csv_bom_header_and_rows() -> None:
    entries = [
        _history_entry("2026-05-23", 4.0),
        _history_entry("2026-05-22", None),  # 缺 30 日周期 → "-" + 共振 0
    ]
    text = export.history_csv(entries, period=30)

    assert text.startswith(BOM)
    lines = text.lstrip(BOM).splitlines()
    assert lines[0] == "日期,30日位置%,共振,标记"
    assert "2026-05-23,4.0,1," in lines[1]
    assert lines[2].startswith("2026-05-22,-,0,")


# ── info_csv (export_cross_section) ───────────────────────────────────


def test_info_csv_full_and_insufficient_period() -> None:
    result = StockScanResult(
        symbol="600519", name="贵州茅台", current_price=1326.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[
            PeriodResult(
                period=30, n_low=1200.0, n_high=1400.0, position_pct=63.0,
                at_low=False, at_high=False,
                distance_to_low=126.0, distance_to_low_pct=10.5,
                distance_to_high=-74.0, distance_to_high_pct=-5.3,
            ),
            PeriodResult(
                period=180, n_low=0, n_high=0, position_pct=0,
                at_low=False, at_high=False, insufficient=True,
            ),
        ],
        low_resonance=0, high_resonance=0,
    )
    trend = TrendResult("600519", "贵州茅台", 1326.0, 3, 4.5, [("2026-05-29", 1.5)])
    volume = VolumeState(ratio=1.42, label="温和放大", window=5)
    moneyflow = MoneyflowMetrics(net_amount=5000.0, net_amount_5d=-1200.0)

    text = export.info_csv(result, trend, volume=volume, moneyflow=moneyflow)

    assert text.startswith(BOM)
    body = text.lstrip(BOM)
    assert "股票,贵州茅台" in body
    assert "代码,600519" in body
    assert "现价,1326.00" in body
    assert "低点共振,0" in body
    assert "成交量状态,温和放大" in body
    assert "量比,1.42" in body
    assert "今日主力(万),5000" in body
    assert "5日主力(万),-1200" in body
    assert "周期,最低,最高,位置%,距低,距低%,距高,距高%" in body
    assert "30日,1200.00,1400.00,63.0,+126.00,+10.5,-74.00,-5.3" in body
    # 数据不足周期 → 全 "-"
    assert "180日,-,-,-,-,-,-,-" in body


def test_info_csv_without_optional_sections() -> None:
    result = _scan_result()
    trend = TrendResult("600519", "贵州茅台", 1326.0, -2, -3.0, [])

    text = export.info_csv(result, trend, volume=None, moneyflow=None)

    assert text.startswith(BOM)
    assert "成交量状态" not in text
    assert "今日主力" not in text
    assert "60日,1000.00,1400.00,81.5" in text


# ── trend_csv (export_trend) ──────────────────────────────────────────


def test_trend_csv_with_latest_date_columns() -> None:
    results = [
        TrendResult("600519", "测试跌5", 100.0, -5, -8.0, [
            ("2026-05-27", -1.0), ("2026-05-28", -2.0), ("2026-05-29", -3.0),
        ]),
        # daily_changes 比 latest 短 → 尾部补空
        TrendResult("000001", "测试涨3", 50.0, 3, 4.5, [("2026-05-29", 1.5)]),
    ]
    text = export.trend_csv(results, latest=2)

    assert text.startswith(BOM)
    lines = text.lstrip(BOM).splitlines()
    # 日期列取 daily_changes 前 2 个 · header 用 MM-DD
    assert lines[0] == "股票,代码,现价,连续,累计%,05-27,05-28"
    assert "测试跌5,600519,100.00,跌5天,8.00,-1.00,-2.00" in lines[1]
    # 短行补空列 · 列数对齐 header
    assert lines[2].endswith(",")


def test_trend_csv_without_latest() -> None:
    results = [TrendResult("600519", "测试平", 20.0, 0, 0.0, [])]
    text = export.trend_csv(results, latest=None)

    assert text.startswith(BOM)
    lines = text.lstrip(BOM).splitlines()
    assert lines[0] == "股票,代码,现价,连续,累计%"
    assert lines[1] == "测试平,600519,20.00,平,0.00"


# ── compare_csv (export_trend) ────────────────────────────────────────


def test_compare_csv_transposed_with_missing_period() -> None:
    a = _scan_result("600519", "贵州茅台")
    b = StockScanResult(
        symbol="000858", name="五粮液", current_price=128.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[
            PeriodResult(
                period=60, n_low=100.0, n_high=150.0,
                position_pct=20.0, at_low=False, at_high=False,
            ),
        ],
        low_resonance=2, high_resonance=0,
    )
    text = export.compare_csv([a, b], periods=[60, 180])

    assert text.startswith(BOM)
    lines = text.lstrip(BOM).splitlines()
    assert lines[0] == "指标,600519,000858"
    assert lines[1] == "股票,贵州茅台,五粮液"
    assert lines[2] == "现价,1326.00,128.00"
    assert "60日位置%,81.5,20.0" in lines
    # b 缺 180 周期 → "-"
    assert "180日位置%,38.7,-" in lines
    assert "低点共振,1,2" in lines
    assert "ST,否,否" in lines
    assert "数据截止,2026-05-29,2026-05-29" in lines


# ── extreme_csv (export_scan) ─────────────────────────────────────────


def test_extreme_csv_low_and_high_label() -> None:
    result = _scan_result()
    pr = result.periods[-1]
    by_period = {180: [(result, pr)]}

    low_text = export.extreme_csv(by_period, mode="low", periods=[180])
    assert low_text.startswith(BOM)
    lines = low_text.lstrip(BOM).splitlines()
    assert lines[0] == "周期,股票,代码,现价,区间最低,区间最高,位置%"
    assert lines[1] == "180日低点,贵州茅台,600519,1326.00,900.00,2000.00,38.7"

    high_text = export.extreme_csv(by_period, mode="high", periods=[180])
    assert "180日高点" in high_text


def test_extreme_csv_default_periods_from_keys() -> None:
    result = _scan_result()
    pr = result.periods[-1]
    text = export.extreme_csv({180: [(result, pr)]}, mode="low")
    assert "180日低点" in text


# ── hold_csv (export_hold) ────────────────────────────────────────────


def _positions_summary() -> PositionsSummary:
    row = PositionView(
        symbol="600519", name="贵州茅台", cost=1680.5, shares=100,
        price=1700.0, prev_close=1690.0, market_value=170000.0,
        cost_value=168050.0, weight_pct=70.0, daily_pnl=1000.0,
        daily_pnl_pct=0.59, total_pnl=1950.0, total_pnl_pct=1.16,
        positions={30: 20.0, 60: 50.0, 180: 80.0},
        price_source="realtime", price_status="ok",
    )
    return PositionsSummary(
        results=[row],
        account=AccountView(
            cash=73000.0, total_market_value=170000.0, total_assets=243000.0,
            total_position_pct=69.96, daily_pnl=1000.0, total_pnl=1950.0,
        ),
        health=PositionHealth(
            high_count=1, low_count=0, middle_count=0,
            profit_count=1, loss_count=0, flat_count=0,
        ),
        price_mode="realtime",
        data_cutoff=datetime.date(2026, 6, 5),
        notes=["盈亏按裸价差计算，未计佣金/印花税。"],
    )


def test_hold_csv_header_and_values() -> None:
    text = export.hold_csv(_positions_summary())

    assert text.startswith(BOM)
    lines = text.lstrip(BOM).splitlines()
    assert lines[0] == (
        "代码,名称,现价,成本,股数,今日盈亏%,累计盈亏%,累计盈亏额,"
        "市值,仓位%,30日位置%,60日位置%,180日位置%"
    )
    row = lines[1]
    assert row.startswith('600519,"贵州茅台",1700.00,1680.5000,100,')
    assert "20.0,50.0,80.0" in row


def test_hold_csv_mask_hides_sensitive_numbers() -> None:
    text = export.hold_csv(_positions_summary(), mask=True)

    assert text.startswith(BOM)
    row = text.lstrip(BOM).splitlines()[1]
    # 成本/股数/盈亏被 mask 置空 · 现价与位置不 mask
    assert "1680.5000" not in row
    assert "1950.00" not in row
    assert row.startswith('600519,"贵州茅台",1700.00,,,,,,,,')
    assert "20.0,50.0,80.0" in row


# ── find_payload 180 日位置分布 (export_find_results) ──────────────────


def _freshness() -> Freshness:
    return Freshness(
        data_cutoff=datetime.date(2026, 5, 29), fetched_at=None,
        expected_cutoff=datetime.date(2026, 5, 29), is_stale=False, phase="closed",
    )


def _find_entry(scan: StockScanResult) -> tuple[FindMatch, EnrichedResult]:
    t = TriggeredFilter(filter_type="pos", param="180:lt:50", value=38.7)
    return FindMatch(result=scan, triggered=(t,)), EnrichedResult.from_scan(scan)


def test_find_payload_position_180_distribution() -> None:
    entries = [
        _find_entry(_scan_result("600519", "低位股", pct_180=10.0)),   # low ≤20
        _find_entry(_scan_result("000858", "高位股", pct_180=95.0)),   # high ≥80
        _find_entry(_scan_result("601318", "中位股", pct_180=50.0)),   # mid
        _find_entry(_scan_result("000001", "缺周期", with_180=False)),  # pr None → 跳过
    ]
    payload = export.find_payload(
        entries, query_time="t", pools=["watchlist"], filters=[],
        pool_size=4, matched_total=4, freshness=_freshness(),
    )

    assert payload["stats"]["position_180_distribution"] == {
        "low_lte_20": 1,
        "mid": 1,
        "high_gte_80": 1,
    }

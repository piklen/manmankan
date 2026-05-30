"""kan/core/models.py · ValuationMetrics + EnrichedResult (地基-1)。"""
import datetime

from kan.core.models import (
    EnrichedResult,
    PeriodResult,
    StockScanResult,
    ValuationMetrics,
)


def _scan() -> StockScanResult:
    return StockScanResult(
        symbol="600519", name="贵州茅台", current_price=1326.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[PeriodResult(
            period=60, n_low=1000.0, n_high=1400.0,
            position_pct=81.5, at_low=False, at_high=False,
        )],
        low_resonance=0, high_resonance=1,
    )


class TestValuationMetrics:
    def test_construct_raw_values(self):
        v = ValuationMetrics(
            trade_date=datetime.date(2026, 5, 29),
            close=1326.0, pe_ttm=20.04, pb=6.19, ps_ttm=9.63,
            dv_ttm=3.90, turnover_rate=0.61, volume_ratio=1.42,
            total_mv=165760820.0, circ_mv=165760820.0, source="tushare_metrics",
        )
        assert v.pe_ttm == 20.04
        assert v.dv_ttm == 3.90  # 股息率原始值 · 非分位
        assert v.source == "tushare_metrics"

    def test_all_metric_fields_optional(self):
        v = ValuationMetrics(trade_date=datetime.date(2026, 5, 29))
        assert v.pe_ttm is None
        assert v.close is None
        assert v.circ_mv is None


class TestEnrichedResult:
    def test_inherits_scan_fields(self):
        er = EnrichedResult.from_scan(_scan())
        assert er.symbol == "600519"
        assert er.name == "贵州茅台"
        assert er.high_resonance == 1
        assert len(er.periods) == 1
        assert er.valuation is None  # 默认未挂载 (lazy)

    def test_from_scan_attaches_valuation(self):
        v = ValuationMetrics(trade_date=datetime.date(2026, 5, 29), pe_ttm=20.04)
        er = EnrichedResult.from_scan(_scan(), v)
        assert er.valuation.pe_ttm == 20.04
        assert er.symbol == "600519"  # scan 字段仍在

    def test_is_a_stock_scan_result(self):
        """继承关系 · 访问扁平 (r.symbol 而非 r.scan.symbol)。"""
        assert isinstance(EnrichedResult.from_scan(_scan()), StockScanResult)

    def test_from_scan_deep_copies_periods(self):
        scan = _scan()
        er = EnrichedResult.from_scan(scan)
        er.periods[0].position_pct = 99.9
        # model_dump 重构 · periods 不共享引用 · 原对象不受影响
        assert scan.periods[0].position_pct == 81.5

    def test_json_serialization_flat(self):
        """scan 字段与 valuation 子对象平铺 · AI 消费友好 (地基-2 JSON)。"""
        v = ValuationMetrics(trade_date=datetime.date(2026, 5, 29), pe_ttm=20.04)
        er = EnrichedResult.from_scan(_scan(), v)
        d = er.model_dump()
        assert d["symbol"] == "600519"
        assert d["valuation"]["pe_ttm"] == 20.04

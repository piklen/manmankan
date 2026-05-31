"""kan/storage/export.py · find_payload / find_markdown / _valuation_public_dict (地基-2)。

合规守护 (compliance §3/§6/§7 · PRD §6):
- 对外 JSON/md **不含估值裸值** (pe_ttm / pb / ps_ttm / dv_ttm)
- 强制 disclaimer 字段 (衍生不可删)
- 不含黑名单判断词
"""
from __future__ import annotations

import datetime
import json

from kan.core.find_filter import FindMatch, TriggeredFilter
from kan.core.models import (
    EnrichedResult,
    PeriodResult,
    StockScanResult,
    ValuationMetrics,
)
from kan.storage import export

# compliance §3 黑名单 (子集 · 判断词 + 估值误读词)
_BANNED = [
    "低估", "被低估", "值得买入", "建议关注", "目标价", "见底",
    "推荐", "看好", "看空", "抄底", "评分", "评级", "优选", "黑马", "潜力股", "牛股",
]


def _scan(symbol: str = "600519", name: str = "贵州茅台", **kw) -> StockScanResult:
    return StockScanResult(
        symbol=symbol, name=name, current_price=1326.0,
        scan_date=datetime.date(2026, 5, 29),
        periods=[
            PeriodResult(period=60, n_low=1000.0, n_high=1400.0,
                         position_pct=81.5, at_low=False, at_high=False),
            PeriodResult(period=180, n_low=900.0, n_high=2000.0,
                         position_pct=38.7, at_low=False, at_high=False),
        ],
        low_resonance=2, high_resonance=0, **kw,
    )


def _valuation() -> ValuationMetrics:
    return ValuationMetrics(
        trade_date=datetime.date(2026, 5, 29), close=1326.0,
        pe_ttm=20.04, pb=6.19, ps_ttm=9.63, dv_ttm=3.9,
        turnover_rate=0.61, volume_ratio=1.42,
        total_mv=1.65e8, circ_mv=1.65e8, source="tushare_metrics",
    )


def _entry(symbol="600519", valuation=None, triggered=()):
    scan = _scan(symbol)
    er = EnrichedResult.from_scan(scan, valuation)
    return FindMatch(result=scan, triggered=triggered), er


def _freshness():
    from kan.core.pipeline import Freshness
    return Freshness(
        data_cutoff=datetime.date(2026, 5, 29), fetched_at=None,
        expected_cutoff=datetime.date(2026, 5, 29), is_stale=False, phase="closed",
    )


class TestValuationPublicDict:
    def test_none(self):
        assert export._valuation_public_dict(None) is None

    def test_omits_estimation_raw_values(self):
        d = export._valuation_public_dict(_valuation())
        # 合规核心:估值裸值不对外 (PRD §6 · 维护者反复明示"分位非裸值")
        for raw in ("pe_ttm", "pb", "ps_ttm", "dv_ttm"):
            assert raw not in d, f"估值裸值 {raw} 不该出现在对外 valuation"
        # 量价/市值客观事实出 (compliance §2 安全区 · OHLCV 类)
        assert d["turnover_rate"] == 0.61
        assert d["volume_ratio"] == 1.42
        assert d["total_mv"] == 1.65e8
        assert d["close"] == 1326.0
        assert d["source"] == "tushare_metrics"
        assert d["trade_date"] == "2026-05-29"


class TestFindPayload:
    def test_schema_and_disclaimer(self):
        t = TriggeredFilter(filter_type="pos", param="180:lt:50", value=38.7)
        entries = [_entry(valuation=_valuation(), triggered=(t,))]
        p = export.find_payload(
            entries, query_time="2026-05-29T15:30:00+08:00",
            pools=["industry:半导体"],
            filters=[{"name": "--pos", "param": "180:lt:50"}],
            pool_size=87, matched_total=1, freshness=_freshness(),
        )
        assert p["schema_version"] == export.FIND_SCHEMA_VERSION
        assert p["command"] == "find"
        assert "候选 ≠ 买入信号" in p["disclaimer"]
        assert "不构成任何形式的推荐或建议" in p["disclaimer"]
        assert p["rule"]["pools"] == ["industry:半导体"]
        assert p["stats"] == {
            "pool_size": 87, "matched": 1, "shown": 1,
            "data_cutoff": "2026-05-29", "stale": False,
        }
        r0 = p["results"][0]
        assert r0["code"] == "600519"
        assert r0["price"] == 1326.0
        assert r0["data_time"] == "2026-05-29"
        assert r0["triggered_filters"][0]["filter"] == "--pos"
        assert r0["triggered_filters"][0]["param"] == "180:lt:50"
        assert r0["triggered_filters"][0]["value"] == 38.7
        assert r0["context"]["low_resonance"] == 2
        assert r0["context"]["positions"]["180"] == 38.7
        # valuation 安全子集 (无估值裸值)
        assert "pe_ttm" not in r0["valuation"]
        assert r0["valuation"]["turnover_rate"] == 0.61

    def test_valuation_none_when_unenriched(self):
        entries = [_entry(valuation=None, triggered=())]
        p = export.find_payload(
            entries, query_time="t", pools=["watchlist"], filters=[],
            pool_size=1, matched_total=1, freshness=_freshness(),
        )
        assert p["results"][0]["valuation"] is None

    def test_empty_entries_valid_payload(self):
        p = export.find_payload(
            [], query_time="t", pools=["watchlist"], filters=[],
            pool_size=0, matched_total=0, freshness=_freshness(),
        )
        assert p["results"] == []
        assert p["stats"]["shown"] == 0
        assert p["disclaimer"]  # 空命中也必带 disclaimer

    def test_json_serializable_chinese_not_escaped(self):
        entries = [_entry(valuation=_valuation())]
        s = export.to_json(export.find_payload(
            entries, query_time="t", pools=["industry:半导体"], filters=[],
            pool_size=1, matched_total=1, freshness=_freshness(),
        ))
        assert "半导体" in s  # ensure_ascii=False
        assert json.loads(s)["command"] == "find"


class TestFindMarkdown:
    def test_table_and_disclaimer(self):
        t = TriggeredFilter(filter_type="pos", param="180:lt:50", value=38.7)
        entries = [_entry(valuation=_valuation(), triggered=(t,))]
        md = export.find_markdown(
            entries, title="慢慢看 · kan find · 行业「半导体」",
            pool_size=87, matched_total=1,
        )
        assert "命中 1 / 87" in md
        assert "600519" in md
        assert "--pos=180:lt:50" in md
        assert "候选 ≠ 买入信号" in md

    def test_empty(self):
        md = export.find_markdown([], title="kan find", pool_size=0, matched_total=0)
        assert "无股票符合" in md
        assert "候选 ≠ 买入信号" in md


class TestFindCompliance:
    """对外 find 输出严守 compliance §3 黑名单 + 估值裸值不出。

    扫描排除 disclaimer 文案:免责声明必须否定式提及禁词("不构成...推荐...")
    才能免责 · 合法 · 真正要查的是可变数据区 (股票名 / filter / valuation) 无禁词。
    """

    def _payload(self):
        t = TriggeredFilter(filter_type="pos", param="180:lt:50", value=38.7)
        entries = [_entry(valuation=_valuation(), triggered=(t,))]
        return export.find_payload(
            entries, query_time="t", pools=["industry:半导体"], filters=[],
            pool_size=1, matched_total=1, freshness=_freshness(),
        )

    def test_json_no_banned_words(self):
        p = dict(self._payload())
        p.pop("disclaimer")  # 固定免责区豁免 · 扫可变数据区
        s = export.to_json(p)
        for w in _BANNED:
            assert w not in s, f"compliance §3 违规: '{w}' 出现在 find JSON 数据区"

    def test_json_no_raw_estimation_keys(self):
        s = export.to_json(self._payload())  # 含 disclaimer 全量扫 key (key 名不会进免责)
        for raw in ("pe_ttm", "pb", "ps_ttm", "dv_ttm"):
            assert raw not in s, f"估值裸值 key {raw} 不该出现在对外 JSON"

    def test_md_no_banned_words(self):
        from kan.render.base import FIND_DISCLAIMER_TEXT
        t = TriggeredFilter(filter_type="resonance", param="low:gte:2", value=2.0)
        entries = [_entry(valuation=_valuation(), triggered=(t,))]
        md = export.find_markdown(entries, title="kan find", pool_size=1, matched_total=1)
        body = md.replace(FIND_DISCLAIMER_TEXT, "")  # 豁免固定免责区
        for w in _BANNED:
            assert w not in body, f"compliance §3 违规: '{w}' 出现在 find md 数据区"


class TestInfoPayloadValuation:
    """kan info --format json valuation 子对象 · 同样守裸值不出。"""

    class _Trend:
        streak = 1
        streak_pct = 0.85
        direction = "↑反弹"

    def test_info_valuation_safe_subset(self):
        p = export.info_payload(
            _scan(), self._Trend(), volume=None,
            data_cutoff=datetime.date(2026, 5, 29), fetched_at=None, stale=False,
            valuation=_valuation(),
        )
        assert p["valuation"]["turnover_rate"] == 0.61
        assert "pe_ttm" not in p["valuation"]  # 估值裸值不出

    def test_info_valuation_none_default(self):
        p = export.info_payload(
            _scan(), self._Trend(), volume=None,
            data_cutoff=None, fetched_at=None, stale=True,
        )
        assert p["valuation"] is None  # 未传 valuation → None (向后兼容)


class TestCrossSectionPayload:
    """kan find --all --format json 截面 payload (地基-3) · 守裸值不出 + disclaimer。"""

    def _row(self, code="600519", name="贵州茅台", with_ctx=True):
        from kan.core.cross_section import CrossSectionRow
        from kan.core.models import ValuationContext
        ctx = ValuationContext(
            industry="食品饮料", lookback_days=730, industry_sample=12,
            pe_pct_rank=None, pb_pct_rank=None,
            pe_industry_pct=62.0, pb_industry_pct=55.0,
            pe_industry_median=28.5, pb_industry_median=4.2,
        ) if with_ctx else None
        return CrossSectionRow(
            code=code, name=name, valuation=_valuation(), valuation_context=ctx,
        )

    def test_schema_and_mode(self):
        p = export.cross_section_payload(
            [self._row()], query_time="2026-05-29T15:30:00+08:00",
            pool_size=5500, data_cutoff=datetime.date(2026, 5, 29), stale=False,
        )
        assert p["schema_version"] == export.FIND_SCHEMA_VERSION
        assert p["command"] == "find"
        assert p["mode"] == "cross_section"
        assert p["rule"]["pools"] == ["all"]
        assert p["stats"] == {
            "pool_size": 5500, "shown": 1,
            "data_cutoff": "2026-05-29", "stale": False,
        }
        r0 = p["results"][0]
        assert r0["code"] == "600519"
        assert r0["valuation_context"]["pe_industry_pct"] == 62.0
        assert r0["valuation_context"]["pe_industry_median"] == 28.5

    def test_disclaimer_present(self):
        p = export.cross_section_payload(
            [self._row()], query_time="t", pool_size=1, data_cutoff=None, stale=True,
        )
        assert "候选 ≠ 买入信号" in p["disclaimer"]
        assert "不构成任何形式的推荐或建议" in p["disclaimer"]

    def test_valuation_omits_raw_estimation(self):
        r0 = export.cross_section_payload(
            [self._row()], query_time="t", pool_size=1, data_cutoff=None, stale=True,
        )["results"][0]
        # 个股估值裸值不出 (valuation 走 _valuation_public_dict)
        for raw in ("pe_ttm", "pb", "ps_ttm", "dv_ttm"):
            assert raw not in r0["valuation"]
        # 客观量价/市值出 (compliance §2 安全区)
        assert r0["valuation"]["turnover_rate"] == 0.61
        assert r0["valuation"]["total_mv"] == 1.65e8

    def test_full_json_no_individual_raw_values(self):
        s = export.to_json(export.cross_section_payload(
            [self._row()], query_time="t", pool_size=1, data_cutoff=None, stale=True,
        ))
        # 个股 PE/PB 裸值 (_valuation: 20.04 / 6.19) 不出。注意 valuation_context 的
        # pb_industry_* 是行业分位/中位 (合规) · 故查裸值数值而非 "pb" 子串。
        assert "20.04" not in s, "个股 PE 裸值不该出现"
        assert "6.19" not in s, "个股 PB 裸值不该出现"
        assert '"pe_ttm"' not in s
        assert '"ps_ttm"' not in s

    def test_no_banned_words(self):
        p = dict(export.cross_section_payload(
            [self._row()], query_time="t", pool_size=1, data_cutoff=None, stale=True,
        ))
        p.pop("disclaimer")  # 固定免责区豁免 · 扫可变数据区
        s = export.to_json(p)
        for w in _BANNED:
            assert w not in s, f"compliance §3 违规: '{w}' 在截面 JSON 数据区"

    def test_ctx_none_safe(self):
        p = export.cross_section_payload(
            [self._row(with_ctx=False)], query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        )
        assert p["results"][0]["valuation_context"] is None

    def test_empty_rows_valid(self):
        p = export.cross_section_payload(
            [], query_time="t", pool_size=5500, data_cutoff=None, stale=True,
        )
        assert p["results"] == []
        assert p["stats"]["shown"] == 0
        assert p["disclaimer"]  # 空命中也必带 disclaimer

    def test_markdown_renders_with_disclaimer(self):
        md = export.cross_section_markdown(
            [self._row()], title="慢慢看 · kan find · A股全市场截面", pool_size=5500,
        )
        assert "全市场 5500 只" in md
        assert "600519" in md
        assert "食品饮料" in md          # 行业
        assert "62%" in md               # PE 行业内分位 (62.0 → 62%)
        assert "候选 ≠ 买入信号" in md   # disclaimer 衍生不可删
        # 个股估值裸值不出 (PE 20.04 / PB 6.19)
        assert "20.04" not in md
        assert "6.19" not in md

    def test_markdown_empty_rows(self):
        md = export.cross_section_markdown([], title="kan find", pool_size=0)
        assert "无截面数据" in md
        assert "候选 ≠ 买入信号" in md

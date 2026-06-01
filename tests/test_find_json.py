"""kan/storage/export.py · find_payload / find_markdown / 截面 payload (地基-2 + 整合-1)。

合规守护 (compliance §2/§3/§7 · 整合-1 2026-05-31 拍板):
- 估值裸值 (pe_ttm / pb / ps_ttm / dv_ttm) 自整合-1 起**对外输出** (用户主导 filter ·
  推翻旧"估值不给裸值"设计)
- fundamentals (ROE/增速) / moneyflow (主力净额) 裸值对外 (客观/单向正向因子)
- 强制 disclaimer 字段 (衍生不可删)
- **仍守不动:不含 §3 黑名单判断词** (推荐/优质/低估 ...) — 放开的是数值不是判断词
"""
from __future__ import annotations

import datetime
import json

from kan.core.find_filter import FindMatch, TriggeredFilter
from kan.core.models import (
    ChipMetrics,
    EnrichedResult,
    FundamentalMetrics,
    MoneyflowMetrics,
    PeriodResult,
    SentimentMetrics,
    StockScanResult,
    TechnicalMetrics,
    ValuationMetrics,
)
from kan.storage import export

# compliance §3 黑名单 (子集 · 判断词 + 估值误读词 · 整合-1 后仍守)
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


def _fundamentals() -> FundamentalMetrics:
    return FundamentalMetrics(
        end_date=datetime.date(2026, 3, 31), roe=15.2,
        netprofit_yoy=8.5, or_yoy=12.1, source="tushare_fina",
    )


def _moneyflow() -> MoneyflowMetrics:
    return MoneyflowMetrics(
        trade_date=datetime.date(2026, 5, 29), net_amount=5000.0,
        buy_elg_amount=3000.0, buy_lg_amount=2000.0, source="tushare_moneyflow",
    )


def _technical() -> TechnicalMetrics:
    # 真实 MCP 值 (600519.SH 20260529 · 前复权)
    return TechnicalMetrics(
        trade_date=datetime.date(2026, 5, 29), close=1326.0,
        macd_dif=-30.8, macd_dea=-30.8, macd=-0.08,
        kdj_k=46.5, kdj_d=25.5, kdj_j=88.5,
        rsi_6=57.3, rsi_12=46.7, rsi_24=43.3,
        ma_5=1292.8, ma_10=1302.8, ma_20=1333.4, ma_60=1397.8,
        boll_upper=1406.0, boll_mid=1333.4, boll_lower=1260.7,
        source="tushare_factor",
    )


def _sentiment() -> SentimentMetrics:
    return SentimentMetrics(
        trade_date=datetime.date(2026, 5, 29), limit_times=3.0,
        open_times=1.0, limit="U", up_stat="3/3", source="tushare_limit",
    )


def _chip() -> ChipMetrics:
    # 真实 MCP 值 (600519.SH 20260529)
    return ChipMetrics(
        trade_date=datetime.date(2026, 5, 29), winner_rate=14.29,
        cost_5pct=1280.4, cost_50pct=1425.6, cost_95pct=2098.8,
        weight_avg=1494.39, source="tushare_cyq",
    )


def _entry(symbol="600519", valuation=None, fundamentals=None, moneyflow=None,
           technical=None, sentiment=None, chip=None, triggered=()):
    scan = _scan(symbol)
    er = EnrichedResult.from_scan(
        scan, valuation, fundamentals, moneyflow, technical, sentiment, chip,
    )
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

    def test_includes_estimation_raw_values(self):
        """整合-1 拍板:估值裸值对外输出 (推翻旧"估值不给裸值")。"""
        d = export._valuation_public_dict(_valuation())
        # 估值裸值现在出 (整合-1 · 用户主导 filter · 裸值客观)
        assert d["pe_ttm"] == 20.04
        assert d["pb"] == 6.19
        assert d["ps_ttm"] == 9.63
        assert d["dv_ttm"] == 3.9
        # 量价/市值客观事实仍出 (compliance §2 安全区)
        assert d["turnover_rate"] == 0.61
        assert d["volume_ratio"] == 1.42
        assert d["total_mv"] == 1.65e8
        assert d["close"] == 1326.0
        assert d["source"] == "tushare_metrics"
        assert d["trade_date"] == "2026-05-29"


class TestFundamentalsMoneyflowDict:
    """整合-1 新增 · fundamentals / moneyflow 对外 dict。"""

    def test_fundamentals(self):
        d = export._fundamentals_public_dict(_fundamentals())
        assert d["roe"] == 15.2
        assert d["netprofit_yoy"] == 8.5
        assert d["or_yoy"] == 12.1
        assert d["end_date"] == "2026-03-31"
        assert d["source"] == "tushare_fina"

    def test_moneyflow(self):
        d = export._moneyflow_public_dict(_moneyflow())
        assert d["net_amount"] == 5000.0
        assert d["buy_elg_amount"] == 3000.0
        assert d["buy_lg_amount"] == 2000.0
        assert d["trade_date"] == "2026-05-29"
        assert d["source"] == "tushare_moneyflow"

    def test_none(self):
        assert export._fundamentals_public_dict(None) is None
        assert export._moneyflow_public_dict(None) is None


class TestTechnicalSentimentChipDict:
    """整合-2 新增 · technical / sentiment / chip 对外 dict (中性字段名 · 裸值 · 无判断词)。"""

    def test_technical(self):
        d = export._technical_public_dict(_technical())
        assert d["rsi_6"] == 57.3
        assert d["macd_dif"] == -30.8
        assert d["macd"] == -0.08
        assert d["kdj_j"] == 88.5
        assert d["ma_20"] == 1333.4
        assert d["boll_upper"] == 1406.0
        assert d["source"] == "tushare_factor"

    def test_sentiment(self):
        d = export._sentiment_public_dict(_sentiment())
        assert d["limit_times"] == 3.0
        assert d["open_times"] == 1.0
        assert d["limit"] == "U"
        assert d["up_stat"] == "3/3"
        assert d["source"] == "tushare_limit"

    def test_chip(self):
        d = export._chip_public_dict(_chip())
        assert d["winner_rate"] == 14.29
        assert d["cost_50pct"] == 1425.6
        assert d["weight_avg"] == 1494.39
        assert d["source"] == "tushare_cyq"

    def test_none(self):
        assert export._technical_public_dict(None) is None
        assert export._sentiment_public_dict(None) is None
        assert export._chip_public_dict(None) is None


class TestFindPayload:
    def test_schema_and_disclaimer(self):
        t = TriggeredFilter(filter_type="pos", param="180:lt:50", value=38.7)
        entries = [_entry(
            valuation=_valuation(), fundamentals=_fundamentals(),
            moneyflow=_moneyflow(), triggered=(t,),
        )]
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
        assert r0["triggered_filters"][0]["filter"] == "--pos"
        assert r0["triggered_filters"][0]["value"] == 38.7
        assert r0["context"]["positions"]["180"] == 38.7
        # 整合-1:估值裸值现在出 + fundamentals / moneyflow 出
        assert r0["valuation"]["pe_ttm"] == 20.04
        assert r0["valuation"]["turnover_rate"] == 0.61
        assert r0["fundamentals"]["roe"] == 15.2
        assert r0["moneyflow"]["net_amount"] == 5000.0

    def test_pe_roe_moneyflow_triggered_echo_raw(self):
        """整合-1 · --pe/--roe/--moneyflow triggered 回显裸值 + flag 名正确。"""
        tpe = TriggeredFilter(filter_type="pe", param="lt:30", value=20.04)
        troe = TriggeredFilter(filter_type="roe", param="gte:15", value=15.2)
        tmf = TriggeredFilter(filter_type="moneyflow", param="gt:0", value=5000.0)
        entries = [_entry(
            valuation=_valuation(), fundamentals=_fundamentals(),
            moneyflow=_moneyflow(), triggered=(tpe, troe, tmf),
        )]
        p = export.find_payload(
            entries, query_time="t", pools=["watchlist"], filters=[],
            pool_size=1, matched_total=1, freshness=_freshness(),
        )
        tfs = {t["filter"]: t for t in p["results"][0]["triggered_filters"]}
        assert tfs["--pe"]["value"] == 20.04
        assert tfs["--roe"]["value"] == 15.2
        assert tfs["--moneyflow"]["value"] == 5000.0

    def test_valuation_none_when_unenriched(self):
        entries = [_entry(valuation=None, triggered=())]
        p = export.find_payload(
            entries, query_time="t", pools=["watchlist"], filters=[],
            pool_size=1, matched_total=1, freshness=_freshness(),
        )
        assert p["results"][0]["valuation"] is None
        assert p["results"][0]["fundamentals"] is None
        assert p["results"][0]["moneyflow"] is None

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

    def test_pe_filter_flag_rendered(self):
        """整合-1 · --pe triggered 在 md 用正确 flag 名渲染。"""
        t = TriggeredFilter(filter_type="pe", param="lt:30", value=20.04)
        entries = [_entry(valuation=_valuation(), triggered=(t,))]
        md = export.find_markdown(entries, title="kan find", pool_size=1, matched_total=1)
        assert "--pe=lt:30" in md

    def test_empty(self):
        md = export.find_markdown([], title="kan find", pool_size=0, matched_total=0)
        assert "无股票符合" in md
        assert "候选 ≠ 买入信号" in md


class TestFindCompliance:
    """对外 find 输出守 compliance §3 黑名单 (估值裸值 §7 拍板放开 · 黑名单仍守不动)。

    扫描排除 disclaimer 文案:免责声明必须否定式提及禁词("不构成...推荐...")
    才能免责 · 合法 · 真正要查的是可变数据区 (股票名 / filter / valuation) 无禁词。
    """

    def _payload(self):
        t = TriggeredFilter(filter_type="pos", param="180:lt:50", value=38.7)
        entries = [_entry(
            valuation=_valuation(), fundamentals=_fundamentals(),
            moneyflow=_moneyflow(), technical=_technical(),
            sentiment=_sentiment(), chip=_chip(), triggered=(t,),
        )]
        return export.find_payload(
            entries, query_time="t", pools=["industry:半导体"], filters=[],
            pool_size=1, matched_total=1, freshness=_freshness(),
        )

    def test_json_no_banned_words(self):
        """§3 黑名单仍守 (整合-1/2 放开数值裸值 · 不放开判断词 · 含技术/情绪/筹码全维度)。"""
        p = dict(self._payload())
        p.pop("disclaimer")  # 固定免责区豁免 · 扫可变数据区
        s = export.to_json(p)
        for w in _BANNED:
            assert w not in s, f"compliance §3 违规: '{w}' 出现在 find JSON 数据区"

    def test_json_includes_new_dimension_keys(self):
        """整合-2:技术/情绪/筹码裸值 key 出现在对外 JSON (中性原始名)。"""
        s = export.to_json(self._payload())
        assert '"rsi_6"' in s and '"macd_dif"' in s and '"kdj_j"' in s
        assert '"limit_times"' in s and '"winner_rate"' in s

    def test_json_includes_estimation_raw_keys(self):
        """整合-1 拍板:估值裸值 key 现在出现在对外 JSON (推翻旧"裸值不出"守护)。"""
        s = export.to_json(self._payload())
        assert '"pe_ttm"' in s
        assert '"pb"' in s
        assert '"roe"' in s
        assert '"net_amount"' in s

    def test_md_no_banned_words(self):
        from kan.render.base import FIND_DISCLAIMER_TEXT
        t = TriggeredFilter(filter_type="resonance", param="low:gte:2", value=2.0)
        entries = [_entry(valuation=_valuation(), triggered=(t,))]
        md = export.find_markdown(entries, title="kan find", pool_size=1, matched_total=1)
        body = md.replace(FIND_DISCLAIMER_TEXT, "")  # 豁免固定免责区
        for w in _BANNED:
            assert w not in body, f"compliance §3 违规: '{w}' 出现在 find md 数据区"


class TestInfoPayloadValuation:
    """kan info --format json valuation 子对象 · 整合-1 裸值放开。"""

    class _Trend:
        streak = 1
        streak_pct = 0.85
        direction = "↑反弹"

    def test_info_valuation_includes_raw(self):
        p = export.info_payload(
            _scan(), self._Trend(), volume=None,
            data_cutoff=datetime.date(2026, 5, 29), fetched_at=None, stale=False,
            valuation=_valuation(),
        )
        assert p["valuation"]["turnover_rate"] == 0.61
        assert p["valuation"]["pe_ttm"] == 20.04  # 整合-1 估值裸值出

    def test_info_valuation_none_default(self):
        p = export.info_payload(
            _scan(), self._Trend(), volume=None,
            data_cutoff=None, fetched_at=None, stale=True,
        )
        assert p["valuation"] is None  # 未传 valuation → None (向后兼容)


class TestCrossSectionPayload:
    """kan find --all --format json 截面 payload (地基-3 + 整合-1) · 裸值放开 + moneyflow。"""

    def _row(self, code="600519", name="贵州茅台", with_ctx=True, with_mf=True, scan=None):
        from kan.core.cross_section import CrossSectionRow
        from kan.core.models import ValuationContext
        ctx = ValuationContext(
            industry="食品饮料", lookback_days=730, industry_sample=12,
            pe_pct_rank=None, pb_pct_rank=None,
            pe_industry_pct=62.0, pb_industry_pct=55.0,
            pe_industry_median=28.5, pb_industry_median=4.2,
        ) if with_ctx else None
        mf = _moneyflow() if with_mf else None
        return CrossSectionRow(
            code=code, name=name, valuation=_valuation(),
            valuation_context=ctx, moneyflow=mf, scan=scan,
        )

    def _entries(self, *rows, triggered=()):
        """包成 (row, triggered) entries (整合-1 cross_section_payload 新签名)。"""
        return [(r, triggered) for r in rows]

    def test_schema_and_mode(self):
        p = export.cross_section_payload(
            self._entries(self._row()), query_time="2026-05-29T15:30:00+08:00",
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
            self._entries(self._row()), query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        )
        assert "候选 ≠ 买入信号" in p["disclaimer"]
        assert "不构成任何形式的推荐或建议" in p["disclaimer"]

    def test_valuation_includes_raw_and_moneyflow(self):
        r0 = export.cross_section_payload(
            self._entries(self._row()), query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        )["results"][0]
        # 整合-1:个股估值裸值现在出 + moneyflow 出
        assert r0["valuation"]["pe_ttm"] == 20.04
        assert r0["valuation"]["turnover_rate"] == 0.61
        assert r0["valuation"]["total_mv"] == 1.65e8
        assert r0["moneyflow"]["net_amount"] == 5000.0

    def test_full_json_includes_individual_raw_values(self):
        s = export.to_json(export.cross_section_payload(
            self._entries(self._row()), query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        ))
        # 整合-1:个股 PE/PB 裸值现在出
        assert "20.04" in s
        assert '"pe_ttm"' in s

    def test_no_banned_words(self):
        """§3 黑名单仍守 (截面 JSON · 整合-1 后不变)。"""
        p = dict(export.cross_section_payload(
            self._entries(self._row()), query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        ))
        p.pop("disclaimer")  # 固定免责区豁免 · 扫可变数据区
        s = export.to_json(p)
        for w in _BANNED:
            assert w not in s, f"compliance §3 违规: '{w}' 在截面 JSON 数据区"

    def test_filter_triggered_and_rule(self):
        """整合-1 · 截面 filter (--pe/--moneyflow) triggered + rule.filters 反映输入。"""
        tpe = TriggeredFilter(filter_type="pe", param="lt:30", value=20.04)
        entries = self._entries(self._row(), triggered=(tpe,))
        p = export.cross_section_payload(
            entries, query_time="t", pool_size=1, data_cutoff=None, stale=True,
            filters=[{"name": "--pe", "param": "lt:30"}],
        )
        assert p["rule"]["filters"] == [{"name": "--pe", "param": "lt:30"}]
        tf = p["results"][0]["triggered_filters"][0]
        assert tf["filter"] == "--pe"
        assert tf["value"] == 20.04

    def test_ctx_none_safe(self):
        p = export.cross_section_payload(
            self._entries(self._row(with_ctx=False)), query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        )
        assert p["results"][0]["valuation_context"] is None

    def test_moneyflow_none_safe(self):
        p = export.cross_section_payload(
            self._entries(self._row(with_mf=False)), query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        )
        assert p["results"][0]["moneyflow"] is None

    def test_scan_context_serialized_when_present(self):
        scan = StockScanResult(
            symbol="600519", name="贵州茅台", current_price=1326.0,
            scan_date=datetime.date(2026, 5, 29),
            periods=[
                PeriodResult(period=30, n_low=1200.0, n_high=1400.0,
                             position_pct=63.0, at_low=False, at_high=False,
                             gain_pct=8.5),
                PeriodResult(period=60, n_low=0.0, n_high=0.0,
                             position_pct=0.0, at_low=False, at_high=False,
                             insufficient=True),
            ],
            low_resonance=1, high_resonance=0, up_days=4,
        )
        p = export.cross_section_payload(
            self._entries(self._row(scan=scan)), query_time="t",
            pool_size=1, data_cutoff=None, stale=True,
        )
        ctx = p["results"][0]["context"]
        assert ctx["up_days"] == 4
        assert ctx["positions"] == {"30": 63.0}
        assert ctx["gains"] == {"30": 8.5}

    def test_empty_entries_valid(self):
        p = export.cross_section_payload(
            [], query_time="t", pool_size=5500, data_cutoff=None, stale=True,
        )
        assert p["results"] == []
        assert p["stats"]["shown"] == 0
        assert p["disclaimer"]  # 空命中也必带 disclaimer

    def test_markdown_renders_with_raw_pe_and_moneyflow(self):
        md = export.cross_section_markdown(
            [self._row()], title="慢慢看 · kan find · A股全市场截面", pool_size=5500,
        )
        assert "全市场 5500 只" in md
        assert "600519" in md
        assert "食品饮料" in md          # 行业
        assert "62%" in md               # PE 行业内分位 (62.0 → 62%)
        assert "候选 ≠ 买入信号" in md   # disclaimer 衍生不可删
        # 整合-1:个股估值裸值现在出 (PE 20.04) + 主力净额
        assert "20.04" in md
        assert "5,000" in md             # net_amount 5000.0 千分位

    def test_markdown_empty_rows(self):
        md = export.cross_section_markdown([], title="kan find", pool_size=0)
        assert "无截面数据" in md
        assert "候选 ≠ 买入信号" in md

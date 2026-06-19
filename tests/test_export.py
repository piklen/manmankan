"""导出渲染测试 · kan/export.py · markdown / json"""

import json
import sys
from datetime import date
from types import SimpleNamespace

from kan.core.models import (
    BoardPositionContext,
    BoardPositionPeriod,
    PeriodResult,
    StockScanResult,
    VolumeState,
)
from kan.storage.export import (
    OutputFormat,
    code_pool_payload,
    compare_markdown,
    compare_payload,
    error_payload,
    extreme_markdown,
    extreme_payload,
    info_markdown,
    info_payload,
    md_table,
    scan_markdown,
    scan_payload,
    to_json,
    trend_markdown,
    trend_payload,
)


def _result(symbol="600519", name="贵州茅台", **kw):
    defaults = {
        "symbol": symbol,
        "name": name,
        "current_price": 100.0,
        "scan_date": date(2026, 5, 21),
        "periods": [
            PeriodResult(
                period=3, n_low=90.0, n_high=110.0,
                position_pct=50.0, at_low=False, at_high=False,
            ),
            PeriodResult(
                period=5, n_low=88.0, n_high=120.0,
                position_pct=3.0, at_low=True, at_high=False,
            ),
        ],
        "low_resonance": 1,
        "high_resonance": 0,
    }
    defaults.update(kw)
    return StockScanResult(**defaults)


def test_output_format_values():
    assert OutputFormat.terminal.value == "terminal"
    assert OutputFormat.md.value == "md"
    assert OutputFormat.json.value == "json"


def test_to_json_chinese_not_escaped():
    out = to_json({"name": "贵州茅台"})
    assert "贵州茅台" in out
    assert "\\u" not in out


def test_to_json_escapes_when_stdout_cannot_encode_unicode(monkeypatch):
    class Cp1252Stdout:
        encoding = "cp1252"

    monkeypatch.setattr(sys, "stdout", Cp1252Stdout())

    out = to_json({"name": "贵州茅台", "disclaimer": "候选 ≠ 买入信号"})

    assert "贵州茅台" not in out
    assert "\\u8d35\\u5dde\\u8305\\u53f0" in out
    assert json.loads(out)["name"] == "贵州茅台"


def test_md_table_structure():
    out = md_table(["A", "B"], [["1", "2"], ["3", "4"]])
    lines = out.splitlines()
    assert lines[0] == "| A | B |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 | 2 |"


def test_scan_payload_shape():
    payload = scan_payload(
        [_result()], mode="low", data_cutoff=date(2026, 5, 21),
        fetched_at="2026-05-21 23:00", stale=False,
    )
    assert payload["command"] == "scan"
    assert payload["mode"] == "low"
    assert payload["data_cutoff"] == "2026-05-21"
    assert "disclaimer" in payload
    assert payload["stale"] is False
    assert len(payload["results"]) == 1
    assert payload["results"][0]["symbol"] == "600519"
    assert payload["results"][0]["periods"][0]["period"] == 3  # 嵌套也序列化


def test_scan_payload_json_roundtrip():
    payload = scan_payload(
        [_result()], mode="low", data_cutoff=None, fetched_at=None, stale=True,
    )
    parsed = json.loads(to_json(payload))
    assert parsed["data_cutoff"] is None
    assert parsed["results"][0]["name"] == "贵州茅台"


def test_scan_payload_includes_ai_daily_metrics():
    payload = scan_payload(
        [_result(
            pe_ttm=20.04,
            pb=6.19,
            turnover_rate=0.61,
            volume_ratio=1.42,
            total_mv=1.65e8,
            moneyflow_net_amount=5000.0,
            moneyflow_buy_elg_amount=3000.0,
            moneyflow_buy_lg_amount=2000.0,
            moneyflow_inflow_days=3,
        )],
        mode="low",
        data_cutoff=date(2026, 5, 21),
        fetched_at=None,
        stale=False,
    )
    row = payload["results"][0]
    assert row["pe_ttm"] == 20.04
    assert row["pb"] == 6.19
    assert row["turnover_rate"] == 0.61
    assert row["volume_ratio"] == 1.42
    assert row["total_mv"] == 1.65e8
    assert row["moneyflow_net_amount"] == 5000.0
    assert row["moneyflow_buy_elg_amount"] == 3000.0
    assert row["moneyflow_buy_lg_amount"] == 2000.0
    assert row["moneyflow_inflow_days"] == 3


def test_scan_markdown_has_header_and_table():
    md = scan_markdown([_result()], periods=[3, 5], mode="low", title="测试标题")
    assert md.startswith("# 测试标题")
    assert "| 股票 | 现价 | 3日 | 5日 | 共振 |" in md
    assert "贵州茅台 600519" in md
    assert "投资建议" in md  # disclaimer


def test_scan_markdown_extreme_bracketed():
    """触及极值的周期 → [x%] 方括号 · 普通 → x%。"""
    md = scan_markdown([_result()], periods=[3, 5], mode="low", title="t")
    assert "[3%]" in md       # period 5 at_low=True
    assert "| 50% |" in md    # period 3 普通


def test_scan_markdown_limit_up_tag():
    md = scan_markdown(
        [_result(limit_up=True)], periods=[3], mode="low", title="t",
    )
    assert "涨停" in md


def test_scan_markdown_context_columns():
    md = scan_markdown(
        [_result(
            pe_ttm=20.4,
            moneyflow_5d_net_amount=12345.0,
            ma_10=101.23,
            ma_20=98.76,
            recent_low_20=90.12,
        )],
        periods=[3],
        mode="low",
        title="t",
        show_context=True,
    )
    assert "| 股票 | 现价 | PE | 5日主力(万) | 10日线 | 20日线 | 20日低 | 除权除息 | 3日 | 共振 |" in md
    assert "| 贵州茅台 600519 | 100.00 | 20.4 | 12,345 | 101.23 | 98.76 | 90.12 | - | 50% | ×1 |" in md


def _fake_trend(**kw):
    defaults = {"streak": -2, "streak_pct": 1.5, "direction": "跌2天"}
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _board_context():
    return BoardPositionContext(
        industry="食品饮料",
        board_code="801016",
        board_level=1,
        constituent_count=3,
        cached_sample=3,
        periods=[
            BoardPositionPeriod(
                period=3,
                position_pct=50.0,
                board_avg_pct=40.0,
                rank_low_to_high=2,
                sample=3,
            )
        ],
    )


def test_extreme_payload_shape():
    rbp = {30: [(_result(), _result().periods[1])]}
    payload = extreme_payload(rbp, mode="low")
    assert payload["command"] == "low"
    assert "disclaimer" in payload
    assert "30" in payload["results_by_period"]
    assert payload["results_by_period"]["30"][0]["symbol"] == "600519"
    assert "reference" not in payload  # 未传 board → 不含 reference 字段(向后兼容)


def test_extreme_payload_with_industry_reference():
    """传入 BoardMeta + board_index_result → payload['reference'] 含 industry kind。"""
    from kan.core.models import Board, BoardMeta

    rbp = {30: [(_result(), _result().periods[1])]}
    board_idx = _result(symbol="801080", name="半导体")
    bm = BoardMeta(
        board=Board(code="801080", name="半导体", level=1, size=50),
        index_kline=__import__("pandas").DataFrame(),
        constituents=[], highlight=set(),
    )
    payload = extreme_payload(
        rbp, mode="low",
        board_index_result=board_idx, board_meta=bm,
    )
    assert "reference" in payload
    assert payload["reference"]["kind"] == "industry"
    assert payload["reference"]["symbol"] == "801080"
    assert payload["reference"]["name"] == "半导体"
    # StockScanResult.model_dump 把 periods 也带进 reference · 直接对照查
    assert any(p["period"] == 5 for p in payload["reference"]["periods"])


def test_extreme_payload_with_theme_reference():
    """传入 ThemeMeta → payload['reference']['kind'] = "theme"。"""
    from kan.core.models import Theme, ThemeMeta

    rbp: dict[int, list] = {30: []}
    board_idx = _result(symbol="886108", name="AI应用")
    tm = ThemeMeta(
        theme=Theme(code="886108", name="AI应用", source="ths"),
        index_kline=__import__("pandas").DataFrame(),
        constituents=[], highlight=set(),
    )
    payload = extreme_payload(
        rbp, mode="high",
        board_index_result=board_idx, board_meta=tm,
    )
    assert payload["reference"]["kind"] == "theme"
    assert payload["reference"]["name"] == "AI应用"


def test_extreme_markdown_per_period_sections():
    rbp = {30: [(_result(), _result().periods[1])]}
    md = extreme_markdown(rbp, mode="low")
    assert "## 30 日低点" in md
    assert "| 股票 | 现价 | 30日最低 | 30日最高 | 位置 |" in md
    assert "[3.0%]" in md  # extreme 用 .1f


def test_extreme_markdown_with_industry_reference():
    """md 输出每张表首行注入 🏛️ 板块指数 reference · 阅读器侧也能看到对照锚点。"""
    from kan.core.models import Board, BoardMeta, PeriodResult

    board_idx = _result(
        symbol="801080", name="半导体",
        periods=[PeriodResult(
            period=30, n_low=10000.0, n_high=11000.0,
            position_pct=37.5, at_low=False, at_high=False,
        )],
    )
    rbp = {30: [(_result(), _result().periods[1])]}
    bm = BoardMeta(
        board=Board(code="801080", name="半导体", level=1, size=50),
        index_kline=__import__("pandas").DataFrame(),
        constituents=[], highlight=set(),
    )
    md = extreme_markdown(
        rbp, mode="low",
        board_index_result=board_idx, board_meta=bm,
    )
    # reference 行(table 第一 data row · 在 hits 之前)
    assert "🏛️ 半导体 板块指数" in md
    assert "37.5%" in md  # reference 行的位置 cell 不带方括号
    # hits 行(带 [pct%] 信号)
    assert "[3.0%]" in md


def test_extreme_markdown_empty_hits_with_reference_still_renders():
    """空 results_by_period + reference + 显式 periods → 仍画 reference 表
    (跟终端空 hits 也显示锚点的行为对齐)。"""
    from kan.core.models import Board, BoardMeta, PeriodResult

    board_idx = _result(
        symbol="801080", name="半导体",
        periods=[PeriodResult(
            period=30, n_low=7000.0, n_high=11000.0,
            position_pct=88.5, at_low=False, at_high=False,
        )],
    )
    bm = BoardMeta(
        board=Board(code="801080", name="半导体", level=1, size=50),
        index_kline=__import__("pandas").DataFrame(),
        constituents=[], highlight=set(),
    )
    md = extreme_markdown(
        {}, mode="low",  # 空 results_by_period(没股票触低)
        board_index_result=board_idx, board_meta=bm,
        periods=[30],  # caller 传周期 · 让 md 知道画哪张表
    )
    assert "## 30 日低点 · 0 只触及" in md
    assert "🏛️ 半导体 板块指数" in md
    assert "88.5%" in md


def test_extreme_markdown_with_theme_reference():
    """题材模式 md 输出首行 🎯 题材指数。"""
    from kan.core.models import PeriodResult, Theme, ThemeMeta

    board_idx = _result(
        symbol="886108", name="AI应用",
        periods=[PeriodResult(
            period=60, n_low=900.0, n_high=1100.0,
            position_pct=82.0, at_low=False, at_high=True,
        )],
    )
    rbp: dict[int, list] = {60: []}
    tm = ThemeMeta(
        theme=Theme(code="886108", name="AI应用", source="ths"),
        index_kline=__import__("pandas").DataFrame(),
        constituents=[], highlight=set(),
    )
    md = extreme_markdown(
        rbp, mode="high",
        board_index_result=board_idx, board_meta=tm,
    )
    assert "🎯 AI应用 题材指数" in md
    assert "82.0%" in md


def test_info_payload_shape():
    payload = info_payload(
        _result(), _fake_trend(), volume=None, data_cutoff=date(2026, 5, 21),
        fetched_at="2026-05-21 23:00", stale=False,
    )
    assert payload["command"] == "info"
    assert payload["symbol"] == "600519"
    assert "disclaimer" in payload
    assert payload["trend"]["direction"] == "跌2天"
    assert payload["result"]["low_resonance"] == 1
    assert payload["volume"] is None


def test_info_payload_with_volume():
    payload = info_payload(
        _result(), _fake_trend(),
        volume=VolumeState(ratio=2.3, label="明显放大", window=5),
        data_cutoff=None, fetched_at=None, stale=True,
    )
    assert payload["volume"]["ratio"] == 2.3
    assert payload["volume"]["label"] == "明显放大"


def test_info_payload_with_board_context():
    payload = info_payload(
        _result(), _fake_trend(), volume=None, data_cutoff=date(2026, 5, 21),
        fetched_at=None, stale=False, board_context=_board_context(),
    )
    ctx = payload["board_position_context"]
    assert ctx["industry"] == "食品饮料"
    assert ctx["periods"][0]["rank_low_to_high"] == 2


def test_info_markdown_structure():
    md = info_markdown(_result(), _fake_trend(), volume=None, title="测试详情")
    assert md.startswith("# 测试详情")
    assert "| 周期 | 最低 | 最高 | 位置 |" in md
    assert "跌2天" in md
    assert "低点共振 ×1" in md


def test_info_markdown_with_volume():
    md = info_markdown(
        _result(), _fake_trend(),
        volume=VolumeState(ratio=2.3, label="明显放大", window=5),
        title="t",
    )
    assert "成交量 · 今日是近 5 日均量的 2.3 倍 · 明显放大" in md


def test_info_markdown_with_board_context():
    md = info_markdown(
        _result(), _fake_trend(), volume=None, title="t",
        board_context=_board_context(),
    )
    assert "板块对比 · 申万一级 食品饮料 · 本地样本 3/3" in md
    assert "| 周期 | 本股位置 | 板块均值 | 低到高排名 |" in md
    assert "| 3日 | 50.0% | 40.0% | 2/3 |" in md


def test_trend_payload_shape():
    tr = _fake_trend(
        symbol="600519", name="贵州茅台", current_price=100.0,
        daily_changes=[("2026-05-08", -2.0), ("2026-05-07", -1.0)],
    )
    payload = trend_payload(
        [tr], candle=False, data_cutoff=date(2026, 5, 8),
        fetched_at=None, stale=False,
    )
    assert payload["command"] == "trend"
    assert payload["mode"] == "close"
    assert "disclaimer" in payload
    assert payload["results"][0]["symbol"] == "600519"
    assert payload["results"][0]["daily_changes"][0] == ["2026-05-08", -2.0]


def test_trend_markdown_base_table():
    tr = _fake_trend(
        symbol="600519", name="贵州茅台", current_price=100.0,
        direction="跌2天", streak_pct=-3.0, daily_changes=[],
    )
    md = trend_markdown([tr], title="趋势", latest=None)
    assert md.startswith("# 趋势")
    assert "| 股票 | 现价 | 连续 | 累计 |" in md
    assert "跌2天" in md


def test_trend_markdown_with_latest_date_columns():
    tr = _fake_trend(
        symbol="600519", name="茅台", current_price=100.0,
        direction="跌2天", streak_pct=-3.0,
        daily_changes=[("2026-05-08", 2.5), ("2026-05-07", -1.0)],
    )
    md = trend_markdown([tr], title="t", latest=2)
    assert "05-08" in md      # 日期列头
    assert "+2.50%" in md
    assert "-1.00%" in md


def test_compare_payload_shape():
    payload = compare_payload(
        [_result(), _result(symbol="000858", name="五粮液")], periods=[30],
    )
    assert payload["command"] == "compare"
    assert payload["periods"] == [30]
    assert "disclaimer" in payload
    assert len(payload["results"]) == 2
    assert payload["results"][1]["symbol"] == "000858"


def test_error_payload_find_machine_readable():
    payload = error_payload(
        "find",
        code="data_unavailable",
        message="全市场截面无数据",
        hint="配置 tushare token",
    )
    assert payload["ok"] is False
    assert payload["command"] == "find"
    assert payload["schema_version"]
    assert payload["error"]["code"] == "data_unavailable"
    assert payload["error"]["hint"] == "配置 tushare token"
    assert "候选" in payload["disclaimer"]


def test_code_pool_payload_is_lightweight_find_schema():
    payload = code_pool_payload(
        [("600519", "贵州茅台"), ("000858", "000858")],
        query_time="2026-06-04T12:00:00+08:00",
        pools=["codes:2"],
    )
    assert payload["ok"] is True
    assert payload["command"] == "find"
    assert payload["mode"] == "code_pool"
    assert payload["results"] == [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000858", "name": "000858"},
    ]
    assert payload["stats"]["matched"] == 2
    assert payload["stats"]["data_cutoff"] is None


def test_compare_markdown_transposed():
    md = compare_markdown(
        [_result(), _result(symbol="000858", name="五粮液")], periods=[3],
    )
    assert "# 慢慢看 · 多股对比" in md
    assert "| 指标 | 贵州茅台 600519 | 五粮液 000858 |" in md
    assert "| 现价 | 100.00 | 100.00 |" in md
    assert "| 3日位置 |" in md
    assert "数据截止" in md

"""导出渲染测试 · kan/export.py · markdown / json"""

import json
from datetime import date
from types import SimpleNamespace

from kan.export import (
    OutputFormat,
    compare_markdown,
    compare_payload,
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
from kan.models import PeriodResult, StockScanResult, VolumeState


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


def _fake_trend(**kw):
    defaults = {"streak": -2, "streak_pct": 1.5, "direction": "跌2天"}
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_extreme_payload_shape():
    rbp = {30: [(_result(), _result().periods[1])]}
    payload = extreme_payload(rbp, mode="low")
    assert payload["command"] == "low"
    assert "30" in payload["results_by_period"]
    assert payload["results_by_period"]["30"][0]["symbol"] == "600519"


def test_extreme_markdown_per_period_sections():
    rbp = {30: [(_result(), _result().periods[1])]}
    md = extreme_markdown(rbp, mode="low")
    assert "## 30 日低点" in md
    assert "| 股票 | 现价 | 30日最低 | 30日最高 | 位置 |" in md
    assert "[3.0%]" in md  # extreme 用 .1f


def test_info_payload_shape():
    payload = info_payload(
        _result(), _fake_trend(), volume=None, data_cutoff=date(2026, 5, 21),
        fetched_at="2026-05-21 23:00", stale=False,
    )
    assert payload["command"] == "info"
    assert payload["symbol"] == "600519"
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
    assert len(payload["results"]) == 2
    assert payload["results"][1]["symbol"] == "000858"


def test_compare_markdown_transposed():
    md = compare_markdown(
        [_result(), _result(symbol="000858", name="五粮液")], periods=[3],
    )
    assert "# 慢慢看 · 多股对比" in md
    assert "| 指标 | 600519 贵州茅台 | 000858 五粮液 |" in md
    assert "| 现价 | 100.00 | 100.00 |" in md
    assert "| 3日位置 |" in md
    assert "数据截止" in md

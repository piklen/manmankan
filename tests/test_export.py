"""导出渲染测试 · kan/export.py · markdown / json"""

import json
from datetime import date

from kan.export import OutputFormat, md_table, scan_markdown, scan_payload, to_json
from kan.models import PeriodResult, StockScanResult


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

"""股东逐股双 endpoint 批量编排。"""
from __future__ import annotations

from kan.data import shareholder
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, operation


def test_shareholder_keeps_partial_endpoint_success(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(shareholder, "DATA_DIR", tmp_path)
    monkeypatch.setattr(shareholder, "ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.data.tushare._resolve_config", lambda: ("test-token", "https://example.invalid"))

    def fetch(*, api_name: str, **_kwargs):
        if api_name == "stk_holdernumber":
            return {
                "fields": ["end_date", "holder_num"],
                "items": [["20260331", 1000], ["20251231", 1200]],
            }, None
        return {"fields": [], "items": []}, None

    monkeypatch.setattr("kan.data.tushare._post_tushare_api", fetch)
    reporter = CollectingReporter()

    with operation("find", reporter=reporter) as lifecycle:
        result = shareholder.fetch_shareholder(
            ["600519"],
            max_workers=2,
            lifecycle=lifecycle,
        )

    assert float(result["600519"]["holder_num"]) == 1000
    assert round(float(result["600519"]["holder_chg_pct"]), 2) == -16.67
    progress = [
        event for event in reporter.events
        if event.kind is LifecycleKind.PROGRESS
        and event.message == "拉取候选股股东指标"
    ]
    assert progress[-1].completed == 2
    assert progress[-1].total == 2
    assert any(
        event.kind is LifecycleKind.DEGRADED
        and event.message == "部分候选股股东指标不可用"
        for event in reporter.events
    )

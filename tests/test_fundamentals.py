"""逐股财务披露与缓存；只在 TuShare 请求边界替换外部响应。"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime
from unittest.mock import Mock

import pandas as pd
import pytest

from kan.data import fundamentals
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, operation


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(fundamentals, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fundamentals, "ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.data.tushare._resolve_config", lambda: ("test-token", "https://example.invalid"))
    return tmp_path


def _raw(roe=15.2):
    return pd.DataFrame([
        {"end_date": "20240331", "ann_date": "20240430", "roe": 10.0, "netprofit_yoy": 5.0, "or_yoy": 6.0},
        {"end_date": "20251231", "ann_date": "20260430", "roe": roe, "netprofit_yoy": 8.5, "or_yoy": 12.1},
    ])


def _response(frame: pd.DataFrame):
    return {"fields": list(frame.columns), "items": frame.values.tolist()}, None


class TestFetchFundamentals:
    def test_latest_period_picked(self, _isolate, monkeypatch):
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", lambda **_: _response(_raw()))
        out = fundamentals.fetch_fundamentals(["600519"])
        assert float(out["600519"]["roe"]) == 15.2
        assert out["600519"]["ann_date"] == date(2026, 4, 30)
        assert datetime.fromisoformat(out["600519"]["fetched_at"]).tzinfo == UTC

    def test_latest_disclosure_of_same_report_is_picked(self, _isolate, monkeypatch):
        revised = _raw(roe=16).tail(1).assign(ann_date="20260506")
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", lambda **_: _response(pd.concat([revised, _raw()])))
        row = fundamentals.fetch_fundamentals(["600519"])["600519"]
        assert row["end_date"] == date(2025, 12, 31)
        assert row["ann_date"] == date(2026, 5, 6) and row["roe"] == 16

    def test_no_token_degrades(self, _isolate, monkeypatch):
        monkeypatch.setattr("kan.data.tushare._resolve_config", lambda: ("", "https://example.invalid"))
        assert fundamentals.fetch_fundamentals(["600519"]) == {}

    def test_empty_symbols_no_fetch(self, _isolate, monkeypatch):
        fetch = Mock(side_effect=AssertionError("empty symbols must not request data"))
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", fetch)
        assert fundamentals.fetch_fundamentals([]) == {}
        fetch.assert_not_called()

    def test_cache_reuse_daily_expiry_and_force_refresh(self, _isolate, monkeypatch):
        fetch = Mock(side_effect=[_response(_raw()), _response(_raw(roe=16)), _response(_raw(roe=17))])
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", fetch)
        first = fundamentals.fetch_fundamentals(["600519"])["600519"]
        cached = fundamentals.fetch_fundamentals(["600519"])["600519"]
        assert fetch.call_count == 1 and first["fetched_at"] == cached["fetched_at"]
        cache = _isolate / "fundamentals_600519.parquet"
        old = cache.stat().st_mtime - 25 * 3600
        os.utime(cache, (old, old))
        assert fundamentals.fetch_fundamentals(["600519"])["600519"]["roe"] == 16
        assert fetch.call_count == 2
        assert fundamentals.fetch_fundamentals(["600519"], force=True)["600519"]["roe"] == 17
        assert fetch.call_count == 3

    def test_cache_without_announcement_date_is_refreshed(self, _isolate, monkeypatch):
        fundamentals._normalize(_raw()).drop(columns="ann_date").to_parquet(_isolate / "fundamentals_600519.parquet")
        fetch = Mock(return_value=_response(_raw()))
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", fetch)
        row = fundamentals.fetch_fundamentals(["600519"])["600519"]
        assert row["ann_date"] == date(2026, 4, 30)
        fundamentals.fetch_fundamentals(["600519"])
        fetch.assert_called_once()

    def test_bad_symbol_skipped(self, _isolate, monkeypatch):
        fetch = Mock(side_effect=AssertionError("invalid symbols must not request data"))
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", fetch)
        assert fundamentals.fetch_fundamentals(["bad"]) == {}
        fetch.assert_not_called()

    def test_reports_batch_progress_in_existing_lifecycle(self, _isolate, monkeypatch):
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", lambda **_: _response(_raw()))
        reporter = CollectingReporter()
        with operation("find", reporter=reporter) as lifecycle:
            out = fundamentals.fetch_fundamentals(["600519", "000858"], max_workers=2, lifecycle=lifecycle)
        assert set(out) == {"600519", "000858"}
        progress = [event for event in reporter.events if event.kind is LifecycleKind.PROGRESS and event.message == "拉取候选股财务指标"]
        assert progress[-1].completed == progress[-1].total == 2
        assert len({event.operation_id for event in reporter.events}) == 1

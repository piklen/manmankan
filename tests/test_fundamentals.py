"""逐股财务披露、24小时缓存与手动刷新。

隔离 DATA_DIR 防污染真实缓存 (仿 test_metrics)· mock adapter _fetch_tushare_fundamentals。
"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime
from unittest.mock import Mock

import pandas as pd
import pytest

from kan.data import fundamentals
from kan.data.provider_contracts import ProviderFetchResult
from kan.infra.lifecycle import CollectingReporter, LifecycleKind, operation


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(fundamentals, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fundamentals, "ensure_dirs", lambda: None)
    return tmp_path


def _raw(roe=15.2):
    # fina_indicator 多报告期 (乱序)· 编排取最新 end_date
    return pd.DataFrame([
        {"end_date": "20240331", "ann_date": "20240430", "roe": 10.0, "netprofit_yoy": 5.0, "or_yoy": 6.0},
        {"end_date": "20251231", "ann_date": "20260430", "roe": roe, "netprofit_yoy": 8.5, "or_yoy": 12.1},
    ])


class TestFetchFundamentals:
    def test_latest_period_picked(self, _isolate, monkeypatch):
        monkeypatch.setattr(
            "kan.data.fundamentals._fetch_tushare_fundamentals", lambda s: _raw(),
        )
        out = fundamentals.fetch_fundamentals(["600519"])
        assert "600519" in out
        assert float(out["600519"]["roe"]) == 15.2  # 最新一期 20251231
        assert out["600519"]["ann_date"] == date(2026, 4, 30)
        assert datetime.fromisoformat(out["600519"]["fetched_at"]).tzinfo == UTC

    def test_latest_disclosure_of_same_report_is_picked(self, _isolate, monkeypatch):
        revised = _raw(roe=16).tail(1).assign(ann_date="20260506")
        monkeypatch.setattr(fundamentals, "_fetch_tushare_fundamentals", lambda s: pd.concat([revised, _raw()]))
        row = fundamentals.fetch_fundamentals(["600519"])["600519"]
        assert row["end_date"] == date(2025, 12, 31)
        assert row["ann_date"] == date(2026, 5, 6) and row["roe"] == 16

    def test_no_token_degrades(self, _isolate, monkeypatch):
        monkeypatch.setattr(
            "kan.data.fundamentals._fetch_tushare_fundamentals", lambda s: None,
        )
        assert fundamentals.fetch_fundamentals(["600519"]) == {}

    def test_empty_symbols_no_fetch(self, _isolate, monkeypatch):
        calls = {"n": 0}

        def _f(s):
            calls["n"] += 1
            return _raw()
        monkeypatch.setattr("kan.data.fundamentals._fetch_tushare_fundamentals", _f)
        assert fundamentals.fetch_fundamentals([]) == {}
        assert calls["n"] == 0

    def test_cache_reuse_daily_expiry_and_force_refresh(self, _isolate, monkeypatch):
        fetch = Mock(side_effect=[_raw(), _raw(roe=16), _raw(roe=17)])
        monkeypatch.setattr(fundamentals, "_fetch_tushare_fundamentals", fetch)
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

    def test_old_cache_without_announcement_date_is_refreshed(self, _isolate, monkeypatch):
        fundamentals._normalize(_raw()).drop(columns="ann_date").to_parquet(_isolate / "fundamentals_600519.parquet")
        fetch = Mock(return_value=_raw())
        monkeypatch.setattr(fundamentals, "_fetch_tushare_fundamentals", fetch)
        row = fundamentals.fetch_fundamentals(["600519"])["600519"]
        assert row["ann_date"] == date(2026, 4, 30)
        fundamentals.fetch_fundamentals(["600519"])
        fetch.assert_called_once()

    def test_bad_symbol_skipped(self, _isolate, monkeypatch):
        monkeypatch.setattr(
            "kan.data.fundamentals._fetch_tushare_fundamentals", lambda s: _raw(),
        )
        assert fundamentals.fetch_fundamentals(["bad"]) == {}  # 非 6 位 → 跳

    def test_reports_batch_progress_in_existing_lifecycle(self, _isolate, monkeypatch):
        monkeypatch.setattr(
            fundamentals,
            "_fetch_tushare_fundamentals_detailed",
            lambda _symbol: ProviderFetchResult.succeeded(_raw()),
        )
        reporter = CollectingReporter()

        with operation("find", reporter=reporter) as lifecycle:
            out = fundamentals.fetch_fundamentals(
                ["600519", "000858"],
                max_workers=2,
                lifecycle=lifecycle,
            )

        assert set(out) == {"600519", "000858"}
        progress = [
            event for event in reporter.events
            if event.kind is LifecycleKind.PROGRESS
            and event.message == "拉取候选股财务指标"
        ]
        assert progress[-1].completed == 2
        assert progress[-1].total == 2
        assert len({event.operation_id for event in reporter.events}) == 1

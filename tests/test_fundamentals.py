"""kan/data/fundamentals.py · 逐股财务指标拉取 + 90d 缓存 + 降级 (整合-1)。

隔离 DATA_DIR 防污染真实缓存 (仿 test_metrics)· mock adapter _fetch_tushare_fundamentals。
"""
from __future__ import annotations

import pandas as pd
import pytest

from kan.data import fundamentals


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(fundamentals, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fundamentals, "ensure_dirs", lambda: None)
    return tmp_path


def _raw(roe=15.2):
    # fina_indicator 多报告期 (乱序)· 编排取最新 end_date
    return pd.DataFrame([
        {"end_date": "20240331", "roe": 10.0, "netprofit_yoy": 5.0, "or_yoy": 6.0},
        {"end_date": "20251231", "roe": roe, "netprofit_yoy": 8.5, "or_yoy": 12.1},
    ])


class TestFetchFundamentals:
    def test_latest_period_picked(self, _isolate, monkeypatch):
        monkeypatch.setattr(
            "kan.data.fundamentals._fetch_tushare_fundamentals", lambda s: _raw(),
        )
        out = fundamentals.fetch_fundamentals(["600519"])
        assert "600519" in out
        assert float(out["600519"]["roe"]) == 15.2  # 最新一期 20251231

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

    def test_cache_reused_within_ttl(self, _isolate, monkeypatch):
        calls = {"n": 0}

        def _f(s):
            calls["n"] += 1
            return _raw()
        monkeypatch.setattr("kan.data.fundamentals._fetch_tushare_fundamentals", _f)
        fundamentals.fetch_fundamentals(["600519"])
        fundamentals.fetch_fundamentals(["600519"])
        assert calls["n"] == 1  # 第二次走 90d 缓存

    def test_bad_symbol_skipped(self, _isolate, monkeypatch):
        monkeypatch.setattr(
            "kan.data.fundamentals._fetch_tushare_fundamentals", lambda s: _raw(),
        )
        assert fundamentals.fetch_fundamentals(["bad"]) == {}  # 非 6 位 → 跳

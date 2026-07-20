"""kan/data/universe.py · fetch_all_stocks (地基-3 · AllStocksSet 截面池原料)。

mock _fetch_tushare_stock_basic_all + 隔离 DATA_DIR cache (仿 test_industry_map)。
"""
from __future__ import annotations

import json
import os
import time

import pandas as pd
import pytest

from kan.data import universe


class TestFetchAllStocks:
    @pytest.fixture
    def temp_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(universe, "DATA_DIR", tmp_path)
        monkeypatch.setattr(universe, "ensure_dirs", lambda: None)
        monkeypatch.setattr(universe, "_MIN_COMPLETE_STOCKS", 1)
        monkeypatch.setattr(universe, "_MIN_COMPLETE_BSE_STOCKS", 0)
        return tmp_path

    def _df(self, rows):
        return pd.DataFrame(rows)

    def test_no_token_empty(self, temp_env, monkeypatch):
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: None,
        )
        assert universe.fetch_all_stocks() == []

    def test_adapter_uses_official_stock_basic_request(self, temp_env, monkeypatch):
        captured = {}

        class _Breaker:
            def is_down(self, _key):
                return False

            def record(self, _key, *, ok):
                captured["breaker_ok"] = ok

        def fake_post(**kwargs):
            captured["params"] = kwargs["params"]
            return ({
                "fields": [
                    "ts_code", "symbol", "name", "market", "exchange", "list_status",
                ],
                "items": [
                    ["600519.SH", "600519", "贵州茅台", "主板", "SSE", "L"],
                    ["920964.BJ", "920964", "润农节水", "北交所", "BSE", "L"],
                ],
            }, None)

        monkeypatch.setattr("kan.data.tushare._resolve_config", lambda: ("token", "https://x"))
        monkeypatch.setattr("kan.data.tushare._post_tushare_api", fake_post)
        monkeypatch.setattr("kan.infra.circuit_breaker.get_breaker", lambda: _Breaker())

        df = universe._fetch_tushare_stock_basic_all()

        assert df is not None and len(df) == 2
        assert captured["params"] == {"list_status": "L"}
        assert captured["breaker_ok"] is True

    def test_adapter_rejects_implausibly_small_stock_basic_response(
        self, temp_env, monkeypatch,
    ):
        class _Breaker:
            def is_down(self, _key):
                return False

            def record(self, _key, *, ok):
                del ok

        monkeypatch.setattr("kan.data.tushare._resolve_config", lambda: ("token", "https://x"))
        monkeypatch.setattr(
            "kan.data.tushare._post_tushare_api",
            lambda **_kw: ({
                "fields": ["ts_code", "symbol", "name", "market", "list_status"],
                "items": [["600519.SH", "600519", "贵州茅台", "主板", "L"]],
            }, None),
        )
        monkeypatch.setattr("kan.infra.circuit_breaker.get_breaker", lambda: _Breaker())
        monkeypatch.setattr(universe, "_MIN_COMPLETE_STOCKS", 2)

        with pytest.raises(
            universe.TushareDataContractError,
            match=r"仅返回 1 只.*校验下界 2",
        ):
            universe._fetch_tushare_stock_basic_all()

    def test_includes_bse(self, temp_env, monkeypatch):
        """--all 是字面全市场，北交所 920xxx 新段与旧代码都保留。"""
        df = self._df([
            {"symbol": "600519", "name": "贵州茅台", "market": "主板"},
            {"symbol": "300750", "name": "宁德时代", "market": "创业板"},
            {"symbol": "688981", "name": "中芯国际", "market": "科创板"},
            {"symbol": "920964", "name": "润农节水", "market": "北交所"},
            {"symbol": "830799", "name": "旧北交所", "market": "北交所"},
        ])
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: df.copy(),
        )
        codes = [c for c, _ in universe.fetch_all_stocks()]
        assert "600519" in codes
        assert "300750" in codes
        assert "688981" in codes
        assert "920964" in codes, "北交所 (920xxx) 应被保留"
        assert "830799" in codes, "北交所 (旧 830xxx) 应被保留"

    def test_keeps_st(self, temp_env, monkeypatch):
        """含 ST · 排不排交给用户 --exclude-st (PRD §9)。"""
        df = self._df([
            {"symbol": "600519", "name": "贵州茅台", "market": "主板"},
            {"symbol": "000111", "name": "*ST 测试", "market": "主板"},
        ])
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: df.copy(),
        )
        codes = [c for c, _ in universe.fetch_all_stocks()]
        assert "000111" in codes, "ST 应保留 (用户自己 --exclude-st 决定)"

    def test_builds_and_caches(self, temp_env, monkeypatch):
        df = self._df([{"symbol": "600519", "name": "贵州茅台", "market": "主板"}])
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: df.copy(),
        )
        pairs = universe.fetch_all_stocks()
        assert pairs == [("600519", "贵州茅台")]
        assert (temp_env / "all_stocks.json").exists()

    def test_cache_hit_skips_fetch(self, temp_env, monkeypatch):
        df = self._df([{"symbol": "600519", "name": "贵州茅台", "market": "主板"}])
        calls = {"n": 0}

        def _f():
            calls["n"] += 1
            return df.copy()
        monkeypatch.setattr("kan.data.universe._fetch_tushare_stock_basic_all", _f)
        universe.fetch_all_stocks()
        universe.fetch_all_stocks()
        assert calls["n"] == 1, "cache 命中不应重复 fetch"

    def test_truncated_cache_refetches(self, temp_env, monkeypatch):
        """旧版第一页缓存不能在 24 小时内继续冒充全市场。"""
        monkeypatch.setattr(universe, "_MIN_COMPLETE_STOCKS", 2)
        cache = temp_env / "all_stocks.json"
        cache.write_text(json.dumps([["600519", "贵州茅台"]]), encoding="utf-8")
        df = self._df([
            {"symbol": "600519", "name": "贵州茅台", "market": "主板"},
            {"symbol": "920964", "name": "润农节水", "market": "北交所"},
        ])
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: df.copy(),
        )

        assert universe.fetch_all_stocks() == [
            ("600519", "贵州茅台"),
            ("920964", "润农节水"),
        ]

    def test_legacy_cache_without_bse_refetches(self, temp_env, monkeypatch):
        """旧版即使行数足够，也不能继续沿用“全市场但排北交所”的语义。"""
        monkeypatch.setattr(universe, "_MIN_COMPLETE_BSE_STOCKS", 1)
        cache = temp_env / "all_stocks.json"
        cache.write_text(json.dumps([["600519", "贵州茅台"]]), encoding="utf-8")
        df = self._df([
            {"symbol": "600519", "name": "贵州茅台", "market": "主板"},
            {"symbol": "920964", "name": "润农节水", "market": "北交所"},
        ])
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: df.copy(),
        )

        assert universe.fetch_all_stocks()[-1] == ("920964", "润农节水")

    def test_corrupted_cache_refetches(self, temp_env, monkeypatch):
        cache = temp_env / "all_stocks.json"
        cache.write_text("{ not valid json", encoding="utf-8")
        df = self._df([{"symbol": "600519", "name": "贵州茅台", "market": "主板"}])
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: df.copy(),
        )
        assert universe.fetch_all_stocks() == [("600519", "贵州茅台")]

    def test_stale_fallback_on_failure(self, temp_env, monkeypatch):
        cache = temp_env / "all_stocks.json"
        cache.write_text(json.dumps([["600519", "贵州茅台"]]), encoding="utf-8")
        old = time.time() - 100000  # 过期 (> TTL)
        os.utime(cache, (old, old))
        monkeypatch.setattr(
            "kan.data.universe._fetch_tushare_stock_basic_all", lambda: None,
        )
        # 拉取失败 → 退化陈旧 cache (而非空)
        assert universe.fetch_all_stocks() == [("600519", "贵州茅台")]

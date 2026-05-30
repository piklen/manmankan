"""kan/data/industry_map.py · 申万一级反查映射 (地基-3 · 行业中位用)。"""
from __future__ import annotations

import json
import os
import time

import pandas as pd
import pytest

from kan.data import industry_map


class TestFetchSwL1Map:
    @pytest.fixture
    def temp_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(industry_map, "DATA_DIR", tmp_path)
        monkeypatch.setattr(industry_map, "ensure_dirs", lambda: None)
        return tmp_path

    def test_no_token_empty(self, temp_env, monkeypatch):
        monkeypatch.setattr("kan.data.tushare._fetch_tushare_sw_l1_members", lambda: None)
        assert industry_map.fetch_sw_l1_map() == {}

    def test_builds_and_caches(self, temp_env, monkeypatch):
        df = pd.DataFrame({
            "symbol": ["600519", "000001"], "l1_name": ["食品饮料", "银行"],
        })
        monkeypatch.setattr(
            "kan.data.tushare._fetch_tushare_sw_l1_members", lambda: df.copy(),
        )
        m = industry_map.fetch_sw_l1_map()
        assert m["600519"] == "食品饮料"
        assert m["000001"] == "银行"
        assert (temp_env / "sw_l1_map.json").exists()

    def test_cache_hit_skips_fetch(self, temp_env, monkeypatch):
        df = pd.DataFrame({"symbol": ["600519"], "l1_name": ["食品饮料"]})
        calls = {"n": 0}

        def _f():
            calls["n"] += 1
            return df.copy()
        monkeypatch.setattr("kan.data.tushare._fetch_tushare_sw_l1_members", _f)
        industry_map.fetch_sw_l1_map()
        industry_map.fetch_sw_l1_map()
        assert calls["n"] == 1

    def test_stale_fallback_on_failure(self, temp_env, monkeypatch):
        cache = temp_env / "sw_l1_map.json"
        cache.write_text(json.dumps({"600519": "食品饮料"}), encoding="utf-8")
        old = time.time() - 100000  # 让 cache 过期 (> TTL)
        os.utime(cache, (old, old))
        monkeypatch.setattr("kan.data.tushare._fetch_tushare_sw_l1_members", lambda: None)
        # 拉取失败 → 退化陈旧 cache (而非空)
        assert industry_map.fetch_sw_l1_map() == {"600519": "食品饮料"}

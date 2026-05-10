"""paths.py 单元测试 · is_stock_names_cache_fresh + NAMES_CACHE_MAX_AGE_DAYS

放在 paths.py 而非 watchlist.py 的目的：让 CLI 在 import 重模块前先决策（参见
v0.0.2 冷启动延迟修复）。本测试守护：mtime 三个边界条件 + 文件缺失。
"""

import os
from datetime import datetime, timedelta

import pytest

from kan import paths


@pytest.fixture
def temp_cache_path(tmp_path, monkeypatch):
    cache = tmp_path / "stock_names.json"
    monkeypatch.setattr(paths, "STOCK_NAMES_CACHE", cache)
    return cache


def test_cache_missing_returns_false(temp_cache_path):
    """缓存文件不存在 → False"""
    assert paths.is_stock_names_cache_fresh() is False


def test_cache_recent_returns_true(temp_cache_path):
    """刚写入的缓存 (mtime ~ now) → True"""
    temp_cache_path.write_text("{}")
    assert paths.is_stock_names_cache_fresh() is True


def test_cache_stale_returns_false(temp_cache_path):
    """缓存 mtime ≥ NAMES_CACHE_MAX_AGE_DAYS → False"""
    temp_cache_path.write_text("{}")
    stale_ts = (
        datetime.now() - timedelta(days=paths.NAMES_CACHE_MAX_AGE_DAYS + 1)
    ).timestamp()
    os.utime(temp_cache_path, (stale_ts, stale_ts))
    assert paths.is_stock_names_cache_fresh() is False


def test_cache_at_boundary_returns_true(temp_cache_path):
    """缓存 mtime = NAMES_CACHE_MAX_AGE_DAYS - 1 天前 → True (边界守护)"""
    temp_cache_path.write_text("{}")
    boundary_ts = (
        datetime.now() - timedelta(days=paths.NAMES_CACHE_MAX_AGE_DAYS - 1)
    ).timestamp()
    os.utime(temp_cache_path, (boundary_ts, boundary_ts))
    assert paths.is_stock_names_cache_fresh() is True

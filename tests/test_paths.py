"""paths.py 单元测试 · is_stock_names_cache_fresh + NAMES_CACHE_MAX_AGE_DAYS

放在 paths.py 而非 watchlist.py 的目的：让 CLI 在 import 重模块前先决策（参见
历史背景冷启动延迟修复）。本测试守护：mtime 三个边界条件 + 文件缺失。
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import pytest

from kan.storage import paths


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


# ── atomic_write_parquet · crash-safe parquet persistence ──────────────


def test_atomic_write_parquet_basic(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    target = tmp_path / "test.parquet"
    paths.atomic_write_parquet(df, target)
    assert target.exists()
    loaded = pd.read_parquet(target)
    assert len(loaded) == 2
    assert list(loaded["a"]) == [1, 2]


def test_atomic_write_parquet_overwrites_existing(tmp_path):
    target = tmp_path / "test.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(target)
    paths.atomic_write_parquet(pd.DataFrame({"a": [99]}), target)
    assert pd.read_parquet(target)["a"].iloc[0] == 99


def test_atomic_write_parquet_preserves_private_schema_metadata(tmp_path):
    import pyarrow.parquet as pq

    target = tmp_path / "test.parquet"
    paths.atomic_write_parquet(
        pd.DataFrame({"a": [1]}),
        target,
        metadata={"kan.requested_days": "180"},
    )

    assert pd.read_parquet(target).columns.tolist() == ["a"]
    assert pq.read_metadata(target).metadata[b"kan.requested_days"] == b"180"


def test_atomic_write_parquet_concurrent_metadata_writes_are_self_consistent(tmp_path):
    import pyarrow.parquet as pq

    target = tmp_path / "test.parquet"

    def write(value: int) -> None:
        paths.atomic_write_parquet(
            pd.DataFrame({"value": [value]}),
            target,
            metadata={"kan.requested_days": str(value)},
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(write, range(60)))

    stored = int(pd.read_parquet(target)["value"].iloc[0])
    requested = int(pq.read_metadata(target).metadata[b"kan.requested_days"])
    assert requested == stored
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_parquet_interrupt_keeps_old(tmp_path, monkeypatch):
    """mock os.replace 抛异常 · 旧文件保留且唯一 tmp 被清理。"""
    target = tmp_path / "test.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(target)
    original = pd.read_parquet(target)["a"].iloc[0]

    def boom(*a, **kw):
        raise OSError("simulated interrupt")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(OSError, match="simulated"):
        paths.atomic_write_parquet(pd.DataFrame({"a": [99]}), target)

    assert pd.read_parquet(target)["a"].iloc[0] == original
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_json_cleans_unique_temp_on_serialization_error(tmp_path):
    target = tmp_path / "snapshot.json"

    with pytest.raises(TypeError):
        paths.atomic_write_json(target, object())

    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_json_handles_concurrent_writers(tmp_path):
    target = tmp_path / "snapshot.json"

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(
            lambda value: paths.atomic_write_json(target, {"value": value}),
            range(30),
        ))

    assert json.loads(target.read_text())["value"] in range(30)
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_boards_dir_under_base(monkeypatch, tmp_path):
    import importlib

    from kan.storage import paths

    with monkeypatch.context() as scoped:
        scoped.setenv("XDG_DATA_HOME", str(tmp_path))
        importlib.reload(paths)
        assert tmp_path / "kan" / "boards" == paths.BOARDS_DIR
        paths.ensure_dirs()
        assert paths.BOARDS_DIR.is_dir()

    importlib.reload(paths)  # 环境恢复后再复位模块常量，防污染后续测试

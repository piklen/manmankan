"""trading_calendar.py 6 case production 故障模式覆盖 (架-5 + 架-2 + 安-1/2/3/6 + CR-3).

之前 test_data_freshness.py 用 fixture monkeypatch _fetch_from_akshare 直接返
准备好的 dataset · 跳过 production fail path (_fetch_from_akshare 0 覆盖率 +
sanity check 0 覆盖率 + chmod 失败路径 0 覆盖率)。

本 file 强制走 production path · 验证 fail-soft 降级行为不抛 RuntimeError。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from kan import trading_calendar as tc


@pytest.fixture(autouse=True)
def reset_memo():
    """每个 test 前后清空 memo + 锁 · 避免污染。"""
    tc.clear_memo()
    yield
    tc.clear_memo()


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """临时 cache file · 防污染真实 ~/.local/share/kan/。"""
    cache_path = tmp_path / "trade_dates.json"
    monkeypatch.setattr(tc, "TRADE_DATES_CACHE", cache_path)
    return cache_path


def _make_valid_dates(start_year: int = 2000) -> set[date]:
    """生成 sanity check 通过的 trade_dates set (所有 weekday in 2000~today+30)."""
    today = datetime.now().date()
    dates: set[date] = set()
    d = date(start_year, 1, 1)
    end = today + timedelta(days=30)
    while d <= end:
        if d.weekday() < 5:
            dates.add(d)
        d += timedelta(days=1)
    return dates


# ─────────────── Case 1: akshare raise (架-2 fail-soft) ───────────────
def test_akshare_raise_falls_back_to_empty_set(tmp_cache, capsys, monkeypatch):
    """架-2: akshare 抛 RuntimeError → get_trade_dates 返空 set · 不再 raise."""
    monkeypatch.setattr(
        tc, "_fetch_from_akshare",
        MagicMock(side_effect=RuntimeError("akshare 拉取失败: HTTPError 503")),
    )

    result = tc.get_trade_dates()

    assert result == set(), "akshare 抛错应降级到空 set"
    captured = capsys.readouterr()
    assert "交易日历不可用" in captured.err
    assert "weekday 启发式" in captured.err


def test_latest_trade_date_uses_weekday_heuristic_when_empty(
    tmp_cache, capsys, monkeypatch
):
    """架-2: trade_days 空时 latest_trade_date 退化 weekday 启发式 · 不抛 RuntimeError."""
    monkeypatch.setattr(
        tc, "_fetch_from_akshare",
        MagicMock(side_effect=RuntimeError("network down")),
    )

    # 2026-05-12 是周二 · 16:00 (after DATA_AVAILABLE_AFTER 15:30) · weekday
    result = tc.latest_trade_date(as_of=datetime(2026, 5, 12, 16, 0))

    assert result == date(2026, 5, 12), "工作日盘后应返今日 (weekday 启发式)"


# ─────────────── Case 2: akshare 返空 DataFrame (安-3) ───────────────
def test_akshare_returns_empty_dataframe_triggers_failure(monkeypatch):
    """安-3: akshare 返空 DataFrame 应被 _fetch_from_akshare 转 RuntimeError."""
    empty_df = pd.DataFrame()
    mock_ak = MagicMock()
    mock_ak.tool_trade_date_hist_sina.return_value = empty_df
    monkeypatch.setitem(sys.modules, "akshare", mock_ak)

    with pytest.raises(RuntimeError, match="返回空"):
        tc._fetch_from_akshare()


# ─────────────── Case 3: akshare 返脏 (sanity 失败 · 安-3) ───────────────
def test_akshare_returns_dirty_data_triggers_sanity_failure(monkeypatch, capsys):
    """安-3: akshare 返回值 count 过少 (5 个 dates) 应触发 sanity check 失败."""
    dirty_df = pd.DataFrame({
        "trade_date": [
            "2026-05-01", "2026-05-02", "2026-05-03",
            "2026-05-04", "2026-05-05",
        ]
    })
    mock_ak = MagicMock()
    mock_ak.tool_trade_date_hist_sina.return_value = dirty_df
    monkeypatch.setitem(sys.modules, "akshare", mock_ak)

    with pytest.raises(RuntimeError, match="sanity 失败"):
        tc._fetch_from_akshare()

    captured = capsys.readouterr()
    assert "count=5" in captured.err
    assert "太少" in captured.err


# ─────────────── Case 4: cache 损坏 (JSONDecodeError · 安-6) ───────────────
def test_corrupt_cache_triggers_refetch(tmp_cache, capsys):
    """安-6: cache JSONDecodeError 应被缩 except 范围 + stderr warn + 返 None."""
    tmp_cache.write_text("{not valid json", encoding="utf-8")

    result = tc._read_cache()

    assert result is None
    captured = capsys.readouterr()
    assert "trade_dates.json 读取失败" in captured.err
    assert "JSONDecodeError" in captured.err


# ─────────────── Case 5: cache TTL 过期 (重拉) ───────────────
def test_expired_cache_returns_none(tmp_cache):
    """TTL 过期 (mtime > 7 天) 应返 None 触发重拉."""
    valid_dates = _make_valid_dates()
    payload = sorted(d.isoformat() for d in valid_dates)
    tmp_cache.write_text(json.dumps(payload), encoding="utf-8")

    # 改 mtime 到 8 天前 (超 TTL_DAYS=7)
    old_time = (datetime.now() - timedelta(days=8)).timestamp()
    os.utime(tmp_cache, (old_time, old_time))

    result = tc._read_cache()
    assert result is None, "TTL 过期应返 None 触发重拉"


# ─────────────── Case 6: chmod 失败 → stderr warn (安-2) ───────────────
def test_chmod_failure_warns_but_does_not_crash(tmp_cache, capsys, monkeypatch):
    """安-2: chmod 0o600 失败不再静默 · stderr warn + 继续 (不抛)."""
    valid_dates = _make_valid_dates()

    real_chmod = Path.chmod

    def mock_chmod(self, mode):
        # 仅 TRADE_DATES_CACHE 这个 file 才抛 · ensure_dirs() 的 dir chmod 不受影响
        if self.name == "trade_dates.json":
            raise OSError("Operation not permitted (mock for 安-2 test)")
        return real_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", mock_chmod)

    # 不应抛
    tc._write_cache(valid_dates)

    captured = capsys.readouterr()
    assert "chmod 失败" in captured.err


# ─────────────── 加分: sanity check 三 invariant 独立测试 ───────────────
class TestSanityCheck:
    """安-1 三 invariant 边界 case · 不依赖 akshare / file."""

    def test_passes_with_valid_dates(self, capsys):
        valid = _make_valid_dates()
        assert tc._sanity_check_dates(valid, context="test") is True
        # 不输出 stderr (passing case)
        assert capsys.readouterr().err == ""

    def test_fails_when_count_too_low(self, capsys):
        few = {date(2020, 1, d) for d in range(1, 30)}  # 仅 ~29 天
        assert tc._sanity_check_dates(few, context="test") is False
        assert "count=29" in capsys.readouterr().err

    def test_fails_when_min_year_too_recent(self, capsys):
        # min year = 2015 (>= SANITY_MAX_YEAR_MIN=2010) · count 用 weekend 凑够
        # 让 count > 5000 先过 · year invariant 才能被触发
        d = date(2015, 1, 1)
        end = date(2035, 12, 31)  # 21 年 ≈ 7665 days (含周末)
        dates: set[date] = set()
        while d <= end:
            dates.add(d)  # 含周末 · 仅测 sanity function (不要求真实交易日)
            d += timedelta(days=1)
        assert len(dates) > 5000, "前置: count 应过 sanity"
        assert tc._sanity_check_dates(dates, context="test") is False
        assert "最早日期" in capsys.readouterr().err

    def test_fails_when_max_date_too_old(self, capsys, monkeypatch):
        # max date < today - 30
        old_dates = _make_valid_dates(start_year=2000)
        # 删掉 today-60 之后所有 dates · 让 max = today - 60
        cutoff = datetime.now().date() - timedelta(days=60)
        old_dates = {d for d in old_dates if d <= cutoff}
        assert tc._sanity_check_dates(old_dates, context="test") is False
        assert "最新日期" in capsys.readouterr().err


# ─────────────── 架-4: env var KAN_DATA_AVAIL_OFFSET_MIN override ───────────────
class TestDataAvailableEnvVar:
    """架-4 v0.0.4.7: 跨时区用户自救 · env var 偏移 DATA_AVAILABLE_AFTER."""

    def test_default_is_15_30(self, monkeypatch):
        from datetime import time
        monkeypatch.delenv("KAN_DATA_AVAIL_OFFSET_MIN", raising=False)
        assert tc._resolve_data_available_after() == time(15, 30)

    def test_offset_60_pushes_to_16_00(self, monkeypatch):
        from datetime import time
        monkeypatch.setenv("KAN_DATA_AVAIL_OFFSET_MIN", "60")
        assert tc._resolve_data_available_after() == time(16, 0)

    def test_offset_510_pushes_to_23_30_wsl2_utc(self, monkeypatch):
        """WSL2 UTC 场景: 中国 23:30 北京时间 = UTC 15:30 · 用户设 +510 min."""
        from datetime import time
        monkeypatch.setenv("KAN_DATA_AVAIL_OFFSET_MIN", "510")
        assert tc._resolve_data_available_after() == time(23, 30)

    def test_invalid_value_falls_back_to_default(self, monkeypatch):
        from datetime import time
        monkeypatch.setenv("KAN_DATA_AVAIL_OFFSET_MIN", "not-a-number")
        assert tc._resolve_data_available_after() == time(15, 30)

    def test_out_of_range_value_falls_back(self, monkeypatch):
        """24h 越界 (e.g. 2000 min) 应 fallback."""
        from datetime import time
        monkeypatch.setenv("KAN_DATA_AVAIL_OFFSET_MIN", "2000")
        assert tc._resolve_data_available_after() == time(15, 30)


# ─────────────── 加分: CR-3 double-checked locking 行为 ───────────────
def test_memo_thread_safety_under_concurrent_first_call(tmp_cache, monkeypatch):
    """CR-3: get_trade_dates 多线程并发首调 · _fetch_from_akshare 只 fire 一次."""
    valid = _make_valid_dates()
    call_count = {"n": 0}

    def fake_fetch():
        call_count["n"] += 1
        return valid

    monkeypatch.setattr(tc, "_fetch_from_akshare", fake_fetch)

    barrier = threading.Barrier(5)
    results: list[set[date]] = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()  # 5 thread 同时冲 get_trade_dates
        r = tc.get_trade_dates()
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 5 thread 都返回相同 set
    assert all(r == valid for r in results)
    # _fetch_from_akshare 只调一次 (double-checked locking)
    assert call_count["n"] == 1, f"应只调 1 次 akshare · 实际 {call_count['n']} 次"

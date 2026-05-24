"""kan.data.theme_leaderboard 单元测试 · v0.0.5.7。

覆盖:
- _resolve_parallel:env / 默认 / clamp
- sort_leaderboard:排序口径 + up/down filter
- load_theme_leaderboard:并行编排 + 失败容忍 + candle 透传
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from kan.core.models import Theme
from kan.core.scanner import TrendResult
from kan.data import theme_leaderboard
from kan.data.boards import ThemeDataUnavailableError


@pytest.fixture(autouse=True)
def _mock_adata(monkeypatch):
    monkeypatch.setitem(sys.modules, "adata", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock.market", MagicMock())


# ── _resolve_parallel ─────────────────────────────────────────────────


def test_resolve_parallel_default(monkeypatch):
    monkeypatch.delenv("KAN_THEME_TOP_PARALLEL", raising=False)
    assert theme_leaderboard._resolve_parallel(None) == 16


def test_resolve_parallel_explicit():
    assert theme_leaderboard._resolve_parallel(8) == 8


def test_resolve_parallel_env(monkeypatch):
    monkeypatch.setenv("KAN_THEME_TOP_PARALLEL", "24")
    assert theme_leaderboard._resolve_parallel(None) == 24


def test_resolve_parallel_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("KAN_THEME_TOP_PARALLEL", "not-a-number")
    assert theme_leaderboard._resolve_parallel(None) == 16


def test_resolve_parallel_clamp_low():
    assert theme_leaderboard._resolve_parallel(0) == 1


def test_resolve_parallel_clamp_high():
    assert theme_leaderboard._resolve_parallel(99) == 32


# ── sort_leaderboard ──────────────────────────────────────────────────


def _make_tr(symbol, name, streak, streak_pct):
    return TrendResult(
        symbol=symbol, name=name, current_price=100.0,
        streak=streak, streak_pct=streak_pct, daily_changes=[],
    )


def test_sort_streak_abs_desc():
    results = [
        _make_tr("A", "甲", 3, 5.0),
        _make_tr("B", "乙", -5, -10.0),
        _make_tr("C", "丙", 7, 12.0),
    ]
    sorted_ = theme_leaderboard.sort_leaderboard(results)
    assert [r.name for r in sorted_] == ["丙", "乙", "甲"]


def test_sort_tiebreak_by_pct_abs():
    results = [
        _make_tr("A", "甲", 5, 3.0),
        _make_tr("B", "乙", 5, 15.0),
        _make_tr("C", "丙", -5, -10.0),
    ]
    sorted_ = theme_leaderboard.sort_leaderboard(results)
    # streak abs 同 5 时 · pct abs 大的在前
    assert [r.name for r in sorted_] == ["乙", "丙", "甲"]


def test_filter_up_keeps_only_long_rises():
    results = [
        _make_tr("A", "甲", 5, 10.0),
        _make_tr("B", "乙", 2, 3.0),
        _make_tr("C", "丙", -4, -8.0),
        _make_tr("D", "丁", 4, 7.0),
    ]
    sorted_ = theme_leaderboard.sort_leaderboard(results, up_filter=3)
    assert [r.name for r in sorted_] == ["甲", "丁"]


def test_filter_down_keeps_only_long_falls():
    results = [
        _make_tr("A", "甲", -6, -12.0),
        _make_tr("B", "乙", -2, -3.0),
        _make_tr("C", "丙", 4, 8.0),
        _make_tr("D", "丁", -4, -7.0),
    ]
    sorted_ = theme_leaderboard.sort_leaderboard(results, down_filter=3)
    assert [r.name for r in sorted_] == ["甲", "丁"]


def test_filter_up_excludes_down():
    """up_filter 优先 · down_filter 不生效(单边语义)。"""
    results = [
        _make_tr("A", "甲", 5, 10.0),
        _make_tr("B", "乙", -5, -10.0),
    ]
    sorted_ = theme_leaderboard.sort_leaderboard(
        results, up_filter=3, down_filter=3,
    )
    assert [r.name for r in sorted_] == ["甲"]


# ── load_theme_leaderboard(并行 + 失败容忍)──────────────────────────


def _make_kline_df(streak_dir: int = 1, n_days: int = 10):
    """构造一个简单 K 线 DataFrame · streak_dir=+1 连涨 / -1 连跌 / 0 平。"""
    base = 100.0
    rows = []
    for i in range(n_days):
        prev_close = base + i * streak_dir
        close = base + (i + 1) * streak_dir
        rows.append({
            "date": f"2026-05-{10 + i:02d}",
            "open": prev_close,
            "high": close + 0.5,
            "low": prev_close - 0.5,
            "close": close,
            "volume": 1000,
            "amount": 100000,
        })
    return pd.DataFrame(rows)


def test_load_leaderboard_all_success(monkeypatch):
    themes = [
        Theme(code="886108", name="AI应用", source="ths"),
        Theme(code="886109", name="同花顺", source="ths"),
        Theme(code="885525", name="白酒", source="ths"),
    ]
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: themes)
    monkeypatch.setattr(
        theme_leaderboard, "fetch_theme_kline",
        lambda theme, force=False: _make_kline_df(streak_dir=1),
    )

    results, errors, source = theme_leaderboard.load_theme_leaderboard(progress_console=None)
    assert source == "em"  # 没配 TuShare token · 走 adata EM 路径

    assert len(results) == 3
    assert errors == []
    # 所有 streak 都 > 0(连涨)
    assert all(r.streak > 0 for r in results)


def test_load_leaderboard_partial_failure(monkeypatch):
    themes = [
        Theme(code=f"88{i:04d}", name=f"题材{i}", source="ths") for i in range(5)
    ]
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: themes)

    def _fake_fetch(theme, force=False):
        # code 末位偶数 ok · 奇数挂
        if int(theme.code[-1]) % 2 == 0:
            return _make_kline_df(streak_dir=-1)
        raise ThemeDataUnavailableError("mock failure")

    monkeypatch.setattr(theme_leaderboard, "fetch_theme_kline", _fake_fetch)

    results, errors, source = theme_leaderboard.load_theme_leaderboard(progress_console=None)
    assert source == "em"  # 没配 TuShare token · 走 adata EM 路径

    # 5 题材中 3 个 code 末位 0/2/4 · 2 个 1/3 挂
    assert len(results) == 3
    assert len(errors) == 2
    assert all(isinstance(e, ThemeDataUnavailableError) for _, e in errors)


def test_load_leaderboard_empty_catalog_raises(monkeypatch):
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: [])
    with pytest.raises(ThemeDataUnavailableError, match="题材清单为空"):
        theme_leaderboard.load_theme_leaderboard(progress_console=None)


def test_load_leaderboard_empty_kline_records_error(monkeypatch):
    themes = [Theme(code="886108", name="AI应用", source="ths")]
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: themes)
    monkeypatch.setattr(
        theme_leaderboard, "fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame(),  # 空 DataFrame
    )

    results, errors, source = theme_leaderboard.load_theme_leaderboard(progress_console=None)
    assert source == "em"  # 没配 TuShare token · 走 adata EM 路径

    assert results == []
    assert len(errors) == 1


def test_load_leaderboard_force_passes_through(monkeypatch):
    """force=True 时透传给 fetch_theme_kline · 不直接读 cache。"""
    themes = [Theme(code="886108", name="AI应用", source="ths")]
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: themes)

    received = {}

    def _spy(theme, force=False):
        received["force"] = force
        return _make_kline_df()

    monkeypatch.setattr(theme_leaderboard, "fetch_theme_kline", _spy)

    theme_leaderboard.load_theme_leaderboard(force=True, progress_console=None)

    assert received["force"] is True


def test_load_leaderboard_candle_passes_through(monkeypatch):
    """candle=True 时影响 calc_trend 口径(阳线阴线 vs 收盘价)。"""
    themes = [Theme(code="886108", name="AI应用", source="ths")]
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: themes)
    monkeypatch.setattr(
        theme_leaderboard, "fetch_theme_kline",
        lambda theme, force=False: _make_kline_df(),
    )

    results, _, _ = theme_leaderboard.load_theme_leaderboard(
        candle=True, progress_console=None,
    )

    assert len(results) == 1
    # 不验具体 streak 值 · 只验函数走通(candle 透传到 calc_trend)

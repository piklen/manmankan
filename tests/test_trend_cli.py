"""trend CLI 集成测试 · 覆盖 --down/--up N 短写 + sys.argv 预处理。

测试矩阵：
  - 不传 --down/--up → 不筛
  - --down (无值) → 注入 3 → 连跌 ≥ 3
  - --down 5 → 连跌 ≥ 5
  - --up (无值) → 注入 3 → 连涨 ≥ 3
  - --up 7 → 连涨 ≥ 7
  - --down + --up 互斥
  - --down 1 / --down 50 范围错误
  - --down + --candle + --latest 组合
  - sys.argv 预处理纯函数

测试策略：把 fetcher / scanner 走通 mock，只验 CLI 解析 + 筛选分支。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from kan.cli import _normalize_streak_args, app
from kan.scanner import TrendResult

# --- sys.argv 预处理纯函数测试 ---


@pytest.mark.parametrize(
    "argv,expected",
    [
        # 不带 --down/--up · 不动
        (["kan", "trend"], ["kan", "trend"]),
        (["kan", "trend", "--latest", "5"], ["kan", "trend", "--latest", "5"]),
        # --down 不带值 → 注入 3
        (["kan", "trend", "--down"], ["kan", "trend", "--down", "3"]),
        (["kan", "trend", "--up"], ["kan", "trend", "--up", "3"]),
        # --down 带值 → 不动
        (["kan", "trend", "--down", "5"], ["kan", "trend", "--down", "5"]),
        (["kan", "trend", "--up", "7"], ["kan", "trend", "--up", "7"]),
        # --down 后跟其他 flag → 注入 3
        (["kan", "trend", "--down", "--candle"], ["kan", "trend", "--down", "3", "--candle"]),
        (["kan", "trend", "--down", "--latest", "5"], ["kan", "trend", "--down", "3", "--latest", "5"]),
        # --down + --up 都不带值（互斥由 typer 后续校验，不在预处理职责）
        (["kan", "trend", "--down", "--up"], ["kan", "trend", "--down", "3", "--up", "3"]),
        # --down 5 --up 7
        (["kan", "trend", "--down", "5", "--up", "7"], ["kan", "trend", "--down", "5", "--up", "7"]),
        # --down 在末尾
        (["kan", "trend", "--candle", "--down"], ["kan", "trend", "--candle", "--down", "3"]),
    ],
)
def test_normalize_streak_args(argv: list[str], expected: list[str]) -> None:
    with patch.object(sys, "argv", list(argv)):
        _normalize_streak_args()
        assert sys.argv == expected


# --- trend 命令集成测试 ---


def _fake_trend_batch(*_args, **_kwargs) -> list[TrendResult]:
    """3 只测试股票：连跌 5 / 连涨 3 / 平盘"""
    return [
        TrendResult(
            symbol="600519",
            name="测试跌5",
            current_price=100.0,
            streak=-5,
            streak_pct=-8.0,
            daily_changes=[("2026-05-08", -2.0)] * 5,
        ),
        TrendResult(
            symbol="000001",
            name="测试涨3",
            current_price=50.0,
            streak=3,
            streak_pct=4.5,
            daily_changes=[("2026-05-08", 1.5)] * 3,
        ),
        TrendResult(
            symbol="002001",
            name="测试平",
            current_price=20.0,
            streak=0,
            streak_pct=0.0,
            daily_changes=[],
        ),
    ]


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """隔离 watchlist + cache_age + fetcher · 让 trend 走 mock 数据。"""
    monkeypatch.setattr(
        "kan.cli._get_watchlist_pairs",
        lambda: [("600519", "测试跌5"), ("000001", "测试涨3"), ("002001", "测试平")],
    )
    monkeypatch.setattr("kan.cli._auto_fetch_stale", lambda _pairs: None)
    monkeypatch.setattr("kan.scanner.trend_batch", _fake_trend_batch)
    monkeypatch.setattr("kan.fetcher.cache_age", lambda _sym: "2026-05-08 12:00")
    monkeypatch.setattr("kan.scanner.get_limit_threshold", lambda *a, **k: 10.0)
    return CliRunner()


def test_trend_no_filter(runner: CliRunner) -> None:
    """无筛选 · 全部 3 只都展示"""
    result = runner.invoke(app, ["trend"])
    assert result.exit_code == 0
    assert "测试跌5" in result.stdout
    assert "测试涨3" in result.stdout
    assert "测试平" in result.stdout


def test_trend_down_5(runner: CliRunner) -> None:
    """--down 5 · 只剩连跌 ≥ 5 的"""
    result = runner.invoke(app, ["trend", "--down", "5"])
    assert result.exit_code == 0
    assert "测试跌5" in result.stdout
    assert "测试涨3" not in result.stdout


def test_trend_down_no_match(runner: CliRunner) -> None:
    """--down 10 · 没匹配 · 友好提示"""
    result = runner.invoke(app, ["trend", "--down", "10"])
    assert result.exit_code == 0
    assert "没有连续跌 10 天以上" in result.stdout


def test_trend_up_3(runner: CliRunner) -> None:
    """--up 3 · 只剩连涨 ≥ 3 的"""
    result = runner.invoke(app, ["trend", "--up", "3"])
    assert result.exit_code == 0
    assert "测试涨3" in result.stdout
    assert "测试跌5" not in result.stdout


def test_trend_down_up_mutex(runner: CliRunner) -> None:
    """--down 与 --up 互斥 · 错误信号走 stderr (P1-9)"""
    import contextlib

    result = runner.invoke(app, ["trend", "--down", "3", "--up", "3"])
    assert result.exit_code == 1
    # P1-9: 错误信号走 stderr · 兼容 CliRunner mix_stderr=True/False 两种情况
    combined = result.stdout
    with contextlib.suppress(ValueError):
        # mix_stderr=True 时 result.stderr 抛 ValueError · 此时 stderr 已合并到 stdout
        combined = combined + (result.stderr or "")
    assert "不能同时使用" in combined


def test_trend_down_below_min(runner: CliRunner) -> None:
    """--down 1 · 越界 · typer 报错"""
    result = runner.invoke(app, ["trend", "--down", "1"])
    assert result.exit_code != 0


def test_trend_down_above_max(runner: CliRunner) -> None:
    """--down 50 · 越界 · typer 报错"""
    result = runner.invoke(app, ["trend", "--down", "50"])
    assert result.exit_code != 0


def test_trend_combo_down_latest_candle(runner: CliRunner) -> None:
    """组合：--down 5 --latest 5 --candle 都能 work"""
    result = runner.invoke(app, ["trend", "--down", "5", "--latest", "5", "--candle"])
    assert result.exit_code == 0
    assert "测试跌5" in result.stdout
    assert "阳线阴线口径" in result.stdout


def test_trend_streak_option_removed(runner: CliRunner) -> None:
    """--streak 参数不提供 · 传 --streak 应当 typer 报错"""
    result = runner.invoke(app, ["trend", "--streak", "5"])
    assert result.exit_code != 0

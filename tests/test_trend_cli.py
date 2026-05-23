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

from kan.cli import app
from kan.cli_helpers import _normalize_streak_args
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
    # cli.py 拆分后 trend 命令在 kan.cli_trend_cmds · from-import 把 helper 引用 bound
    # 到 cli_trend_cmds 的 namespace · monkeypatch 必须改这里才能拦截
    monkeypatch.setattr(
        "kan.cli_trend_cmds._get_watchlist_pairs",
        lambda: [("600519", "测试跌5"), ("000001", "测试涨3"), ("002001", "测试平")],
    )
    monkeypatch.setattr("kan.cli_trend_cmds._auto_fetch_stale", lambda _pairs: None)
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
    """--down 与 --up 互斥 · 错误信号走 stderr"""
    import contextlib

    result = runner.invoke(app, ["trend", "--down", "3", "--up", "3"])
    assert result.exit_code == 1
    # 错误信号走 stderr · 兼容 CliRunner mix_stderr=True/False 两种情况
    combined = result.stdout
    with contextlib.suppress(ValueError):
        # mix_stderr=True 时 result.stderr 抛 ValueError · 此时 stderr 已合并到 stdout
        combined = combined + (result.stderr or "")
    assert "不能同时使用" in combined


def test_trend_format_json(runner: CliRunner) -> None:
    """`kan trend --format json` · 输出合法 JSON · 含 3 只结果"""
    import json as _json

    result = runner.invoke(app, ["trend", "--format", "json"])
    assert result.exit_code == 0, f"output: {result.stdout[:400]}"
    out = result.stdout
    data = _json.loads(out[out.index("{"):])
    assert data["command"] == "trend"
    assert len(data["results"]) == 3
    assert data["results"][0]["symbol"] == "600519"


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


# ════════════════════════════════════════════════════════════════
# stale/intraday warning runtime 真测
# (v0.0.4.8 改造自 test_cli_helpers_format.py TestNoLegacyTextInWarnings grep-source 作弊)
# ════════════════════════════════════════════════════════════════
def test_trend_stale_warning_uses_new_phrasing(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stale 警告应含'当前缓存到 X 收盘' + '数据滞后 N 天' · 不再'应有最近交易日'.

    v0.0.4.8: 旧 grep-source 作弊改 CliRunner 真测 ·
    模拟 data_cutoff < expected_cutoff → is_stale=True 触发 stale 警告分支.
    """
    from datetime import date

    # data_cutoff_date 是 cli_trend_cmds.trend() 内 lazy import from kan.fetcher · patch 原 module
    monkeypatch.setattr(
        "kan.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 1)
    )
    monkeypatch.setattr(
        "kan.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    monkeypatch.setattr("kan.trading_calendar.market_phase", lambda: "PRE_OPEN")

    result = runner.invoke(app, ["trend"])
    assert result.exit_code == 0, f"trend 退出失败 · stderr: {result.stderr if hasattr(result, 'stderr') else ''}"
    output = result.output
    # 新文案三件套
    assert "当前缓存到" in output, f"新文案 '当前缓存到' 应出现 · 实际 output: {output[:500]}"
    assert "数据滞后" in output, "新文案 '数据滞后 N 天' 应出现"
    assert "kan fetch --force" in output, "新文案应含行动建议 'kan fetch --force'"
    # 旧文案应删
    assert "应有最近交易日" not in output, "旧术语 '应有最近交易日' 应删除"


def test_trend_intraday_warning_compliant_phrasing(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """盘中警告应是状态描述 · 不含预测性'下一秒打开' AGENTS.md §6 红线词.

    v0.0.4.8: 旧 grep-source 改 CliRunner 真测 ·
    模拟 fresh data + phase=INTRADAY → 触发 intraday 警告分支.
    """
    from datetime import date

    # 让 data_cutoff = expected_cutoff → is_stale=False · 不触发 stale 分支
    monkeypatch.setattr(
        "kan.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 14)
    )
    monkeypatch.setattr(
        "kan.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    # phase=INTRADAY 触发 elif intraday 分支
    monkeypatch.setattr(
        "kan.trading_calendar.market_phase", lambda: "in"
    )

    result = runner.invoke(app, ["trend"])
    assert result.exit_code == 0
    output = result.output
    # 新文案 v0.0.4.8 cross-validated: 纯状态描述 · 移除 "可能回落/可能回升/都是正常波动" 预测性词
    assert "涨跌停标签反映当前时刻" in output, (
        f"v0.0.4.8 新文案 '涨跌停标签反映当前时刻' 应出现 · 实际 output: {output[-500:]}"
    )
    assert "建议盘后 15:30" in output, "新文案应含 '建议盘后 15:30'"
    # 红线: 旧预测性词不应残留 (AGENTS.md §6 不预测涨跌)
    assert "下一秒打开" not in output, "预测性词 '下一秒打开' 应删除 (v0.0.4.7)"
    assert "都是正常波动" not in output, "v0.0.4.8: '都是正常波动' 含预测语义 · 应删除"
    assert "可能回落" not in output, "v0.0.4.8: '可能回落' 含方向词 · 应删除"


def test_trend_warnings_mutex_stale_wins(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stale+intraday 同时为 True 时只显示 stale · intraday 不显示 (if/elif 互斥).

    v0.0.4.8: 旧 grep-source 作弊改 CliRunner 真测 ·
    场景: 用户跑 scan 时盘中数据 stale (数据中断 + 行情仍在跑) → stale 优先(用户最先动作就是 fetch).
    """
    from datetime import date

    # stale=True + phase=INTRADAY
    monkeypatch.setattr(
        "kan.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 1)
    )
    monkeypatch.setattr(
        "kan.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    monkeypatch.setattr(
        "kan.trading_calendar.market_phase", lambda: "in"
    )

    result = runner.invoke(app, ["trend"])
    assert result.exit_code == 0
    output = result.output
    # stale 警告应显示
    assert "当前缓存到" in output, "stale 警告应显示"
    assert "数据滞后" in output, "stale 警告应含'数据滞后'"
    # intraday 警告不应同时显示 (if/elif 互斥)
    assert "涨跌停标签反映当前时刻" not in output, (
        "stale=True 时不应同时显示 intraday 警告 (互斥 · 用户首动作 fetch)"
    )

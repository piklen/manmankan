"""kan theme trend CLI 子命令测试 · v0.0.5.7。

模仿 test_theme_cli.py 风格 · mock adata + stub data layer。
"""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import Theme
from kan.core.scanner import TrendResult


@pytest.fixture(autouse=True)
def _mock_adata(monkeypatch):
    monkeypatch.setitem(sys.modules, "adata", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock.market", MagicMock())


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from kan.data import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.ensure_dirs", lambda: None)
    return tmp_path


def _stub_leaderboard(monkeypatch, results=None, errors=None, source="em"):
    """stub load_theme_leaderboard · 直接返回预制 (results, errors, source)。"""
    if results is None:
        results = [
            TrendResult("886108", "AI应用", 1245.3, 7, 12.5, [
                ("2026-05-20", 1.2), ("2026-05-21", 2.0), ("2026-05-22", 3.4),
            ]),
            TrendResult("886112", "数据要素", 892.1, 5, 8.2, [
                ("2026-05-20", 1.5), ("2026-05-21", 0.8), ("2026-05-22", 2.0),
            ]),
            TrendResult("885525", "白酒", 805.2, -6, -8.4, [
                ("2026-05-20", -1.2), ("2026-05-21", -1.5), ("2026-05-22", -1.8),
            ]),
            TrendResult("886058", "煤炭", 445.6, -3, -5.0, [
                ("2026-05-20", -1.0), ("2026-05-21", -1.5), ("2026-05-22", -1.8),
            ]),
        ]
    if errors is None:
        errors = []
    monkeypatch.setattr(
        "kan.data.theme_leaderboard.load_theme_leaderboard",
        lambda **kw: (results, errors, source),
    )


def test_trend_default(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend"])
    assert result.exit_code == 0
    # 默认按 streak abs 排 · 白酒(-6)在前 · AI应用(+7)更大在最前
    assert "AI应用" in result.output
    assert "白酒" in result.output
    # 排名列存在
    assert "排名" in result.output


def test_trend_up_filter(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--up", "3"])
    assert result.exit_code == 0
    # 连涨 ≥3 的题材保留 · 连跌不留
    assert "AI应用" in result.output
    assert "数据要素" in result.output
    assert "白酒" not in result.output
    assert "煤炭" not in result.output


def test_trend_down_filter(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--down", "3"])
    assert result.exit_code == 0
    # 连跌 ≥3 的题材保留 · 连涨不留
    assert "白酒" in result.output
    assert "煤炭" in result.output
    assert "AI应用" not in result.output


def test_trend_up_down_mutual_exclusion(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--up", "3", "--down", "3"])
    assert result.exit_code == 1
    assert "不能同时使用" in result.output


def test_trend_up_out_of_range(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--up", "1"])
    assert result.exit_code == 1
    assert "2-30" in result.output


def test_trend_limit(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--limit", "2"])
    assert result.exit_code == 0
    # 排序后取前 2 · streak abs 大的:AI应用(7) · 白酒(-6)
    assert "AI应用" in result.output
    assert "白酒" in result.output
    # 截断的不应出现
    assert "数据要素" not in result.output


def test_trend_all_flag(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--all"])
    assert result.exit_code == 0
    # --all 应展示所有 4 个 · 包括较小 streak 的"煤炭"
    assert "煤炭" in result.output


def test_trend_format_json(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--format", "json", "--limit", "2"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "theme_trend"
    assert payload["mode"] == "close"
    assert payload["shown"] == 2
    assert "results" in payload
    assert payload["results"][0]["rank"] == 1
    assert payload["results"][1]["rank"] == 2


def test_trend_format_md(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--format", "md", "--limit", "2"])
    assert result.exit_code == 0
    assert "# 慢慢看 · 题材连续涨跌榜" in result.output
    assert "| 排名 |" in result.output  # md table header


def test_trend_latest(monkeypatch):
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--latest", "3", "--limit", "1"])
    assert result.exit_code == 0
    # 应该出现 day 列(MM-DD 格式)
    assert "05-20" in result.output or "05-21" in result.output or "05-22" in result.output


def test_trend_candle(monkeypatch):
    """--candle 切到阳线阴线口径 · 标题应反映。"""
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--candle"])
    assert result.exit_code == 0
    assert "阳线阴线" in result.output


def test_trend_no_results_after_filter(monkeypatch):
    """filter 后 results 为空 · 友好提示 + exit 0(不算错)。"""
    results = [
        TrendResult("886108", "AI应用", 100.0, 2, 3.0, []),
    ]
    _stub_leaderboard(monkeypatch, results=results, errors=[])
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--up", "5"])
    # 没有 ≥5 天连涨的题材 · 友好退出
    assert result.exit_code == 0
    assert "没有连续涨" in result.output


def test_trend_all_themes_failed(monkeypatch):
    """所有题材抓 K 线失败时 exit 1 + 错误提示。"""
    _stub_leaderboard(monkeypatch, results=[], errors=[
        (Theme(code=f"88{i:04d}", name=f"T{i}", source="ths"), Exception("net"))
        for i in range(5)
    ])
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend"])
    assert result.exit_code == 1
    assert "无数据" in result.output


def test_trend_catalog_failure(monkeypatch):
    """题材清单本身拿不到时 exit 1 + 友好提示。"""
    from kan.data.boards import ThemeDataUnavailableError

    def _raise(**kw):
        raise ThemeDataUnavailableError("catalog 不可用")

    monkeypatch.setattr("kan.data.theme_leaderboard.load_theme_leaderboard", _raise)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend"])
    assert result.exit_code == 1
    assert "题材榜不可用" in result.output


def test_trend_disclaimer_5_lines(monkeypatch):
    """terminal 输出底部必带 5 行 disclaimer(比 scan 多 1 行 anti-FOMO)。"""
    _stub_leaderboard(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--limit", "1"])
    assert result.exit_code == 0
    # 4 行常规 + 1 行连涨连跌专属
    assert "位置 ≠ 买卖信号" in result.output
    assert "题材跟风风险高于行业" in result.output
    assert "题材方向变化比个股快" in result.output
    assert "不预测涨跌" in result.output


def test_trend_partial_errors_shown(monkeypatch):
    """部分题材失败时输出末尾提示数量。"""
    _stub_leaderboard(monkeypatch, errors=[
        (Theme(code="886108", name="挂掉题材A", source="ths"), Exception("net")),
        (Theme(code="886109", name="挂掉题材B", source="ths"), Exception("net")),
    ])
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend", "--limit", "2"])
    assert result.exit_code == 0
    assert "2 题材数据不可用" in result.output

"""kan theme trend CLI 子命令测试 · 历史背景。

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


def _stub_leaderboard(monkeypatch, results=None, errors=None, source="em", diagnosis=None):
    """stub load_theme_leaderboard · 直接返回预制 (results, errors, source, diagnosis)。"""
    from kan.data.theme_leaderboard import LeaderboardDiagnosis

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
    if diagnosis is None:
        diagnosis = LeaderboardDiagnosis(
            em_attempted=True, em_total=len(results) + len(errors),
            em_failed_count=len(errors),
        )
    monkeypatch.setattr(
        "kan.data.theme_leaderboard.load_theme_leaderboard",
        lambda **kw: (results, errors, source, diagnosis),
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
    result = runner.invoke(app, ["theme", "trend", "--up", "0"])
    assert result.exit_code == 1
    assert "1-30" in result.output


def test_trend_min_streak_one(monkeypatch):
    results = [
        TrendResult("886108", "AI应用", 100.0, 1, 1.2, []),
        TrendResult("886109", "平盘题材", 100.0, 0, 0.0, []),
    ]
    _stub_leaderboard(monkeypatch, results=results, errors=[])
    result = CliRunner().invoke(app, ["theme", "trend", "--min-streak", "1"])
    assert result.exit_code == 0
    assert "AI应用" in result.output
    assert "平盘题材" not in result.output


def test_trend_sort_latest(monkeypatch):
    _stub_leaderboard(monkeypatch)
    result = CliRunner().invoke(app, ["theme", "trend", "--sort", "latest", "--limit", "1"])
    assert result.exit_code == 0
    # stub 中 latest 单日涨幅最大的是数据要素(1.5%)
    assert "数据要素" in result.output


def test_trend_sort_moneyflow_json(monkeypatch):
    _stub_leaderboard(monkeypatch)
    monkeypatch.setattr(
        "kan.data.board_leaderboard.theme_moneyflow_map",
        lambda themes, force=False: {"886112": 300.0, "886108": 100.0},
    )
    result = CliRunner().invoke(
        app, ["theme", "trend", "--sort", "moneyflow", "--format", "json", "--limit", "1"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["results"][0]["symbol"] == "886112"
    assert payload["results"][0]["moneyflow_net"] == 300.0


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


def test_trend_failure_diagnosis_with_tushare_self_hosted_proxy(monkeypatch):
    """背景 · 6.6 更新: 自部署代理 + 没拿到具体 code → 推切官方端点。

    历史: 之前文案 '可能是网络问题' 屏蔽链路 · 现透传 server msg 给用户。
    """
    from kan.data.theme_leaderboard import LeaderboardDiagnosis

    diagnosis = LeaderboardDiagnosis(
        tushare_attempted=True,
        tushare_failed_at="catalog",
        tushare_endpoint="http://lianghua.example.top",
        tushare_token_masked="***3c7d",
        em_attempted=True, em_total=391, em_failed_count=391,
    )
    errors = [
        (Theme(code=f"88{i:04d}", name=f"T{i}", source="ths"), Exception("net"))
        for i in range(391)
    ]
    _stub_leaderboard(monkeypatch, results=[], errors=errors, diagnosis=diagnosis)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend"])
    assert result.exit_code == 1
    assert "TuShare Pro" in result.output
    assert "***3c7d" in result.output
    assert "lianghua.example.top" in result.output
    assert "catalog (ths_index) 拉取失败" in result.output
    assert "391/391" in result.output
    # 没拿到具体 code · 用了自部署代理 → 推切官方
    assert "kan config set tushare-endpoint" in result.output
    assert "kan config unset tushare-token" in result.output


def test_trend_failure_diagnosis_passes_server_msg_through(monkeypatch):
    """核心: server 返的 msg 透传给用户 · code/msg 都在输出里。

    场景: 8000 积分官方 endpoint · ths_daily 仍 1次/小时 · 频率超限 40203。
    用户必须直接看到 TuShare 原话 "频率超限(1次/小时)" · 不靠我们脑补。
    """
    from kan.data.theme_leaderboard import LeaderboardDiagnosis
    from kan.data.tushare import DEFAULT_ENDPOINT

    diagnosis = LeaderboardDiagnosis(
        tushare_attempted=True,
        tushare_failed_at="klines",
        tushare_endpoint=DEFAULT_ENDPOINT,
        tushare_token_masked="***3835",
        tushare_error_code=40203,
        tushare_error_msg="抱歉，您访问接口(ths_daily)频率超限(1次/小时)",
        em_attempted=True, em_total=391, em_failed_count=391,
    )
    errors = [
        (Theme(code=f"88{i:04d}", name=f"T{i}", source="ths"), Exception("net"))
        for i in range(391)
    ]
    _stub_leaderboard(monkeypatch, results=[], errors=errors, diagnosis=diagnosis)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend"])
    assert result.exit_code == 1
    # server msg 必须原文透传(已 redact 防 token · 这里 msg 无 token-like pattern)
    assert "code=40203" in result.output
    assert "频率超限" in result.output
    assert "1次/小时" in result.output
    # 按 40203 给精准建议
    assert "频率超限" in result.output  # 建议段也包含
    assert "doc_id=290" in result.output  # 频次表 URL
    # 不该硬编码 "2000+ 积分" 或 "6000 积分" 之类的猜测数字
    assert "2000+" not in result.output
    # token 必须 masked
    assert "***3835" in result.output


def test_trend_failure_diagnosis_token_invalid(monkeypatch):
    """code=40101 token 不对 → 推 token 重复制(不推切端点)。"""
    from kan.data.theme_leaderboard import LeaderboardDiagnosis
    from kan.data.tushare import DEFAULT_ENDPOINT

    diagnosis = LeaderboardDiagnosis(
        tushare_attempted=True,
        tushare_failed_at="catalog",
        tushare_endpoint=DEFAULT_ENDPOINT,
        tushare_token_masked="***xxxx",
        tushare_error_code=40101,
        tushare_error_msg="您的token不对，请确认。",
        em_attempted=True, em_total=391, em_failed_count=391,
    )
    _stub_leaderboard(monkeypatch, results=[], errors=[], diagnosis=diagnosis)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend"])
    assert result.exit_code == 1
    assert "token 无效" in result.output
    assert "tushare.pro/user/token" in result.output
    # 40101 不是频率/积分问题
    assert "频率超限" not in result.output.split("可能修复")[1]
    assert "积分不足" not in result.output


def test_trend_failure_diagnosis_without_tushare(monkeypatch):
    """没配 token + EM 全失败 → 错误消息提示 TuShare 未尝试 + 推荐配 token。"""
    from kan.data.theme_leaderboard import LeaderboardDiagnosis

    diagnosis = LeaderboardDiagnosis(
        tushare_attempted=False,
        em_attempted=True, em_total=391, em_failed_count=391,
    )
    errors = [
        (Theme(code=f"88{i:04d}", name=f"T{i}", source="ths"), Exception("net"))
        for i in range(391)
    ]
    _stub_leaderboard(monkeypatch, results=[], errors=errors, diagnosis=diagnosis)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "trend"])
    assert result.exit_code == 1
    # 没配 token → 提示未尝试
    assert "未尝试" in result.output
    # 推荐配 TuShare 走付费源
    assert "kan config set tushare-token" in result.output
    # token 没配时不应推荐 unset(那是配了的场景)
    assert "kan config unset" not in result.output

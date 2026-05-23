"""v0.0.4.7(用户反馈触发):resolve_max_workers 启发式测试.

改动: max_workers 硬编码 5 → min(cpu_count*2, 12) 启发式.
- akshare 是 I/O bound 不是 CPU bound · cpu_count*2 比 cpu-1 更合理
- 上限 cap 12 防 akshare 限流

教育性 (用户反馈"并发可以根据系统的核数-1来自动适配"):
- 老观点: cpu-1 (CPU bound 经典启发式 · 留 1 核给主线程)
- 修正: I/O bound 程序 thread 大多在等 syscall 阻塞 · cpu*2~5 都合理 · 关键是上限 cap
"""
from __future__ import annotations

from unittest.mock import patch

from kan.fetcher import resolve_max_workers


class TestAutoMaxWorkers:
    """4 case 覆盖 cpu_count 边界 (8/4/2/None)."""

    def test_default_8_core_returns_12_capped(self, monkeypatch):
        """8 核: cpu_count*2 = 16 → cap 12."""
        monkeypatch.delenv("KAN_WORKERS", raising=False)
        with patch("os.cpu_count", return_value=8):
            assert resolve_max_workers() == 12

    def test_default_4_core_returns_8(self, monkeypatch):
        """4 核: cpu_count*2 = 8 (未到 cap)."""
        monkeypatch.delenv("KAN_WORKERS", raising=False)
        with patch("os.cpu_count", return_value=4):
            assert resolve_max_workers() == 8

    def test_default_2_core_returns_4(self, monkeypatch):
        """2 核老机器: cpu_count*2 = 4."""
        monkeypatch.delenv("KAN_WORKERS", raising=False)
        with patch("os.cpu_count", return_value=2):
            assert resolve_max_workers() == 4

    def test_default_none_cpu_count_returns_8(self, monkeypatch):
        """cpu_count() 返 None (罕见 · 某些 cgroup): fallback 4 → workers=8."""
        monkeypatch.delenv("KAN_WORKERS", raising=False)
        with patch("os.cpu_count", return_value=None):
            assert resolve_max_workers() == 8

    def test_default_16_core_caps_at_12(self, monkeypatch):
        """16 核 Mac Studio: cpu_count*2 = 32 · cap 12 防 akshare 限流."""
        monkeypatch.delenv("KAN_WORKERS", raising=False)
        with patch("os.cpu_count", return_value=16):
            assert resolve_max_workers() == 12


class TestKanWorkersEnvVar:
    """KAN_WORKERS env var override 覆盖通道."""

    def test_env_var_3_overrides_to_3(self, monkeypatch):
        monkeypatch.setenv("KAN_WORKERS", "3")
        with patch("os.cpu_count", return_value=8):
            assert resolve_max_workers() == 3

    def test_env_var_zero_falls_back(self, monkeypatch):
        """0 不在 1-20 范围 · 回退默认 (v0.0.4.7 上限 50→20)."""
        monkeypatch.setenv("KAN_WORKERS", "0")
        with patch("os.cpu_count", return_value=8):
            assert resolve_max_workers() == 12  # 8*2 cap 12

    def test_env_var_over_20_falls_back(self, monkeypatch):
        """v0.0.4.7 安全收紧:上限 50→20 · 防 KAN_WORKERS=50 反射 DoS akshare."""
        monkeypatch.setenv("KAN_WORKERS", "21")
        with patch("os.cpu_count", return_value=8):
            assert resolve_max_workers() == 12

    def test_env_var_20_at_upper_boundary(self, monkeypatch):
        """20 是新上限边界 · 应允许."""
        monkeypatch.setenv("KAN_WORKERS", "20")
        with patch("os.cpu_count", return_value=8):
            assert resolve_max_workers() == 20

    def test_env_var_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("KAN_WORKERS", "not-a-number")
        with patch("os.cpu_count", return_value=4):
            assert resolve_max_workers() == 8


class TestD1RuntimeBehavior:
    """v0.0.4.7:_auto_fetch_stale 运行时行为真测.

    v0.0.4.8 改造:从旧"grep 源码作弊"测试改为 CliRunner runtime 真测.
    新设计: mock rich.Console / rich.Progress · capture 所有调用 · verify runtime 用户面输出.
    """

    @staticmethod
    def _run_auto_fetch_stale(pairs, max_workers=8, errors=None):
        """Helper: 跑 _auto_fetch_stale + mock 所有依赖 + 返回 (console_prints, status_updates).

        mock 策略:
        - Console / Progress 整体替换 MagicMock · 不渲染但记录调用
        - is_fresh return False → 所有 pairs 都进 stale list
        - fetch_batch 返回空 results · errors 可由调用方注入
        - resolve_max_workers / latest_trade_date 也 mock 防真实 fetch
        """
        from unittest.mock import MagicMock, patch

        from kan.cli_helpers import _auto_fetch_stale

        fake_console = MagicMock()
        fake_status = MagicMock()
        fake_status.__enter__ = MagicMock(return_value=fake_status)
        fake_status.__exit__ = MagicMock(return_value=None)
        fake_console.status = MagicMock(return_value=fake_status)

        fake_progress = MagicMock()
        fake_progress.__enter__ = MagicMock(return_value=fake_progress)
        fake_progress.__exit__ = MagicMock(return_value=None)
        fake_progress.add_task = MagicMock(return_value=0)

        with patch("rich.console.Console", return_value=fake_console), \
             patch("rich.progress.Progress", return_value=fake_progress), \
             patch("kan.fetcher.is_fresh", return_value=False), \
             patch(
                 "kan.fetcher.fetch_batch",
                 return_value=({}, errors or {})
             ), \
             patch("kan.fetcher.resolve_max_workers", return_value=max_workers), \
             patch("kan.trading_calendar.latest_trade_date", return_value=None):
            _auto_fetch_stale(pairs)

        # 提取所有 console.print 调用文本
        prints = []
        for call_obj in fake_console.print.call_args_list:
            args = call_obj.args
            if args:
                prints.append(str(args[0]))

        # 提取所有 status.update 调用文本
        status_updates = []
        for call_obj in fake_status.update.call_args_list:
            args = call_obj.args
            if args:
                status_updates.append(str(args[0]))

        # 提取所有 progress.update description
        progress_descs = []
        for call_obj in fake_progress.update.call_args_list:
            desc = call_obj.kwargs.get("description", "")
            if desc:
                progress_descs.append(str(desc))

        return {
            "console_prints": prints,
            "status_updates": status_updates,
            "progress_descs": progress_descs,
            "all_text": "\n".join(prints + status_updates + progress_descs),
        }

    def test_no_v045_migration_text_in_runtime_output(self):
        """v0.0.4.5 一次性迁移文案不应出现在 _auto_fetch_stale 的任何 user-facing 输出中."""
        pairs = [(f"60000{i:04d}", f"股{i}") for i in range(35)]
        result = self._run_auto_fetch_stale(pairs)
        assert "v0.0.4.5 起首次刷新会全量补数据" not in result["all_text"], (
            f"旧迁移文案不应出现在用户面输出 · 实际全部输出: {result['all_text'][:500]}"
        )

    def test_status_spinner_shows_stale_count(self):
        """status spinner 在 ticking 阶段应显示 'N 只 stale' 信息密度 ·

        让用户理解"为什么这么多只在拉"(cache 全失效场景).
        """
        # 30 只 (> n_total // 20 = 1 · 触发 ticking update)
        pairs = [(f"60000{i:04d}", f"股{i}") for i in range(30)]
        result = self._run_auto_fetch_stale(pairs)
        all_status = "\n".join(result["status_updates"])
        assert "只 stale" in all_status, (
            f"status spinner 应在 ticking 阶段显示 '只 stale' · 实际 status updates: "
            f"{result['status_updates']}"
        )

    def test_concurrency_message_shows_dynamic_workers_not_hardcoded_5(self):
        """30+ stale 股票时 concurrency 提示应显示 resolve_max_workers 动态值 · 不硬编码 '并发 5'."""
        pairs = [(f"60000{i:04d}", f"股{i}") for i in range(35)]
        # max_workers=8 模拟 4 核 mac 的启发式结果
        result = self._run_auto_fetch_stale(pairs, max_workers=8)
        all_prints = "\n".join(result["console_prints"])
        assert "并发 8" in all_prints, (
            f"应显示动态 '并发 8' · 实际 console prints: {result['console_prints']}"
        )
        assert "并发 5" not in all_prints, (
            "不应硬编码 '并发 5' (v0.0.4.7 改造点)"
        )

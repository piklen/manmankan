"""历史背景(用户反馈触发):resolve_max_workers 启发式测试.

改动: max_workers 硬编码 5 → min(cpu_count*2, 12) 启发式.
- akshare 是 I/O bound 不是 CPU bound · cpu_count*2 比 cpu-1 更合理
- 上限 cap 12 防 akshare 限流

教育性 (用户反馈"并发可以根据系统的核数-1来自动适配"):
- 老观点: cpu-1 (CPU bound 经典启发式 · 留 1 核给主线程)
- 修正: I/O bound 程序 thread 大多在等 syscall 阻塞 · cpu*2~5 都合理 · 关键是上限 cap
"""
from __future__ import annotations

from unittest.mock import patch

from kan.data.fetcher import resolve_max_workers


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
        """0 不在 1-20 范围 · 回退默认 (历史背景上限 50→20)."""
        monkeypatch.setenv("KAN_WORKERS", "0")
        with patch("os.cpu_count", return_value=8):
            assert resolve_max_workers() == 12  # 8*2 cap 12

    def test_env_var_over_20_falls_back(self, monkeypatch):
        """历史背景安全收紧:上限 50→20 · 防 KAN_WORKERS=50 反射 DoS akshare."""
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
    """背景:_auto_fetch_stale 运行时行为真测.

    背景:从旧"grep 源码作弊"测试改为 CliRunner runtime 真测.
    新设计: mock rich.Console / rich.Progress · capture 所有调用 · verify runtime 用户面输出.
    """

    @staticmethod
    def _run_auto_fetch_stale(pairs, max_workers=8, errors=None):
        """运行自动补数据并返回中性的 lifecycle 事件。"""
        from unittest.mock import patch

        from kan.cli.helpers import _auto_fetch_stale
        from kan.infra.lifecycle import CollectingReporter, operation

        error_map = errors or {}

        def fake_fetch_batch(symbols, **kwargs):
            on_progress = kwargs.get("on_progress")
            if on_progress is not None:
                for sym in symbols:
                    on_progress(sym, sym not in error_map, error_map.get(sym))
            results = {sym: object() for sym in symbols if sym not in error_map}
            return results, error_map

        reporter = CollectingReporter()
        with patch("kan.data.fetcher.is_fresh", return_value=False), \
             patch("kan.data.fetcher.fetch_batch", side_effect=fake_fetch_batch), \
             patch(
                 "kan.data.fetcher.resolve_batch_worker_bounds",
                 return_value=(max_workers, max_workers),
             ), \
             patch("kan.core.trading_calendar.latest_trade_date", return_value=None), \
             operation("test-auto-fetch", reporter=reporter) as lifecycle:
            _auto_fetch_stale(pairs, lifecycle=lifecycle)
        return reporter.events

    def test_no_legacy_migration_text_in_lifecycle(self):
        """旧一次性迁移文案不应进入 lifecycle。"""
        pairs = [(f"60000{i:04d}", f"股{i}") for i in range(35)]
        events = self._run_auto_fetch_stale(pairs)
        assert all("首次刷新会全量补数据" not in (event.message or "") for event in events)

    def test_cache_progress_shows_stale_count(self):
        """缓存检查进度携带聚合 stale 数。"""
        from kan.infra.lifecycle import LifecycleKind

        pairs = [(f"60000{i:04d}", f"股{i}") for i in range(30)]
        events = self._run_auto_fetch_stale(pairs)
        progress = [
            event for event in events
            if event.kind is LifecycleKind.PROGRESS and event.message == "检查缓存"
        ]
        assert progress[-1].details["stale_count"] == 30

    def test_wait_event_shows_dynamic_workers(self):
        """30+ stale 股票时等待事件携带动态并发。"""
        from kan.infra.lifecycle import LifecycleKind

        pairs = [(f"60000{i:04d}", f"股{i}") for i in range(35)]
        events = self._run_auto_fetch_stale(pairs, max_workers=8)
        wait = next(event for event in events if event.kind is LifecycleKind.WAIT)
        assert wait.details["initial_workers"] == 8
        assert wait.details["max_workers"] == 8

    def test_medium_batch_errors_emit_one_aggregated_degraded_event(self):
        """多只失败只发一个聚合 degraded，并限制样本为 5 条。"""
        from kan.infra.lifecycle import LifecycleKind

        pairs = [(f"60000{i:04d}", f"测试股{i}") for i in range(6)]
        errors = {sym: "Max retries exceeded while fetching" for sym, _ in pairs}
        events = self._run_auto_fetch_stale(pairs, errors=errors)

        degraded = [event for event in events if event.kind is LifecycleKind.DEGRADED]
        assert len(degraded) == 1
        assert degraded[0].details["success_count"] == 0
        assert degraded[0].details["failure_count"] == 6
        samples = degraded[0].details["samples"]
        assert isinstance(samples, list)
        assert len(samples) == 5
        assert all("网络异常" in str(sample["error"]) for sample in samples)

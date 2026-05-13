"""D-2 + D-3 (v0.0.4.7 · 用户 5-13 反馈): resolve_max_workers 启发式测试.

D-2 改动: max_workers 硬编码 5 → min(cpu_count*2, 12) 启发式.
- akshare 是 I/O bound 不是 CPU bound · cpu_count*2 比 cpu-1 更合理
- 上限 cap 12 防 akshare 限流

教育性 (用户 5-13 反馈"并发可以根据系统的核数-1来自动适配"):
- 老观点: cpu-1 (CPU bound 经典启发式 · 留 1 核给主线程)
- 修正: I/O bound 程序 thread 大多在等 syscall 阻塞 · cpu*2~5 都合理 · 关键是上限 cap
"""
from __future__ import annotations

from unittest.mock import patch

from kan.fetcher import resolve_max_workers


class TestAutoMaxWorkers:
    """D-2: 4 case 覆盖 cpu_count 边界 (8/4/2/None)."""

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
        """0 不在 1-20 范围 · 回退默认 (安-4 v0.0.4.7 上限 50→20)."""
        monkeypatch.setenv("KAN_WORKERS", "0")
        with patch("os.cpu_count", return_value=8):
            assert resolve_max_workers() == 12  # 8*2 cap 12

    def test_env_var_over_20_falls_back(self, monkeypatch):
        """安-4 (v0.0.4.7): 上限 50→20 · 防 KAN_WORKERS=50 反射 DoS akshare."""
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


class TestD1MigrationTextRemoved:
    """D-1: v0.0.4.5 一次性迁移文案应该被删除 (对老用户冗余)."""

    def test_no_v045_migration_text_in_cli_helpers(self):
        from pathlib import Path
        src = Path("kan/cli_helpers.py").read_text(encoding="utf-8")
        assert "v0.0.4.5 起首次刷新会全量补数据" not in src, (
            "v0.0.4.5 迁移文案应在 v0.0.4.7 移除 (D-1)"
        )

    def test_spinner_description_contains_stale_count(self):
        """D-1: spinner description 应含 '{n} 只 stale' · 解释为什么这么多只在拉."""
        from pathlib import Path
        src = Path("kan/cli_helpers.py").read_text(encoding="utf-8")
        # 新 spinner 文本应含 "只 stale" 字眼
        assert "只 stale" in src, (
            "spinner description 应含 '{n} 只 stale' (D-1)"
        )

    def test_concurrency_message_uses_auto_workers_not_hardcoded_5(self):
        """D-2: 并发数提示不再硬编码 '并发 5' · 应动态显示."""
        from pathlib import Path
        src = Path("kan/cli_helpers.py").read_text(encoding="utf-8")
        assert "并发 5" not in src, (
            "硬编码 '并发 5' 应替换为 resolve_max_workers() 动态值 (D-2)"
        )
        assert "resolve_max_workers" in src, (
            "应调用 resolve_max_workers 显示实际并发数 (D-2)"
        )

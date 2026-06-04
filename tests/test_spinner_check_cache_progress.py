"""spinner hotfix: _auto_fetch_stale 3 阶段 spinner 真测.

真用户反馈触发:用户升级 历史背景 `kan scan` "检查缓存..." spinner
5-30s 沉默 · 真小白误判卡死。本次 hotfix 3 阶段 spinner (B+C 组合):

- Stage 1: ⏳ 加载数据模块... (akshare/pandas import)
- Stage 2: ⏳ 加载交易日历 · N 只自选股待检查... (latest_trade_date pre-warm)
- Stage 3: ⏳ 检查缓存 · K/N 只 · 已发现 M 只 stale (ticking · 每 5%)

测试用 mock 捕获 status.update() 调用序列 · 验证多阶段行为. 不走 grep-source
作弊路径 (LOCKED: bootstrap-test 作弊检测).
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from kan.cli import helpers


class _FakeStatus:
    """模拟 Rich Status · 捕获 .update() 调用历史."""

    def __init__(self, initial_msg: str, sink: list[str]) -> None:
        sink.append(initial_msg)
        self._sink = sink

    def __enter__(self) -> _FakeStatus:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def update(self, msg: str) -> None:
        self._sink.append(msg)


@pytest.fixture
def captured_status_messages(monkeypatch):
    """注入 fake Console.status · 捕获所有 spinner 文字 (initial + updates)."""
    messages: list[str] = []

    @contextmanager
    def fake_status(self, msg, **kwargs):
        del kwargs  # spinner / refresh_per_second 等 Rich Status 参数忽略
        s = _FakeStatus(msg, messages)
        try:
            yield s
        finally:
            pass

    from rich.console import Console
    monkeypatch.setattr(Console, "status", fake_status)
    # 静音 console.print · 避免 spinner 之外 print 污染断言
    monkeypatch.setattr(Console, "print", lambda self, *a, **kw: None)
    return messages


@pytest.fixture
def patched_dependencies(monkeypatch):
    """所有股票 is_fresh=True → 无 stale · _auto_fetch_stale 走 early-return · 测前半段 spinner."""
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda sym: True)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: None)
    # 防 fetch_batch 走真网络 (即使 stale=0 不调 · 防御性 mock)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, **kw: ({}, {}),
    )


def test_3_stage_spinner_visible_169_stocks(captured_status_messages, patched_dependencies):
    """169 只 ≥ 3 阶段 spinner update · 用户能看到工具在动."""
    pairs = [(f"{600000 + i:06d}", f"测试股{i}") for i in range(169)]

    helpers._auto_fetch_stale(pairs)

    msgs = captured_status_messages
    # 至少 3 个不同 stage 的 status 文字
    assert len(msgs) >= 3, f"应至少 3 阶段 spinner · 实际 {len(msgs)}: {msgs}"

    # Stage 1: 加载阶段 (含"加载")
    assert any("加载" in m for m in msgs), f"缺 Stage 1 '加载'· {msgs}"

    # Stage 2: 交易日历 pre-warm
    assert any("交易日历" in m for m in msgs), f"缺 Stage 2 '交易日历'· {msgs}"

    # Stage 3: ticking 进度 (含 "/169" 格式)
    ticking_msgs = [m for m in msgs if "/169" in m]
    assert ticking_msgs, f"缺 Stage 3 ticking '/169'· {msgs}"
    # 至少 5 次 ticking update (169 // 20 = 8 个间隔 · 实际 ≥ 5)
    assert len(ticking_msgs) >= 5, f"ticking update 太少 · 应 ≥ 5 次实际 {len(ticking_msgs)}"


def test_ticking_progress_shows_stale_count(captured_status_messages, monkeypatch):
    """Stage 3 ticking 应在 spinner 文字里显示 '已发现 M 只 stale'."""
    # 让 odd index 股票 stale · even index fresh
    def fake_is_fresh(sym: str) -> bool:
        return int(sym) % 2 == 0
    monkeypatch.setattr("kan.data.fetcher.is_fresh", fake_is_fresh)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: None)
    # 防真网络:即使 50 只 stale · fetch_batch 返空 dict 不走 akshare
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, **kw: ({}, {}),
    )

    pairs = [(f"{i:06d}", f"股{i}") for i in range(100)]
    helpers._auto_fetch_stale(pairs)

    msgs = captured_status_messages
    stale_msgs = [m for m in msgs if "已发现" in m and "只 stale" in m]
    assert stale_msgs, f"缺 '已发现 N 只 stale' · {msgs}"

    # 最后一条 spinner 文字应显示 ~50 个 stale (100 中 odd 一半)
    final_stale_msg = stale_msgs[-1]
    assert "已发现 50 只 stale" in final_stale_msg, (
        f"最终 stale 数应 50 (100 中 odd 一半) · 实际 '{final_stale_msg}'"
    )


def test_small_watchlist_3_stocks(captured_status_messages, patched_dependencies):
    """边界:3 只股票仍走 3 阶段 spinner · ticking 至少 1 次完成."""
    pairs = [("600519", "茅台"), ("000001", "平安"), ("600000", "浦发")]
    helpers._auto_fetch_stale(pairs)

    msgs = captured_status_messages
    # 仍有 stage 1/2/3
    assert any("加载" in m for m in msgs)
    assert any("交易日历" in m for m in msgs)
    # ticking 应有至少 1 次 "3/3" (完成)
    assert any("/3 只" in m for m in msgs), f"应有 N/3 ticking · {msgs}"


def test_empty_watchlist_no_crash(captured_status_messages, patched_dependencies):
    """边界:空 watchlist 不应 crash (n_total // 20 = 0 防除 0)."""
    helpers._auto_fetch_stale([])
    # 应至少有 stage 1/2 进入 · stage 3 ticking 0 次但不抛
    msgs = captured_status_messages
    assert len(msgs) >= 2, f"空 watchlist 至少 stage 1/2 · {msgs}"


def test_latest_trade_date_exception_does_not_crash(captured_status_messages, monkeypatch):
    """fail-soft:latest_trade_date 抛异常时 spinner 不 crash."""
    def raise_for_pre_warm():
        raise RuntimeError("trade calendar unavailable (mock)")
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", raise_for_pre_warm)
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda sym: True)

    pairs = [("600519", "茅台")]
    # 不应 raise
    helpers._auto_fetch_stale(pairs)

    msgs = captured_status_messages
    # Stage 1/3 仍跑 (Stage 2 抛被 catch · 但 spinner 文字已发出)
    assert any("加载" in m for m in msgs)

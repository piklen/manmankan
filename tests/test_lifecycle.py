"""统一 operation 生命周期事件测试。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from kan.infra.lifecycle import (
    CollectingReporter,
    LifecycleKind,
    NullReporter,
    OperationReporter,
    OperationState,
    operation,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def test_operation_emits_ordered_render_neutral_events() -> None:
    clock = _Clock()
    reporter = CollectingReporter()

    with operation("补充行情", reporter=reporter, clock=clock, operation_id="op-1") as op:
        clock.now = 11.0
        op.phase("检查缓存", source="local")
        clock.now = 12.0
        op.progress(2, 5, "下载行情")
        clock.now = 13.0
        op.wait("等待限流窗口")
        clock.now = 14.0
        op.degraded("主源不可用")
        clock.now = 15.0
        op.heartbeat("仍在重试")

    events = reporter.events
    assert [event.sequence for event in events] == list(range(1, 8))
    assert [event.kind for event in events] == [
        LifecycleKind.OPERATION,
        LifecycleKind.PHASE,
        LifecycleKind.PROGRESS,
        LifecycleKind.WAIT,
        LifecycleKind.DEGRADED,
        LifecycleKind.HEARTBEAT,
        LifecycleKind.OPERATION,
    ]
    assert events[0].state is OperationState.STARTED
    assert events[-1].state is OperationState.SUCCEEDED
    assert events[1].details == {"source": "local"}
    assert events[2].completed == 2
    assert events[2].total == 5
    assert events[-1].elapsed == 5.0


def test_operation_can_close_explicitly_as_failed() -> None:
    reporter = CollectingReporter()

    with operation("批量拉取", reporter=reporter) as op:
        terminal = op.fail("部分股票拉取失败", failed=2)

    assert terminal.state is OperationState.FAILED
    assert terminal.message == "部分股票拉取失败"
    assert terminal.details == {"failed": 2}
    assert len(reporter.events) == 2


def test_operation_sequence_is_unique_across_threads() -> None:
    reporter = CollectingReporter()

    with (
        operation("并行下载", reporter=reporter) as op,
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        futures = [pool.submit(op.heartbeat, f"tick-{index}") for index in range(100)]
        for future in futures:
            future.result()

    sequences = [event.sequence for event in reporter.events]
    assert sequences == list(range(1, 103))


def test_null_reporter_is_noop_and_public_protocol_is_available() -> None:
    reporter: OperationReporter = NullReporter()

    with operation("静默操作", reporter=reporter) as op:
        op.phase("不会被保存")


def test_exception_finishes_as_failed_and_keyboard_interrupt_as_cancelled() -> None:
    reporter = CollectingReporter()
    with pytest.raises(RuntimeError), operation("失败操作", reporter=reporter):
        raise RuntimeError("boom")
    assert reporter.events[-1].state is OperationState.FAILED

    reporter = CollectingReporter()
    with pytest.raises(KeyboardInterrupt), operation("取消操作", reporter=reporter):
        raise KeyboardInterrupt
    assert reporter.events[-1].state is OperationState.CANCELLED

"""单 operation Rich Live renderer 测试。"""
from __future__ import annotations

import io
from collections.abc import Callable
from contextlib import redirect_stdout
from typing import Any

import pytest
from rich.console import Console

from kan.infra.lifecycle import NullReporter, operation
from kan.infra.progress import (
    FeedbackMode,
    RichOperationReporter,
    operation_feedback_enabled,
    operation_reporter,
)


class _Stream(io.StringIO):
    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _plain(renderable: object) -> str:
    snapshot = getattr(renderable, "snapshot", None)
    current = snapshot() if snapshot is not None else renderable
    return current.plain


class _FakeLive:
    def __init__(self, renderable: object, **kwargs: Any) -> None:
        self.renderables = [renderable]
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    def start(self, refresh: bool = False) -> None:
        assert refresh is True
        self.started = True

    def update(self, renderable: object, *, refresh: bool = False) -> None:
        del refresh
        self.renderables.append(renderable)

    def stop(self) -> None:
        self.stopped = True


class _FakeTimer:
    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.delay = delay
        self._callback = callback
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        assert callable(self._callback)
        self._callback()


@pytest.mark.parametrize(
    ("mode", "env", "tty", "expected"),
    [
        (FeedbackMode.CLI, {}, True, True),
        (FeedbackMode.CLI, {}, False, False),
        (FeedbackMode.MCP, {}, True, False),
        (FeedbackMode.COMPLETION, {}, True, False),
        (FeedbackMode.EMBEDDED, {}, True, False),
        (FeedbackMode.AUTO, {"_KAN_COMPLETE": "complete_zsh"}, True, False),
        (FeedbackMode.AUTO, {"_TYPER_COMPLETE_ARGS": "kan f"}, True, False),
        (FeedbackMode.AUTO, {"KAN_MCP": "1"}, True, False),
        (FeedbackMode.AUTO, {"KAN_EMBEDDED": "1"}, True, False),
    ],
)
def test_operation_feedback_mode_matrix(
    mode: FeedbackMode,
    env: dict[str, str],
    tty: bool,
    expected: bool,
) -> None:
    assert operation_feedback_enabled(
        mode=mode,
        stderr=_Stream(tty=tty),
        environ=env,
    ) is expected


def test_non_tty_factory_is_noop_without_constructing_live() -> None:
    constructed = False

    def live_factory(*args: object, **kwargs: object) -> _FakeLive:
        del args, kwargs
        nonlocal constructed
        constructed = True
        raise AssertionError("non-TTY must not construct Live")

    reporter = operation_reporter(
        stderr=_Stream(tty=False),
        live_factory=live_factory,
    )

    assert isinstance(reporter, NullReporter)
    with operation("静默", reporter=reporter) as op:
        op.phase("执行")
    assert constructed is False


def test_short_operation_never_starts_live() -> None:
    clock = _Clock()
    lives: list[_FakeLive] = []
    timers: list[_FakeTimer] = []

    def live_factory(renderable: object, **kwargs: Any) -> _FakeLive:
        live = _FakeLive(renderable, **kwargs)
        lives.append(live)
        return live

    def timer_factory(delay: float, callback: Callable[[], None]) -> _FakeTimer:
        timer = _FakeTimer(delay, callback)
        timers.append(timer)
        return timer

    reporter = RichOperationReporter(
        console=Console(file=_Stream(tty=True), force_terminal=True),
        clock=clock,
        show_after=0.5,
        live_factory=live_factory,
        timer_factory=timer_factory,
    )
    with operation("短操作", reporter=reporter, clock=clock) as op:
        clock.now = 0.2
        op.phase("完成前阶段")
    assert lives == []
    assert len(timers) == 1
    assert timers[0].started is True
    assert timers[0].cancelled is True


def test_delayed_live_starts_without_a_second_lifecycle_event() -> None:
    clock = _Clock()
    lives: list[_FakeLive] = []
    timers: list[_FakeTimer] = []

    def live_factory(renderable: object, **kwargs: Any) -> _FakeLive:
        live = _FakeLive(renderable, **kwargs)
        lives.append(live)
        return live

    def timer_factory(delay: float, callback: Callable[[], None]) -> _FakeTimer:
        timer = _FakeTimer(delay, callback)
        timers.append(timer)
        return timer

    reporter = RichOperationReporter(
        console=Console(file=_Stream(tty=True), force_terminal=True),
        clock=clock,
        show_after=0.5,
        live_factory=live_factory,
        timer_factory=timer_factory,
    )
    with operation("阻塞操作", reporter=reporter, clock=clock):
        assert lives == []
        assert len(timers) == 1
        clock.now = 0.5
        timers[0].fire()
        assert len(lives) == 1
        assert lives[0].started is True


def test_live_uses_stderr_console_without_redirecting_stdout() -> None:
    clock = _Clock()
    stderr = _Stream(tty=True)
    stdout = io.StringIO()
    reporter = RichOperationReporter(
        console=Console(file=stderr, force_terminal=True),
        clock=clock,
        show_after=0.0,
    )

    with redirect_stdout(stdout), operation(
        "输出隔离", reporter=reporter, clock=clock
    ) as op:
        clock.now = 0.1
        op.phase("处理数据")

    assert stdout.getvalue() == ""
    assert "输出隔离" in stderr.getvalue() or "处理数据" in stderr.getvalue()


def test_renderer_exposes_wait_slow_and_stalled_states() -> None:
    clock = _Clock()
    lives: list[_FakeLive] = []

    def live_factory(renderable: object, **kwargs: Any) -> _FakeLive:
        live = _FakeLive(renderable, **kwargs)
        lives.append(live)
        return live

    reporter = RichOperationReporter(
        console=Console(file=_Stream(tty=True), force_terminal=True),
        clock=clock,
        show_after=0.0,
        slow_after=1.0,
        stalled_after=2.0,
        live_factory=live_factory,
    )
    with operation("长操作", reporter=reporter, clock=clock) as op:
        clock.now = 1.1
        op.progress(1, 10, "下载中")
        assert "处理中" in _plain(lives[0].renderables[-1])

        clock.now = 2.2
        reporter.refresh()
        assert "较慢" in _plain(lives[0].renderables[-1])

        clock.now = 2.8
        op.heartbeat("仍在运行")
        clock.now = 3.2
        # heartbeat 只负责刷新画面，不能伪装成有意义的业务进展。
        assert "疑似停滞" in _plain(lives[0].renderables[-1])

        op.wait("等待上游")
        assert "等待" in _plain(lives[0].renderables[-1])


def test_renderer_redacts_exception_message() -> None:
    clock = _Clock()
    lives: list[_FakeLive] = []

    def live_factory(renderable: object, **kwargs: Any) -> _FakeLive:
        live = _FakeLive(renderable, **kwargs)
        lives.append(live)
        return live

    reporter = RichOperationReporter(
        console=Console(file=_Stream(tty=True), force_terminal=True),
        clock=clock,
        show_after=0.0,
        live_factory=live_factory,
    )
    with pytest.raises(RuntimeError), operation(
        "失败操作", reporter=reporter, clock=clock
    ):
        clock.now = 0.1
        raise RuntimeError("https://example.test/?token=secret-value")

    terminal = _plain(lives[0].renderables[-1])
    assert "secret-value" not in terminal
    assert "token=<redacted>" in terminal


def test_renderer_marks_keyboard_interrupt_as_cancelled() -> None:
    clock = _Clock()
    lives: list[_FakeLive] = []

    def live_factory(renderable: object, **kwargs: Any) -> _FakeLive:
        live = _FakeLive(renderable, **kwargs)
        lives.append(live)
        return live

    reporter = RichOperationReporter(
        console=Console(file=_Stream(tty=True), force_terminal=True),
        clock=clock,
        show_after=0.0,
        live_factory=live_factory,
    )
    with pytest.raises(KeyboardInterrupt), operation(
        "可取消操作", reporter=reporter, clock=clock
    ):
        clock.now = 0.1
        raise KeyboardInterrupt

    assert "已取消" in _plain(lives[0].renderables[-1])

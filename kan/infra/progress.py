"""CLI 反馈层：兼容旧进度 API，并渲染统一 operation 生命周期。"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from enum import StrEnum
from threading import RLock, Timer
from time import monotonic
from typing import Any, Protocol, TextIO

from kan.infra.lifecycle import (
    LifecycleEvent,
    LifecycleKind,
    LifecycleReporter,
    NullReporter,
    OperationState,
)
from kan.infra.log import redact_text


class FeedbackMode(StrEnum):
    """反馈所在的调用模式。"""

    AUTO = "auto"
    CLI = "cli"
    MCP = "mcp"
    COMPLETION = "completion"
    EMBEDDED = "embedded"


class _LiveDisplay(Protocol):
    def start(self, refresh: bool = False) -> None: ...

    def update(self, renderable: object, *, refresh: bool = False) -> None: ...

    def stop(self) -> None: ...


class _TimerHandle(Protocol):
    def start(self) -> None: ...

    def cancel(self) -> None: ...


TimerFactory = Callable[[float, Callable[[], None]], _TimerHandle]


class _DynamicRenderable:
    """每次 Rich 刷新时重新计算 elapsed / stalled 状态。"""

    def __init__(self, render: Callable[[], object]) -> None:
        self._render = render

    def __rich_console__(self, console: object, options: object) -> Iterator[object]:
        del console, options
        yield self._render()

    def snapshot(self) -> object:
        """返回当前帧，供无终端环境测试。"""
        return self._render()


def feedback_console():
    """返回 CLI 反馈专用 console。"""
    from rich.console import Console

    return Console(stderr=True)


@contextmanager
def cli_status(message: str, *, console=None, spinner: str = "dots") -> Iterator:
    """统一的短阶段 spinner。"""
    if console is None:
        console = feedback_console()
    with console.status(f"[yellow]{message}[/yellow]", spinner=spinner) as status:
        yield status


def determinate_progress(*, console=None, transient: bool = False):
    """统一的批量进度条：spinner + 描述 + 百分比 + 计数 + 耗时。"""
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    if console is None:
        console = feedback_console()
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[dim]({task.completed}/{task.total})[/dim]"),
        TimeElapsedColumn(),
        console=console,
        transient=transient,
    )


def operation_feedback_enabled(
    *,
    mode: FeedbackMode | str = FeedbackMode.AUTO,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """仅在直接 CLI 的 stderr TTY 中启用动态 operation 反馈。"""
    resolved_mode = FeedbackMode(mode)
    env = os.environ if environ is None else environ
    if resolved_mode in {FeedbackMode.MCP, FeedbackMode.COMPLETION, FeedbackMode.EMBEDDED}:
        return False
    if resolved_mode is FeedbackMode.AUTO and (
        env.get("_KAN_COMPLETE")
        or env.get("_TYPER_COMPLETE_ARGS")
        or env.get("KAN_MCP") == "1"
        or env.get("KAN_EMBEDDED") == "1"
    ):
        return False
    stream = sys.stderr if stderr is None else stderr
    return bool(stream.isatty())


def _daemon_timer(delay: float, callback: Callable[[], None]) -> Timer:
    """创建不阻止 CLI 进程退出的延迟显示计时器。"""
    timer = Timer(delay, callback)
    timer.daemon = True
    return timer


class RichOperationReporter:
    """一个 operation 对应一个 Rich Live 区域。"""

    def __init__(
        self,
        *,
        console: Any = None,
        clock: Callable[[], float] = monotonic,
        show_after: float = 0.15,
        slow_after: float = 5.0,
        stalled_after: float = 15.0,
        live_factory: Callable[..., _LiveDisplay] | None = None,
        timer_factory: TimerFactory = _daemon_timer,
    ) -> None:
        if console is None:
            console = feedback_console()
        if live_factory is None:
            from rich.live import Live

            live_factory = Live
        self._console = console
        self._clock = clock
        self._show_after = show_after
        self._slow_after = slow_after
        self._stalled_after = stalled_after
        self._live_factory = live_factory
        self._timer_factory = timer_factory
        self._lock = RLock()
        self._live: _LiveDisplay | None = None
        self._show_timer: _TimerHandle | None = None
        self._operation_id: str | None = None
        self._operation_name = ""
        self._started_at = 0.0
        self._last_meaningful_at = 0.0
        self._last_event: LifecycleEvent | None = None
        self._semantic_state: LifecycleKind | None = None
        self._closed = False
        self._last_info_event: LifecycleEvent | None = None
        self._renderable = _DynamicRenderable(lambda: self._render(self._clock()))

    def report(self, event: LifecycleEvent) -> None:
        with self._lock:
            self._accept_operation(event)
            if self._closed:
                return
            self._last_event = event
            if event.kind not in {LifecycleKind.HEARTBEAT}:
                self._last_info_event = event
            if event.kind in {LifecycleKind.PHASE, LifecycleKind.PROGRESS}:
                self._last_meaningful_at = event.occurred_at
            if event.kind in {LifecycleKind.WAIT, LifecycleKind.DEGRADED}:
                self._semantic_state = event.kind
            elif event.kind in {LifecycleKind.PHASE, LifecycleKind.PROGRESS}:
                self._semantic_state = None

            terminal = event.kind is LifecycleKind.OPERATION and event.state in {
                OperationState.SUCCEEDED,
                OperationState.FAILED,
                OperationState.CANCELLED,
            }
            if terminal:
                self._cancel_show_timer()
                if self._live is not None:
                    self._live.update(self._renderable, refresh=True)
                    self._live.stop()
                    self._live = None
                self._closed = True
                return
            self._update_display(event.occurred_at)

    def refresh(self) -> None:
        """由外部 tick 主动刷新 elapsed / slow / stalled 状态。"""
        with self._lock:
            if self._closed or self._last_event is None:
                return
            self._update_display(self._clock(), force_refresh=True)

    def close(self) -> None:
        """幂等关闭 Live，供异常清理。"""
        with self._lock:
            self._cancel_show_timer()
            if self._live is not None:
                self._live.stop()
                self._live = None
            self._closed = True

    def _accept_operation(self, event: LifecycleEvent) -> None:
        if self._operation_id is None:
            self._operation_id = event.operation_id
            self._operation_name = event.operation_name
            self._started_at = event.occurred_at - event.elapsed
            self._last_meaningful_at = event.occurred_at
        elif event.operation_id != self._operation_id:
            raise ValueError("RichOperationReporter only supports one operation")

    def _update_display(self, now: float, *, force_refresh: bool = False) -> None:
        elapsed = max(0.0, now - self._started_at)
        if self._live is None:
            if elapsed < self._show_after:
                self._schedule_delayed_show(self._show_after - elapsed)
                return
            self._cancel_show_timer()
            self._live = self._live_factory(
                self._renderable,
                console=self._console,
                refresh_per_second=10,
                transient=True,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._live.start(refresh=True)
            return
        self._live.update(self._renderable, refresh=force_refresh)

    def _schedule_delayed_show(self, delay: float) -> None:
        if self._show_timer is not None or self._closed:
            return
        self._show_timer = self._timer_factory(max(0.0, delay), self.refresh)
        self._show_timer.start()

    def _cancel_show_timer(self) -> None:
        if self._show_timer is None:
            return
        self._show_timer.cancel()
        self._show_timer = None

    def _render(self, now: float) -> object:
        from rich.text import Text

        event = self._last_event
        info = self._last_info_event
        elapsed = max(0.0, now - self._started_at)
        state, style = self._state(now)
        raw_message = (
            info.message if info is not None and info.message
            else event.message if event is not None and event.message
            else self._operation_name
        )
        message = redact_text(raw_message)
        text = Text()
        text.append(f"{state} ", style=style)
        text.append(message)
        if info is not None and info.kind is LifecycleKind.PROGRESS:
            text.append(self._progress_suffix(info), style="dim")
        text.append(f" · {elapsed:.1f}s", style="dim")
        return text

    def _state(self, now: float) -> tuple[str, str]:
        event = self._last_event
        if event is not None and event.kind is LifecycleKind.OPERATION:
            if event.state is OperationState.FAILED:
                return "失败", "bold red"
            if event.state is OperationState.SUCCEEDED:
                return "完成", "green"
            if event.state is OperationState.CANCELLED:
                return "已取消", "yellow"
        if self._semantic_state is LifecycleKind.WAIT:
            return "等待", "yellow"
        if self._semantic_state is LifecycleKind.DEGRADED:
            return "降级", "yellow"
        idle_seconds = now - self._last_meaningful_at
        if idle_seconds >= self._stalled_after:
            return "疑似停滞", "bold red"
        if idle_seconds >= self._slow_after:
            return "较慢", "yellow"
        return "处理中", "cyan"

    @staticmethod
    def _progress_suffix(event: LifecycleEvent) -> str:
        if event.total is None:
            return f" ({event.completed:g})" if event.completed is not None else ""
        if event.completed is None:
            return f" (/{event.total:g})"
        if event.total > 0:
            percentage = event.completed / event.total * 100
            return f" ({event.completed:g}/{event.total:g}, {percentage:.0f}%)"
        return f" ({event.completed:g}/{event.total:g})"


def operation_reporter(
    *,
    mode: FeedbackMode | str = FeedbackMode.AUTO,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
    console: Any = None,
    clock: Callable[[], float] = monotonic,
    show_after: float = 0.15,
    slow_after: float = 5.0,
    stalled_after: float = 15.0,
    live_factory: Callable[..., _LiveDisplay] | None = None,
    timer_factory: TimerFactory = _daemon_timer,
) -> LifecycleReporter:
    """按调用模式创建单 operation reporter；静默场景不导入 Rich Live。"""
    if not operation_feedback_enabled(mode=mode, stderr=stderr, environ=environ):
        return NullReporter()
    return RichOperationReporter(
        console=console,
        clock=clock,
        show_after=show_after,
        slow_after=slow_after,
        stalled_after=stalled_after,
        live_factory=live_factory,
        timer_factory=timer_factory,
    )

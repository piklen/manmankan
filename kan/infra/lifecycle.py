"""与渲染无关的操作生命周期事件。"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock, RLock
from time import monotonic
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

Clock = Callable[[], float]


class LifecycleKind(StrEnum):
    """生命周期事件类型。"""

    OPERATION = "operation"
    PHASE = "phase"
    PROGRESS = "progress"
    WAIT = "wait"
    DEGRADED = "degraded"
    HEARTBEAT = "heartbeat"


class OperationState(StrEnum):
    """operation 事件的状态。"""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """单个可跨线程传递的中性生命周期事件。"""

    sequence: int
    kind: LifecycleKind
    operation_id: str
    operation_name: str
    occurred_at: float
    elapsed: float
    message: str | None = None
    state: OperationState | None = None
    completed: int | float | None = None
    total: int | float | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 跨线程投递前复制并冻结，避免调用方后续修改原字典。
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


class OperationReporter(Protocol):
    """单个 operation 的生命周期事件接收端协议。"""

    def report(self, event: LifecycleEvent) -> None: ...


# 兼容更泛化的称呼；公开首选名是 OperationReporter。
LifecycleReporter = OperationReporter


class NullReporter:
    """完全静默的 reporter。"""

    __slots__ = ()

    def report(self, event: LifecycleEvent) -> None:
        del event


class CollectingReporter:
    """线程安全地收集事件，供测试和嵌入调用检查。"""

    def __init__(self) -> None:
        self._events: list[LifecycleEvent] = []
        self._lock = Lock()

    def report(self, event: LifecycleEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        with self._lock:
            return tuple(self._events)


class OperationLifecycle:
    """一个 operation 的线程安全事件源。"""

    def __init__(
        self,
        name: str,
        *,
        reporter: LifecycleReporter | None = None,
        clock: Clock = monotonic,
        operation_id: str | None = None,
    ) -> None:
        self.name = name
        self.operation_id = operation_id or uuid4().hex
        self._reporter = reporter if reporter is not None else NullReporter()
        self._clock = clock
        self._lock = RLock()
        self._sequence = 0
        self._started_at: float | None = None
        self._closed = False

    def __enter__(self) -> OperationLifecycle:
        with self._lock:
            if self._started_at is not None:
                raise RuntimeError("operation lifecycle cannot be entered twice")
            self._started_at = self._clock()
            self._emit(LifecycleKind.OPERATION, state=OperationState.STARTED)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, traceback
        if isinstance(exc, KeyboardInterrupt):
            state = OperationState.CANCELLED
        else:
            state = OperationState.FAILED if exc is not None else OperationState.SUCCEEDED
        message = str(exc) if exc is not None else None
        with self._lock:
            if not self._closed:
                self._emit(LifecycleKind.OPERATION, state=state, message=message)
                self._closed = True

    def phase(self, message: str, **details: object) -> LifecycleEvent:
        return self._emit(LifecycleKind.PHASE, message=message, details=details)

    def progress(
        self,
        completed: int | float,
        total: int | float | None = None,
        message: str | None = None,
        **details: object,
    ) -> LifecycleEvent:
        return self._emit(
            LifecycleKind.PROGRESS,
            message=message,
            completed=completed,
            total=total,
            details=details,
        )

    def wait(self, message: str, **details: object) -> LifecycleEvent:
        return self._emit(LifecycleKind.WAIT, message=message, details=details)

    def degraded(self, message: str, **details: object) -> LifecycleEvent:
        return self._emit(LifecycleKind.DEGRADED, message=message, details=details)

    def heartbeat(self, message: str | None = None, **details: object) -> LifecycleEvent:
        return self._emit(LifecycleKind.HEARTBEAT, message=message, details=details)

    def fail(self, message: str | None = None, **details: object) -> LifecycleEvent:
        """显式以失败态关闭 operation，供调用方随后转换协议层 exit。"""
        with self._lock:
            event = self._emit(
                LifecycleKind.OPERATION,
                state=OperationState.FAILED,
                message=message,
                details=details,
            )
            self._closed = True
            return event

    def _emit(
        self,
        kind: LifecycleKind,
        *,
        message: str | None = None,
        state: OperationState | None = None,
        completed: int | float | None = None,
        total: int | float | None = None,
        details: Mapping[str, object] | None = None,
    ) -> LifecycleEvent:
        with self._lock:
            if self._started_at is None:
                raise RuntimeError("operation lifecycle has not started")
            if self._closed:
                raise RuntimeError("operation lifecycle has already finished")
            now = self._clock()
            self._sequence += 1
            event = LifecycleEvent(
                sequence=self._sequence,
                kind=kind,
                operation_id=self.operation_id,
                operation_name=self.name,
                occurred_at=now,
                elapsed=max(0.0, now - self._started_at),
                message=message,
                state=state,
                completed=completed,
                total=total,
                details=details or {},
            )
            self._reporter.report(event)
            return event


@contextmanager
def operation(
    name: str,
    *,
    reporter: LifecycleReporter | None = None,
    clock: Clock = monotonic,
    operation_id: str | None = None,
) -> Iterator[OperationLifecycle]:
    """创建并完整关闭一个 operation 生命周期。"""

    with OperationLifecycle(
        name,
        reporter=reporter,
        clock=clock,
        operation_id=operation_id,
    ) as lifecycle:
        yield lifecycle

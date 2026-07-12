"""数据提供方的结构化结果与能力契约。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class FetchFailureKind(StrEnum):
    """一次 provider 拉取失败的稳定分类。"""

    EMPTY = "empty"
    INVALID = "invalid"
    INVALID_SCHEMA = "invalid_schema"
    PERMANENT = "permanent"
    CIRCUIT_OPEN = "circuit_open"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    TRANSPORT = "transport"


@dataclass(frozen=True, slots=True)
class FetchFailure:
    """可供编排层判断退避、降级和熔断的失败事实。"""

    kind: FetchFailureKind
    message: str = ""
    code: int | str | None = None
    retryable: bool = False
    retry_after: float | None = None
    affects_circuit: bool = False

    def __post_init__(self) -> None:
        if self.retry_after is not None:
            if self.retry_after <= 0:
                raise ValueError("retry_after 必须大于 0")
            if not self.retryable:
                raise ValueError("带 retry_after 的失败必须可重试")
        if self.kind in {
            FetchFailureKind.EMPTY,
            FetchFailureKind.INVALID,
            FetchFailureKind.CIRCUIT_OPEN,
            FetchFailureKind.UNAVAILABLE,
            FetchFailureKind.RATE_LIMIT,
        } and self.affects_circuit:
            raise ValueError(f"{self.kind.value} 不能计入熔断器失败")


@dataclass(frozen=True, slots=True)
class ProviderFetchResult(Generic[T]):
    """provider 单次调用结果；成功数据与失败信息严格二选一。"""

    data: T | None = None
    failure: FetchFailure | None = None
    breaker_recorded: bool = False

    def __post_init__(self) -> None:
        if (self.data is None) == (self.failure is None):
            raise ValueError("data 与 failure 必须且只能设置一个")
        if self.breaker_recorded and self.failure is not None and not self.failure.affects_circuit:
            raise ValueError("不影响熔断器的失败不能标记为已记账")

    @property
    def is_success(self) -> bool:
        return self.failure is None

    @classmethod
    def succeeded(cls, data: T, *, breaker_recorded: bool = False) -> ProviderFetchResult[T]:
        return cls(data=data, breaker_recorded=breaker_recorded)

    @classmethod
    def failed(
        cls,
        failure: FetchFailure,
        *,
        breaker_recorded: bool = False,
    ) -> ProviderFetchResult[T]:
        return cls(failure=failure, breaker_recorded=breaker_recorded)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """调度器可依赖的 provider 并发与请求能力声明。"""

    max_concurrency: int = 1
    initial_concurrency: int = 1
    max_attempts: int = 1
    timeout_seconds: float | None = None
    backoff_base_seconds: float = 0.5
    backoff_cap_seconds: float = 5.0
    rate_limit_cooldown_seconds: float = 30.0
    supports_retry_after: bool = False
    serializes_requests: bool = False

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency 必须至少为 1")
        if self.initial_concurrency < 1:
            raise ValueError("initial_concurrency 必须至少为 1")
        if self.initial_concurrency > self.max_concurrency:
            object.__setattr__(self, "initial_concurrency", self.max_concurrency)
        if self.max_attempts < 1:
            raise ValueError("max_attempts 必须至少为 1")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if self.backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds 不能小于 0")
        if self.backoff_cap_seconds < self.backoff_base_seconds:
            raise ValueError("backoff_cap_seconds 不能小于 backoff_base_seconds")
        if self.rate_limit_cooldown_seconds < 0:
            raise ValueError("rate_limit_cooldown_seconds 不能小于 0")
        if self.serializes_requests and self.max_concurrency != 1:
            raise ValueError("串行 provider 的 max_concurrency 必须为 1")

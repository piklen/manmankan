from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from kan.data.protocols import (
    DetailedKlineSource,
    LegacyKlineSourceAdapter,
    as_detailed_kline_source,
)
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)


def test_fetch_result_requires_exactly_one_data_or_failure() -> None:
    with pytest.raises(ValueError, match="必须且只能"):
        ProviderFetchResult[pd.DataFrame]()
    with pytest.raises(ValueError, match="必须且只能"):
        ProviderFetchResult(
            data=pd.DataFrame({"date": ["2026-01-01"]}),
            failure=FetchFailure(FetchFailureKind.EMPTY),
        )


def test_failure_retry_after_requires_retryable_positive_value() -> None:
    with pytest.raises(ValueError, match="必须可重试"):
        FetchFailure(FetchFailureKind.RATE_LIMIT, retry_after=1)
    with pytest.raises(ValueError, match="大于 0"):
        FetchFailure(FetchFailureKind.RATE_LIMIT, retryable=True, retry_after=0)


def test_capabilities_validate_scheduler_bounds() -> None:
    capped = ProviderCapabilities(max_concurrency=2, initial_concurrency=3)
    assert capped.initial_concurrency == 2
    with pytest.raises(ValueError, match="max_attempts"):
        ProviderCapabilities(max_attempts=0)
    with pytest.raises(ValueError, match="backoff_cap_seconds"):
        ProviderCapabilities(backoff_base_seconds=2, backoff_cap_seconds=1)


@dataclass
class _LegacySource:
    name: str = "legacy"
    priority: int = 50

    def is_available(self) -> bool:
        return True

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        del symbol, start
        return pd.DataFrame(
            {
                "date": ["2026-01-01"],
                "open": [1],
                "high": [1],
                "low": [1],
                "close": [1],
            }
        )


def test_legacy_adapter_preserves_old_source_contract() -> None:
    source = _LegacySource()
    detailed = as_detailed_kline_source(source)

    assert isinstance(detailed, LegacyKlineSourceAdapter)
    assert isinstance(detailed, DetailedKlineSource)
    assert detailed.fetch("600519", "20260101") is not None
    assert detailed.fetch_detailed("600519", "20260101").is_success

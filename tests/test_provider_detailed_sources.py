from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from kan.data import sources, tushare
from kan.data.provider_contracts import FetchFailureKind, ProviderCapabilities


def test_builtin_sources_declare_capabilities_and_detailed_fetch() -> None:
    providers = [
        tushare.TushareKlineSource(),
        sources.BaostockKlineSource(),
        sources.EastmoneyKlineSource(),
        sources.SinaKlineSource(),
        sources.TencentKlineSource(),
    ]
    for provider in providers:
        assert isinstance(provider.capabilities, ProviderCapabilities)
        assert provider.capabilities.initial_concurrency <= provider.capabilities.max_concurrency
        assert callable(provider.fetch_detailed)
    assert sources.BaostockKlineSource.capabilities.serializes_requests


def test_baostock_login_rejects_nonzero_integer_error_code(monkeypatch) -> None:
    import baostock

    result = type("LoginResult", (), {"error_code": 1001})()
    monkeypatch.setattr(sources, "_bs_logged_in", False)
    monkeypatch.setattr(baostock, "login", lambda: result)

    with pytest.raises(RuntimeError, match="error_code=1001"):
        sources._ensure_bs_login()

    assert not sources._bs_logged_in


def test_eastmoney_detailed_empty_and_schema_are_distinct(
    monkeypatch, isolated_breaker,
) -> None:
    monkeypatch.setattr("akshare.stock_zh_a_hist", lambda **kwargs: pd.DataFrame())
    empty = sources._fetch_eastmoney_detailed("600519", "20260101")
    assert empty.failure is not None
    assert empty.failure.kind == FetchFailureKind.EMPTY

    monkeypatch.setattr(
        "akshare.stock_zh_a_hist",
        lambda **kwargs: pd.DataFrame({"unexpected": [1]}),
    )
    invalid = sources._fetch_eastmoney_detailed("600519", "20260101")
    assert invalid.failure is not None
    assert invalid.failure.kind == FetchFailureKind.INVALID_SCHEMA
    assert not isolated_breaker.is_down("eastmoney")


def test_detailed_record_breaker_false_leaves_accounting_to_scheduler(
    monkeypatch, isolated_breaker,
) -> None:
    monkeypatch.setattr(
        "akshare.stock_zh_a_hist",
        MagicMock(side_effect=RuntimeError("upstream failed")),
    )
    result = sources.EastmoneyKlineSource().fetch_detailed(
        "600519", "20260101", record_breaker=False,
    )

    assert result.failure is not None
    assert result.failure.kind == FetchFailureKind.TRANSPORT
    assert not result.breaker_recorded
    assert not isolated_breaker.is_down("eastmoney")


def test_tushare_detailed_uses_single_attempt_without_sleep(
    monkeypatch, isolated_breaker,
) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tk")
    calls: list[bool] = []
    err = tushare.TushareApiError(
        code=40203,
        msg="rate limited",
        api_name="stk_factor_pro",
        retryable=True,
        retry_after=2,
        failure_kind=FetchFailureKind.RATE_LIMIT,
    )

    def fake_post(*args, **kwargs):
        del args
        calls.append(kwargs["allow_transport_retries"])
        return None, err

    monkeypatch.setattr(tushare, "_post_tushare_api", fake_post)
    monkeypatch.setattr(tushare.time, "sleep", lambda *_: (_ for _ in ()).throw(AssertionError()))

    result = tushare.TushareKlineSource().fetch_detailed("600519", "20260101")

    assert calls == [False]
    assert result.failure is not None
    assert result.failure.kind == FetchFailureKind.RATE_LIMIT
    assert result.failure.code == 40203
    assert result.failure.retry_after == 2
    assert not result.breaker_recorded
    assert not isolated_breaker.is_down("tushare")


def test_tushare_http_429_and_timeout_are_classified(monkeypatch) -> None:
    response = MagicMock()
    response.status_code = 429
    response.headers = {"Retry-After": "7"}
    session = MagicMock()
    session.post.return_value = response
    monkeypatch.setattr(tushare, "_get_session", lambda: session)

    data, error = tushare._post_tushare_api("https://example.com", "tk", "daily", {}, "x")
    assert data is None
    assert error is not None
    assert error.code == 429
    assert error.failure_kind == FetchFailureKind.RATE_LIMIT
    assert error.retry_after == 7

    session.post.side_effect = tushare.requests.Timeout("slow")
    _data, timeout = tushare._post_tushare_api("https://example.com", "tk", "daily", {}, "x")
    assert timeout is not None
    assert timeout.failure_kind == FetchFailureKind.TIMEOUT

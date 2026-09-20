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


@pytest.mark.parametrize("api_name,code,message,headers", [
    ("research_report", 40203, "无该接口权限", {}),
    ("report_rc", "40203", "无该接口权限", {
        "X-Data-Hub-Error-Retryable": "1",
        "X-Data-Hub-Retry-After": "7",
        "Retry-After": "9",
    }),
    ("research_report", 40203, "抱歉，您没有访问该接口的权限", {}),
])
def test_tushare_permission_refusal_does_not_retry_or_throttle(
    monkeypatch, isolated_breaker, api_name, code, message, headers,
) -> None:
    from kan.data.provider_batch import ProviderJob, run_provider_jobs
    from kan.data.provider_contracts import ProviderFetchResult
    from kan.data.scheduler import ProviderLane, _GlobalPermitPool

    response = MagicMock()
    response.status_code = 200
    response.headers = headers
    response.json.return_value = {"code": code, "msg": message, "data": None}
    session = MagicMock()
    session.post.return_value = response
    monkeypatch.setattr(tushare, "_get_session", lambda: session)
    failures = []

    def call():
        data, error = tushare._post_tushare_api(
            "https://example.com", "synthetic", api_name, {}, "x",
        )
        assert data is None
        assert error is not None
        assert error.code == code
        assert error.msg == message
        assert error.api_name == api_name
        assert tushare._retryable_sleep_seconds(error, 0) is None
        failure = tushare._api_error_to_failure(error)
        failures.append(failure)
        return ProviderFetchResult.failed(failure)

    caps = ProviderCapabilities(
        max_concurrency=16, initial_concurrency=16, max_attempts=2,
        backoff_base_seconds=0, backoff_cap_seconds=0,
        rate_limit_cooldown_seconds=0,
    )
    result = run_provider_jobs([ProviderJob("one", "tushare", call, caps)])
    assert result["one"].attempts == 1
    assert session.post.call_count == 1
    failure = failures[0]
    assert failure.kind == FetchFailureKind.PERMANENT
    assert not failure.retryable
    assert failure.retry_after is None
    assert not failure.affects_circuit
    assert not isolated_breaker.is_down("tushare")

    lane = ProviderLane("tushare", ProviderCapabilities(
        max_concurrency=16, initial_concurrency=16, rate_limit_cooldown_seconds=2,
    ), clock=lambda: 0)
    permits = _GlobalPermitPool(16)
    lane.record(failure)
    permits.record(failure)
    assert lane.limit == permits.limit == 16
    assert lane.blocked_until == 0


@pytest.mark.parametrize("message", [
    "频率超限(1次/小时)",
    "频率超限，接口权限详情请查看权限说明",
])
def test_tushare_rate_limit_with_permission_help_still_throttles(monkeypatch, message) -> None:
    from kan.data.scheduler import ProviderLane

    response = MagicMock()
    response.status_code = 200
    response.headers = {"Retry-After": "7"}
    response.json.return_value = {"code": 40203, "msg": message, "data": None}
    session = MagicMock()
    session.post.return_value = response
    monkeypatch.setattr(tushare, "_get_session", lambda: session)
    _, error = tushare._post_tushare_api("https://example.com", "synthetic", "daily", {}, "x")
    assert error is not None
    failure = tushare._api_error_to_failure(error)
    assert failure.kind == FetchFailureKind.RATE_LIMIT
    assert failure.retryable
    assert failure.retry_after == 7
    lane = ProviderLane("tushare", ProviderCapabilities(
        max_concurrency=16, initial_concurrency=16, rate_limit_cooldown_seconds=2,
    ), clock=lambda: 0)
    lane.record(failure)
    assert lane.limit == 8
    assert lane.blocked_until == 7

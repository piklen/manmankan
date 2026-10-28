from __future__ import annotations

from kan.data import fundamentals, shareholder
from kan.data.provider_contracts import FetchFailureKind


def _fail_post(*_args, **_kwargs):
    raise AssertionError("breaker down should fast-fail before HTTP")


def test_fundamentals_breaker_fast_fails(monkeypatch, isolated_breaker) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tk")
    monkeypatch.setattr("kan.data.tushare._post_tushare_api", _fail_post)

    isolated_breaker.record("tushare_fina", ok=False)

    assert fundamentals._fetch_tushare_fundamentals_detailed("600519").failure.kind is FetchFailureKind.CIRCUIT_OPEN


def test_shareholder_holdernumber_breaker_fast_fails(monkeypatch, isolated_breaker) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tk")
    monkeypatch.setattr("kan.data.tushare._post_tushare_api", _fail_post)

    isolated_breaker.record("tushare_holdernum", ok=False)

    result = shareholder._fetch_tushare_table_detailed(
        "600519", provider="tushare_holdernum", api_name="stk_holdernumber",
        fields_text=shareholder._HOLDERNUM_FIELDS,
    )
    assert result.failure.kind is FetchFailureKind.CIRCUIT_OPEN


def test_shareholder_top10_breaker_fast_fails(monkeypatch, isolated_breaker) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tk")
    monkeypatch.setattr("kan.data.tushare._post_tushare_api", _fail_post)

    isolated_breaker.record("tushare_top10float", ok=False)

    result = shareholder._fetch_tushare_table_detailed(
        "600519", provider="tushare_top10float", api_name="top10_floatholders",
        fields_text=shareholder._TOP10FLOAT_FIELDS,
    )
    assert result.failure.kind is FetchFailureKind.CIRCUIT_OPEN

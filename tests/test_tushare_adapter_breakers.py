from __future__ import annotations

from kan.data import fundamentals, shareholder


def _fail_post(*_args, **_kwargs):
    raise AssertionError("breaker down should fast-fail before HTTP")


def test_fundamentals_breaker_fast_fails(monkeypatch, isolated_breaker) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tk")
    monkeypatch.setattr("kan.data.tushare._post_tushare_api", _fail_post)

    isolated_breaker.record("tushare_fina", ok=False)

    assert fundamentals._fetch_tushare_fundamentals("600519") is None


def test_shareholder_holdernumber_breaker_fast_fails(monkeypatch, isolated_breaker) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tk")
    monkeypatch.setattr("kan.data.tushare._post_tushare_api", _fail_post)

    isolated_breaker.record("tushare_holdernum", ok=False)

    assert shareholder._fetch_tushare_holdernumber("600519") is None


def test_shareholder_top10_breaker_fast_fails(monkeypatch, isolated_breaker) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tk")
    monkeypatch.setattr("kan.data.tushare._post_tushare_api", _fail_post)

    isolated_breaker.record("tushare_top10float", ok=False)

    assert shareholder._fetch_tushare_top10float("600519") is None

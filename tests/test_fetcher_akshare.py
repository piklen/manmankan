"""akshare 双源并发 fallback + no_proxy 代理隔离测试

历史背景 `_fetch_*` 搬到 kan.data.sources · monkeypatch 走 sources namespace
(`_fetch_via_akshare` 通过 module globals 查名字 · patch source location 才生效)。
"""

import os

import pandas as pd
import pytest

from kan.data import fetcher, sources


@pytest.fixture
def raw_df():
    """_fetch_* 返回的 raw DataFrame（英文列 · normalize 前形态）."""
    return pd.DataFrame({
        "date": ["2026-04-29", "2026-04-30"],
        "open": [100.0, 101.0],
        "high": [101.5, 102.5],
        "low": [99.5, 100.5],
        "close": [101.0, 102.0],
        "volume": [10000, 11000],
        "amount": [1e6, 1.1e6],
    })


def test_via_akshare_eastmoney_wins_when_sina_none(raw_df, monkeypatch):
    """新浪返 None · 东财出数 · 结果标 eastmoney."""
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_eastmoney", lambda *a, **kw: raw_df)

    result = sources._fetch_via_akshare("600519", "20260101")
    assert result is not None
    df, source = result
    assert source == "eastmoney"
    assert len(df) == 2


def test_via_akshare_sina_wins_when_eastmoney_none(raw_df, monkeypatch):
    """东财返 None · 新浪出数 · 结果标 sina."""
    monkeypatch.setattr(sources, "_fetch_eastmoney", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: raw_df)

    result = sources._fetch_via_akshare("600519", "20260101")
    assert result is not None
    _, source = result
    assert source == "sina"


def test_via_akshare_both_fail_returns_none(monkeypatch):
    """双源都返 None · _fetch_via_akshare 返 None（上层降级腾讯）."""
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_eastmoney", lambda *a, **kw: None)

    assert sources._fetch_via_akshare("600519", "20260101") is None


def test_via_akshare_both_succeed_returns_one(raw_df, monkeypatch):
    """双源都出数 · 返回其一（race · 非确定）· source 合法."""
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: raw_df)
    monkeypatch.setattr(sources, "_fetch_eastmoney", lambda *a, **kw: raw_df)

    result = sources._fetch_via_akshare("600519", "20260101")
    assert result is not None
    df, source = result
    assert source in ("sina", "eastmoney")
    assert len(df) == 2


def test_via_akshare_source_exception_skipped(raw_df, monkeypatch):
    """一个源抛异常 · 不外泄 · 另一个源仍可中标."""
    def boom(*a, **kw):
        raise RuntimeError("source blew up")

    monkeypatch.setattr(sources, "_fetch_eastmoney", boom)
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: raw_df)

    result = sources._fetch_via_akshare("600519", "20260101")
    assert result is not None
    _, source = result
    assert source == "sina"


# ── _ensure_no_proxy ──────────────────────────────────────────────────


@pytest.fixture
def reset_no_proxy(monkeypatch):
    """复位模块 flag + 清空相关 env · monkeypatch 测试结束自动还原."""
    monkeypatch.setattr(fetcher, "_no_proxy_configured", False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("KAN_KEEP_PROXY", raising=False)


def test_ensure_no_proxy_appends_data_source_domains(reset_no_proxy):
    """数据源域名全部并入 no_proxy."""
    fetcher._ensure_no_proxy()
    no_proxy = os.environ.get("no_proxy", "")
    for domain in fetcher._DATA_SOURCE_DOMAINS:
        assert domain in no_proxy


def test_ensure_no_proxy_preserves_user_value(reset_no_proxy, monkeypatch):
    """不 clobber 用户已设的 no_proxy · 取并集."""
    monkeypatch.setenv("no_proxy", "internal.corp")
    fetcher._ensure_no_proxy()
    no_proxy = os.environ.get("no_proxy", "")
    assert "internal.corp" in no_proxy
    assert "eastmoney.com" in no_proxy


def test_ensure_no_proxy_skips_when_keep_proxy_set(reset_no_proxy, monkeypatch):
    """KAN_KEEP_PROXY 置位 · 整体跳过 · 不动 no_proxy."""
    monkeypatch.setenv("KAN_KEEP_PROXY", "1")
    fetcher._ensure_no_proxy()
    assert os.environ.get("no_proxy", "") == ""


def test_ensure_no_proxy_no_duplicate_when_domain_preset(reset_no_proxy, monkeypatch):
    """env 已含某数据源域名 · 不重复 append."""
    monkeypatch.setenv("no_proxy", "eastmoney.com")
    fetcher._ensure_no_proxy()
    no_proxy = os.environ.get("no_proxy", "")
    assert no_proxy.count("eastmoney.com") == 1
    assert "sina.com.cn" in no_proxy


def test_ensure_no_proxy_idempotent(reset_no_proxy):
    """重复调用安全 · 模块 flag 守一次性."""
    fetcher._ensure_no_proxy()
    first = os.environ.get("no_proxy", "")
    fetcher._ensure_no_proxy()
    assert os.environ.get("no_proxy", "") == first

"""MetricsSourceChain + _builtin_sources 截面指标注册表 单元测试 (地基-1)。

覆盖 (对齐 test_source_chain.py · 签名改 fetch(trade_date, symbols)):
- chain priority 排序 / 单源 / fallback / race / is_available 跳过 / 异常吞 / 全失败 None
- register/clear_user_metrics_sources 影响 default_metrics_chain
"""
from __future__ import annotations

import pandas as pd
import pytest

from kan.data._builtin_sources import (
    clear_user_metrics_sources,
    register_metrics_source,
)
from kan.data.source_chain import (
    MetricsSourceChain,
    default_metrics_chain,
    reset_default_metrics_chain,
)


class _FakeMetricsSource:
    """测试用截面源 · is_available / fetch 可注入 · 不依赖网络。"""

    def __init__(
        self, name, priority, *, available=True, df=None,
        fetch_exc=None, available_exc=None,
    ):
        self.name = name
        self.priority = priority
        self._available = available
        self._df = df
        self._fetch_exc = fetch_exc
        self._available_exc = available_exc
        self.fetch_calls = 0
        self.last_args = None

    def is_available(self) -> bool:
        if self._available_exc is not None:
            raise self._available_exc
        return self._available

    def fetch(self, trade_date, symbols=None):
        self.fetch_calls += 1
        self.last_args = (trade_date, symbols)
        if self._fetch_exc is not None:
            raise self._fetch_exc
        return self._df


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({"symbol": ["600519"], "pe_ttm": [20.04], "pb": [6.19]})


# ── priority 排序 ─────────────────────────────────────────────────────


def test_sources_sorted_by_priority():
    a = _FakeMetricsSource("a", 30)
    b = _FakeMetricsSource("b", 10)
    c = _FakeMetricsSource("c", 20)
    chain = MetricsSourceChain([a, b, c])
    assert [s.name for s in chain.sources] == ["b", "c", "a"]


# ── 单源 group · trade_date/symbols 透传 ──────────────────────────────


def test_single_source_success_passes_args(sample_df):
    src = _FakeMetricsSource("only", 10, df=sample_df)
    chain = MetricsSourceChain([src])
    result = chain.fetch("20260529", ["600519"])
    assert result is not None
    df, name = result
    assert name == "only"
    assert df.iloc[0]["symbol"] == "600519"
    assert src.last_args == ("20260529", ["600519"])  # 截面签名透传


def test_single_source_unavailable_no_fetch():
    src = _FakeMetricsSource("only", 10, available=False)
    chain = MetricsSourceChain([src])
    assert chain.fetch("20260529") is None
    assert src.fetch_calls == 0


def test_single_source_none_returns_none():
    src = _FakeMetricsSource("only", 10, df=None)
    chain = MetricsSourceChain([src])
    assert chain.fetch("20260529") is None


# ── 多 priority fallback ──────────────────────────────────────────────


def test_fallback_to_lower_priority(sample_df):
    top = _FakeMetricsSource("top", 10, df=None)
    backup = _FakeMetricsSource("backup", 20, df=sample_df)
    chain = MetricsSourceChain([backup, top])
    result = chain.fetch("20260529")
    assert result is not None
    assert result[1] == "backup"
    assert top.fetch_calls == 1


def test_top_success_skips_lower(sample_df):
    top = _FakeMetricsSource("top", 10, df=sample_df)
    backup = _FakeMetricsSource("backup", 20, df=sample_df)
    chain = MetricsSourceChain([backup, top])
    result = chain.fetch("20260529")
    assert result[1] == "top"
    assert backup.fetch_calls == 0


def test_all_fail_returns_none():
    a = _FakeMetricsSource("a", 10, df=None)
    b = _FakeMetricsSource("b", 20, df=None)
    chain = MetricsSourceChain([a, b])
    assert chain.fetch("20260529") is None


# ── 同 priority race ──────────────────────────────────────────────────


def test_race_one_succeeds(sample_df):
    win = _FakeMetricsSource("win", 30, df=sample_df)
    lose = _FakeMetricsSource("lose", 30, df=None)
    chain = MetricsSourceChain([win, lose])
    assert chain.fetch("20260529")[1] == "win"


def test_race_both_fail_falls_back(sample_df):
    a = _FakeMetricsSource("a", 30, df=None)
    b = _FakeMetricsSource("b", 30, df=None)
    fb = _FakeMetricsSource("fb", 40, df=sample_df)
    chain = MetricsSourceChain([a, b, fb])
    assert chain.fetch("20260529")[1] == "fb"


# ── 异常防御 ──────────────────────────────────────────────────────────


def test_fetch_exception_falls_back(sample_df):
    boom = _FakeMetricsSource("boom", 10, fetch_exc=RuntimeError("oops"))
    backup = _FakeMetricsSource("backup", 20, df=sample_df)
    chain = MetricsSourceChain([boom, backup])
    assert chain.fetch("20260529")[1] == "backup"


def test_is_available_exception_treated_false(sample_df):
    poison = _FakeMetricsSource(
        "poison", 10, available_exc=RuntimeError("dirty"), df=sample_df,
    )
    backup = _FakeMetricsSource("backup", 20, df=sample_df)
    chain = MetricsSourceChain([poison, backup])
    result = chain.fetch("20260529")
    assert result[1] == "backup"
    assert poison.fetch_calls == 0


# ── default_metrics_chain + 注册表 ────────────────────────────────────


def test_default_chain_includes_tushare_metrics():
    reset_default_metrics_chain()
    chain = default_metrics_chain()
    assert "tushare_metrics" in {s.name for s in chain.sources}


def test_register_user_metrics_source(sample_df):
    clear_user_metrics_sources()

    class _My:
        name = "user_metrics_test"
        priority = 50
        def is_available(self):
            return True
        def fetch(self, trade_date, symbols=None):
            return sample_df

    register_metrics_source(_My())
    try:
        names = [s.name for s in default_metrics_chain().sources]
        assert "user_metrics_test" in names
    finally:
        clear_user_metrics_sources()


def test_clear_user_metrics_sources(sample_df):
    clear_user_metrics_sources()

    class _Once:
        name = "once_metrics"
        priority = 60
        def is_available(self):
            return True
        def fetch(self, trade_date, symbols=None):
            return sample_df

    register_metrics_source(_Once())
    assert any(s.name == "once_metrics" for s in default_metrics_chain().sources)
    clear_user_metrics_sources()
    assert not any(s.name == "once_metrics" for s in default_metrics_chain().sources)
    # 内置仍在
    assert any(s.name == "tushare_metrics" for s in default_metrics_chain().sources)


def test_user_metrics_source_can_take_priority(sample_df):
    """用户源 priority=5 (<tushare_metrics 10) · 顶档 · chain 首位走它。"""
    clear_user_metrics_sources()

    class _Top:
        name = "user_top_metrics"
        priority = 5
        def is_available(self):
            return True
        def fetch(self, trade_date, symbols=None):
            return sample_df

    register_metrics_source(_Top())
    try:
        assert default_metrics_chain().sources[0].name == "user_top_metrics"
    finally:
        clear_user_metrics_sources()

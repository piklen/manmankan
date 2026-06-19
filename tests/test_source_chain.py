"""KlineSourceChain + _builtin_sources 注册表 单元测试 (历史背景)。

覆盖:
- chain priority 排序 (构造时 sort · 同 priority 保持注册序)
- 单源 group 顺利 fetch
- 同 priority 多源 race (一败一成 / 双成 / 双败 → fallback 下一档)
- is_available=False 跳过 (不调 fetch)
- fetch / is_available 异常防御性吞掉
- 全失败返 None (不抛)
- register/clear_user_kline_sources 影响 default_kline_chain
"""
from __future__ import annotations

import subprocess
import sys
import time

import pandas as pd
import pytest

from kan.data._builtin_sources import (
    builtin_kline_sources,
    clear_user_kline_sources,
    register_kline_source,
)
from kan.data.source_chain import (
    KlineSourceChain,
    default_kline_chain,
    reset_default_chain,
)

# ── 测试用 fake KlineSource ────────────────────────────────────────────


class _FakeSource:
    """测试用 source · is_available / fetch 可注入 · 不依赖网络。"""

    def __init__(
        self,
        name: str,
        priority: int,
        *,
        available: bool = True,
        df: pd.DataFrame | None = None,
        fetch_exc: Exception | None = None,
        available_exc: Exception | None = None,
    ) -> None:
        self.name = name
        self.priority = priority
        self._available = available
        self._df = df
        self._fetch_exc = fetch_exc
        self._available_exc = available_exc
        self.fetch_calls = 0
        self.available_calls = 0

    def is_available(self) -> bool:
        self.available_calls += 1
        if self._available_exc is not None:
            raise self._available_exc
        return self._available

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        self.fetch_calls += 1
        if self._fetch_exc is not None:
            raise self._fetch_exc
        return self._df


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2026-05-08"], "open": [100.0], "high": [101.0],
        "low": [99.0], "close": [100.5], "volume": [10000], "amount": [1e6],
    })


# ── priority 排序 ─────────────────────────────────────────────────────


def test_sources_sorted_by_priority_on_construct():
    """构造时按 priority 升序排序 · 不论传入顺序。"""
    a = _FakeSource("a", priority=30)
    b = _FakeSource("b", priority=10)
    c = _FakeSource("c", priority=20)
    chain = KlineSourceChain([a, b, c])
    names = [s.name for s in chain.sources]
    assert names == ["b", "c", "a"]


def test_same_priority_preserves_registration_order():
    """同 priority 保持注册顺序 · 用于 race 候选稳定。"""
    a = _FakeSource("first", priority=30)
    b = _FakeSource("second", priority=30)
    chain = KlineSourceChain([a, b])
    assert [s.name for s in chain.sources] == ["first", "second"]


# ── 单源 group ────────────────────────────────────────────────────────


def test_single_source_fetch_success(sample_df):
    src = _FakeSource("only", priority=10, df=sample_df)
    chain = KlineSourceChain([src])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    df, name = result
    assert name == "only"
    assert len(df) == 1
    assert src.fetch_calls == 1


def test_single_source_unavailable_returns_none():
    src = _FakeSource("only", priority=10, available=False)
    chain = KlineSourceChain([src])
    assert chain.fetch("600519", "20260101") is None
    assert src.fetch_calls == 0  # is_available=False · 不调 fetch


def test_single_source_returns_none_no_fallback_returns_none():
    src = _FakeSource("only", priority=10, df=None)
    chain = KlineSourceChain([src])
    assert chain.fetch("600519", "20260101") is None


# ── 多 priority fallback ──────────────────────────────────────────────


def test_fallback_to_lower_priority_when_top_fails(sample_df):
    top = _FakeSource("top", priority=10, df=None)
    backup = _FakeSource("backup", priority=20, df=sample_df)
    chain = KlineSourceChain([backup, top])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "backup"
    assert top.fetch_calls == 1
    assert backup.fetch_calls == 1


def test_top_priority_success_skips_lower(sample_df):
    top = _FakeSource("top", priority=10, df=sample_df)
    backup = _FakeSource("backup", priority=20, df=sample_df)
    chain = KlineSourceChain([backup, top])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "top"
    assert top.fetch_calls == 1
    assert backup.fetch_calls == 0


def test_all_fail_returns_none():
    a = _FakeSource("a", priority=10, df=None)
    b = _FakeSource("b", priority=20, df=None)
    c = _FakeSource("c", priority=30, df=None)
    chain = KlineSourceChain([a, b, c])
    assert chain.fetch("600519", "20260101") is None


# ── 同 priority race ──────────────────────────────────────────────────


def test_race_one_succeeds_one_fails(sample_df):
    """同 priority 双源 · 一败一成 · 成功源中标。"""
    win = _FakeSource("winner", priority=30, df=sample_df)
    lose = _FakeSource("loser", priority=30, df=None)
    chain = KlineSourceChain([win, lose])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "winner"


def test_race_both_succeed_one_wins(sample_df):
    """同 priority 双源都返 df · 返其一 (race 非确定)。"""
    a = _FakeSource("a", priority=30, df=sample_df)
    b = _FakeSource("b", priority=30, df=sample_df)
    chain = KlineSourceChain([a, b])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name in {"a", "b"}


def test_race_slow_loser_does_not_hold_process_open():
    """慢 loser 不应在 race 已中标后拖住 CLI 进程退出。"""
    slow_loser_sleep = 20.0
    # timeout 覆盖解释器启动和 pandas/import 成本，但仍短于慢源 sleep；
    # 如果 race 退回到非 daemon worker，这里仍会被卡住并失败。
    exit_timeout = 12.0
    code = r"""
import time
import pandas as pd
from kan.data.source_chain import KlineSourceChain

class Slow:
    name = "slow"
    priority = 30
    def is_available(self):
        return True
    def fetch(self, symbol, start):
        time.sleep(SLOW_LOSER_SLEEP)
        return None

class Fast:
    name = "fast"
    priority = 30
    def is_available(self):
        return True
    def fetch(self, symbol, start):
        return pd.DataFrame({"date": ["2026-05-08"], "close": [1.0]})

result = KlineSourceChain([Slow(), Fast()]).fetch("600519", "20260101")
assert result is not None
assert result[1] == "fast"
""".replace("SLOW_LOSER_SLEEP", str(slow_loser_sleep))
    started = time.monotonic()
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=exit_timeout,
    )
    assert time.monotonic() - started < exit_timeout


def test_race_both_fail_falls_back(sample_df):
    """同 priority 双源都失败 · 降级到下一 priority。"""
    a = _FakeSource("a", priority=30, df=None)
    b = _FakeSource("b", priority=30, df=None)
    fallback = _FakeSource("fb", priority=40, df=sample_df)
    chain = KlineSourceChain([a, b, fallback])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "fb"


def test_race_exception_swallowed_other_wins(sample_df):
    """race 一源抛异常 · 不外泄 · 另一源中标。"""
    boom = _FakeSource("boom", priority=30, fetch_exc=RuntimeError("blew up"))
    win = _FakeSource("win", priority=30, df=sample_df)
    chain = KlineSourceChain([boom, win])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "win"


# ── 异常防御性 ────────────────────────────────────────────────────────


def test_fetch_exception_swallowed_falls_back(sample_df):
    boom = _FakeSource("boom", priority=10, fetch_exc=RuntimeError("oops"))
    backup = _FakeSource("backup", priority=20, df=sample_df)
    chain = KlineSourceChain([boom, backup])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "backup"


def test_is_available_exception_treated_as_false(sample_df):
    """is_available 抛异常 → chain 视同 False · 跳过此源 · 不破整链。"""
    poison = _FakeSource(
        "poison", priority=10, available_exc=RuntimeError("dirty impl"), df=sample_df,
    )
    backup = _FakeSource("backup", priority=20, df=sample_df)
    chain = KlineSourceChain([poison, backup])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "backup"
    assert poison.fetch_calls == 0  # is_available 异常 · 不调 fetch


# ── 跳过不可用源 ──────────────────────────────────────────────────────


def test_unavailable_source_skipped_no_fetch(sample_df):
    unavail = _FakeSource("unavail", priority=10, available=False, df=sample_df)
    backup = _FakeSource("backup", priority=20, df=sample_df)
    chain = KlineSourceChain([unavail, backup])
    result = chain.fetch("600519", "20260101")
    assert result is not None
    _, name = result
    assert name == "backup"
    assert unavail.fetch_calls == 0


def test_all_sources_unavailable_returns_none():
    a = _FakeSource("a", priority=10, available=False)
    b = _FakeSource("b", priority=20, available=False)
    chain = KlineSourceChain([a, b])
    assert chain.fetch("600519", "20260101") is None


# ── default_kline_chain + _builtin_sources 注册表 ──────────────────────


def test_default_chain_includes_builtin_sources():
    reset_default_chain()
    chain = default_kline_chain()
    names = {s.name for s in chain.sources}
    assert {"tushare", "baostock", "eastmoney", "sina", "tencent"}.issubset(names)


def test_default_chain_priority_order():
    """内置源 priority 约定 · tushare(10) < baostock(20) < em/sina(30) < tencent(40)。"""
    reset_default_chain()
    chain = default_kline_chain()
    by_name = {s.name: s.priority for s in chain.sources}
    assert by_name["tushare"] < by_name["baostock"]
    assert by_name["baostock"] < by_name["eastmoney"]
    assert by_name["eastmoney"] == by_name["sina"]  # 同 priority race
    assert by_name["sina"] < by_name["tencent"]


def test_register_user_source_appears_in_default_chain(sample_df):
    """register_kline_source 后 · default chain 含新源。"""
    clear_user_kline_sources()  # 确保起始干净

    class _MySource:
        name = "user_test"
        priority = 50
        def is_available(self) -> bool:
            return True
        def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
            return sample_df

    src = _MySource()
    register_kline_source(src)
    try:
        chain = default_kline_chain()
        names = [s.name for s in chain.sources]
        assert "user_test" in names
    finally:
        clear_user_kline_sources()  # 不污染其他测试


def test_clear_user_sources_removes_them(sample_df):
    """clear_user_kline_sources 清空用户源 · 内置源保留。"""
    clear_user_kline_sources()

    class _OnceSource:
        name = "once"
        priority = 60
        def is_available(self) -> bool:
            return True
        def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
            return sample_df

    register_kline_source(_OnceSource())
    assert any(s.name == "once" for s in default_kline_chain().sources)

    clear_user_kline_sources()
    assert not any(s.name == "once" for s in default_kline_chain().sources)
    # 内置仍在
    assert any(s.name == "tushare" for s in default_kline_chain().sources)


def test_builtin_includes_user_sources_in_factory(sample_df):
    """builtin_kline_sources() 同样含已注册用户源 (chain 构造时取这个 list)。"""
    clear_user_kline_sources()

    class _U:
        name = "u_factory"
        priority = 55
        def is_available(self) -> bool:
            return True
        def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
            return sample_df

    register_kline_source(_U())
    try:
        names = [s.name for s in builtin_kline_sources()]
        assert "u_factory" in names
    finally:
        clear_user_kline_sources()


def test_user_source_can_take_priority_over_builtin(sample_df):
    """用户源 priority=5 (<tushare 10) · 顶档 · 实际 chain 调用走它。

    场景: 用户接入更稳定的私有数据源 · 想顶替 tushare。
    """
    clear_user_kline_sources()

    class _TopSource:
        name = "user_top"
        priority = 5  # 顶档 (内置最高 tushare=10)
        def is_available(self) -> bool:
            return True
        def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
            return sample_df

    register_kline_source(_TopSource())
    try:
        chain = default_kline_chain()
        first = chain.sources[0]
        assert first.name == "user_top"
    finally:
        clear_user_kline_sources()

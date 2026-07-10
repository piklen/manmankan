"""ThemeConstituentSource Protocol + Chain 测试 (Phase 2)。

覆盖:
- chain priority sort / fallback / 全失败 None
- ThsConstituentSource / EmConstituentSource fetch + is_available (含熔断)
- register / clear user constituent sources
- boards.get_theme_constituents 集成 (走 chain · cache + 熔断器 error 文案)
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from kan.core.models import Theme
from kan.data import concepts
from kan.data.boards import ThemeDataUnavailableError, get_theme_constituents
from kan.data.theme_constituents import (
    EmConstituentSource,
    ThemeConstituentSourceChain,
    ThsConstituentSource,
    clear_user_theme_constituent_sources,
    default_theme_constituent_chain,
    register_theme_constituent_source,
    reset_default_theme_constituent_chain,
)

# ── 测试用 fake source ────────────────────────────────────────────────


class _FakeConsSource:
    def __init__(self, name: str, priority: int, *, available: bool = True,
                 pairs: list[tuple[str, str]] | None = None,
                 fetch_exc: Exception | None = None) -> None:
        self.name = name
        self.priority = priority
        self._available = available
        self._pairs = pairs
        self._fetch_exc = fetch_exc
        self.fetch_calls = 0

    def is_available(self) -> bool:
        return self._available

    def fetch(self, theme: Theme) -> list[tuple[str, str]] | None:
        self.fetch_calls += 1
        if self._fetch_exc is not None:
            raise self._fetch_exc
        return self._pairs


@pytest.fixture
def sample_theme() -> Theme:
    return Theme(code="886108", name="AI应用", source="ths", size=None)


@pytest.fixture(autouse=True)
def clean_user_sources():
    """每测试前后清空用户源 · 防污染。"""
    clear_user_theme_constituent_sources()
    yield
    clear_user_theme_constituent_sources()


# ── chain priority sort + fallback ────────────────────────────────────


def test_chain_sorted_by_priority(sample_theme):
    a = _FakeConsSource("a", priority=30)
    b = _FakeConsSource("b", priority=10)
    c = _FakeConsSource("c", priority=20)
    chain = ThemeConstituentSourceChain([a, b, c])
    assert [s.name for s in chain.sources] == ["b", "c", "a"]


def test_chain_top_priority_wins(sample_theme):
    pairs = [("600519", "贵州茅台")]
    top = _FakeConsSource("top", priority=10, pairs=pairs)
    backup = _FakeConsSource("backup", priority=20, pairs=pairs)
    chain = ThemeConstituentSourceChain([backup, top])
    result = chain.fetch(sample_theme)
    assert result is not None
    got_pairs, name = result
    assert name == "top"
    assert got_pairs == pairs
    assert backup.fetch_calls == 0


def test_chain_fallback_when_top_returns_none(sample_theme):
    pairs = [("600519", "贵州茅台")]
    top = _FakeConsSource("top", priority=10, pairs=None)
    backup = _FakeConsSource("backup", priority=20, pairs=pairs)
    chain = ThemeConstituentSourceChain([backup, top])
    result = chain.fetch(sample_theme)
    assert result is not None
    got_pairs, name = result
    assert name == "backup"
    assert got_pairs == pairs


def test_chain_all_fail_returns_none(sample_theme):
    a = _FakeConsSource("a", priority=10, pairs=None)
    b = _FakeConsSource("b", priority=20, pairs=None)
    chain = ThemeConstituentSourceChain([a, b])
    assert chain.fetch(sample_theme) is None


def test_chain_fetch_exception_swallowed(sample_theme):
    pairs = [("600519", "贵州茅台")]
    boom = _FakeConsSource("boom", priority=10,
                           fetch_exc=RuntimeError("source blew up"))
    backup = _FakeConsSource("backup", priority=20, pairs=pairs)
    chain = ThemeConstituentSourceChain([boom, backup])
    result = chain.fetch(sample_theme)
    assert result is not None
    _, name = result
    assert name == "backup"


def test_chain_unavailable_skipped(sample_theme):
    pairs = [("600519", "贵州茅台")]
    unavail = _FakeConsSource("unavail", priority=10, available=False, pairs=pairs)
    backup = _FakeConsSource("backup", priority=20, pairs=pairs)
    chain = ThemeConstituentSourceChain([unavail, backup])
    result = chain.fetch(sample_theme)
    assert result is not None
    _, name = result
    assert name == "backup"
    assert unavail.fetch_calls == 0


# ── Real source class · ThsConstituentSource ──────────────────────────


def test_ths_source_returns_pairs(sample_theme):
    """ThsConstituentSource.fetch 调内部适配器 · 返回 pairs。"""
    mock_df = pd.DataFrame({
        "stock_code": ["600519", "000858"],
        "short_name": ["贵州茅台", "五粮液"],
    })
    src = ThsConstituentSource()
    with patch.object(concepts, "fetch_ths_constituents", return_value=mock_df):
        pairs = src.fetch(sample_theme)
    assert pairs == [("600519", "贵州茅台"), ("000858", "五粮液")]


def test_ths_source_empty_returns_none(sample_theme):
    src = ThsConstituentSource()
    with patch.object(concepts, "fetch_ths_constituents", return_value=pd.DataFrame()):
        assert src.fetch(sample_theme) is None


def test_ths_source_exception_returns_none(sample_theme):
    src = ThsConstituentSource()
    with patch.object(concepts, "fetch_ths_constituents",
               side_effect=RuntimeError("network")):
        assert src.fetch(sample_theme) is None


# ── Real source class · EmConstituentSource ───────────────────────────


def test_em_source_returns_pairs_and_records_breaker_ok(sample_theme, isolated_breaker):
    mock_df = pd.DataFrame({
        "stock_code": ["600519"],
        "short_name": ["贵州茅台"],
    })
    src = EmConstituentSource()
    with patch.object(concepts, "fetch_em_constituents", return_value=mock_df):
        pairs = src.fetch(sample_theme)
    assert pairs == [("600519", "贵州茅台")]
    assert not isolated_breaker.is_down("em_push2_concept")


def test_em_source_exception_records_breaker_down(sample_theme, isolated_breaker):
    src = EmConstituentSource()
    with patch.object(concepts, "fetch_em_constituents",
               side_effect=RuntimeError("push2 banned")):
        assert src.fetch(sample_theme) is None
    assert isolated_breaker.is_down("em_push2_concept")


def test_em_source_name_miss_does_not_trip_global_breaker(sample_theme, isolated_breaker):
    src = EmConstituentSource()
    with patch.object(
        concepts,
        "fetch_em_constituents",
        side_effect=LookupError("unmapped theme"),
    ):
        assert src.fetch(sample_theme) is None
    assert not isolated_breaker.is_down("em_push2_concept")


def test_em_source_unavailable_when_breaker_down(sample_theme, isolated_breaker):
    """em_push2_concept 熔断中 · is_available 返 False (chain skip)。"""
    isolated_breaker.record("em_push2_concept", ok=False)
    src = EmConstituentSource()
    assert not src.is_available()


# ── default chain + 注册表 ────────────────────────────────────────────


def test_default_chain_includes_builtin():
    reset_default_theme_constituent_chain()
    chain = default_theme_constituent_chain()
    names = {s.name for s in chain.sources}
    assert {"ths_constituent", "em_push2_concept"}.issubset(names)


def test_default_chain_priority_order():
    reset_default_theme_constituent_chain()
    chain = default_theme_constituent_chain()
    by_name = {s.name: s.priority for s in chain.sources}
    assert by_name["ths_constituent"] < by_name["em_push2_concept"]


def test_register_user_source(sample_theme):
    pairs = [("600519", "贵州茅台")]

    class _U:
        name = "u_cons"
        priority = 5  # 顶档
        def is_available(self) -> bool:
            return True
        def fetch(self, theme: Theme) -> list[tuple[str, str]] | None:
            return pairs

    register_theme_constituent_source(_U())
    chain = default_theme_constituent_chain()
    assert chain.sources[0].name == "u_cons"


# ── boards.get_theme_constituents 集成 (chain + cache + error 文案) ────


@pytest.fixture
def temp_boards_dir(tmp_path, monkeypatch):
    from kan.data import boards
    monkeypatch.setattr(boards, "BOARDS_DIR", tmp_path)
    return tmp_path


def test_boards_uses_chain_ths_path(sample_theme, temp_boards_dir):
    """boards.get_theme_constituents 走 chain · THS 命中 · 落 cache。"""
    mock_df = pd.DataFrame({
        "stock_code": ["600519", "000858"],
        "short_name": ["贵州茅台", "五粮液"],
    })
    with patch.object(concepts, "fetch_ths_constituents", return_value=mock_df):
        pairs = get_theme_constituents(sample_theme, force=True)
    assert pairs == [("600519", "贵州茅台"), ("000858", "五粮液")]
    # cache 文件名 cons_THS<code>.json (src_prefix='THS' 因 theme.source='ths')
    assert (temp_boards_dir / f"cons_THS{sample_theme.code}.json").exists()


def test_boards_falls_back_to_em(sample_theme, temp_boards_dir, isolated_breaker):
    """THS 失败 · EM 命中 · chain 自动 fallback。"""
    mock_em_df = pd.DataFrame({
        "stock_code": ["600519"],
        "short_name": ["贵州茅台"],
    })
    with patch.object(concepts, "fetch_ths_constituents",
               side_effect=RuntimeError("ths down")), \
         patch.object(concepts, "fetch_em_constituents", return_value=mock_em_df):
        pairs = get_theme_constituents(sample_theme, force=True)
    assert pairs == [("600519", "贵州茅台")]


def test_boards_raises_when_em_breaker_down(sample_theme, temp_boards_dir,
                                              isolated_breaker):
    """THS 失败 + EM 熔断 → 抛 ThemeDataUnavailableError 含 '5min 熔断' 文案。"""
    isolated_breaker.record("em_push2_concept", ok=False)
    with patch.object(concepts, "fetch_ths_constituents",
               side_effect=RuntimeError("ths down")), \
         pytest.raises(ThemeDataUnavailableError, match="5min 熔断"):
        get_theme_constituents(sample_theme, force=True)


def test_boards_raises_when_all_sources_fail(sample_theme, temp_boards_dir,
                                                isolated_breaker):
    """THS 失败 + EM 也失败 · chain 全 None · 抛 ThemeDataUnavailableError。"""
    with patch.object(concepts, "fetch_ths_constituents",
               side_effect=RuntimeError("ths down")), \
         patch.object(concepts, "fetch_em_constituents",
               side_effect=RuntimeError("em down")), pytest.raises(ThemeDataUnavailableError):
        get_theme_constituents(sample_theme, force=True)

"""StockSet 抽象 + 4 实现 + factory 单元测试。

不真跑数据获取 (网络 / 文件系统全部 mock)，只验证:
- Protocol 契约 (codes / pairs / name 都暴露)
- 构造器懒加载 (init 时不触发 IO)
- factory 互斥逻辑
- pairs/codes 返回独立 list (不让外部 mutate 内部状态)
"""
from __future__ import annotations

import pytest

from kan.core.stock_set import (
    HotRankSet,
    IndustrySet,
    StockSet,
    ThemeSet,
    WatchlistSet,
    from_flags,
)

# ─────────────── Protocol 契约 ───────────────


@pytest.mark.parametrize(
    "instance",
    [
        WatchlistSet(_pairs=[("600519", "贵州茅台")]),
        HotRankSet(mode="rank", _pairs=[("000858", "五粮液")]),
        ThemeSet(theme="AI", _pairs=[("002230", "科大讯飞")]),
        IndustrySet(industry="白酒", _pairs=[("600519", "贵州茅台")]),
    ],
)
def test_satisfies_stock_set_protocol(instance):
    """4 个实现都满足 StockSet Protocol (runtime_checkable)。"""
    assert isinstance(instance, StockSet), f"{type(instance).__name__} 不满足 Protocol"
    # name 字段必存在
    assert isinstance(instance.name, str) and instance.name
    # codes / pairs 返回 list
    assert isinstance(instance.codes(), list)
    assert isinstance(instance.pairs(), list)


# ─────────────── WatchlistSet ───────────────


def test_watchlist_set_lazy_load(monkeypatch):
    """构造 WatchlistSet 不触发 storage 读取 (lazy)。"""
    calls = {"n": 0}

    def fake_load():
        calls["n"] += 1
        # 用 duck-typed object 绕过 Stock pydantic required fields (added_at 等)
        fake_stock = type("S", (), {"symbol": "600519", "name": "贵州茅台"})()
        return type("WL", (), {"stocks": [fake_stock]})()

    monkeypatch.setattr("kan.storage.watchlist.load_watchlist", fake_load)
    ws = WatchlistSet()
    assert calls["n"] == 0, "构造时不应读 storage"

    # 第一次 .pairs() 才触发
    pairs = ws.pairs()
    assert calls["n"] == 1
    assert pairs == [("600519", "贵州茅台")]

    # 第二次走 cache · 不再读
    ws.pairs()
    assert calls["n"] == 1, "重复调用应走 cache · 不再读 storage"


def test_watchlist_set_pairs_returns_copy():
    """pairs() 返回独立 list · 外部 mutate 不影响内部 state。"""
    ws = WatchlistSet(_pairs=[("600519", "贵州茅台")])
    out = ws.pairs()
    out.append(("000858", "五粮液"))
    assert ws.pairs() == [("600519", "贵州茅台")], "内部 pairs 被外部 mutate 污染"


def test_watchlist_set_codes_strips_names():
    ws = WatchlistSet(_pairs=[("600519", "贵州茅台"), ("000858", "五粮液")])
    assert ws.codes() == ["600519", "000858"]


def test_watchlist_set_len():
    ws = WatchlistSet(_pairs=[("600519", "贵州茅台"), ("000858", "五粮液")])
    assert len(ws) == 2


# ─────────────── HotRankSet ───────────────


@pytest.mark.parametrize("mode,expected_name", [
    ("rank", "东财人气榜"),
    ("surge", "东财飙升榜"),
])
def test_hot_rank_set_name(mode, expected_name):
    hs = HotRankSet(mode=mode)
    assert hs.name == expected_name


def test_hot_rank_set_lazy_load(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(which):
        calls["n"] += 1
        return [
            type("E", (), {"symbol": "300750", "name": "宁德时代"})(),
        ]

    monkeypatch.setattr("kan.data.hot.fetch_hot_list", fake_fetch)
    hs = HotRankSet(mode="rank")
    assert calls["n"] == 0
    assert hs.pairs() == [("300750", "宁德时代")]
    assert calls["n"] == 1


# ─────────────── ThemeSet ───────────────


def test_theme_set_name():
    ts = ThemeSet(theme="国产软件")
    assert ts.name == "题材「国产软件」"


def test_theme_set_lazy_load(monkeypatch):
    calls = {"search": 0, "constituents": 0}

    def fake_search(query):
        calls["search"] += 1
        return type("T", (), {"name": query})()

    def fake_constituents(themed):
        calls["constituents"] += 1
        return [("002230", "科大讯飞"), ("002405", "四维图新")]

    monkeypatch.setattr("kan.data.boards.search_theme", fake_search)
    monkeypatch.setattr("kan.data.boards.get_theme_constituents", fake_constituents)

    ts = ThemeSet(theme="AI")
    assert calls["search"] == 0
    assert ts.pairs() == [("002230", "科大讯飞"), ("002405", "四维图新")]
    assert calls["search"] == 1
    assert calls["constituents"] == 1


# ─────────────── IndustrySet ───────────────


def test_industry_set_name():
    its = IndustrySet(industry="白酒")
    assert its.name == "行业「白酒」"


def test_industry_set_lazy_load(monkeypatch):
    def fake_search(query):
        return type("B", (), {"name": query})()

    def fake_constituents(board):
        return [("600519", "贵州茅台"), ("000858", "五粮液")]

    monkeypatch.setattr("kan.data.boards.search_industry", fake_search)
    monkeypatch.setattr("kan.data.boards.get_industry_constituents", fake_constituents)

    its = IndustrySet(industry="白酒")
    assert its.codes() == ["600519", "000858"]


# ─────────────── from_flags factory ───────────────


def test_from_flags_default_returns_watchlist():
    s = from_flags()
    assert isinstance(s, WatchlistSet)


def test_from_flags_industry():
    s = from_flags(industry="白酒")
    assert isinstance(s, IndustrySet)
    assert s.industry == "白酒"


def test_from_flags_hot():
    s = from_flags(hot="rank")
    assert isinstance(s, HotRankSet)
    assert s.mode == "rank"


def test_from_flags_theme():
    s = from_flags(theme="AI")
    assert isinstance(s, ThemeSet)
    assert s.theme == "AI"


@pytest.mark.parametrize("kwargs", [
    {"industry": "白酒", "hot": "rank"},
    {"industry": "白酒", "theme": "AI"},
    {"hot": "rank", "theme": "AI"},
    {"industry": "白酒", "hot": "rank", "theme": "AI"},
])
def test_from_flags_mutual_exclusion(kwargs):
    with pytest.raises(ValueError, match="互斥"):
        from_flags(**kwargs)

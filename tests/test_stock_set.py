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
    AllStocksSet,
    CodeListSet,
    HoldingsSet,
    HotRankSet,
    IndustrySet,
    StockSet,
    ThemeSet,
    WatchlistHoldingsSet,
    WatchlistSet,
    from_flags,
)

# ─────────────── Protocol 契约 ───────────────


@pytest.mark.parametrize(
    "instance",
    [
        WatchlistSet(_pairs=[("600519", "贵州茅台")]),
        HoldingsSet(_pairs=[("600519", "贵州茅台")]),
        WatchlistHoldingsSet(_pairs=[("600519", "贵州茅台")]),
        HotRankSet(mode="rank", _pairs=[("000858", "五粮液")]),
        ThemeSet(theme="AI", _pairs=[("002230", "科大讯飞")]),
        IndustrySet(industry="白酒", _pairs=[("600519", "贵州茅台")]),
        AllStocksSet(_pairs=[("600519", "贵州茅台")]),
        CodeListSet(pairs_input=[("000001", "平安银行")]),
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


def test_stock_set_facade_exports_public_contract():
    """兼容门面继续暴露历史公共导入路径。"""
    from kan.core import stock_set

    assert stock_set.__all__ == [
        "AllStocksSet",
        "CodeListSet",
        "HoldingsSet",
        "HotRankSet",
        "IndustrySet",
        "StockSet",
        "ThemeSet",
        "WatchlistHoldingsSet",
        "WatchlistSet",
        "from_flags",
    ]
    assert stock_set.WatchlistSet is WatchlistSet
    assert stock_set.CodeListSet is CodeListSet


# ─────────────── WatchlistSet ───────────────


def test_watchlist_set_lazy_load(monkeypatch):
    """构造 WatchlistSet 不触发 storage 读取 (lazy)。"""
    calls = {"n": 0}

    def fake_load(group=None):
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


# ─────────────── HoldingsSet / WatchlistHoldingsSet ───────────────


def test_holdings_set_lazy_load(monkeypatch):
    """构造 HoldingsSet 不触发 positions 读取。"""
    calls = {"n": 0}

    def fake_load_positions():
        calls["n"] += 1
        fake_position = type("P", (), {"symbol": "600519", "name": "贵州茅台"})()
        return type("Book", (), {"positions": [fake_position]})()

    monkeypatch.setattr("kan.storage.positions.load_positions", fake_load_positions)
    hs = HoldingsSet()
    assert calls["n"] == 0
    assert hs.pairs() == [("600519", "贵州茅台")]
    assert hs.membership("600519") == (False, True)
    assert calls["n"] == 1


def test_watchlist_holdings_set_merges_and_marks_sources(monkeypatch):
    """默认池为自选 ∪ 持仓；同代码保留自选名称并记录双来源。"""
    fake_watch = type("S", (), {"symbol": "600519", "name": "贵州茅台"})()
    fake_hold_same = type("P", (), {"symbol": "600519", "name": "茅台持仓名"})()
    fake_hold_only = type("P", (), {"symbol": "000858", "name": "五粮液"})()

    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist",
        lambda group=None: type("WL", (), {"stocks": [fake_watch]})(),
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: type("Book", (), {"positions": [fake_hold_same, fake_hold_only]})(),
    )

    stock_set = WatchlistHoldingsSet()

    assert stock_set.pairs() == [("600519", "贵州茅台"), ("000858", "五粮液")]
    assert stock_set.membership("600519") == (True, True)
    assert stock_set.membership("000858") == (False, True)


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
        # 背景: stub HotEntry 加 rank · meta() 算 rank_map 用
        return [
            type("E", (), {"symbol": "300750", "name": "宁德时代", "rank": 1})(),
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
    import pandas as pd

    calls = {"search": 0, "constituents": 0, "kline": 0}

    def fake_search(query):
        calls["search"] += 1
        # 背景: 加 code 属性 · fetch_theme_kline 拼 cache path 用
        return type("T", (), {"name": query, "code": "886108", "source": "ths"})()

    def fake_constituents(themed):
        calls["constituents"] += 1
        return [("002230", "科大讯飞"), ("002405", "四维图新")]

    def fake_kline(themed, force=False):
        calls["kline"] += 1
        return pd.DataFrame()

    monkeypatch.setattr("kan.data.boards.search_theme", fake_search)
    monkeypatch.setattr("kan.data.boards.get_theme_constituents", fake_constituents)
    monkeypatch.setattr("kan.data.boards.fetch_theme_kline", fake_kline)

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
    import pandas as pd

    def fake_search(query):
        # 背景: 加 code + level + size · fetch_industry_kline 拼 cache path 用
        return type("B", (), {"name": query, "code": "801080", "level": 2, "size": 5})()

    def fake_constituents(board):
        return [("600519", "贵州茅台"), ("000858", "五粮液")]

    def fake_kline(board, force=False):
        return pd.DataFrame()

    monkeypatch.setattr("kan.data.boards.search_industry", fake_search)
    monkeypatch.setattr("kan.data.boards.get_industry_constituents", fake_constituents)
    monkeypatch.setattr("kan.data.boards.fetch_industry_kline", fake_kline)

    its = IndustrySet(industry="白酒")
    assert its.codes() == ["600519", "000858"]


# ─────────────── from_flags factory ───────────────


def test_from_flags_default_returns_watchlist():
    s = from_flags()
    assert isinstance(s, WatchlistHoldingsSet)


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


# ─────────────── meta() · 历史背景新加 ───────────────


def test_watchlist_meta_is_none():
    """WatchlistSet 无 meta · meta() 返回 None (industry/hot/theme 才有 meta)。"""
    ws = WatchlistSet(_pairs=[("600519", "贵州茅台")])
    assert ws.meta() is None


def test_hot_rank_meta_carries_rank_map_and_highlight(monkeypatch):
    """HotRankSet.meta() 返回 HotMeta · 含 list_name / rank_map / highlight (∩ 自选)。"""
    def fake_fetch(which):
        return [
            type("E", (), {"symbol": "300750", "name": "宁德时代", "rank": 1})(),
            type("E", (), {"symbol": "600519", "name": "贵州茅台", "rank": 2})(),
        ]
    monkeypatch.setattr("kan.data.hot.fetch_hot_list", fake_fetch)

    hs = HotRankSet(mode="rank", watchlist_pairs=[("600519", "贵州茅台")])
    meta = hs.meta()
    assert meta.list_name == "东财人气榜"
    assert meta.rank_map == {"300750": 1, "600519": 2}
    assert meta.highlight == {"600519"}, "highlight 应为热榜 ∩ 自选"


def test_hot_rank_only_watchlist_filters_pairs(monkeypatch):
    """only_watchlist=True · .pairs() 仅返热榜 ∩ 自选 (∩ filter)。"""
    def fake_fetch(which):
        return [
            type("E", (), {"symbol": "300750", "name": "宁德时代", "rank": 1})(),
            type("E", (), {"symbol": "600519", "name": "贵州茅台", "rank": 2})(),
        ]
    monkeypatch.setattr("kan.data.hot.fetch_hot_list", fake_fetch)

    hs = HotRankSet(
        mode="rank",
        watchlist_pairs=[("600519", "贵州茅台")],
        only_watchlist=True,
    )
    assert hs.pairs() == [("600519", "贵州茅台")], "only_watchlist=True 应只留 ∩ 自选"


def test_theme_meta_carries_constituents_index_highlight(monkeypatch):
    """ThemeSet.meta() 返回 ThemeMeta · 含 theme/constituents/highlight/index_kline。"""
    import pandas as pd

    def fake_search(q):
        return type("T", (), {"name": q, "code": "886108", "source": "ths"})()
    def fake_cons(themed):
        return [("002230", "科大讯飞"), ("002405", "四维图新")]
    def fake_kline(themed, force=False):
        return pd.DataFrame({"date": ["2026-05-23"], "close": [100.0]})
    monkeypatch.setattr("kan.data.boards.search_theme", fake_search)
    monkeypatch.setattr("kan.data.boards.get_theme_constituents", fake_cons)
    monkeypatch.setattr("kan.data.boards.fetch_theme_kline", fake_kline)

    ts = ThemeSet(theme="AI", watchlist_pairs=[("002230", "科大讯飞")])
    meta = ts.meta()
    assert meta.theme.name == "AI"
    assert meta.highlight == {"002230"}, "highlight = 题材成分 ∩ 自选"
    assert len(meta.constituents) == 2
    assert not meta.index_kline.empty


def test_theme_kline_failure_degrades_to_empty(monkeypatch):
    """题材 K 线 fetch 失败 · index_kline 降级空 df · constituents 仍可用。"""
    import pandas as pd

    from kan.data.boards import ThemeDataUnavailableError

    def fake_search(q):
        return type("T", (), {"name": q, "code": "886108", "source": "ths"})()
    def fake_cons(themed):
        return [("002230", "科大讯飞")]
    def fake_kline_fail(themed, force=False):
        raise ThemeDataUnavailableError("kline down")
    monkeypatch.setattr("kan.data.boards.search_theme", fake_search)
    monkeypatch.setattr("kan.data.boards.get_theme_constituents", fake_cons)
    monkeypatch.setattr("kan.data.boards.fetch_theme_kline", fake_kline_fail)

    ts = ThemeSet(theme="AI")
    meta = ts.meta()
    assert isinstance(meta.index_kline, pd.DataFrame)
    assert meta.index_kline.empty
    assert len(meta.constituents) == 1, "K 线挂掉不应影响 constituents"


def test_industry_meta_carries_board_constituents_highlight(monkeypatch):
    """IndustrySet.meta() 返回 BoardMeta · 含 board/constituents/highlight/index_kline。"""
    import pandas as pd

    def fake_search(q):
        return type("B", (), {"name": q, "code": "801080", "level": 2, "size": 2})()
    def fake_cons(b):
        return [("600519", "贵州茅台"), ("000858", "五粮液")]
    def fake_kline(b, force=False):
        return pd.DataFrame({"date": ["2026-05-23"], "close": [200.0]})
    monkeypatch.setattr("kan.data.boards.search_industry", fake_search)
    monkeypatch.setattr("kan.data.boards.get_industry_constituents", fake_cons)
    monkeypatch.setattr("kan.data.boards.fetch_industry_kline", fake_kline)

    its = IndustrySet(industry="白酒", watchlist_pairs=[("600519", "贵州茅台")])
    meta = its.meta()
    assert meta.board.name == "白酒"
    assert meta.highlight == {"600519"}
    assert len(meta.constituents) == 2


# ─────────────── from_flags 透传 watchlist_pairs / only_watchlist ───────────────


def test_from_flags_passes_watchlist_pairs_to_industry():
    s = from_flags(industry="白酒", watchlist_pairs=[("600519", "贵州茅台")])
    assert isinstance(s, IndustrySet)
    assert s.watchlist_pairs == [("600519", "贵州茅台")]
    assert s.only_watchlist is False


def test_from_flags_passes_only_watchlist_to_hot():
    s = from_flags(hot="rank", watchlist_pairs=[("600519", "贵州茅台")], only_watchlist=True)
    assert isinstance(s, HotRankSet)
    assert s.watchlist_pairs == [("600519", "贵州茅台")]
    assert s.only_watchlist is True


def test_from_flags_only_watchlist_without_source_uses_watchlist_pool():
    """三源都 None + only_watchlist=True → 自选池。"""
    s = from_flags(watchlist_pairs=[("600519", "贵州茅台")], only_watchlist=True)
    assert isinstance(s, WatchlistSet)


def test_from_flags_hot_accepts_str_or_enum():
    """from_flags(hot=) 接 str 或 HotList enum 都 work (StrEnum compat)。"""
    from kan.data.hot import HotList

    s1 = from_flags(hot="rank")
    assert isinstance(s1, HotRankSet)
    s2 = from_flags(hot=HotList.RANK)
    assert isinstance(s2, HotRankSet)
    s3 = from_flags(hot=HotList.SURGE)
    assert isinstance(s3, HotRankSet)
    assert s3.name == "东财飙升榜"


# ─────────────── AllStocksSet · 地基-3 ───────────────


def test_all_stocks_set_satisfies_protocol():
    s = AllStocksSet(_pairs=[("600519", "贵州茅台")])
    assert isinstance(s, StockSet)
    assert s.name == "A股全市场"
    assert s.codes() == ["600519"]
    assert s.pairs() == [("600519", "贵州茅台")]


def test_all_stocks_set_lazy_load(monkeypatch):
    """构造 AllStocksSet 不触发 fetch_all_stocks · .codes()/.pairs() 才拉 · 走 cache。"""
    calls = {"n": 0}

    def fake_fetch(force=False):
        calls["n"] += 1
        return [("600519", "贵州茅台"), ("000001", "平安银行")]

    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", fake_fetch)
    s = AllStocksSet()
    assert calls["n"] == 0, "构造时不应 fetch"
    assert s.codes() == ["600519", "000001"]
    assert calls["n"] == 1
    s.pairs()
    assert calls["n"] == 1, "重复调用走 cache · 不再 fetch"


def test_all_stocks_set_can_force_universe_refresh(monkeypatch):
    captured = {}

    def fake_fetch(*, force=False):
        captured["force"] = force
        return [("600519", "贵州茅台")]

    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", fake_fetch)

    assert AllStocksSet(force_refresh=True).codes() == ["600519"]
    assert captured["force"] is True


def test_all_stocks_set_meta_none():
    """AllStocksSet 无 meta (同 WatchlistSet · 全市场无 highlight/index_kline)。"""
    assert AllStocksSet(_pairs=[]).meta() is None


def test_all_stocks_set_len():
    s = AllStocksSet(_pairs=[("600519", "贵州茅台"), ("000001", "平安银行")])
    assert len(s) == 2


def test_from_flags_all_stocks():
    s = from_flags(all_stocks=True)
    assert isinstance(s, AllStocksSet)


def test_from_flags_all_stocks_force():
    s = from_flags(all_stocks=True, all_stocks_force=True)
    assert isinstance(s, AllStocksSet)
    assert s.force_refresh is True


def test_from_flags_only_holdings():
    s = from_flags(only_holdings=True)
    assert isinstance(s, HoldingsSet)


@pytest.mark.parametrize("kwargs", [
    {"all_stocks": True, "industry": "白酒"},
    {"all_stocks": True, "hot": "rank"},
    {"all_stocks": True, "theme": "AI"},
    {"all_stocks": True, "only_watchlist": True},
    {"all_stocks": True, "watchlist_group": "观察"},
    {"all_stocks": True, "only_holdings": True},
])
def test_from_flags_all_stocks_mutual_exclusion(kwargs):
    with pytest.raises(ValueError, match="互斥"):
        from_flags(**kwargs)


def test_from_flags_only_holdings_mutual_exclusion():
    with pytest.raises(ValueError, match="互斥"):
        from_flags(only_holdings=True, industry="白酒")

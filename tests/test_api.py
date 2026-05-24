"""kan.api 公开 surface sanity check。

确保 kan.api 暴露的符号 (4 个 Set + 5 个 verb + StockSet Protocol + from_flags)
都是 importable 且类型正确 · 防止内部重构悄悄破坏公开 contract。
"""
from __future__ import annotations


def test_api_exports_all_stock_sets():
    """kan.api 暴露 4 个 StockSet 实现 + Protocol + factory。"""
    from kan import api

    # 4 个具体实现
    assert hasattr(api, "WatchlistSet")
    assert hasattr(api, "HotRankSet")
    assert hasattr(api, "ThemeSet")
    assert hasattr(api, "IndustrySet")
    # Protocol
    assert hasattr(api, "StockSet")
    # factory
    assert hasattr(api, "from_flags")


def test_api_exports_all_verbs():
    """kan.api 暴露 5 个 verb · 都是 callable。"""
    from kan import api

    for verb_name in ("scan", "low", "high", "trend", "fetch"):
        assert hasattr(api, verb_name), f"kan.api 缺 verb: {verb_name}"
        assert callable(getattr(api, verb_name)), f"{verb_name} 必须 callable"


def test_api_watchlist_set_instantiates():
    """WatchlistSet 可直接构造 (空 _pairs 注入避免 IO)。"""
    from kan.api import WatchlistSet

    ws = WatchlistSet(_pairs=[("600519", "贵州茅台")])
    assert ws.name == "自选股"
    assert ws.pairs() == [("600519", "贵州茅台")]
    assert ws.codes() == ["600519"]
    assert ws.meta() is None


def test_api_from_flags_returns_protocol_instance():
    """from_flags 返回值满足 StockSet Protocol (鸭子类型)。"""
    from kan.api import StockSet, WatchlistSet, from_flags

    s = from_flags()  # 默认 WatchlistSet
    assert isinstance(s, WatchlistSet)
    assert isinstance(s, StockSet), "from_flags 返回值必须满足 StockSet Protocol"


def test_api_custom_class_satisfies_protocol():
    """用户自定义 class 实现 codes/pairs/meta + name attr → 自动满足 StockSet。"""
    from kan.api import StockSet

    class MyBasket:
        name = "我的篮子"

        def codes(self) -> list[str]:
            return ["600519"]

        def pairs(self) -> list[tuple[str, str]]:
            return [("600519", "贵州茅台")]

        def meta(self):
            return None

    assert isinstance(MyBasket(), StockSet), "自定义类应自动满足 Protocol"


def test_api_all_lists_match_actual_exports():
    """kan.api.__all__ 必须与实际导出的符号一致 (防漏 / 防多)。"""
    from kan import api

    declared = set(api.__all__)
    expected = {
        # StockSet
        "HotRankSet", "IndustrySet", "StockSet", "ThemeSet", "WatchlistSet",
        "from_flags",
        # verbs
        "fetch", "high", "low", "scan", "trend",
    }
    assert declared == expected, f"kan.api.__all__ 与预期 surface 不符: 多={declared-expected} · 少={expected-declared}"

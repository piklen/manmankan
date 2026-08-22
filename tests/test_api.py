"""kan.api 公开 surface sanity check。

确保 kan.api 暴露的符号 (Set + verb + StockSet Protocol + from_flags)
都是 importable 且类型正确 · 防止内部重构悄悄破坏公开 contract。
"""
from __future__ import annotations


def test_api_exports_all_stock_sets():
    """kan.api 暴露 StockSet 实现 + Protocol + factory。"""
    from kan import api

    # 具体实现
    assert hasattr(api, "WatchlistSet")
    assert hasattr(api, "HoldingsSet")
    assert hasattr(api, "WatchlistHoldingsSet")
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
    from kan.api import StockSet, WatchlistHoldingsSet, from_flags

    s = from_flags()  # 默认自选 ∪ 持仓
    assert isinstance(s, WatchlistHoldingsSet)
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
        "HoldingsSet", "HotRankSet", "IndustrySet", "StockSet", "ThemeSet",
        "WatchlistHoldingsSet", "WatchlistSet", "from_flags",
        # verbs
        "fetch", "high", "low", "scan", "trend",
        # 背景: 数据源扩展 API
        "KlineSource", "ThemeConstituentSource",
        "register_kline_source", "register_theme_constituent_source",
        "clear_user_kline_sources", "clear_user_theme_constituent_sources",
        "kline_chain", "theme_constituent_chain",
        # vNext Screen application service
        "CandidateList", "CompareSet", "SavedScreen", "ScreenRun", "ScreenSpec",
        "ScreenExplainInput", "ScreenParseInput", "ScreenPlanInput",
        "save_screen", "get_screen", "list_screens", "run_screen", "get_run", "list_runs",
        "list_candidate_lists", "add_candidate", "remove_candidate",
        "save_compare_set", "list_compare_sets", "filter_catalog", "screen_schema",
        "parse_screen_text", "plan_screen", "explain_run",
    }
    assert declared == expected, f"kan.api.__all__ 与预期 surface 不符: 多={declared-expected} · 少={expected-declared}"


def test_api_exports_vnext_screen_application_service():
    """Python 用户不需要 import 内部 service/storage 模块。"""
    from kan import api

    assert api.ScreenSpec(name="公开 API 规则", exclude_st=True)
    for function_name in (
        "save_screen",
        "get_screen",
        "list_screens",
        "run_screen",
        "get_run",
        "list_runs",
        "parse_screen_text",
        "plan_screen",
        "explain_run",
    ):
        assert callable(getattr(api, function_name))


# ── 早期数据源扩展 API surface ──────────────────────────────────────


def test_api_exports_kline_source_protocol():
    """kan.api 暴露 KlineSource Protocol · 用户写自定义源时 typing 用。"""
    from kan.api import KlineSource

    # Protocol 是 runtime_checkable · 自定义 class 鸭子满足
    class _MyKline:
        name = "user_t"
        priority = 50
        def is_available(self) -> bool: return True
        def fetch(self, symbol, start): return None

    assert isinstance(_MyKline(), KlineSource), "鸭子类型必须自动满足 Protocol"


def test_api_exports_theme_constituent_source_protocol():
    from kan.api import ThemeConstituentSource

    class _MyTheme:
        name = "user_t"
        priority = 50
        def is_available(self) -> bool: return True
        def fetch(self, theme): return None

    assert isinstance(_MyTheme(), ThemeConstituentSource)


def test_api_register_kline_source_round_trip():
    """register_kline_source → kline_chain() 可见新源 → clear 后消失。"""
    from kan.api import (
        clear_user_kline_sources,
        kline_chain,
        register_kline_source,
    )

    clear_user_kline_sources()  # 干净起手

    class _U:
        name = "u_test_api"
        priority = 55
        def is_available(self) -> bool: return True
        def fetch(self, symbol, start): return None

    register_kline_source(_U())
    try:
        names = [s.name for s in kline_chain().sources]
        assert "u_test_api" in names
    finally:
        clear_user_kline_sources()
        names_after = [s.name for s in kline_chain().sources]
        assert "u_test_api" not in names_after


def test_api_register_theme_constituent_source_round_trip():
    from kan.api import (
        clear_user_theme_constituent_sources,
        register_theme_constituent_source,
        theme_constituent_chain,
    )

    clear_user_theme_constituent_sources()

    class _U:
        name = "u_theme_api"
        priority = 55
        def is_available(self) -> bool: return True
        def fetch(self, theme): return None

    register_theme_constituent_source(_U())
    try:
        names = [s.name for s in theme_constituent_chain().sources]
        assert "u_theme_api" in names
    finally:
        clear_user_theme_constituent_sources()
        names_after = [s.name for s in theme_constituent_chain().sources]
        assert "u_theme_api" not in names_after


def test_api_kline_chain_returns_chain_with_builtin_sources():
    """kline_chain() 返回 default chain · 含内置 5 源。"""
    from kan.api import clear_user_kline_sources, kline_chain

    clear_user_kline_sources()
    chain = kline_chain()
    names = {s.name for s in chain.sources}
    assert {"tushare", "baostock", "eastmoney", "sina", "tencent"}.issubset(names)


def test_api_theme_constituent_chain_returns_chain_with_builtin_sources():
    """theme_constituent_chain() 返回 default chain · 含内置 2 源。"""
    from kan.api import (
        clear_user_theme_constituent_sources,
        theme_constituent_chain,
    )

    clear_user_theme_constituent_sources()
    chain = theme_constituent_chain()
    names = {s.name for s in chain.sources}
    assert {"ths_constituent", "em_push2_concept"}.issubset(names)

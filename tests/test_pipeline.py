"""kan/core/pipeline.py 单元测试 · mock 上游 (StockSet / fetcher / trading_calendar)。

历史背景 (cleanup):
- resolve_targets_or_exit 已删 · 改测 resolve_stock_set_or_exit
- run_data_pipeline 老签名已删 · 改测 StockSet 单签名
"""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest
import typer

from kan.core import pipeline
from kan.core.pipeline import Freshness
from kan.core.trading_calendar import PHASE_INTRADAY
from kan.data.boards import (
    BoardDataUnavailableError,
    BoardNotFoundError,
    ThemeDataUnavailableError,
    ThemeNotFoundError,
)
from kan.data.hot import HotListUnavailableError

# ─────────────── fake StockSet ───────────────


class _FakeStockSet:
    """fake StockSet for testing · pairs() / meta() / codes() / .name 都可控。

    用关键字参数构造 · 字段全 optional · 覆盖 happy / error / industry / theme
    各种场景。industry / theme 名字段 setter 可选 · 模拟 IndustrySet / ThemeSet
    暴露的 industry / theme 属性 (供错误文案抽取)。
    """

    def __init__(
        self,
        *,
        pairs: list[tuple[str, str]] | None = None,
        meta: object | None = None,
        name: str = "fake",
        pairs_error: Exception | None = None,
        industry: str | None = None,
        theme: str | None = None,
    ):
        self.name = name
        self._pairs = pairs or []
        self._meta = meta
        self._pairs_error = pairs_error
        if industry is not None:
            self.industry = industry
        if theme is not None:
            self.theme = theme

    def pairs(self) -> list[tuple[str, str]]:
        if self._pairs_error is not None:
            raise self._pairs_error
        return self._pairs

    def codes(self) -> list[str]:
        return [c for c, _ in self.pairs()]

    def meta(self):
        return self._meta


# ═══ resolve_stock_set_or_exit ═════════════════════════════════════════


def test_resolve_stock_set_or_exit_happy_path_returns_pairs_and_meta():
    """成功路径 · stock_set.pairs() + .meta() 原样返回。"""
    pairs = [("600519", "贵州茅台"), ("000858", "五粮液")]
    sentinel_meta = object()
    stock_set = _FakeStockSet(pairs=pairs, meta=sentinel_meta)
    targets, meta = pipeline.resolve_stock_set_or_exit(stock_set)
    assert targets == pairs
    assert meta is sentinel_meta


def test_resolve_stock_set_or_exit_no_meta_returns_none():
    """WatchlistSet 风格 · meta() 返回 None · 透传到 caller。"""
    pairs = [("600519", "贵州茅台")]
    stock_set = _FakeStockSet(pairs=pairs, meta=None)
    targets, meta = pipeline.resolve_stock_set_or_exit(stock_set)
    assert targets == pairs
    assert meta is None


def test_resolve_stock_set_source_error_is_domain_error_without_printing(monkeypatch):
    """纯 resolve 不打印、不 Typer exit；CLI adapter 在边界负责展示。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan.core.pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    stock_set = _FakeStockSet(
        pairs_error=ThemeNotFoundError("我的题材"),
        theme="我的题材",
    )

    with pytest.raises(pipeline.StockSetResolveError) as exc_info:
        pipeline.resolve_stock_set(stock_set)

    assert err_calls == []
    assert exc_info.value.code == "theme_not_found"
    assert exc_info.value.exit_code == 2
    assert "我的题材" in exc_info.value.message


@pytest.mark.parametrize(("exc_cls", "expected_code", "msg_part"), [
    (BoardNotFoundError, 1, "未找到行业"),
    (BoardDataUnavailableError, 1, "行业数据源"),
    (HotListUnavailableError, 1, "东财热榜源"),
    (ThemeNotFoundError, 2, "未找到题材"),
    (ThemeDataUnavailableError, 1, "题材数据源"),
])
def test_resolve_stock_set_or_exit_source_errors(
    monkeypatch, exc_cls, expected_code, msg_part,
):
    """5 类 source 错误统一转换为 _print_err + typer.Exit · exit 码与现状一致。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan.core.pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    stock_set = _FakeStockSet(
        pairs_error=exc_cls("test"),
        industry="test",
        theme="testtheme",
    )
    with pytest.raises(typer.Exit) as exc_info:
        pipeline.resolve_stock_set_or_exit(stock_set)
    assert exc_info.value.exit_code == expected_code
    assert len(err_calls) == 1
    assert msg_part in err_calls[0]


def test_resolve_stock_set_or_exit_board_not_found_includes_industry_and_examples(
    monkeypatch,
):
    """BoardNotFound 错误消息引用 stock_set.industry + 散户化示例关键词。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan.core.pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    stock_set = _FakeStockSet(
        pairs_error=BoardNotFoundError("我的行业"),
        industry="我的行业",
    )
    with pytest.raises(typer.Exit):
        pipeline.resolve_stock_set_or_exit(stock_set)
    msg = err_calls[0]
    assert "我的行业" in msg
    assert "半导体" in msg
    assert "白酒" in msg
    assert "❌" in msg


def test_resolve_stock_set_or_exit_theme_not_found_includes_theme_and_search_hint(
    monkeypatch,
):
    """ThemeNotFound 错误消息引用 stock_set.theme + 提示 kan theme search。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan.core.pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    stock_set = _FakeStockSet(
        pairs_error=ThemeNotFoundError("我的题材"),
        theme="我的题材",
    )
    with pytest.raises(typer.Exit):
        pipeline.resolve_stock_set_or_exit(stock_set)
    msg = err_calls[0]
    assert "我的题材" in msg
    assert "kan theme search" in msg
    assert "AI" in msg or "华为" in msg


def test_resolve_stock_set_or_exit_theme_data_unavailable_hints_industry(monkeypatch):
    """ThemeDataUnavailable 提示用户可以退化用 --industry(题材源死时的降级路径)。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan.core.pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    stock_set = _FakeStockSet(
        pairs_error=ThemeDataUnavailableError("api down"),
        theme="AI",
    )
    with pytest.raises(typer.Exit):
        pipeline.resolve_stock_set_or_exit(stock_set)
    msg = err_calls[0]
    assert "题材数据源" in msg
    assert "--industry" in msg


def test_resolve_stock_set_or_exit_missing_industry_attr_uses_none(monkeypatch):
    """stock_set 无 .industry 属性 (如 WatchlistSet / HotRankSet) → 错误文案显「None」不崩。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan.core.pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    stock_set = _FakeStockSet(pairs_error=BoardNotFoundError("x"))  # 不传 industry
    with pytest.raises(typer.Exit):
        pipeline.resolve_stock_set_or_exit(stock_set)
    # getattr fallback 到 None · 不应抛 AttributeError
    assert "None" in err_calls[0] or "❌" in err_calls[0]


# ═══ Freshness / freshness_of ══════════════════════════════════════════


def _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23), phase="post"):
    """统一 patch latest_trade_date + market_phase。"""
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date", lambda: expected_date,
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: phase)


def _patch_fetcher(monkeypatch, cutoffs: dict, ages: dict):
    """patch data_cutoff_date 与 cache_age,字典 lookup,缺失返回 None。"""
    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date", lambda sym: cutoffs.get(sym),
    )
    monkeypatch.setattr(
        "kan.data.fetcher.cache_age", lambda sym: ages.get(sym),
    )
    monkeypatch.setattr(
        "kan.data.fetcher.cache_has_min_rows", lambda _sym, _rows: True,
    )


def test_freshness_of_empty_symbols(monkeypatch):
    """空 symbols → data_cutoff=None · fetched_at=None · is_stale=True。"""
    _patch_calendar(monkeypatch)
    _patch_fetcher(monkeypatch, cutoffs={}, ages={})
    f = pipeline.freshness_of([])
    assert f.data_cutoff is None
    assert f.fetched_at is None
    assert f.expected_cutoff == date(2026, 5, 23)
    assert f.is_stale is True
    assert f.phase == "post"


def test_freshness_of_single_symbol_fresh(monkeypatch):
    """单 symbol 且 cutoff == expected → is_stale=False。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23)},
        ages={"600519": "2026-05-23T16:00:00"},
    )
    f = pipeline.freshness_of(["600519"])
    assert f.data_cutoff == date(2026, 5, 23)
    assert f.fetched_at == "2026-05-23T16:00:00"
    assert f.is_stale is False


def test_freshness_of_single_symbol_stale(monkeypatch):
    """单 symbol 但 cutoff < expected → is_stale=True。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 20)},
        ages={"600519": "2026-05-20T16:00:00"},
    )
    f = pipeline.freshness_of(["600519"])
    assert f.data_cutoff == date(2026, 5, 20)
    assert f.is_stale is True


def test_freshness_of_multi_symbol_takes_max(monkeypatch):
    """多 symbols → data_cutoff 与 fetched_at 都取 max。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={
            "600519": date(2026, 5, 20),
            "000858": date(2026, 5, 22),  # max
            "300750": date(2026, 5, 19),
        },
        ages={
            "600519": "2026-05-20T10:00:00",
            "000858": "2026-05-22T16:00:00",  # max(字典序 = 时间序)
            "300750": "2026-05-19T09:00:00",
        },
    )
    f = pipeline.freshness_of(["600519", "000858", "300750"])
    assert f.data_cutoff == date(2026, 5, 22)
    assert f.fetched_at == "2026-05-22T16:00:00"
    assert f.is_stale is True


def test_freshness_of_skips_none_cutoff(monkeypatch):
    """某 symbol 无 cutoff → 保留最新日期，但整池必须标记 stale。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={
            "600519": date(2026, 5, 22),
            "NEW01": None,
        },
        ages={"600519": "2026-05-22T16:00:00"},
    )
    f = pipeline.freshness_of(["600519", "NEW01"])
    assert f.data_cutoff == date(2026, 5, 22)
    assert f.fetched_at == "2026-05-22T16:00:00"
    assert f.missing_count == 1
    assert f.is_stale is True


def test_freshness_of_mixed_cutoffs_is_stale_even_when_max_is_current(monkeypatch):
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23), "000858": date(2026, 5, 22)},
        ages={},
    )

    freshness = pipeline.freshness_of(["600519", "000858"])

    assert freshness.data_cutoff == date(2026, 5, 23)
    assert freshness.min_cutoff == date(2026, 5, 22)
    assert freshness.current_count == 1
    assert freshness.target_count == 2
    assert freshness.is_stale is True


def test_freshness_of_requires_enough_history_for_requested_period(monkeypatch):
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23), "000858": date(2026, 5, 23)},
        ages={},
    )
    monkeypatch.setattr(
        "kan.data.fetcher.cache_has_min_rows",
        lambda symbol, rows: symbol == "600519" and rows == 180,
    )

    freshness = pipeline.freshness_of(["600519", "000858"], min_rows=180)

    assert freshness.current_count == 2
    assert freshness.history_incomplete_count == 1
    assert freshness.required_rows == 180
    assert freshness.is_stale is True


def test_freshness_history_count_preserves_duplicate_symbols(monkeypatch):
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23)},
        ages={},
    )
    monkeypatch.setattr(
        "kan.data.fetcher.cache_has_min_rows",
        lambda _symbol, _rows: False,
    )

    freshness = pipeline.freshness_of(["600519", "600519"], min_rows=180)

    assert freshness.target_count == 2
    assert freshness.history_incomplete_count == 2


def test_freshness_of_skips_falsy_cache_age(monkeypatch):
    """cache_age 返回 None / 空串 → 跳过(沿用现状 `if t and ...` 判定)。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 22), "000858": date(2026, 5, 22)},
        ages={"600519": "", "000858": "2026-05-22T16:00:00"},
    )
    f = pipeline.freshness_of(["600519", "000858"])
    assert f.fetched_at == "2026-05-22T16:00:00"


def test_freshness_of_phase_passthrough(monkeypatch):
    """phase 直接来自 market_phase()。"""
    _patch_calendar(monkeypatch, phase="intraday")
    _patch_fetcher(monkeypatch, cutoffs={}, ages={})
    f = pipeline.freshness_of([])
    assert f.phase == "intraday"


def test_freshness_of_accepts_generator(monkeypatch):
    """symbols 可以是生成器(支持 `freshness_of(r.symbol for r in results)` 用法)。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 22), "000858": date(2026, 5, 21)},
        ages={"600519": "x", "000858": "y"},
    )
    f = pipeline.freshness_of(sym for sym in ["600519", "000858"])
    assert f.data_cutoff == date(2026, 5, 22)
    assert f.fetched_at == "y"


def test_freshness_returns_frozen_dataclass(monkeypatch):
    """Freshness 是 frozen=True · 不可变 · 防意外修改。"""
    _patch_calendar(monkeypatch)
    _patch_fetcher(monkeypatch, cutoffs={}, ages={})
    f = pipeline.freshness_of([])
    with pytest.raises((AttributeError, Exception)):
        f.is_stale = False  # type: ignore[misc]


# ═══ render_freshness_warning ═══════════════════════════════════════════


def _make_freshness(
    *,
    data_cutoff=date(2026, 5, 22),
    fetched_at="2026-05-22T16:00:00",
    expected_cutoff=date(2026, 5, 23),
    is_stale=True,
    phase="post",
) -> Freshness:
    """Freshness fixture · 默认 stale 状态。"""
    return Freshness(
        data_cutoff=data_cutoff,
        fetched_at=fetched_at,
        expected_cutoff=expected_cutoff,
        is_stale=is_stale,
        phase=phase,
    )


def test_render_freshness_warning_stale_prints_cache_lag():
    """is_stale=True · 有 data_cutoff → 「当前缓存到 X 收盘」警告。"""
    console = Mock()
    f = _make_freshness(
        data_cutoff=date(2026, 5, 20),
        expected_cutoff=date(2026, 5, 23),
        is_stale=True,
    )
    pipeline.render_freshness_warning(f, console)
    console.print.assert_called_once()
    msg = console.print.call_args.args[0]
    assert "当前缓存到" in msg
    assert "05-20" in msg
    assert "05-23" in msg
    assert "3 天" in msg
    assert "kan fetch --force" in msg


def test_render_freshness_warning_stale_no_cutoff_shows_placeholder():
    """is_stale=True 但 data_cutoff=None → 「无缓存」+ days_behind 显「?」。"""
    console = Mock()
    f = _make_freshness(
        data_cutoff=None,
        expected_cutoff=date(2026, 5, 23),
        is_stale=True,
    )
    pipeline.render_freshness_warning(f, console)
    msg = console.print.call_args.args[0]
    assert "无缓存" in msg
    assert "? 天" in msg


def test_render_freshness_warning_uses_oldest_cutoff_for_mixed_pool():
    console = Mock()
    f = Freshness(
        data_cutoff=date(2026, 5, 23),
        min_cutoff=date(2026, 5, 20),
        fetched_at=None,
        expected_cutoff=date(2026, 5, 23),
        is_stale=True,
        phase="post",
    )

    pipeline.render_freshness_warning(f, console)

    msg = console.print.call_args.args[0]
    assert "05-20" in msg
    assert "3 天" in msg


def test_render_freshness_warning_intraday_prints_intraday_warning():
    """is_stale=False + phase=intraday → 「当前盘中」警告。"""
    console = Mock()
    f = _make_freshness(
        is_stale=False,
        phase=PHASE_INTRADAY,
    )
    pipeline.render_freshness_warning(f, console)
    console.print.assert_called_once()
    msg = console.print.call_args.args[0]
    assert "当前盘中" in msg
    assert "涨跌停标签反映当前时刻" in msg
    assert "15:30" in msg


def test_render_freshness_warning_fresh_and_post_silent():
    """is_stale=False + phase=post → 不打任何内容。"""
    console = Mock()
    f = _make_freshness(
        is_stale=False,
        phase="post",
    )
    pipeline.render_freshness_warning(f, console)
    console.print.assert_not_called()


def test_render_freshness_warning_stale_supersedes_intraday():
    """is_stale=True 即使 phase=intraday · 仍走 stale 分支(互斥优先级)。

    Why(当前行为):stale 状态下用户首动作是 fetch → fetch 后会重 scan → 那时再判 intraday。
    """
    console = Mock()
    f = _make_freshness(
        is_stale=True,
        phase=PHASE_INTRADAY,
    )
    pipeline.render_freshness_warning(f, console)
    msg = console.print.call_args.args[0]
    assert "当前缓存到" in msg  # stale 分支
    assert "盘中" not in msg  # 没走 intraday 分支


# ═══ run_data_pipeline (StockSet 单签名) ═══════════════════════════════


class _FakeResult:
    """compute 函数的 result 元素 stub · 只需有 .symbol。"""

    def __init__(self, symbol: str):
        self.symbol = symbol


def _patch_pipeline_deps(
    monkeypatch,
    *,
    cutoffs=None,
    ages=None,
    expected_date=date(2026, 5, 23),
    phase="post",
):
    """mock auto_fetch_stale + freshness 依赖 (calendar + fetcher)。

    返回 fetched_targets 可观察容器供测试 assert auto-fetch 调用。
    """
    cutoffs = cutoffs or {}
    ages = ages or {}
    fetched_targets: list = []

    monkeypatch.setattr(
        "kan.core.auto_fetch.auto_fetch_stale",
        lambda pairs: fetched_targets.append(pairs),
    )
    _patch_calendar(monkeypatch, expected_date=expected_date, phase=phase)
    _patch_fetcher(monkeypatch, cutoffs=cutoffs, ages=ages)
    return fetched_targets


def test_run_data_pipeline_happy_path(monkeypatch):
    """resolve → auto_fetch → compute → freshness 4 步顺序串好 · DataCtx 字段都填齐。"""
    targets = [("600519", "贵州茅台"), ("000858", "五粮液")]
    fetched_targets = _patch_pipeline_deps(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23), "000858": date(2026, 5, 23)},
        ages={"600519": "2026-05-22T16:00:00", "000858": "2026-05-23T16:00:00"},
    )
    stock_set = _FakeStockSet(pairs=targets, meta=None)
    compute_calls = []

    def _compute(t, **kw):
        compute_calls.append((t, kw))
        return [_FakeResult("600519"), _FakeResult("000858")]

    ctx = pipeline.run_data_pipeline(stock_set, compute=_compute)
    assert ctx.targets == targets
    assert ctx.meta is None
    assert [r.symbol for r in ctx.results] == ["600519", "000858"]
    assert ctx.freshness.data_cutoff == date(2026, 5, 23)
    assert ctx.freshness.fetched_at == "2026-05-23T16:00:00"
    assert ctx.freshness.is_stale is False
    assert ctx.freshness.phase == "post"
    assert fetched_targets == [targets]
    assert compute_calls == [(targets, {})]


def test_run_data_pipeline_counts_targets_missing_from_compute_results(monkeypatch):
    targets = [("600519", "贵州茅台"), ("000858", "五粮液")]
    _patch_pipeline_deps(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23), "000858": None},
        ages={"600519": "2026-05-23T16:00:00"},
    )
    stock_set = _FakeStockSet(pairs=targets)

    ctx = pipeline.run_data_pipeline(
        stock_set,
        compute=lambda _targets, **_kwargs: [_FakeResult("600519")],
        auto_fetch=False,
    )

    assert ctx.freshness.target_count == 2
    assert ctx.freshness.missing_count == 1
    assert ctx.freshness.is_stale is True


def test_run_data_pipeline_passes_meta_through(monkeypatch):
    """stock_set.meta() 返回值原样进 DataCtx.meta(BoardMeta/HotMeta/ThemeMeta sentinel)。"""
    targets = [("600519", "贵州茅台")]
    sentinel_meta = object()
    _patch_pipeline_deps(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23)},
        ages={"600519": "2026-05-23T16:00:00"},
    )
    stock_set = _FakeStockSet(pairs=targets, meta=sentinel_meta, industry="半导体")
    ctx = pipeline.run_data_pipeline(
        stock_set, compute=lambda t, **kw: [_FakeResult("600519")],
    )
    assert ctx.meta is sentinel_meta


def test_run_data_pipeline_forwards_compute_kwargs(monkeypatch):
    """compute_kwargs 原样透传给 compute · 不解释 / 不重命名(mode / candle 等都靠它过去)。"""
    targets = [("600519", "贵州茅台")]
    _patch_pipeline_deps(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23)},
        ages={"600519": "2026-05-23T16:00:00"},
    )
    stock_set = _FakeStockSet(pairs=targets)
    captured = {}

    def _compute(t, **kw):
        captured["targets"] = t
        captured["kwargs"] = kw
        return [_FakeResult("600519")]

    pipeline.run_data_pipeline(
        stock_set, compute=_compute, mode="high", candle=True, extra=42,
    )
    assert captured["targets"] == targets
    assert captured["kwargs"] == {"mode": "high", "candle": True, "extra": 42}


def test_run_data_pipeline_source_error_exits_before_compute(monkeypatch):
    """stock_set.pairs() 抛 source 错误时 · helper 在第 1 步就 Exit · compute 不应被调到。"""
    monkeypatch.setattr(
        "kan.core.pipeline._print_err", lambda msg: None,
    )
    stock_set = _FakeStockSet(
        pairs_error=BoardNotFoundError("ghost industry"),
        industry="ghost industry",
    )
    compute_calls = []

    def _compute(t, **kw):
        compute_calls.append(t)
        return []

    with pytest.raises(typer.Exit) as exc_info:
        pipeline.run_data_pipeline(stock_set, compute=_compute)
    assert exc_info.value.exit_code == 1
    assert compute_calls == []  # compute 不该被调


def test_run_data_pipeline_can_raise_domain_error_before_compute(monkeypatch):
    """service/web 路径可选择 domain error，不被 Typer 绑死。"""
    def fail_print(_msg: str) -> None:
        raise AssertionError("should not print")

    monkeypatch.setattr(
        "kan.core.pipeline._print_err",
        fail_print,
    )
    stock_set = _FakeStockSet(
        pairs_error=BoardNotFoundError("ghost industry"),
        industry="ghost industry",
    )
    compute_calls = []

    def _compute(t, **kw):
        compute_calls.append(t)
        return []

    with pytest.raises(pipeline.StockSetResolveError) as exc_info:
        pipeline.run_data_pipeline(
            stock_set,
            compute=_compute,
            exit_on_resolve_error=False,
        )
    assert exc_info.value.code == "board_not_found"
    assert exc_info.value.exit_code == 1
    assert compute_calls == []


def test_run_data_pipeline_empty_results_yields_stale_freshness(monkeypatch):
    """compute 返回空列表 · freshness_of 收到空 generator · data_cutoff=None / is_stale=True。"""
    _patch_pipeline_deps(monkeypatch, cutoffs={}, ages={})
    stock_set = _FakeStockSet(pairs=[])
    ctx = pipeline.run_data_pipeline(
        stock_set, compute=lambda t, **kw: [],
    )
    assert ctx.results == []
    assert ctx.freshness.data_cutoff is None
    assert ctx.freshness.fetched_at is None
    assert ctx.freshness.is_stale is True


def test_run_data_pipeline_calls_auto_fetch_with_resolved_targets(monkeypatch):
    """_auto_fetch_stale 必须用 stock_set.pairs() 返回的 targets。

    Why:industry/hot/theme 模式下 stock_set.pairs() = 板块成分股 ≠ 自选股 ·
    误用 watchlist 会漏拉板块成分股。
    """
    resolved = [("000001", "平安银行"), ("000002", "万科 A")]
    fetched_targets = _patch_pipeline_deps(
        monkeypatch,
        cutoffs={"000001": date(2026, 5, 23), "000002": date(2026, 5, 23)},
        ages={"000001": "2026-05-23T16:00:00", "000002": "2026-05-23T16:00:00"},
    )
    stock_set = _FakeStockSet(pairs=resolved, industry="银行")
    pipeline.run_data_pipeline(
        stock_set,
        compute=lambda t, **kw: [_FakeResult(s) for s, _ in t],
    )
    assert fetched_targets == [resolved]


def test_run_data_pipeline_passes_fetch_days_to_auto_fetch(monkeypatch):
    """360 日 find/low/high 路径需要把最小缓存行数传给 auto-fetch。"""
    targets = [("600519", "贵州茅台")]
    fetched_calls = []
    monkeypatch.setattr(
        "kan.core.auto_fetch.auto_fetch_stale",
        lambda pairs, **kwargs: fetched_calls.append((pairs, kwargs)),
    )
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 23)},
        ages={"600519": "2026-05-23T16:00:00"},
    )
    stock_set = _FakeStockSet(pairs=targets)

    pipeline.run_data_pipeline(
        stock_set,
        compute=lambda t, **kw: [_FakeResult("600519")],
        fetch_days=360,
    )

    assert fetched_calls == [(targets, {"days": 360})]

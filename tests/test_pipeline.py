"""kan/_pipeline.py 单元测试 · mock 上游(resolve_scan_targets / fetcher / trading_calendar)。"""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest
import typer

from kan import _pipeline
from kan._pipeline import Freshness
from kan.boards import (
    BoardDataUnavailableError,
    BoardNotFoundError,
    ThemeDataUnavailableError,
    ThemeNotFoundError,
)
from kan.hot import HotListUnavailableError
from kan.trading_calendar import PHASE_INTRADAY


def _make_raiser(exc: Exception):
    """生成 raise 指定异常的 fake · 用于 monkeypatch resolve_scan_targets。"""
    def _raise(*args, **kwargs):
        raise exc
    return _raise


# ═══ resolve_targets_or_exit ═══════════════════════════════════════════


def test_resolve_targets_or_exit_no_source_returns_watchlist_pairs():
    """三源都 None → 真实 resolve_scan_targets 直接返回 (pairs, None)。"""
    pairs = [("600519", "贵州茅台"), ("000858", "五粮液")]
    targets, meta = _pipeline.resolve_targets_or_exit(
        None, only_watchlist=False, watchlist_pairs=pairs,
    )
    assert targets is pairs
    assert meta is None


def test_resolve_targets_or_exit_passes_through_return(monkeypatch):
    """成功路径 · resolve_scan_targets 返回值原样返回,不做加工。"""
    expected_targets = [("600519", "贵州茅台")]
    monkeypatch.setattr(
        "kan._pipeline.resolve_scan_targets",
        lambda *a, **kw: (expected_targets, None),
    )
    targets, meta = _pipeline.resolve_targets_or_exit(
        None, only_watchlist=False, watchlist_pairs=expected_targets,
    )
    assert targets is expected_targets
    assert meta is None


def test_resolve_targets_or_exit_passes_kwargs_through(monkeypatch):
    """industry / hot / theme / only_watchlist / pairs 都正确透传给 resolve_scan_targets。"""
    captured = {}

    def _capture(industry, only_watchlist, pairs, *, hot=None, theme=None):
        captured.update(
            industry=industry,
            only_watchlist=only_watchlist,
            pairs=pairs,
            hot=hot,
            theme=theme,
        )
        return ([], None)

    monkeypatch.setattr("kan._pipeline.resolve_scan_targets", _capture)
    _pipeline.resolve_targets_or_exit(
        "半导体",
        only_watchlist=True,
        watchlist_pairs=[("600519", "茅台")],
        hot=None,
        theme=None,
    )
    assert captured == {
        "industry": "半导体",
        "only_watchlist": True,
        "pairs": [("600519", "茅台")],
        "hot": None,
        "theme": None,
    }


@pytest.mark.parametrize(("exc_cls", "expected_code", "msg_part"), [
    (BoardNotFoundError, 1, "未找到行业"),
    (BoardDataUnavailableError, 1, "行业数据源"),
    (HotListUnavailableError, 1, "热榜数据源"),
    (ThemeNotFoundError, 2, "未找到题材"),
    (ThemeDataUnavailableError, 1, "题材数据源"),
])
def test_resolve_targets_or_exit_source_errors(
    monkeypatch, exc_cls, expected_code, msg_part,
):
    """5 类 source 错误统一转换为 _print_err + typer.Exit · exit 码与现状一致。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan._pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    monkeypatch.setattr(
        "kan._pipeline.resolve_scan_targets",
        _make_raiser(exc_cls("test")),
    )
    with pytest.raises(typer.Exit) as exc_info:
        _pipeline.resolve_targets_or_exit(
            "test",
            only_watchlist=False,
            watchlist_pairs=[],
            theme="testtheme",
        )
    assert exc_info.value.exit_code == expected_code
    assert len(err_calls) == 1
    assert msg_part in err_calls[0]


def test_resolve_targets_or_exit_board_not_found_includes_industry_and_examples(
    monkeypatch,
):
    """BoardNotFound 错误消息引用 industry 参数名 + 散户化示例关键词。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan._pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    monkeypatch.setattr(
        "kan._pipeline.resolve_scan_targets",
        _make_raiser(BoardNotFoundError("我的行业")),
    )
    with pytest.raises(typer.Exit):
        _pipeline.resolve_targets_or_exit(
            "我的行业", only_watchlist=False, watchlist_pairs=[],
        )
    msg = err_calls[0]
    assert "我的行业" in msg
    assert "半导体" in msg
    assert "白酒" in msg
    assert "❌" in msg


def test_resolve_targets_or_exit_theme_not_found_includes_theme_and_search_hint(
    monkeypatch,
):
    """ThemeNotFound 错误消息引用 theme 参数名 + 提示 kan theme search。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan._pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    monkeypatch.setattr(
        "kan._pipeline.resolve_scan_targets",
        _make_raiser(ThemeNotFoundError("我的题材")),
    )
    with pytest.raises(typer.Exit):
        _pipeline.resolve_targets_or_exit(
            None, only_watchlist=False, watchlist_pairs=[], theme="我的题材",
        )
    msg = err_calls[0]
    assert "我的题材" in msg
    assert "kan theme search" in msg
    assert "AI" in msg or "华为" in msg


def test_resolve_targets_or_exit_theme_data_unavailable_hints_industry(monkeypatch):
    """ThemeDataUnavailable 提示用户可以退化用 --industry(题材源死时的降级路径)。"""
    err_calls: list[str] = []
    monkeypatch.setattr(
        "kan._pipeline._print_err",
        lambda msg: err_calls.append(msg),
    )
    monkeypatch.setattr(
        "kan._pipeline.resolve_scan_targets",
        _make_raiser(ThemeDataUnavailableError("api down")),
    )
    with pytest.raises(typer.Exit):
        _pipeline.resolve_targets_or_exit(
            None, only_watchlist=False, watchlist_pairs=[], theme="AI",
        )
    msg = err_calls[0]
    assert "题材数据源" in msg
    assert "--industry" in msg


# ═══ Freshness / freshness_of ══════════════════════════════════════════


def _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23), phase="post"):
    """统一 patch latest_trade_date + market_phase。"""
    monkeypatch.setattr(
        "kan.trading_calendar.latest_trade_date", lambda: expected_date,
    )
    monkeypatch.setattr("kan.trading_calendar.market_phase", lambda: phase)


def _patch_fetcher(monkeypatch, cutoffs: dict, ages: dict):
    """patch data_cutoff_date 与 cache_age,字典 lookup,缺失返回 None。"""
    monkeypatch.setattr(
        "kan.fetcher.data_cutoff_date", lambda sym: cutoffs.get(sym),
    )
    monkeypatch.setattr(
        "kan.fetcher.cache_age", lambda sym: ages.get(sym),
    )


def test_freshness_of_empty_symbols(monkeypatch):
    """空 symbols → data_cutoff=None · fetched_at=None · is_stale=True。"""
    _patch_calendar(monkeypatch)
    _patch_fetcher(monkeypatch, cutoffs={}, ages={})
    f = _pipeline.freshness_of([])
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
    f = _pipeline.freshness_of(["600519"])
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
    f = _pipeline.freshness_of(["600519"])
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
    f = _pipeline.freshness_of(["600519", "000858", "300750"])
    assert f.data_cutoff == date(2026, 5, 22)
    assert f.fetched_at == "2026-05-22T16:00:00"
    assert f.is_stale is True


def test_freshness_of_skips_none_cutoff(monkeypatch):
    """某 symbol 无 cutoff → 跳过 · 不影响其他 symbol。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={
            "600519": date(2026, 5, 22),
            "NEW01": None,
        },
        ages={"600519": "2026-05-22T16:00:00"},
    )
    f = _pipeline.freshness_of(["600519", "NEW01"])
    assert f.data_cutoff == date(2026, 5, 22)
    assert f.fetched_at == "2026-05-22T16:00:00"


def test_freshness_of_skips_falsy_cache_age(monkeypatch):
    """cache_age 返回 None / 空串 → 跳过(沿用现状 `if t and ...` 判定)。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 22), "000858": date(2026, 5, 22)},
        ages={"600519": "", "000858": "2026-05-22T16:00:00"},
    )
    f = _pipeline.freshness_of(["600519", "000858"])
    assert f.fetched_at == "2026-05-22T16:00:00"


def test_freshness_of_phase_passthrough(monkeypatch):
    """phase 直接来自 market_phase()。"""
    _patch_calendar(monkeypatch, phase="intraday")
    _patch_fetcher(monkeypatch, cutoffs={}, ages={})
    f = _pipeline.freshness_of([])
    assert f.phase == "intraday"


def test_freshness_of_accepts_generator(monkeypatch):
    """symbols 可以是生成器(支持 `freshness_of(r.symbol for r in results)` 用法)。"""
    _patch_calendar(monkeypatch, expected_date=date(2026, 5, 23))
    _patch_fetcher(
        monkeypatch,
        cutoffs={"600519": date(2026, 5, 22), "000858": date(2026, 5, 21)},
        ages={"600519": "x", "000858": "y"},
    )
    f = _pipeline.freshness_of(sym for sym in ["600519", "000858"])
    assert f.data_cutoff == date(2026, 5, 22)
    assert f.fetched_at == "y"


def test_freshness_returns_frozen_dataclass(monkeypatch):
    """Freshness 是 frozen=True · 不可变 · 防意外修改。"""
    _patch_calendar(monkeypatch)
    _patch_fetcher(monkeypatch, cutoffs={}, ages={})
    f = _pipeline.freshness_of([])
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
    _pipeline.render_freshness_warning(f, console)
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
    _pipeline.render_freshness_warning(f, console)
    msg = console.print.call_args.args[0]
    assert "无缓存" in msg
    assert "? 天" in msg


def test_render_freshness_warning_intraday_prints_intraday_warning():
    """is_stale=False + phase=intraday → 「当前盘中」警告。"""
    console = Mock()
    f = _make_freshness(
        is_stale=False,
        phase=PHASE_INTRADAY,
    )
    _pipeline.render_freshness_warning(f, console)
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
    _pipeline.render_freshness_warning(f, console)
    console.print.assert_not_called()


def test_render_freshness_warning_stale_supersedes_intraday():
    """is_stale=True 即使 phase=intraday · 仍走 stale 分支(互斥优先级)。

    Why(v0.0.4.7 ***REMOVED*** 行为):stale 状态下用户首动作是 fetch → fetch 后会重 scan → 那时再判 intraday。
    """
    console = Mock()
    f = _make_freshness(
        is_stale=True,
        phase=PHASE_INTRADAY,
    )
    _pipeline.render_freshness_warning(f, console)
    msg = console.print.call_args.args[0]
    assert "当前缓存到" in msg  # stale 分支
    assert "盘中" not in msg  # 没走 intraday 分支

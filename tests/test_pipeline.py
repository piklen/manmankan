"""kan/_pipeline.py 单元测试 · mock resolve_scan_targets 与 _print_err · 不走真网络。"""
from __future__ import annotations

import pytest
import typer

from kan import _pipeline
from kan.boards import (
    BoardDataUnavailableError,
    BoardNotFoundError,
    ThemeDataUnavailableError,
    ThemeNotFoundError,
)
from kan.hot import HotListUnavailableError


def _make_raiser(exc: Exception):
    """生成 raise 指定异常的 fake · 用于 monkeypatch resolve_scan_targets。"""
    def _raise(*args, **kwargs):
        raise exc
    return _raise


# ── 透传行为 ──────────────────────────────────────────────────────────


def test_resolve_targets_or_exit_no_source_returns_watchlist_pairs():
    """三源都 None → 真实 resolve_scan_targets 直接返回 (pairs, None)。"""
    pairs = [("600519", "贵州茅台"), ("000858", "五粮液")]
    targets, meta = _pipeline.resolve_targets_or_exit(
        None, only_watchlist=False, watchlist_pairs=pairs,
    )
    assert targets is pairs  # 透传(同一对象)
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


# ── 5 类 source 错误 → typer.Exit ────────────────────────────────────


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
            theme="testtheme",  # 给 theme 错误消息引用用
        )
    assert exc_info.value.exit_code == expected_code
    assert len(err_calls) == 1
    assert msg_part in err_calls[0]


# ── 错误消息内容(防 future 简化导致用户体验回退)──────────────────────


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
    assert "--industry" in msg  # 降级路径提示

"""resolve_scan_targets 加 theme 分支单元测试。"""
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from kan._scan_targets import ThemeMeta, resolve_scan_targets
from kan.models import Theme


@pytest.fixture(autouse=True)
def _mock_adata(monkeypatch):
    """防真网络。"""
    mock_adata = MagicMock()
    monkeypatch.setitem(sys.modules, "adata", mock_adata)
    monkeypatch.setitem(sys.modules, "adata.stock", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock.info", MagicMock())
    return mock_adata


@pytest.fixture(autouse=True)
def _isolate_boards_dir(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    return bdir


def _stub_search_theme(*args, **kwargs):
    return Theme(code="886108", name="AI应用", source="ths")


def _stub_get_constituents(*args, **kwargs):
    return [("002230", "科大讯飞"), ("300033", "同花顺")]


def _stub_fetch_kline(*args, **kwargs):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-21", "2026-05-22", "2026-05-23"]).date,
            "open": [100, 102, 101],
            "high": [103, 104, 102],
            "low": [99, 101, 100],
            "close": [102, 103, 101],
            "volume": [1e6, 2e6, 1.5e6],
            "amount": [1e8, 2e8, 1.5e8],
        }
    )


def test_resolve_theme_returns_constituents_and_theme_meta(monkeypatch):
    """--theme=AI应用 + 自选 [(002230,科大讯飞)] → targets=成分股全 · ThemeMeta.highlight={'002230'}。"""
    monkeypatch.setattr("kan.boards.search_theme", _stub_search_theme)
    monkeypatch.setattr("kan.boards.get_theme_constituents", _stub_get_constituents)
    monkeypatch.setattr("kan.boards.fetch_theme_kline", _stub_fetch_kline)

    watchlist = [("002230", "科大讯飞")]
    targets, meta = resolve_scan_targets(
        industry=None, only_watchlist=False, watchlist_pairs=watchlist, theme="AI应用"
    )
    assert isinstance(meta, ThemeMeta)
    assert meta.theme.name == "AI应用"
    assert meta.highlight == {"002230"}
    assert len(targets) == 2


def test_resolve_theme_only_watchlist_filters(monkeypatch):
    """--theme + --only-watchlist → targets = 成分股 ∩ 自选。"""
    monkeypatch.setattr("kan.boards.search_theme", _stub_search_theme)
    monkeypatch.setattr("kan.boards.get_theme_constituents", _stub_get_constituents)
    monkeypatch.setattr("kan.boards.fetch_theme_kline", _stub_fetch_kline)

    watchlist = [("002230", "科大讯飞")]
    targets, meta = resolve_scan_targets(
        industry=None, only_watchlist=True, watchlist_pairs=watchlist, theme="AI应用"
    )
    assert targets == [("002230", "科大讯飞")]
    assert meta.highlight == {"002230"}


def test_resolve_industry_theme_mutually_exclusive():
    """--industry + --theme 同时指定 → ValueError。"""
    with pytest.raises(ValueError, match=r"互斥|不能同时"):
        resolve_scan_targets(
            industry="半导体", only_watchlist=False, watchlist_pairs=[], theme="AI应用"
        )


def test_resolve_hot_theme_mutually_exclusive():
    """--hot + --theme 同时指定 → ValueError。"""
    from kan.hot import HotList
    with pytest.raises(ValueError, match=r"互斥|不能同时"):
        resolve_scan_targets(
            industry=None,
            only_watchlist=False,
            watchlist_pairs=[],
            hot=HotList.RANK,
            theme="AI应用",
        )


def test_resolve_theme_kline_failure_degrades(monkeypatch):
    """题材 K 线拉取失败 → ThemeMeta.index_kline 为空 DataFrame · 不阻塞 targets。"""
    from kan.boards import ThemeDataUnavailableError

    monkeypatch.setattr("kan.boards.search_theme", _stub_search_theme)
    monkeypatch.setattr("kan.boards.get_theme_constituents", _stub_get_constituents)

    def kline_fail(theme, force=False):
        raise ThemeDataUnavailableError("kline down")

    monkeypatch.setattr("kan.boards.fetch_theme_kline", kline_fail)
    targets, meta = resolve_scan_targets(
        industry=None, only_watchlist=False, watchlist_pairs=[], theme="AI应用"
    )
    assert isinstance(meta, ThemeMeta)
    assert meta.index_kline.empty or len(meta.index_kline) == 0
    assert len(targets) == 2  # 成分股仍可用

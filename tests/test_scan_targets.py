import pandas as pd

from kan.core.models import Board
from kan.core.scan_targets import resolve_scan_targets
from kan.data import boards


def test_no_industry_returns_watchlist_unchanged():
    wl = [("600519", "贵州茅台"), ("000858", "五粮液")]
    targets, meta = resolve_scan_targets(None, only_watchlist=False, watchlist_pairs=wl)
    assert targets == wl
    assert meta is None


def test_industry_returns_constituents_and_meta(monkeypatch):
    board = Board(code="801016", name="种植业", level=2, size=2)
    cons = [("000998", "隆平高科"), ("600519", "贵州茅台")]
    kline = pd.DataFrame({"date": ["2026-05-21"], "close": [1000.0]})
    monkeypatch.setattr(boards, "search_industry", lambda q: board)
    monkeypatch.setattr(boards, "get_industry_constituents", lambda b, force=False: cons)
    monkeypatch.setattr(boards, "fetch_industry_kline", lambda b, force=False: kline)

    wl = [("600519", "贵州茅台")]
    targets, meta = resolve_scan_targets("种植业", only_watchlist=False, watchlist_pairs=wl)
    assert targets == cons
    assert meta is not None
    assert meta.board == board
    assert meta.highlight == {"600519"}  # 成分股 ∩ 自选


def test_only_watchlist_filters_to_intersection(monkeypatch):
    board = Board(code="801016", name="种植业", level=2, size=2)
    cons = [("000998", "隆平高科"), ("600519", "贵州茅台")]
    monkeypatch.setattr(boards, "search_industry", lambda q: board)
    monkeypatch.setattr(boards, "get_industry_constituents", lambda b, force=False: cons)
    monkeypatch.setattr(boards, "fetch_industry_kline", lambda b, force=False: pd.DataFrame())

    wl = [("600519", "贵州茅台")]
    targets, meta = resolve_scan_targets("种植业", only_watchlist=True, watchlist_pairs=wl)
    assert targets == [("600519", "贵州茅台")]
    assert meta.highlight == {"600519"}

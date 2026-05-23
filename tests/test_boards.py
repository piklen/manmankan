import json

import pandas as pd
import pytest

from kan.core.models import Board
from kan.data import boards


@pytest.fixture(autouse=True)
def _isolate_boards_dir(tmp_path, monkeypatch):
    """boards cache 指向 tmp · 杜绝读写真实 ~/.local/share/kan/boards/。"""
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    return bdir


def _fake_sw_df(rows):
    return pd.DataFrame(rows, columns=["行业代码", "行业名称", "成份个数"])


def test_load_catalog_merges_three_levels(monkeypatch):
    monkeypatch.setattr(
        "akshare.sw_index_first_info",
        lambda: _fake_sw_df([["801080.SI", "电子", 300]]),
    )
    monkeypatch.setattr(
        "akshare.sw_index_second_info",
        lambda: _fake_sw_df([["801081.SI", "半导体", 131]]),
    )
    monkeypatch.setattr(
        "akshare.sw_index_third_info",
        lambda: _fake_sw_df([["850000.SI", "种子", 8]]),
    )
    catalog = boards.load_industry_catalog(force=True)
    assert len(catalog) == 3
    assert {b.level for b in catalog} == {1, 2, 3}
    assert all(isinstance(b, Board) for b in catalog)
    assert catalog[0].code == "801080"  # 后缀 .SI 已剥


def test_catalog_uses_cache_within_ttl(monkeypatch, _isolate_boards_dir):
    cache = _isolate_boards_dir / "catalog_sw.json"
    cache.write_text(
        json.dumps([{"code": "801080", "name": "电子", "level": 1, "size": 300}]),
        encoding="utf-8",
    )

    def _boom():
        raise AssertionError("不应调用 akshare · 应命中 cache")

    monkeypatch.setattr("akshare.sw_index_first_info", _boom)
    catalog = boards.load_industry_catalog()
    assert catalog[0].name == "电子"


def test_search_industry_exact_and_fuzzy(monkeypatch):
    monkeypatch.setattr(
        "akshare.sw_index_first_info",
        lambda: _fake_sw_df([["801080.SI", "电子", 300]]),
    )
    monkeypatch.setattr(
        "akshare.sw_index_second_info",
        lambda: _fake_sw_df([["801081.SI", "半导体", 131]]),
    )
    monkeypatch.setattr("akshare.sw_index_third_info", lambda: _fake_sw_df([]))
    boards.load_industry_catalog(force=True)
    assert boards.search_industry("半导体").code == "801081"   # 精确名
    assert boards.search_industry("801080").name == "电子"      # 精确代码
    assert boards.search_industry("电").name == "电子"          # 模糊含


def test_search_industry_not_found(monkeypatch):
    monkeypatch.setattr(
        "akshare.sw_index_first_info",
        lambda: _fake_sw_df([["801080.SI", "电子", 300]]),
    )
    monkeypatch.setattr(
        "akshare.sw_index_second_info",
        lambda: _fake_sw_df([["801081.SI", "半导体", 131]]),
    )
    monkeypatch.setattr("akshare.sw_index_third_info", lambda: _fake_sw_df([]))
    boards.load_industry_catalog(force=True)
    with pytest.raises(boards.BoardNotFoundError):
        boards.search_industry("不存在的行业")


def test_catalog_all_empty_raises_unavailable(monkeypatch):
    monkeypatch.setattr("akshare.sw_index_first_info", lambda: _fake_sw_df([]))
    monkeypatch.setattr("akshare.sw_index_second_info", lambda: _fake_sw_df([]))
    monkeypatch.setattr("akshare.sw_index_third_info", lambda: _fake_sw_df([]))
    with pytest.raises(boards.BoardDataUnavailableError):
        boards.load_industry_catalog(force=True)


def test_get_constituents_returns_pairs(monkeypatch):
    cons_df = pd.DataFrame(
        [["1", "000998", "隆平高科"], ["2", "002041", "登海种业"]],
        columns=["序号", "证券代码", "证券名称"],
    )
    monkeypatch.setattr("akshare.index_component_sw", lambda symbol: cons_df)
    board = Board(code="801016", name="种植业", level=2, size=20)
    pairs = boards.get_industry_constituents(board, force=True)
    assert pairs == [("000998", "隆平高科"), ("002041", "登海种业")]


def test_get_constituents_uses_cache(monkeypatch, _isolate_boards_dir):
    cache = _isolate_boards_dir / "cons_801016.json"
    cache.write_text(json.dumps([["600519", "贵州茅台"]]), encoding="utf-8")

    def _boom(symbol):
        raise AssertionError("应命中 cache")

    monkeypatch.setattr("akshare.index_component_sw", _boom)
    board = Board(code="801016", name="种植业", level=2, size=20)
    assert boards.get_industry_constituents(board) == [("600519", "贵州茅台")]


def test_fetch_industry_kline_normalizes_schema(monkeypatch):
    raw = pd.DataFrame(
        {
            "代码": ["801016", "801016"],
            "日期": ["2026-05-20", "2026-05-21"],
            "收盘": [1300.0, 1320.0],
            "开盘": [1290.0, 1305.0],
            "最高": [1325.0, 1330.0],
            "最低": [1288.0, 1300.0],
            "成交量": [1.0e8, 1.1e8],
            "成交额": [2.0e11, 2.1e11],
        }
    )
    monkeypatch.setattr(
        "akshare.index_hist_sw", lambda symbol, period="day": raw
    )
    board = Board(code="801016", name="种植业", level=2, size=20)
    df = boards.fetch_industry_kline(board, force=True)
    assert list(df.columns) == [
        "date", "open", "high", "low", "close", "volume", "amount",
    ]
    assert len(df) == 2
    # scan_stock 能直接吃:有 date/close/low/high
    from kan.core.scanner import scan_stock
    result = scan_stock(df, board.code, board.name)
    assert result.symbol == "801016"


def test_fetch_industry_kline_empty_raises(monkeypatch):
    monkeypatch.setattr(
        "akshare.index_hist_sw", lambda symbol, period="day": pd.DataFrame()
    )
    board = Board(code="801016", name="种植业", level=2, size=20)
    with pytest.raises(boards.BoardDataUnavailableError):
        boards.fetch_industry_kline(board, force=True)

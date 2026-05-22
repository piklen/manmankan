import json

import pandas as pd
import pytest

from kan import boards
from kan.models import Board


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
    with pytest.raises(boards.BoardNotFound):
        boards.search_industry("不存在的行业")


def test_catalog_all_empty_raises_unavailable(monkeypatch):
    monkeypatch.setattr("akshare.sw_index_first_info", lambda: _fake_sw_df([]))
    monkeypatch.setattr("akshare.sw_index_second_info", lambda: _fake_sw_df([]))
    monkeypatch.setattr("akshare.sw_index_third_info", lambda: _fake_sw_df([]))
    with pytest.raises(boards.BoardDataUnavailable):
        boards.load_industry_catalog(force=True)

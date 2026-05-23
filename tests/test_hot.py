"""kan/hot.py 单元测试 · mock akshare · 不走真网络。"""
import json
import os
import time

import pandas as pd
import pytest

from kan import hot
from kan.hot import HotEntry, HotList, HotListUnavailableError


@pytest.fixture(autouse=True)
def _isolate_hot_dir(tmp_path, monkeypatch):
    """hot cache 指向 tmp · 杜绝读写真实 ~/.local/share/kan/hot/。"""
    hdir = tmp_path / "hot"
    hdir.mkdir()
    monkeypatch.setattr(hot, "HOT_DIR", hdir)
    return hdir


def _fake_rank_df(rows):
    """rows: list of [当前排名, 代码, 股票名称]。"""
    return pd.DataFrame(rows, columns=["当前排名", "代码", "股票名称"])


def test_fetch_hot_list_normalizes_codes(monkeypatch):
    monkeypatch.setattr(
        "akshare.stock_hot_rank_em",
        lambda: _fake_rank_df([
            [1, "SZ000725", "京东方Ａ"],
            [2, "SH600519", "贵州茅台"],
        ]),
    )
    entries = hot.fetch_hot_list(HotList.RANK, force=True)
    assert entries == [
        HotEntry(rank=1, symbol="000725", name="京东方Ａ"),
        HotEntry(rank=2, symbol="600519", name="贵州茅台"),
    ]


def test_fetch_hot_list_skips_bad_codes(monkeypatch):
    monkeypatch.setattr(
        "akshare.stock_hot_rank_em",
        lambda: _fake_rank_df([
            [1, "SZ000725", "京东方Ａ"],
            [2, "HK00700", "腾讯控股"],   # 港股 · 归一化后非 6 位数字 → 跳过
        ]),
    )
    entries = hot.fetch_hot_list(HotList.RANK, force=True)
    assert len(entries) == 1
    assert entries[0].symbol == "000725"


def test_fetch_hot_list_uses_cache(monkeypatch, _isolate_hot_dir):
    cache = _isolate_hot_dir / "hot_rank.json"
    cache.write_text(
        json.dumps([{"rank": 1, "symbol": "600519", "name": "贵州茅台"}]),
        encoding="utf-8",
    )

    def _boom():
        raise AssertionError("不应调用 akshare · 应命中 cache")

    monkeypatch.setattr("akshare.stock_hot_rank_em", _boom)
    entries = hot.fetch_hot_list(HotList.RANK)
    assert entries[0].name == "贵州茅台"


def test_fetch_hot_list_empty_raises(monkeypatch):
    monkeypatch.setattr("akshare.stock_hot_rank_em", lambda: pd.DataFrame())
    with pytest.raises(HotListUnavailableError):
        hot.fetch_hot_list(HotList.RANK, force=True)


def test_fetch_hot_list_akshare_error_raises(monkeypatch):
    def _raise():
        raise ConnectionError("network down")

    monkeypatch.setattr("akshare.stock_hot_rank_em", _raise)
    with pytest.raises(HotListUnavailableError):
        hot.fetch_hot_list(HotList.RANK, force=True)


def test_fetch_hot_list_all_bad_codes_raises(monkeypatch):
    monkeypatch.setattr(
        "akshare.stock_hot_rank_em",
        lambda: _fake_rank_df([[1, "HK00700", "腾讯控股"]]),
    )
    with pytest.raises(HotListUnavailableError):
        hot.fetch_hot_list(HotList.RANK, force=True)


def test_surge_uses_stock_hot_up_em(monkeypatch):
    called = []
    monkeypatch.setattr(
        "akshare.stock_hot_up_em",
        lambda: called.append("up") or _fake_rank_df([[5, "SH603759", "海天股份"]]),
    )
    entries = hot.fetch_hot_list(HotList.SURGE, force=True)
    assert called == ["up"]
    assert entries[0].symbol == "603759"


def test_hot_list_name():
    assert hot.hot_list_name(HotList.RANK) == "东财人气榜"
    assert hot.hot_list_name(HotList.SURGE) == "东财飙升榜"


def test_fetch_hot_list_stale_cache_refetches(monkeypatch, _isolate_hot_dir):
    """cache 存在但超 1h TTL → 重新拉 akshare,不返回旧数据。"""
    cache = _isolate_hot_dir / "hot_rank.json"
    cache.write_text(
        json.dumps([{"rank": 1, "symbol": "000001", "name": "旧数据"}]),
        encoding="utf-8",
    )
    old = time.time() - 7200  # 2h 前 · 超过 1h TTL
    os.utime(cache, (old, old))

    monkeypatch.setattr(
        "akshare.stock_hot_rank_em",
        lambda: _fake_rank_df([[1, "SZ000725", "京东方Ａ"]]),
    )
    entries = hot.fetch_hot_list(HotList.RANK)  # force=False · cache 已 stale
    assert entries[0].name == "京东方Ａ"   # 新数据,不是 "旧数据"

"""热榜数据层失败路径 · 不走真网络。"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from kan.data import hot
from kan.data.hot import HotEntry, HotList, HotListUnavailableError


def _isolate_hot_paths(tmp_path, monkeypatch):
    hot_dir = tmp_path / "hot"
    names_cache = tmp_path / "stock_names.json"
    hot_dir.mkdir(parents=True)
    monkeypatch.setattr(hot, "HOT_DIR", hot_dir)
    monkeypatch.setattr(hot, "STOCK_NAMES_CACHE", names_cache)
    return hot_dir, names_cache


def test_surge_uses_eastmoney_direct_fallback_when_akshare_fails(tmp_path, monkeypatch):
    hot_dir, names_cache = _isolate_hot_paths(tmp_path, monkeypatch)
    names_cache.write_text(
        json.dumps({"600706": "曲江文旅", "300011": "鼎汉技术"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_hot_up_em=lambda: (_ for _ in ()).throw(ValueError("empty json"))),
    )
    monkeypatch.setattr(
        hot,
        "_post_json",
        lambda _url, _payload: {
            "data": [
                {"sc": "SH600706", "rk": 3427},
                {"sc": "SZ300011", "rk": "3735"},
            ]
        },
    )

    entries = hot.fetch_hot_list(HotList.SURGE, force=True)

    assert entries == [
        HotEntry(rank=3427, symbol="600706", name="曲江文旅"),
        HotEntry(rank=3735, symbol="300011", name="鼎汉技术"),
    ]
    assert (hot_dir / "hot_surge.json").exists()


def test_fetch_hot_list_uses_stale_cache_when_source_fails(tmp_path, monkeypatch):
    hot_dir, _names_cache = _isolate_hot_paths(tmp_path, monkeypatch)
    (hot_dir / "hot_rank.json").write_text(
        json.dumps([{"rank": 1, "symbol": "600519", "name": "贵州茅台"}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_hot_rank_em=lambda: (_ for _ in ()).throw(RuntimeError("down"))),
    )

    entries = hot.fetch_hot_list(HotList.RANK, force=True)

    assert entries == [HotEntry(rank=1, symbol="600519", name="贵州茅台")]


def test_surge_failure_keeps_unavailable_error_when_all_fallbacks_fail(tmp_path, monkeypatch):
    _isolate_hot_paths(tmp_path, monkeypatch)
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_hot_up_em=lambda: (_ for _ in ()).throw(ValueError("empty json"))),
    )
    monkeypatch.setattr(
        hot,
        "_post_json",
        lambda _url, _payload: (_ for _ in ()).throw(
            HotListUnavailableError("direct down")
        ),
    )

    try:
        hot.fetch_hot_list(HotList.SURGE, force=True)
    except HotListUnavailableError as e:
        assert "direct fallback" in str(e)
    else:
        raise AssertionError("expected HotListUnavailableError")

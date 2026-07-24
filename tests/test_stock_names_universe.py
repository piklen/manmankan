"""代码表 universe 增强(北交所 920 段)测试。"""
from __future__ import annotations

from kan.storage import watchlist_names


def test_augment_adds_missing_bj_codes(monkeypatch) -> None:
    monkeypatch.setattr(
        "kan.data.universe.fetch_all_stocks",
        lambda: [("920799", "艾融软件"), ("600519", "贵州茅台"), ("bad", "x"), ("920001", "")],
    )
    mapping = {"600519": "贵州茅台-old"}

    out = watchlist_names._augment_with_universe(mapping)

    # 只补缺:920799 加入 · 600519 不覆盖 · 非法代码/空名跳过
    assert out["920799"] == "艾融软件"
    assert out["600519"] == "贵州茅台-old"
    assert "bad" not in out
    assert "920001" not in out


def test_augment_fail_open_when_universe_unavailable(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("no token")

    monkeypatch.setattr("kan.data.universe.fetch_all_stocks", _boom)
    mapping = {"600519": "贵州茅台"}

    assert watchlist_names._augment_with_universe(mapping) == {"600519": "贵州茅台"}

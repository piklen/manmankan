"""真实持仓存储测试。"""
from __future__ import annotations

import stat

import pytest


@pytest.fixture
def isolated_positions(tmp_path, monkeypatch):
    from kan.storage import positions

    base = tmp_path / "kan"
    monkeypatch.setattr(positions, "POSITIONS_PATH", base / "positions.json")
    monkeypatch.setattr(positions, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        positions,
        "_load_cached_names",
        lambda: {"600519": "贵州茅台", "000858": "五粮液", "300750": "宁德时代"},
    )
    return positions


def test_add_merge_reduce_remove_and_permissions(isolated_positions) -> None:
    positions = isolated_positions

    first = positions.add_position("sh600519", cost=1680.0, shares=100)
    assert first.symbol == "600519"
    assert first.name == "贵州茅台"

    merged = positions.add_position("600519", cost=1600.0, shares=100, merge=True)
    assert merged.shares == 200
    assert merged.cost == 1640.0

    reduced, removed = positions.reduce_position("600519", shares=50)
    assert removed is False
    assert reduced.shares == 150
    assert reduced.cost == 1640.0

    removed_position, removed = positions.reduce_position("600519", shares=150)
    assert removed is True
    assert removed_position.symbol == "600519"
    assert positions.load_positions().positions == []

    path = positions.POSITIONS_PATH
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_add_positions_rejects_existing_without_silent_overwrite(isolated_positions) -> None:
    positions = isolated_positions
    positions.add_position("600519", cost=1680.0, shares=100)
    row = positions.parse_compact_token("600519:1500:100")

    with pytest.raises(ValueError, match="已有持仓"):
        positions.add_positions([row])

    stored = positions.load_positions().find("600519")
    assert stored is not None
    assert stored.cost == 1680.0
    assert stored.shares == 100


def test_import_text_supports_header_stdin_and_overwrites_for_correction(isolated_positions) -> None:
    positions = isolated_positions
    positions.add_position("600519", cost=1680.0, shares=100)

    rows = positions.parse_import_text(
        "名称,代码,成本,股数\n"
        "贵州茅台,600519,1660,120\n"
        "五粮液,000858,150,200\n"
    )
    summary = positions.import_positions(rows)

    assert summary.count == 2
    book = positions.load_positions()
    maotai = book.find("600519")
    wuliangye = book.find("000858")
    assert maotai is not None and maotai.cost == 1660.0 and maotai.shares == 120
    assert wuliangye is not None and wuliangye.name == "五粮液"


def test_set_cash_validates_non_negative(isolated_positions) -> None:
    positions = isolated_positions

    assert positions.set_cash(73000.129).cash == 73000.13
    with pytest.raises(ValueError, match="现金不能为负"):
        positions.set_cash(-1)

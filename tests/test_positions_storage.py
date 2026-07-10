"""真实持仓存储测试。"""
from __future__ import annotations

import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
    assert stat.S_IMODE(path.with_suffix(".lock").stat().st_mode) == 0o600


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


def test_cost_rounding_cannot_write_an_unreadable_position(isolated_positions) -> None:
    positions = isolated_positions

    with pytest.raises(ValueError, match=r"至少为 0\.0001"):
        positions.add_position("600519", cost=0.00001, shares=100)

    assert positions.load_positions().positions == []


def test_successful_position_write_can_be_reloaded(isolated_positions) -> None:
    positions = isolated_positions

    positions.add_position("600519", cost=0.0001, shares=100)

    stored = positions.load_positions().find("600519")
    assert stored is not None
    assert stored.cost == 0.0001


@pytest.mark.parametrize(
    ("cost", "shares", "message"),
    [
        (float("nan"), 100, "成本至少为"),
        (-1.0, 100, "成本至少为"),
        (10_000_001.0, 100, "成本超出"),
        (10.0, 10_000_000_001, "股数超出"),
    ],
)
def test_merge_rejects_invalid_lot_without_corrupting_existing_position(
    isolated_positions, cost, shares, message
) -> None:
    positions = isolated_positions
    positions.add_position("600519", cost=100.0, shares=100)

    with pytest.raises(ValueError, match=message):
        positions.add_position(
            "600519",
            cost=cost,
            shares=shares,
            merge=True,
        )

    stored = positions.load_positions().find("600519")
    assert stored is not None
    assert stored.cost == 100.0
    assert stored.shares == 100


def test_concurrent_position_writes_do_not_lose_rows(isolated_positions) -> None:
    positions = isolated_positions
    symbols = [f"60{index:04d}" for index in range(20)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(
            lambda symbol: positions.add_position(symbol, cost=10.0, shares=100),
            symbols,
        ))

    assert {row.symbol for row in positions.load_positions().positions} == set(symbols)


def test_windows_positions_lock_locks_and_releases_first_byte(
    isolated_positions, tmp_path, monkeypatch
) -> None:
    positions = isolated_positions
    calls: list[tuple[int, int]] = []
    fake_msvcrt = SimpleNamespace(
        LK_LOCK=1,
        LK_UNLCK=2,
        locking=lambda _fd, mode, size: calls.append((mode, size)),
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    with open(tmp_path / "positions.lock", "a+b") as handle:
        lock = positions._windows_positions_lock(handle)
        next(lock)
        assert handle.read(1) == b"\0"
        with pytest.raises(StopIteration):
            next(lock)

    assert calls == [(fake_msvcrt.LK_LOCK, 1), (fake_msvcrt.LK_UNLCK, 1)]

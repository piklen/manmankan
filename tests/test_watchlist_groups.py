"""watchlist 多分组测试 · 历史背景。

覆盖:
- v1 → v2 schema 自动迁移幂等
- group CRUD (create / list / rename / delete / default / copy)
- default 组保护(不可删 / 不可重命名到合并)
- move_stock 跨组 (源/目标不存在 / 同股已在目标组)
- 同股可同时在多组(独立 added_at)
- 0o600 权限延续(持仓画像隐私底线)
- 老 API thin wrapper 仍返 default 组
"""
from __future__ import annotations

import json
import os
import stat
from datetime import date
from pathlib import Path

import pytest

from kan.core.models import Stock
from kan.storage import paths, watchlist


@pytest.fixture
def temp_kan_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(paths, "STOCK_NAMES_CACHE", tmp_path / "stock_names.json")
    monkeypatch.setattr(paths, "SNAPSHOT_PATH", tmp_path / "last_scan.json")
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(watchlist, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(watchlist, "STOCK_NAMES_CACHE", tmp_path / "stock_names.json")
    return tmp_path


# ───────────────────── v1 → v2 迁移 ─────────────────────


def test_v2_schema_roundtrip(temp_kan_dir):
    """v2 schema 写回 + 读回保持完整。"""
    gw = watchlist.GroupedWatchlist(
        groups={
            "自选": [Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1))],
            "持仓": [Stock(symbol="000858", name="五粮液", added_at=date(2026, 5, 15))],
        },
        default="自选",
    )
    watchlist.save_grouped_watchlist(gw)

    loaded = watchlist.load_grouped_watchlist()
    assert loaded.default == "自选"
    assert set(loaded.groups) == {"自选", "持仓"}
    assert loaded.groups["持仓"][0].symbol == "000858"
    assert loaded.groups["持仓"][0].added_at == date(2026, 5, 15)


def test_load_grouped_watchlist_empty_file_creates_default(temp_kan_dir):
    """无 watchlist.json 时返 GroupedWatchlist 含 default 组(空)。"""
    gw = watchlist.load_grouped_watchlist()
    assert gw.default == "自选"
    assert gw.groups == {"自选": []}


def test_v2_corrupted_default_recovers(temp_kan_dir):
    """v2 但 default 指向不存在组 → 降级到第一个组(防御性)。"""
    bad = {
        "version": 2,
        "default": "幽灵组",
        "groups": {"自选": {"stocks": []}, "持仓": {"stocks": []}},
    }
    watchlist.WATCHLIST_PATH.write_text(json.dumps(bad, ensure_ascii=False))
    gw = watchlist.load_grouped_watchlist()
    # 降级到第一个存在的组(自选)
    assert gw.default in {"自选", "持仓"}
    assert gw.default in gw.groups


# ───────────────────── group CRUD ─────────────────────


def test_create_group(temp_kan_dir):
    name = watchlist.create_group("持仓")
    assert name == "持仓"
    gs = watchlist.list_groups()
    assert {g[0] for g in gs} == {"自选", "持仓"}


def test_create_group_strips_whitespace(temp_kan_dir):
    name = watchlist.create_group("  短线池  ")
    assert name == "短线池"


def test_create_group_duplicate_raises(temp_kan_dir):
    watchlist.create_group("持仓")
    with pytest.raises(watchlist.GroupExistsError, match="已存在"):
        watchlist.create_group("持仓")


def test_create_group_empty_name_raises(temp_kan_dir):
    with pytest.raises(ValueError, match="不能为空"):
        watchlist.create_group("")
    with pytest.raises(ValueError, match="不能为空"):
        watchlist.create_group("   ")


def test_create_group_rejects_special_chars(temp_kan_dir):
    with pytest.raises(ValueError, match="特殊字符"):
        watchlist.create_group("a/b")
    with pytest.raises(ValueError, match="特殊字符"):
        watchlist.create_group("a\nb")


def test_create_group_too_long_raises(temp_kan_dir):
    with pytest.raises(ValueError, match="过长"):
        watchlist.create_group("a" * 33)


def test_list_groups_marks_default(temp_kan_dir):
    watchlist.create_group("持仓")
    gs = watchlist.list_groups()
    by_name = {g[0]: g for g in gs}
    assert by_name["自选"][2] is True   # is_default
    assert by_name["持仓"][2] is False


def test_rename_group(temp_kan_dir):
    watchlist.create_group("temp")
    new = watchlist.rename_group("temp", "持仓")
    assert new == "持仓"
    names = {g[0] for g in watchlist.list_groups()}
    assert "持仓" in names
    assert "temp" not in names


def test_rename_default_updates_default_pointer(temp_kan_dir):
    """重命名 default 组时 · default 指针自动跟着改。"""
    new = watchlist.rename_group("自选", "watchlist")
    assert new == "watchlist"
    assert watchlist.get_default_group() == "watchlist"


def test_rename_nonexistent_raises(temp_kan_dir):
    with pytest.raises(watchlist.GroupNotFoundError):
        watchlist.rename_group("ghost", "持仓")


def test_rename_to_existing_raises(temp_kan_dir):
    watchlist.create_group("a")
    watchlist.create_group("b")
    with pytest.raises(watchlist.GroupExistsError, match="拒绝合并"):
        watchlist.rename_group("a", "b")


def test_rename_to_same_name_is_noop(temp_kan_dir):
    """重命名到自己 = noop (不抛 GroupExistsError)。"""
    watchlist.create_group("x")
    new = watchlist.rename_group("x", "x")
    assert new == "x"


def test_delete_group(temp_kan_dir):
    watchlist.create_group("temp")
    count = watchlist.delete_group("temp")
    assert count == 0
    assert "temp" not in {g[0] for g in watchlist.list_groups()}


def test_delete_default_group_protected(temp_kan_dir):
    """default 组不能删 · 必须先 default 切换。"""
    with pytest.raises(watchlist.GroupProtectedError, match="默认组"):
        watchlist.delete_group("自选")


def test_delete_group_returns_stock_count(temp_kan_dir):
    watchlist.create_group("temp")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["temp"] = [
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1)),
        Stock(symbol="000858", name="五粮液", added_at=date(2026, 5, 1)),
    ]
    watchlist.save_grouped_watchlist(gw)
    count = watchlist.delete_group("temp")
    assert count == 2


def test_set_default_group(temp_kan_dir):
    watchlist.create_group("持仓")
    old = watchlist.set_default_group("持仓")
    assert old == "自选"
    assert watchlist.get_default_group() == "持仓"


def test_set_default_to_nonexistent_raises(temp_kan_dir):
    with pytest.raises(watchlist.GroupNotFoundError):
        watchlist.set_default_group("ghost")


def test_copy_group(temp_kan_dir):
    gw = watchlist.load_grouped_watchlist()
    gw.groups["自选"] = [
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1)),
        Stock(symbol="000858", name="五粮液", added_at=date(2026, 5, 1)),
    ]
    watchlist.save_grouped_watchlist(gw)

    count = watchlist.copy_group("自选", "短线池")
    assert count == 2

    gw2 = watchlist.load_grouped_watchlist()
    src_codes = {s.symbol for s in gw2.groups["自选"]}
    dst_codes = {s.symbol for s in gw2.groups["短线池"]}
    assert src_codes == dst_codes == {"600519", "000858"}


def test_copy_group_dst_exists_rejected(temp_kan_dir):
    """目标已存在拒绝复制 (防误覆盖)。"""
    watchlist.create_group("dst")
    with pytest.raises(watchlist.GroupExistsError, match="拒绝覆盖"):
        watchlist.copy_group("自选", "dst")


def test_copy_group_src_missing_raises(temp_kan_dir):
    with pytest.raises(watchlist.GroupNotFoundError, match="源组"):
        watchlist.copy_group("ghost", "新")


# ───────────────────── move_stock 跨组 ─────────────────────


def test_move_stock_basic(temp_kan_dir):
    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["自选"] = [
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1)),
    ]
    watchlist.save_grouped_watchlist(gw)

    stock, existed = watchlist.move_stock("600519", "自选", "持仓")
    assert stock.symbol == "600519"
    assert existed is False

    after = watchlist.load_grouped_watchlist()
    assert [s.symbol for s in after.groups["自选"]] == []
    assert [s.symbol for s in after.groups["持仓"]] == ["600519"]


def test_move_stock_dst_already_has(temp_kan_dir):
    """目标组已有该股 → 只从源组移除 · 不重复添加。"""
    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    early = Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1))
    later = Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 20))
    gw.groups["自选"] = [later]
    gw.groups["持仓"] = [early]
    watchlist.save_grouped_watchlist(gw)

    _stock, existed = watchlist.move_stock("600519", "自选", "持仓")
    assert existed is True

    after = watchlist.load_grouped_watchlist()
    assert [s.symbol for s in after.groups["自选"]] == []
    # 目标组保留原 added_at(不替换为源组的新 added_at)
    assert len(after.groups["持仓"]) == 1
    assert after.groups["持仓"][0].added_at == date(2026, 5, 1)


def test_move_stock_src_missing_raises(temp_kan_dir):
    with pytest.raises(watchlist.GroupNotFoundError, match="源组"):
        watchlist.move_stock("600519", "ghost", "自选")


def test_move_stock_dst_missing_raises(temp_kan_dir):
    """目标组不存在拒绝(不自动建组 · 防 typo)。"""
    with pytest.raises(watchlist.GroupNotFoundError, match="目标组"):
        watchlist.move_stock("600519", "自选", "ghost")


def test_move_stock_not_in_src_raises(temp_kan_dir):
    watchlist.create_group("持仓")
    with pytest.raises(ValueError, match="不在"):
        watchlist.move_stock("600519", "自选", "持仓")


# ───────────────────── 同股多组 ─────────────────────


def test_same_stock_in_multiple_groups(temp_kan_dir):
    """同股可以独立存在于多个组 · added_at 各自独立。"""
    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["自选"] = [
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1)),
    ]
    gw.groups["持仓"] = [
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 15)),
    ]
    watchlist.save_grouped_watchlist(gw)

    after = watchlist.load_grouped_watchlist()
    assert after.groups["自选"][0].added_at == date(2026, 5, 1)
    assert after.groups["持仓"][0].added_at == date(2026, 5, 15)


# ───────────────────── 0o600 权限延续 ─────────────────────


@pytest.mark.skipif(os.name == "nt", reason="Windows 无 POSIX 权限")
def test_v2_storage_keeps_0o600_permissions(temp_kan_dir):
    """v2 schema 写入仍是 0o600 (持仓画像隐私底线)。"""
    watchlist.create_group("持仓")
    mode = stat.S_IMODE(watchlist.WATCHLIST_PATH.stat().st_mode)
    assert mode == 0o600, f"v2 watchlist.json 权限应为 0o600 · 实际 0o{mode:o}"


# ───────────────────── 老 API 向后兼容 ─────────────────────


def test_old_load_watchlist_returns_default_group(temp_kan_dir):
    """老 load_watchlist() 不带参 → 返 default 组 (向后兼容)。"""
    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["自选"] = [
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1)),
    ]
    gw.groups["持仓"] = [
        Stock(symbol="000858", name="五粮液", added_at=date(2026, 5, 1)),
    ]
    watchlist.save_grouped_watchlist(gw)

    wl = watchlist.load_watchlist()
    codes = {s.symbol for s in wl.stocks}
    assert codes == {"600519"}, "load_watchlist() 应返 default 组（自选）· 不包含持仓"


def test_old_save_watchlist_writes_default_group(temp_kan_dir):
    """老 save_watchlist(wl) 不带 group → 写 default 组 (向后兼容)。"""
    watchlist.create_group("持仓")
    new = watchlist.Watchlist(stocks=[
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1)),
    ])
    watchlist.save_watchlist(new)

    gw = watchlist.load_grouped_watchlist()
    assert {s.symbol for s in gw.groups["自选"]} == {"600519"}
    assert gw.groups["持仓"] == [], "save_watchlist 不应擦掉其他组"


def test_add_to_specific_group(temp_kan_dir):
    """add(symbol, group=X) 加到指定组(不是 default)。"""
    watchlist.create_group("持仓")
    # mock name lookup 避免触发网络
    from unittest.mock import patch

    with patch("kan.storage.watchlist_items._lookup_name", return_value="贵州茅台"):
        ok, _msg = watchlist.add("600519", group="持仓")
    assert ok

    gw = watchlist.load_grouped_watchlist()
    assert gw.groups["自选"] == []
    assert {s.symbol for s in gw.groups["持仓"]} == {"600519"}


def test_remove_from_specific_group(temp_kan_dir):
    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["持仓"] = [
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1)),
    ]
    watchlist.save_grouped_watchlist(gw)

    ok, _msg = watchlist.remove("600519", group="持仓")
    assert ok

    gw2 = watchlist.load_grouped_watchlist()
    assert gw2.groups["持仓"] == []


def test_clear_only_target_group(temp_kan_dir):
    """clear(group=X) 只清指定组 · 不影响其他组。"""
    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["自选"] = [Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1))]
    gw.groups["持仓"] = [Stock(symbol="000858", name="五粮液", added_at=date(2026, 5, 1))]
    watchlist.save_grouped_watchlist(gw)

    count = watchlist.clear(group="持仓")
    assert count == 1

    gw2 = watchlist.load_grouped_watchlist()
    assert {s.symbol for s in gw2.groups["自选"]} == {"600519"}, "default 组应保留"
    assert gw2.groups["持仓"] == []


def test_clear_default_keeps_other_groups(temp_kan_dir):
    """clear() 不带 group → 只清 default · 其他组保留。"""
    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["自选"] = [Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1))]
    gw.groups["持仓"] = [Stock(symbol="000858", name="五粮液", added_at=date(2026, 5, 1))]
    watchlist.save_grouped_watchlist(gw)

    count = watchlist.clear()
    assert count == 1
    gw2 = watchlist.load_grouped_watchlist()
    assert gw2.groups["自选"] == []
    assert {s.symbol for s in gw2.groups["持仓"]} == {"000858"}


def test_add_to_nonexistent_group_raises(temp_kan_dir):
    from unittest.mock import patch

    with (
        patch("kan.storage.watchlist_items._lookup_name", return_value="贵州茅台"),
        pytest.raises(watchlist.GroupNotFoundError, match="不存在"),
    ):
        watchlist.add("600519", group="ghost")

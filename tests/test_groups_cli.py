"""kan group / kan move / kan export / watchlist 命令带 --group 的 CLI 集成测试 ·
v0.0.6.1 引入。

测试策略:
- temp_kan_dir 隔离 watchlist.json
- mock _load_names_with_optional_spinner / _lookup_name (避免 baostock/akshare)
- CliRunner.invoke 跑实际命令 · assert stdout + exit code + 文件副作用
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kan.app import app
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


@pytest.fixture
def fake_names() -> dict[str, str]:
    return {
        "600519": "贵州茅台",
        "000858": "五粮液",
        "000001": "平安银行",
    }


@pytest.fixture
def runner(temp_kan_dir, fake_names, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setattr(
        "kan.cli.watchlist_cmds._load_names_with_optional_spinner",
        lambda _console: fake_names,
    )
    monkeypatch.setattr(
        "kan.storage.watchlist._load_stock_names",
        lambda: fake_names,
    )
    return CliRunner()


# ───────────────────── kan group create / list ─────────────────────


def test_group_create_basic(runner):
    result = runner.invoke(app, ["group", "create", "持仓"])
    assert result.exit_code == 0
    assert "已创建组「持仓」" in result.output

    gs = {g[0] for g in watchlist.list_groups()}
    assert gs == {"自选", "持仓"}


def test_group_create_duplicate_exits_2(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    result = runner.invoke(app, ["group", "create", "持仓"])
    assert result.exit_code == 2
    assert "已存在" in result.output


def test_group_create_empty_name_exits_2(runner):
    result = runner.invoke(app, ["group", "create", "  "])
    assert result.exit_code == 2
    assert "不能为空" in result.output


def test_group_create_special_chars_rejected(runner):
    result = runner.invoke(app, ["group", "create", "a/b"])
    assert result.exit_code == 2
    assert "特殊字符" in result.output


def test_group_list_shows_default(runner):
    result = runner.invoke(app, ["group", "list"])
    assert result.exit_code == 0
    assert "自选" in result.output
    assert "默认" in result.output


def test_group_list_shows_all_groups(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["group", "create", "短线池"])
    result = runner.invoke(app, ["group", "list"])
    assert result.exit_code == 0
    assert "自选" in result.output
    assert "持仓" in result.output
    assert "短线池" in result.output


# ───────────────────── kan group rename / delete / default ─────────────────────


def test_group_rename(runner):
    runner.invoke(app, ["group", "create", "temp"])
    result = runner.invoke(app, ["group", "rename", "temp", "持仓"])
    assert result.exit_code == 0
    assert "重命名为「持仓」" in result.output


def test_group_rename_default_updates_pointer(runner):
    result = runner.invoke(app, ["group", "rename", "自选", "watchlist"])
    assert result.exit_code == 0
    assert watchlist.get_default_group() == "watchlist"


def test_group_delete_protected_default(runner):
    """default 组 不能删 → exit 2。"""
    result = runner.invoke(app, ["group", "delete", "自选"])
    assert result.exit_code == 2
    assert "默认组" in result.output or "不能删除" in result.output


def test_group_delete_empty_group_skips_confirm(runner):
    runner.invoke(app, ["group", "create", "temp"])
    result = runner.invoke(app, ["group", "delete", "temp"])
    assert result.exit_code == 0
    assert "已删除组" in result.output


def test_group_delete_with_stocks_asks_confirm(runner):
    """有股票的组删除前要确认。"""
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519", "--group", "持仓"])
    # 输入 n 取消
    result = runner.invoke(app, ["group", "delete", "持仓"], input="n\n")
    assert result.exit_code == 0
    assert "已取消" in result.output

    gs = {g[0] for g in watchlist.list_groups()}
    assert "持仓" in gs  # 没被删


def test_group_delete_with_yes_skips_confirm(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519", "--group", "持仓"])
    result = runner.invoke(app, ["group", "delete", "持仓", "--yes"])
    assert result.exit_code == 0
    assert "已删除" in result.output


def test_group_default_switches_target(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    result = runner.invoke(app, ["group", "default", "持仓"])
    assert result.exit_code == 0
    assert "default 组" in result.output
    assert watchlist.get_default_group() == "持仓"


def test_group_default_no_arg_shows_current(runner):
    result = runner.invoke(app, ["group", "default"])
    assert result.exit_code == 0
    assert "自选" in result.output


# ───────────────────── kan group copy ─────────────────────


def test_group_copy_basic(runner):
    runner.invoke(app, ["add", "600519"])  # 加到 default
    result = runner.invoke(app, ["group", "copy", "自选", "短线池"])
    assert result.exit_code == 0
    assert "1 只" in result.output

    gw = watchlist.load_grouped_watchlist()
    assert {s.symbol for s in gw.groups["自选"]} == {"600519"}
    assert {s.symbol for s in gw.groups["短线池"]} == {"600519"}


def test_group_copy_dst_exists_rejected(runner):
    runner.invoke(app, ["group", "create", "dst"])
    result = runner.invoke(app, ["group", "copy", "自选", "dst"])
    assert result.exit_code == 2
    assert "已存在" in result.output or "拒绝覆盖" in result.output


# ───────────────────── kan add --group / remove --group ─────────────────────


def test_add_with_group_adds_to_target(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    result = runner.invoke(app, ["add", "600519", "--group", "持仓"])
    assert result.exit_code == 0
    assert "「持仓」" in result.output

    gw = watchlist.load_grouped_watchlist()
    assert gw.groups["自选"] == []
    assert {s.symbol for s in gw.groups["持仓"]} == {"600519"}


def test_add_to_nonexistent_group_exits_2(runner):
    result = runner.invoke(app, ["add", "600519", "--group", "ghost"])
    assert result.exit_code == 2
    assert "不存在" in result.output


def test_remove_with_group(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519", "--group", "持仓"])
    result = runner.invoke(app, ["remove", "600519", "--group", "持仓"])
    assert result.exit_code == 0
    assert "已移除" in result.output

    gw = watchlist.load_grouped_watchlist()
    assert gw.groups["持仓"] == []


# ───────────────────── kan list --group / --all ─────────────────────


def test_list_with_group(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519", "--group", "持仓"])
    result = runner.invoke(app, ["list", "--group", "持仓"])
    assert result.exit_code == 0
    assert "600519" in result.output
    assert "贵州茅台" in result.output


def test_list_all_shows_each_group(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519"])
    runner.invoke(app, ["add", "000858", "--group", "持仓"])

    result = runner.invoke(app, ["list", "--all"])
    assert result.exit_code == 0
    assert "自选" in result.output
    assert "持仓" in result.output
    assert "600519" in result.output
    assert "000858" in result.output


def test_list_all_with_group_rejects(runner):
    result = runner.invoke(app, ["list", "--all", "--group", "持仓"])
    assert result.exit_code == 2


# ───────────────────── kan clear --group ─────────────────────


def test_clear_specific_group_keeps_others(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519"])
    runner.invoke(app, ["add", "000858", "--group", "持仓"])
    result = runner.invoke(app, ["clear", "--group", "持仓", "--yes"])
    assert result.exit_code == 0

    gw = watchlist.load_grouped_watchlist()
    assert {s.symbol for s in gw.groups["自选"]} == {"600519"}
    assert gw.groups["持仓"] == []


# ───────────────────── kan move ─────────────────────


def test_move_basic(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519"])
    result = runner.invoke(app, ["move", "600519", "自选", "持仓"])
    assert result.exit_code == 0
    assert "已移动" in result.output

    gw = watchlist.load_grouped_watchlist()
    assert gw.groups["自选"] == []
    assert {s.symbol for s in gw.groups["持仓"]} == {"600519"}


def test_move_dst_nonexistent_exits_2(runner):
    runner.invoke(app, ["add", "600519"])
    result = runner.invoke(app, ["move", "600519", "自选", "ghost"])
    assert result.exit_code == 2
    assert "不存在" in result.output


def test_move_src_nonexistent_exits_2(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    result = runner.invoke(app, ["move", "600519", "ghost", "持仓"])
    assert result.exit_code == 2


def test_move_dst_already_has_only_removes_from_src(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519"])
    runner.invoke(app, ["add", "600519", "--group", "持仓"])

    result = runner.invoke(app, ["move", "600519", "自选", "持仓"])
    assert result.exit_code == 0
    assert "已有该股" in result.output

    gw = watchlist.load_grouped_watchlist()
    assert gw.groups["自选"] == []
    assert len(gw.groups["持仓"]) == 1  # 不重复


def test_move_by_name(runner):
    """move 接受名称模糊搜 (跟 add 同入口)。"""
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519"])
    result = runner.invoke(app, ["move", "茅台", "自选", "持仓"])
    assert result.exit_code == 0
    assert "贵州茅台" in result.output


# ───────────────────── kan export ─────────────────────


def test_export_default_group_csv(runner):
    runner.invoke(app, ["add", "600519"])
    runner.invoke(app, ["add", "000858"])
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 0
    assert "symbol,name,added_at" in result.output
    assert "600519" in result.output
    assert "000858" in result.output


def test_export_specific_group(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519", "--group", "持仓"])
    runner.invoke(app, ["add", "000858"])  # default 组
    result = runner.invoke(app, ["export", "--group", "持仓"])
    assert result.exit_code == 0
    assert "600519" in result.output
    assert "000858" not in result.output


def test_export_all_groups_includes_group_column(runner):
    runner.invoke(app, ["group", "create", "持仓"])
    runner.invoke(app, ["add", "600519"])
    runner.invoke(app, ["add", "000858", "--group", "持仓"])
    result = runner.invoke(app, ["export", "--all"])
    assert result.exit_code == 0
    assert "group,symbol,name,added_at" in result.output
    assert "自选" in result.output
    assert "持仓" in result.output


def test_export_all_with_group_rejects(runner):
    result = runner.invoke(app, ["export", "--all", "--group", "持仓"])
    assert result.exit_code == 2


# ───────────────────── WatchlistSet(group=) ─────────────────────


def test_watchlistset_with_group_loads_target(temp_kan_dir):
    """WatchlistSet(group=X) 走该组 · 不带 group 走 default。"""
    from kan.core.stock_set import WatchlistSet

    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["自选"] = [Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1))]
    gw.groups["持仓"] = [Stock(symbol="000858", name="五粮液", added_at=date(2026, 5, 1))]
    watchlist.save_grouped_watchlist(gw)

    default_set = WatchlistSet()
    assert default_set.codes() == ["600519"]

    holding = WatchlistSet(group="持仓")
    assert holding.codes() == ["000858"]
    # name 自动加组名 suffix
    assert "持仓" in holding.name


def test_from_flags_with_watchlist_group(temp_kan_dir):
    """from_flags(watchlist_group=X) 构造 WatchlistSet 走指定组。"""
    from kan.core.stock_set import WatchlistSet, from_flags

    watchlist.create_group("持仓")
    gw = watchlist.load_grouped_watchlist()
    gw.groups["持仓"] = [Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 1))]
    watchlist.save_grouped_watchlist(gw)

    ss = from_flags(watchlist_group="持仓")
    assert isinstance(ss, WatchlistSet)
    assert ss.codes() == ["600519"]


# ───────────────────── 整体回归 ─────────────────────


def test_old_v1_storage_users_unaffected(temp_kan_dir):
    """老用户的 v1 watchlist.json 仍能 kan list / kan scan · 透明迁移。"""
    v1 = {
        "stocks": [
            {"symbol": "600519", "name": "贵州茅台", "added_at": "2026-05-01"},
        ]
    }
    watchlist.WATCHLIST_PATH.write_text(json.dumps(v1, ensure_ascii=False))

    runner = CliRunner()
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "600519" in result.output

    # 验证已透明升级到 v2
    data = json.loads(watchlist.WATCHLIST_PATH.read_text())
    assert data.get("version") == 2

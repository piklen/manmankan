"""watchlist remove/list runner 边界测试。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.core.models import Board, Stock
from kan.data import boards
from kan.storage import paths, watchlist


@pytest.fixture
def temp_kan_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        "000001": "平安银行",
        "601318": "中国平安",
        "300750": "宁德时代",
    }


@pytest.fixture
def cli_runner(temp_kan_dir, fake_names, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    watchlist.STOCK_NAMES_CACHE.write_text(json.dumps(fake_names, ensure_ascii=False))
    monkeypatch.setattr(
        "kan.cli.watchlist_add._load_names_with_optional_spinner",
        lambda _console: fake_names,
    )
    return CliRunner()


@pytest.fixture
def fake_board(monkeypatch: pytest.MonkeyPatch):
    board = Board(code="801016", name="食品饮料", level=2, size=3)
    cons = [("600519", "贵州茅台"), ("000858", "五粮液"), ("000998", "隆平高科")]
    monkeypatch.setattr(boards, "search_industry", lambda q: board)
    monkeypatch.setattr(
        boards, "get_industry_constituents", lambda b, force=False: cons
    )
    return board, cons


@pytest.fixture
def fake_theme(monkeypatch: pytest.MonkeyPatch):
    themed = Board(code="T001", name="AI应用", level=1, size=2)
    cons = [("300750", "宁德时代"), ("600519", "贵州茅台")]
    monkeypatch.setattr(boards, "search_theme", lambda q: themed)
    monkeypatch.setattr(
        boards, "get_theme_constituents", lambda t, force=False: cons
    )
    return themed, cons


def _stock(symbol: str, name: str) -> Stock:
    return Stock(symbol=symbol, name=name, added_at=date(2026, 5, 1))


def test_remove_without_symbols_exits_2(cli_runner):
    """remove 无参数时给中文提示。"""
    result = cli_runner.invoke(app, ["remove"])

    assert result.exit_code == 2
    assert "请告诉我要移除哪只股票" in result.output


def test_remove_blank_symbol_reports_failure(cli_runner):
    """remove 空字符串应报告无效输入。"""
    result = cli_runner.invoke(app, ["remove", ""])

    assert result.exit_code == 1
    assert "空字符串不是有效股票名" in result.output


def test_remove_numeric_group_not_found(cli_runner):
    """remove 数字代码时，指定不存在组 → Exit 2。"""
    result = cli_runner.invoke(app, ["remove", "600519", "--group=不存在"])

    assert result.exit_code == 2
    assert "不存在" in result.output


def test_remove_numeric_value_error(cli_runner, monkeypatch):
    """storage.remove 抛 ValueError 时输出错误并 exit 1。"""
    monkeypatch.setattr(
        "kan.storage.watchlist.remove",
        lambda code, group=None: (_ for _ in ()).throw(ValueError("bad code")),
    )

    result = cli_runner.invoke(app, ["remove", "600519"])

    assert result.exit_code == 1
    assert "bad code" in result.output


def test_remove_by_name_success(cli_runner):
    """remove 支持按唯一名称匹配移除。"""
    watchlist.save_watchlist(
        watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")])
    )

    result = cli_runner.invoke(app, ["remove", "茅台"])

    assert result.exit_code == 0
    assert "已移除 贵州茅台 (600519)" in result.output
    assert not watchlist.load_watchlist().stocks


def test_remove_by_name_no_match(cli_runner):
    """remove 名称无匹配 → Exit 1。"""
    result = cli_runner.invoke(app, ["remove", "茅台"])

    assert result.exit_code == 1
    assert "没有包含「茅台」" in result.output


def test_remove_by_name_multi_match(cli_runner):
    """remove 名称多匹配时列候选，要求用户用代码。"""
    watchlist.save_watchlist(
        watchlist.Watchlist(
            stocks=[
                _stock("000001", "平安银行"),
                _stock("601318", "中国平安"),
            ]
        )
    )

    result = cli_runner.invoke(app, ["remove", "平安"])

    assert result.exit_code == 1
    assert "匹配到 2 只自选股" in result.output
    assert "000001" in result.output
    assert "601318" in result.output


def test_remove_industry_data_unavailable(cli_runner, monkeypatch):
    """行业数据源不可用 → Exit 1。"""
    def _raise(_industry):
        raise boards.BoardDataUnavailableError("unavailable")

    monkeypatch.setattr(boards, "search_industry", _raise)
    result = cli_runner.invoke(app, ["remove", "--industry=食品饮料"])

    assert result.exit_code == 1
    assert "行业数据源暂时不可用" in result.output


def test_remove_industry_group_not_found(cli_runner, fake_board):
    """remove --industry 指定不存在组 → Exit 2。"""
    result = cli_runner.invoke(app, ["remove", "--industry=食品饮料", "--group=不存在"])

    assert result.exit_code == 2
    assert "不存在" in result.output


def test_remove_theme_requires_confirm(cli_runner, fake_theme):
    """remove --theme 默认弹确认，用户取消时不删。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("300750", "宁德时代")]))

    result = cli_runner.invoke(app, ["remove", "--theme=AI应用"], input="n\n")

    assert result.exit_code == 0
    assert "已取消" in result.output
    assert any(s.symbol == "300750" for s in watchlist.load_watchlist().stocks)


def test_remove_theme_yes_removes_intersection(cli_runner, fake_theme):
    """remove --theme --yes 只删除自选 ∩ 题材成分。"""
    watchlist.save_watchlist(
        watchlist.Watchlist(
            stocks=[
                _stock("300750", "宁德时代"),
                _stock("000001", "平安银行"),
            ]
        )
    )

    result = cli_runner.invoke(app, ["remove", "--theme=AI应用", "--yes"])

    assert result.exit_code == 0
    codes = {s.symbol for s in watchlist.load_watchlist().stocks}
    assert codes == {"000001"}


def test_remove_theme_empty(cli_runner, fake_theme):
    """自选里没有该题材成分时不弹确认。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("000001", "平安银行")]))

    result = cli_runner.invoke(app, ["remove", "--theme=AI应用"])

    assert result.exit_code == 0
    assert "没有「AI应用」题材的股票" in result.output
    assert "继续?" not in result.output


def test_remove_theme_conflicts_with_symbols(cli_runner, fake_theme):
    """remove 同时给股票代码和 --theme → Exit 2。"""
    result = cli_runner.invoke(app, ["remove", "600519", "--theme=AI应用"])

    assert result.exit_code == 2
    assert "二选一" in result.output


def test_remove_industry_and_theme_conflict(cli_runner, fake_board, fake_theme):
    """remove 同时指定 --industry 和 --theme → Exit 2。"""
    result = cli_runner.invoke(
        app, ["remove", "--industry=食品饮料", "--theme=AI应用"]
    )

    assert result.exit_code == 2
    assert "二选一" in result.output


def test_remove_theme_not_found(cli_runner, monkeypatch):
    """题材搜不到 → Exit 2。"""
    def _raise(q):
        raise boards.ThemeNotFoundError(q)

    monkeypatch.setattr(boards, "search_theme", _raise)
    result = cli_runner.invoke(app, ["remove", "--theme=不存在"])

    assert result.exit_code == 2
    assert "未找到题材" in result.output


def test_remove_theme_data_unavailable(cli_runner, monkeypatch):
    """题材数据源不可用 → Exit 1。"""
    def _raise(_theme):
        raise boards.ThemeDataUnavailableError("unavailable")

    monkeypatch.setattr(boards, "search_theme", _raise)
    result = cli_runner.invoke(app, ["remove", "--theme=AI应用"])

    assert result.exit_code == 1
    assert "题材数据源暂时不可用" in result.output


def test_remove_theme_group_not_found(cli_runner, fake_theme):
    """remove --theme 指定不存在组 → Exit 2。"""
    result = cli_runner.invoke(app, ["remove", "--theme=AI应用", "--group=不存在"])

    assert result.exit_code == 2
    assert "不存在" in result.output


def test_list_all_empty(cli_runner):
    """list --all 在所有组为空时给提示。"""
    result = cli_runner.invoke(app, ["list", "--all"])

    assert result.exit_code == 0
    assert "所有组都是空的" in result.output


def test_list_all_includes_empty_group(cli_runner):
    """list --all 应显示空组分段。"""
    cli_runner.invoke(app, ["group", "create", "空组"])
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")]))

    result = cli_runner.invoke(app, ["list", "--all"])

    assert result.exit_code == 0
    assert "空组" in result.output
    assert "空" in result.output


def test_list_group_not_found(cli_runner):
    """list 指定不存在组 → Exit 2。"""
    result = cli_runner.invoke(app, ["list", "--group=不存在"])

    assert result.exit_code == 2
    assert "不存在" in result.output


def test_list_industry_not_found(cli_runner, monkeypatch):
    """list --industry 行业搜不到 → Exit 1。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")]))

    def _raise(q):
        raise boards.BoardNotFoundError(q)

    monkeypatch.setattr(boards, "search_industry", _raise)
    result = cli_runner.invoke(app, ["list", "--industry=不存在"])

    assert result.exit_code == 1
    assert "未找到行业" in result.output


def test_list_industry_data_unavailable(cli_runner, monkeypatch):
    """list --industry 数据源不可用 → Exit 1。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")]))

    def _raise(_industry):
        raise boards.BoardDataUnavailableError("unavailable")

    monkeypatch.setattr(boards, "search_industry", _raise)
    result = cli_runner.invoke(app, ["list", "--industry=食品饮料"])

    assert result.exit_code == 1
    assert "行业数据源暂时不可用" in result.output


def test_list_industry_empty(cli_runner, fake_board):
    """list --industry 无交集时给空提示。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("000001", "平安银行")]))

    result = cli_runner.invoke(app, ["list", "--industry=食品饮料"])

    assert result.exit_code == 0
    assert "没有属于「食品饮料」行业" in result.output


def test_list_theme_not_found(cli_runner, monkeypatch):
    """list --theme 题材搜不到 → Exit 2。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")]))

    def _raise(q):
        raise boards.ThemeNotFoundError(q)

    monkeypatch.setattr(boards, "search_theme", _raise)
    result = cli_runner.invoke(app, ["list", "--theme=不存在"])

    assert result.exit_code == 2
    assert "未找到题材" in result.output


def test_list_theme_data_unavailable(cli_runner, monkeypatch):
    """list --theme 数据源不可用 → Exit 1。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")]))

    def _raise(_theme):
        raise boards.ThemeDataUnavailableError("unavailable")

    monkeypatch.setattr(boards, "search_theme", _raise)
    result = cli_runner.invoke(app, ["list", "--theme=AI应用"])

    assert result.exit_code == 1
    assert "题材数据源暂时不可用" in result.output


def test_list_theme_empty(cli_runner, fake_theme):
    """list --theme 无交集时给空提示。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("000001", "平安银行")]))

    result = cli_runner.invoke(app, ["list", "--theme=AI应用"])

    assert result.exit_code == 0
    assert "没有属于「AI应用」题材" in result.output

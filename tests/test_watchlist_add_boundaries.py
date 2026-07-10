"""watchlist add runner 边界测试。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.cli import watchlist_add
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
        "002007": "平安股份",
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


def test_fetch_added_empty_is_noop():
    """_fetch_added 空列表直接返回，不触发数据拉取。"""
    assert watchlist_add._fetch_added([]) is None


def test_fetch_added_reports_failures(monkeypatch, capsys):
    """_fetch_added 输出失败摘要和前几条错误。"""
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, days: ({"600519": object()}, {"000001": "boom"}),
    )

    watchlist_add._fetch_added(["600519", "000001"])

    captured = capsys.readouterr()
    assert "成功 1 · 失败 1" in captured.err
    assert "000001: boom" in captured.err


def test_add_from_stdin_mixes_literal_symbols(cli_runner):
    """`kan add 000001 -` 保留普通参数并展开 stdin。"""
    result = cli_runner.invoke(app, ["add", "000001", "-"], input="600519\n")

    assert result.exit_code == 0
    codes = [s.symbol for s in watchlist.load_watchlist().stocks]
    assert codes == ["000001", "600519"]


def test_add_without_symbols_exits_2(cli_runner):
    """add 无参数时给中文提示。"""
    result = cli_runner.invoke(app, ["add"])

    assert result.exit_code == 2
    assert "请告诉我要加哪只股票" in result.output


def test_add_short_numeric_code_rejected_before_name_lookup(
    temp_kan_dir,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """明显非法数字代码应即时失败，不加载全市场名称表。"""
    monkeypatch.setattr(
        "kan.cli.watchlist_add._load_names_with_optional_spinner",
        lambda _console: (_ for _ in ()).throw(AssertionError("不应加载名称表")),
    )

    result = CliRunner().invoke(app, ["add", "123"])

    assert result.exit_code == 2
    assert "不是 6 位股票代码" in result.output


def test_add_dry_run_without_pool_rejected(cli_runner):
    """--dry-run 只适用于行业/题材批量添加。"""
    result = cli_runner.invoke(app, ["add", "--dry-run"])

    assert result.exit_code == 2
    assert "--dry-run 仅支持" in result.output


def test_add_batch_blank_and_unknown_reports_failures(cli_runner):
    """批量 add 中空字符串和未知名称应累计失败并 exit 1。"""
    result = cli_runner.invoke(app, ["add", "", "不存在"])

    assert result.exit_code == 1
    assert "空字符串不是有效股票名" in result.output
    assert "未找到包含「不存在」" in result.output
    assert "失败 2" in result.output


def test_add_batch_duplicate_name_reports_skip(cli_runner):
    """批量名称添加时，第二次匹配到已存在股票应进入 skip 明细。"""
    result = cli_runner.invoke(app, ["add", "茅台", "茅台"])

    assert result.exit_code == 0
    assert "跳过" in result.output
    assert "已在自选" in result.output


def test_add_single_fetch_runs_after_save(cli_runner, monkeypatch):
    """单只 add --fetch 走单只结束分支。"""
    fetched: list[list[str]] = []
    monkeypatch.setattr(
        "kan.cli.watchlist_add._fetch_added",
        lambda codes: fetched.append(list(codes)),
    )

    result = cli_runner.invoke(app, ["add", "600519", "--fetch"])

    assert result.exit_code == 0
    assert fetched == [["600519"]]


def test_add_industry_group_not_found(cli_runner, fake_board):
    """add --industry 指定不存在组 → Exit 2。"""
    result = cli_runner.invoke(app, ["add", "--industry=食品饮料", "--group=不存在"])

    assert result.exit_code == 2
    assert "不存在" in result.output


def test_add_industry_data_unavailable(cli_runner, monkeypatch):
    """行业数据源不可用 → Exit 1。"""
    def _raise(_industry):
        raise boards.BoardDataUnavailableError("unavailable")

    monkeypatch.setattr(boards, "search_industry", _raise)
    result = cli_runner.invoke(app, ["add", "--industry=食品饮料"])

    assert result.exit_code == 1
    assert "行业数据源暂时不可用" in result.output


def test_add_industry_dry_run(cli_runner, fake_board):
    """add --industry --dry-run 只预览，不写 watchlist。"""
    result = cli_runner.invoke(app, ["add", "--industry=食品饮料", "--dry-run"])

    assert result.exit_code == 0
    assert "dry-run: 未写入自选股" in result.output
    assert len(watchlist.load_watchlist().stocks) == 0


def test_add_industry_fetches_after_yes(cli_runner, fake_board, monkeypatch):
    """add --industry --fetch 对新增成分股触发拉取。"""
    fetched: list[list[str]] = []
    monkeypatch.setattr(
        "kan.cli.watchlist_add._fetch_added",
        lambda codes: fetched.append(list(codes)),
    )

    result = cli_runner.invoke(app, ["add", "--industry=食品饮料", "--yes", "--fetch"])

    assert result.exit_code == 0
    assert fetched == [["600519", "000858", "000998"]]


def test_add_theme_yes(cli_runner, fake_theme):
    """add --theme --yes 写入题材成分股。"""
    result = cli_runner.invoke(app, ["add", "--theme=AI应用", "--yes"])

    assert result.exit_code == 0
    assert "已加 2 只AI应用股" in result.output
    codes = {s.symbol for s in watchlist.load_watchlist().stocks}
    assert codes == {"300750", "600519"}


def test_add_theme_dry_run(cli_runner, fake_theme):
    """add --theme --dry-run 不写入。"""
    result = cli_runner.invoke(app, ["add", "--theme=AI应用", "--dry-run"])

    assert result.exit_code == 0
    assert "dry-run: 未写入自选股" in result.output
    assert len(watchlist.load_watchlist().stocks) == 0


def test_add_theme_conflicts_with_symbols(cli_runner, fake_theme):
    """add 同时给股票代码和 --theme → Exit 2。"""
    result = cli_runner.invoke(app, ["add", "600519", "--theme=AI应用"])

    assert result.exit_code == 2
    assert "二选一" in result.output


def test_add_theme_not_found(cli_runner, monkeypatch):
    """题材搜不到 → Exit 2。"""
    def _raise(q):
        raise boards.ThemeNotFoundError(q)

    monkeypatch.setattr(boards, "search_theme", _raise)
    result = cli_runner.invoke(app, ["add", "--theme=不存在"])

    assert result.exit_code == 2
    assert "未找到题材" in result.output


def test_add_theme_data_unavailable(cli_runner, monkeypatch):
    """题材数据源不可用 → Exit 1。"""
    def _raise(_theme):
        raise boards.ThemeDataUnavailableError("unavailable")

    monkeypatch.setattr(boards, "search_theme", _raise)
    result = cli_runner.invoke(app, ["add", "--theme=AI应用"])

    assert result.exit_code == 1
    assert "题材数据源暂时不可用" in result.output


def test_add_theme_group_not_found(cli_runner, fake_theme):
    """add --theme 指定不存在组 → Exit 2。"""
    result = cli_runner.invoke(app, ["add", "--theme=AI应用", "--group=不存在"])

    assert result.exit_code == 2
    assert "不存在" in result.output


def test_add_theme_all_already_present(cli_runner, fake_theme):
    """题材成分股全部已存在时不弹确认。"""
    _theme, cons = fake_theme
    watchlist.save_watchlist(
        watchlist.Watchlist(stocks=[_stock(code, name) for code, name in cons])
    )

    result = cli_runner.invoke(app, ["add", "--theme=AI应用"])

    assert result.exit_code == 0
    assert "无需添加" in result.output
    assert "继续?" not in result.output


def test_add_theme_cancel(cli_runner, fake_theme):
    """add --theme 用户取消时不写入。"""
    result = cli_runner.invoke(app, ["add", "--theme=AI应用"], input="n\n")

    assert result.exit_code == 0
    assert "已取消" in result.output
    assert len(watchlist.load_watchlist().stocks) == 0


def test_add_theme_fetches_after_yes(cli_runner, fake_theme, monkeypatch):
    """add --theme --fetch 对新增成分股触发拉取。"""
    fetched: list[list[str]] = []
    monkeypatch.setattr(
        "kan.cli.watchlist_add._fetch_added",
        lambda codes: fetched.append(list(codes)),
    )

    result = cli_runner.invoke(app, ["add", "--theme=AI应用", "--yes", "--fetch"])

    assert result.exit_code == 0
    assert fetched == [["300750", "600519"]]

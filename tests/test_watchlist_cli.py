"""watchlist CLI 命令组 CliRunner 真测(v0.0.4.8:行覆盖率 13% → 60%+)

测试策略:
- 用 temp_kan_dir fixture 隔离 watchlist.json
- mock _load_names_with_optional_spinner 返 fake name map (避免真跑 baostock/akshare)
- CliRunner.invoke 跑实际命令 · assert stdout/stderr

覆盖命令: add / remove / list / clear
"""
from __future__ import annotations

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
    """每个测试用临时目录 · 避免污染真实 watchlist."""
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(paths, "STOCK_NAMES_CACHE", tmp_path / "stock_names.json")
    monkeypatch.setattr(paths, "SNAPSHOT_PATH", tmp_path / "last_scan.json")
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(
        watchlist, "WATCHLIST_PATH", tmp_path / "watchlist.json"
    )
    monkeypatch.setattr(
        watchlist, "STOCK_NAMES_CACHE", tmp_path / "stock_names.json"
    )
    return tmp_path


@pytest.fixture
def fake_names() -> dict[str, str]:
    """fake stock name map · 避免 add 跑真实 baostock/akshare 拉名称."""
    return {
        "600519": "贵州茅台",
        "000001": "平安银行",
        "601318": "中国平安",
        "002007": "平安股份",  # 多匹配 case
        "300750": "宁德时代",
    }


@pytest.fixture
def cli_runner(temp_kan_dir, fake_names, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """watchlist CLI CliRunner · mock 全部 name lookup 走 fake_names."""
    monkeypatch.setattr(
        "kan.cli.watchlist_cmds._load_names_with_optional_spinner",
        lambda _console: fake_names,
    )
    return CliRunner()


# ════════════════════════════════════════════════════════════════
# add 命令 (cli_watchlist_cmds.py:67-184)
# ════════════════════════════════════════════════════════════════
def test_add_command_by_code_succeeds(cli_runner, fake_names):
    """`kan add 600519` 单只代码 · 添加成功"""
    result = cli_runner.invoke(app, ["add", "600519"])
    assert result.exit_code == 0
    assert "已添加" in result.output
    assert "贵州茅台" in result.output

    # verify watchlist 真的写了
    wl = watchlist.load_watchlist()
    assert len(wl.stocks) == 1
    assert wl.stocks[0].symbol == "600519"
    assert wl.stocks[0].name == "贵州茅台"


def test_add_command_by_name_single_match_succeeds(cli_runner):
    """`kan add 茅台` 单只名称 single match → 添加"""
    result = cli_runner.invoke(app, ["add", "茅台"])
    assert result.exit_code == 0
    assert "已添加" in result.output
    assert "600519" in result.output  # 反查代码

    wl = watchlist.load_watchlist()
    assert any(s.symbol == "600519" for s in wl.stocks)


def test_add_command_multi_match_lists_candidates(cli_runner):
    """LOCKED 真测 (v0.0.4.7): 多匹配应列出候选 · 不 dead-end.

    `kan add 平安` 匹配 平安银行(000001) + 中国平安(601318) + 平安股份(002007).
    旧行为: "匹配到 N 只 · 请用更精确名称或代码" → dead-end.
    新行为: 列出全部候选 (code + name) · 用户能 copy 代码精确 add.
    """
    result = cli_runner.invoke(app, ["add", "平安"])
    # exit_code=1 因为 add 失败 (没添加任何股票 · multi match 需用户精确化)
    assert result.exit_code != 0 or result.output != ""
    # 关键: 应列出全部 3 个候选 (LOCKED: 不 dead-end)
    assert "000001" in result.output
    assert "601318" in result.output
    assert "002007" in result.output
    assert "平安银行" in result.output


def test_add_command_invalid_code_reports_not_found(cli_runner):
    """`kan add 999999` 不存在代码 · 应给"未找到"提示 (exit_code 可能非 0)"""
    result = cli_runner.invoke(app, ["add", "999999"])
    # exit_code 可能 1 (add 失败) · 关键是 output 有 "未找到" / "不在" 提示
    assert "未找到" in result.output or "不在" in result.output, (
        f"应给未找到提示 · 实际 output: {result.output[:300]}"
    )


def test_add_command_duplicate_is_skipped(cli_runner):
    """`kan add 600519` 然后再 add 600519 · 第二次应 skip"""
    cli_runner.invoke(app, ["add", "600519"])
    result = cli_runner.invoke(app, ["add", "600519"])
    assert result.exit_code == 0
    assert "已在自选列表" in result.output


# ════════════════════════════════════════════════════════════════
# remove 命令 (cli_watchlist_cmds.py:186-215)
# ════════════════════════════════════════════════════════════════
def test_remove_command_existing_stock(cli_runner):
    """`kan remove 600519` 已存在股票 · 移除成功"""
    cli_runner.invoke(app, ["add", "600519"])
    result = cli_runner.invoke(app, ["remove", "600519"])
    assert result.exit_code == 0
    assert "已移除" in result.output or "已删除" in result.output or "移除" in result.output

    wl = watchlist.load_watchlist()
    assert not any(s.symbol == "600519" for s in wl.stocks)


def test_remove_command_nonexistent_stock(cli_runner):
    """`kan remove 600519` 自选列表为空 · 应给提示"""
    result = cli_runner.invoke(app, ["remove", "600519"])
    assert result.exit_code == 0
    # 应给"未找到 / 不在 / 没有"等用户友好提示
    output = result.output.lower()
    assert "未找到" in result.output or "不在" in result.output or "no" in output


# ════════════════════════════════════════════════════════════════
# list 命令 (cli_watchlist_cmds.py:217-239)
# ════════════════════════════════════════════════════════════════
def test_list_command_empty(cli_runner):
    """`kan list` 空自选 · 应跑通不 crash"""
    result = cli_runner.invoke(app, ["list"])
    assert result.exit_code == 0
    # 空 watchlist 不应 crash · 应给指示性提示 (e.g. "自选列表为空" / "未添加")
    assert "Traceback" not in result.output


def test_list_command_with_stocks(cli_runner):
    """`kan list` 有股票 · 应显示"""
    # 直接 manipulate watchlist json (避免依赖 add command)
    wl = watchlist.Watchlist(
        stocks=[
            Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 14)),
            Stock(symbol="000001", name="平安银行", added_at=date(2026, 5, 14)),
        ]
    )
    watchlist.save_watchlist(wl)

    result = cli_runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "600519" in result.output
    assert "000001" in result.output


# ════════════════════════════════════════════════════════════════
# clear 命令 (cli_watchlist_cmds.py:258-281)
# ════════════════════════════════════════════════════════════════
def test_clear_command_with_yes_confirms(cli_runner):
    """`kan clear` + 'y' 确认 · 应清空"""
    # setup: 添 2 只
    wl = watchlist.Watchlist(
        stocks=[
            Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 14)),
        ]
    )
    watchlist.save_watchlist(wl)

    # invoke with stdin='y'
    result = cli_runner.invoke(app, ["clear"], input="y\n")
    assert result.exit_code == 0

    # watchlist 应为空
    wl_after = watchlist.load_watchlist()
    assert len(wl_after.stocks) == 0


def test_clear_command_aborted_with_no(cli_runner):
    """`kan clear` + 'n' · 应保留"""
    wl = watchlist.Watchlist(
        stocks=[
            Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 14)),
        ]
    )
    watchlist.save_watchlist(wl)

    # exit_code 可能 0 或 1 (依赖 typer.confirm 的 abort 行为)
    # 关键: watchlist 应保留
    cli_runner.invoke(app, ["clear"], input="n\n")
    wl_after = watchlist.load_watchlist()
    assert len(wl_after.stocks) == 1


# ════════════════════════════════════════════════════════════════
# add / remove --industry · 按行业批量增删自选股 (F10 破坏性命令)
# ════════════════════════════════════════════════════════════════
@pytest.fixture
def fake_board(monkeypatch: pytest.MonkeyPatch):
    """mock boards 层 · 食品饮料行业 3 只成分股 · 不走真网络。"""
    board = Board(code="801016", name="食品饮料", level=2, size=3)
    cons = [("600519", "贵州茅台"), ("000858", "五粮液"), ("000998", "隆平高科")]
    monkeypatch.setattr(boards, "search_industry", lambda q: board)
    monkeypatch.setattr(
        boards, "get_industry_constituents", lambda b, force=False: cons
    )
    return board, cons


def _stock(symbol: str, name: str) -> Stock:
    return Stock(symbol=symbol, name=name, added_at=date(2026, 5, 1))


def test_add_industry_requires_confirm(cli_runner, fake_board):
    """add --industry 默认弹二次确认 · 输 n 自选股不变。"""
    result = cli_runner.invoke(app, ["add", "--industry=食品饮料"], input="n\n")
    assert result.exit_code == 0
    assert "将加 3 只食品饮料股" in result.output
    assert "继续?" in result.output
    assert "已取消" in result.output
    assert len(watchlist.load_watchlist().stocks) == 0


def test_add_industry_yes_skips_confirm(cli_runner, fake_board):
    """add --industry --yes 跳过确认 · 直接加入全部成分股。"""
    result = cli_runner.invoke(app, ["add", "--industry=食品饮料", "--yes"])
    assert result.exit_code == 0
    assert "继续?" not in result.output
    codes = {s.symbol for s in watchlist.load_watchlist().stocks}
    assert codes == {"600519", "000858", "000998"}


def test_add_industry_impact_summary_counts_dedup(cli_runner, fake_board):
    """影响摘要区分「已在自选」与「实际新增」· 已有的不重复加。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")]))
    result = cli_runner.invoke(app, ["add", "--industry=食品饮料"], input="y\n")
    assert result.exit_code == 0
    assert "其中 1 只已在自选 · 实际新增 2 只" in result.output
    assert "自选股 1 → 3 只" in result.output
    assert len(watchlist.load_watchlist().stocks) == 3


def test_add_industry_all_already_present(cli_runner, fake_board):
    """全部成分股已在自选 → 「无需添加」· 不弹确认。"""
    _board, cons = fake_board
    watchlist.save_watchlist(
        watchlist.Watchlist(stocks=[_stock(c, n) for c, n in cons])
    )
    result = cli_runner.invoke(app, ["add", "--industry=食品饮料"])
    assert result.exit_code == 0
    assert "无需添加" in result.output
    assert "继续?" not in result.output


def test_add_industry_conflicts_with_symbols(cli_runner, fake_board):
    """add 同时给股票代码和 --industry → Exit 2。"""
    result = cli_runner.invoke(app, ["add", "600519", "--industry=食品饮料"])
    assert result.exit_code == 2
    assert "二选一" in result.output


def test_add_industry_not_found(cli_runner, monkeypatch):
    """行业搜不到 → Exit 1。"""
    def _raise(q):
        raise boards.BoardNotFoundError(q)

    monkeypatch.setattr(boards, "search_industry", _raise)
    result = cli_runner.invoke(app, ["add", "--industry=不存在的行业"])
    assert result.exit_code == 1
    assert "未找到行业" in result.output


def test_remove_industry_requires_confirm(cli_runner, fake_board):
    """remove --industry 默认弹确认 · 输 n 不删。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("600519", "贵州茅台")]))
    result = cli_runner.invoke(app, ["remove", "--industry=食品饮料"], input="n\n")
    assert result.exit_code == 0
    assert "将从自选删除 1 只食品饮料股" in result.output
    assert "已取消" in result.output
    assert any(s.symbol == "600519" for s in watchlist.load_watchlist().stocks)


def test_remove_industry_yes_removes_intersection(cli_runner, fake_board):
    """remove --industry --yes 删掉自选 ∩ 行业 · 不属该行业的保留。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[
        _stock("600519", "贵州茅台"),
        _stock("000001", "平安银行"),
    ]))
    result = cli_runner.invoke(app, ["remove", "--industry=食品饮料", "--yes"])
    assert result.exit_code == 0
    codes = {s.symbol for s in watchlist.load_watchlist().stocks}
    assert codes == {"000001"}


def test_remove_industry_empty(cli_runner, fake_board):
    """自选里没有该行业的股票 → 友好提示 · 不弹确认。"""
    watchlist.save_watchlist(watchlist.Watchlist(stocks=[_stock("000001", "平安银行")]))
    result = cli_runner.invoke(app, ["remove", "--industry=食品饮料"])
    assert result.exit_code == 0
    assert "没有「食品饮料」行业的股票" in result.output
    assert "继续?" not in result.output


def test_remove_industry_conflicts_with_symbols(cli_runner, fake_board):
    """remove 同时给股票代码和 --industry → Exit 2。"""
    result = cli_runner.invoke(app, ["remove", "600519", "--industry=食品饮料"])
    assert result.exit_code == 2
    assert "二选一" in result.output

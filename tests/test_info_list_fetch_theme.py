"""kan info/list/fetch --theme CLI 真测。"""
import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan.data import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.storage.paths.WATCHLIST_PATH", tmp_path / "wl.json")
    monkeypatch.setattr("kan.storage.paths.DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


def _stub(monkeypatch):
    monkeypatch.setattr(
        "kan.data.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.data.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    monkeypatch.setattr(
        "kan.data.boards.fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame({
            "date": dates,
            "open": [100.0] * 100, "high": [105.0] * 100,
            "low": [95.0] * 100, "close": [102.0] * 100,
            "volume": [1e6] * 100, "amount": [1e8] * 100,
        }),
    )


def test_info_theme_shows_dossier(monkeypatch, _isolate_all):
    """`kan info --theme=AI应用` 输出题材档案 + 成分股数 + 4 行 disclaimer。"""
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output
    assert "成分股" in result.output
    assert "题材跟风风险高于行业" in result.output


def test_info_theme_industry_mutually_exclusive(_isolate_all):
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2


def test_list_theme_shows_intersection(monkeypatch, _isolate_all):
    """list --theme=AI应用 · 自选 [002230, 600000] · 题材 [002230, 300033] → 只 002230。"""
    from datetime import date

    from kan.core.models import Stock

    # mock list_all 返回固定股票 · 不依赖真 wl.json 文件格式
    monkeypatch.setattr(
        "kan.storage.watchlist.list_all",
        lambda group=None: [
            Stock(symbol="002230", name="科大讯飞", added_at=date(2026, 5, 1)),
            Stock(symbol="600000", name="浦发银行", added_at=date(2026, 5, 1)),
        ],
    )
    _stub(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "002230" in result.output
    assert "600000" not in result.output


def test_list_theme_industry_mutually_exclusive(_isolate_all):
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2


def test_fetch_theme_pulls_constituents(monkeypatch, _isolate_all):
    """fetch --theme=AI应用 把两个成分股一次性交给批量 fetcher。"""
    _stub(monkeypatch)
    calls: list[tuple[list[str], bool]] = []

    def fetch_batch(symbols, force=False, **kwargs):
        calls.append((list(symbols), force))
        return ({symbol: pd.DataFrame({"close": [1.0]}) for symbol in symbols}, {})

    monkeypatch.setattr("kan.data.fetcher.fetch_batch", fetch_batch)
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda symbol: False)
    runner = CliRunner()
    result = runner.invoke(app, ["fetch", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert calls == [(["002230", "300033"], False)]


def test_fetch_theme_empty_watchlist_intersection_does_not_fall_back(
    monkeypatch, _isolate_all
):
    """题材与自选无交集时保持空池，不误拉整份自选。"""
    from types import SimpleNamespace

    _stub(monkeypatch)
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist",
        lambda group=None: SimpleNamespace(
            stocks=[SimpleNamespace(symbol="600000", name="浦发银行")]
        ),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, force=False, **kw: (calls.append(list(symbols)) or {}, {}),
    )

    result = CliRunner().invoke(app, ["fetch", "--theme=AI应用", "--only-watchlist"])

    assert result.exit_code == 0, result.output
    assert calls == [[]]
    assert "0 只无需更新" in result.output


def test_fetch_returns_nonzero_when_any_symbol_fails(monkeypatch, _isolate_all):
    """fetch 任一股票拉取失败时必须 exit 非 0 · 防脚本误判成功。"""
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda symbol: False)
    monkeypatch.setattr(
        "kan.data.fetcher.fetch_batch",
        lambda symbols, force=False, **kw: (
            {},
            {symbol: f"无效股票代码或无数据: {symbol}" for symbol in symbols},
        ),
    )
    runner = CliRunner()
    result = runner.invoke(app, ["fetch", "999999"])
    assert result.exit_code == 1
    assert "拉取失败" in result.output

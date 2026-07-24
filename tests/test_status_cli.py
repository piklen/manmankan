"""kan status · 本地数据状态命令测试。

状态页自身必须 fail-open:任何单项读取失败都不能拖垮整页(本地优先 —
状态页绝不能成为新的故障点)。测试用 tmp_path 重定向 XDG_DATA_HOME 隔离。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture()
def status_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离的本地数据环境:2 只 K 线缓存 + 1 个非股票缓存文件。"""
    import pandas as pd

    data_home = tmp_path / "xdg"
    data_dir = data_home / "kan" / "data"
    data_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "date": [pd.Timestamp("2026-07-22"), pd.Timestamp("2026-07-23")],
        "open": [10.0, 10.5],
        "high": [10.8, 11.0],
        "low": [9.9, 10.4],
        "close": [10.5, 10.9],
        "volume": [1000, 1200],
    })
    df.to_parquet(data_dir / "600519.parquet")
    df.to_parquet(data_dir / "000858.parquet")
    # 非股票缓存文件(chip 筹码等)不得计入 K 线股票数
    df.to_parquet(data_dir / "chip_20260723.parquet")
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    # 各模块在 import 时按值拷贝路径常量 · 必须逐模块 patch 使用点
    import kan.storage.paths as paths

    monkeypatch.setattr(paths, "BASE_DIR", data_home / "kan")
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "STOCK_NAMES_CACHE", data_home / "kan" / "stock_names.json")
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", data_home / "kan" / "snapshots")
    monkeypatch.setattr(paths, "CIRCUIT_PATH", data_home / "kan" / "circuit.json")
    monkeypatch.setattr("kan.data.fetcher.DATA_DIR", data_dir)
    monkeypatch.setattr(
        "kan.storage.positions.POSITIONS_PATH", data_home / "kan" / "positions.json"
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.WATCHLIST_PATH", data_home / "kan" / "watchlist.json"
    )
    monkeypatch.setattr(
        "kan.storage.watchlist.STOCK_NAMES_CACHE",
        data_home / "kan" / "stock_names.json",
    )
    monkeypatch.setattr(
        "kan.storage.config.CONFIG_PATH", data_home / "kan" / "config.json"
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date",
        lambda: __import__("datetime").date(2026, 7, 23),
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.market_phase", lambda: "post"
    )
    monkeypatch.setattr(
        "kan.data.universe.fetch_all_stocks",
        lambda: [("600519", "贵州茅台"), ("000858", "五粮液"), ("300750", "宁德时代"), ("920799", "艾融软件")],
    )
    return data_home


def test_status_json_shape(status_env) -> None:
    from kan.cli import app

    result = CliRunner().invoke(app, ["status", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "status"
    assert payload["kline_cached_count"] == 2  # chip_* 不计入
    assert payload["kline_universe_count"] == 4
    assert payload["freshness"]["data_cutoff"] == "2026-07-23"
    assert payload["freshness"]["is_stale"] is False
    assert payload["tushare"]["token_configured"] is False
    assert payload["circuit_down_sources"] == []


def test_status_terminal_renders(status_env) -> None:
    from kan.cli import app

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "本地数据状态" in result.output
    assert "K线缓存 2/4 只（覆盖 50%）" in result.output
    assert "最新截止 07-23" in result.output
    assert "未配置" in result.output  # tushare 凭证未配置


def test_status_fail_open_on_broken_pieces(status_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """单项读取(如持仓文件损坏)失败时整页仍出,不 traceback。"""
    positions_path = status_env / "kan" / "positions.json"
    positions_path.write_text("{broken json", encoding="utf-8")

    from kan.cli import app

    result = CliRunner().invoke(app, ["status", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["kline_cached_count"] == 2

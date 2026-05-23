"""scanner 核心算法测试 · 构造已知 DataFrame 验证位置百分比"""

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from kan.core.models import PeriodResult, StockScanResult
from kan.core.scanner import save_snapshot, scan_stock
from kan.storage import paths


def _make_df(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> pd.DataFrame:
    """构造测试用 DataFrame。默认 OHLC 全等于 close（无价差），可单独指定 high/low。"""
    n = len(closes)
    base_date = date(2026, 5, 1) - timedelta(days=n)
    if highs is None:
        highs = closes
    if lows is None:
        lows = closes
    return pd.DataFrame({
        "date": [base_date + timedelta(days=i) for i in range(n)],
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [10000] * n,
    })


def test_position_at_midpoint():
    """当前价在区间正中间 → 50%"""
    closes = [10.0] * 5 + [20.0] * 5 + [15.0]
    df = _make_df(closes)
    result = scan_stock(df, "000001", "测试股")
    p10 = next(p for p in result.periods if p.period == 10)
    assert p10.position_pct == 50.0


def test_position_at_low():
    """当前价 = 区间最低 → 0%"""
    closes = [20.0] * 9 + [10.0]
    df = _make_df(closes)
    result = scan_stock(df, "000001", "测试股")
    p10 = next(p for p in result.periods if p.period == 10)
    assert p10.position_pct == 0.0
    assert p10.at_low is True


def test_position_at_high():
    """当前价 = 区间最高 → 100%"""
    closes = [10.0] * 9 + [20.0]
    df = _make_df(closes)
    result = scan_stock(df, "000001", "测试股")
    p10 = next(p for p in result.periods if p.period == 10)
    assert p10.position_pct == 100.0
    assert p10.at_high is True


def test_flat_price_returns_50():
    """完全横盘（high==low）→ 50%，不除零"""
    closes = [10.0] * 10
    df = _make_df(closes)
    result = scan_stock(df, "000001", "横盘股")
    p10 = next(p for p in result.periods if p.period == 10)
    assert p10.position_pct == 50.0
    assert p10.insufficient is False


def test_insufficient_data():
    """数据不足 N 日 → insufficient=True"""
    closes = [10.0] * 5
    df = _make_df(closes)
    result = scan_stock(df, "000001", "新股")
    p10 = next(p for p in result.periods if p.period == 10)
    assert p10.insufficient is True
    p3 = next(p for p in result.periods if p.period == 3)
    assert p3.insufficient is False


def test_resonance_count():
    """多周期同时触及低点 → low_resonance 正确计数"""
    closes = [20.0] * 50 + [10.0]
    df = _make_df(closes)
    result = scan_stock(df, "000001", "共振股")
    # 最后一天收盘价 = 区间最低 → 所有有效周期都 at_low
    assert result.low_resonance >= 5
    assert result.high_resonance == 0


def test_high_low_uses_correct_columns():
    """n_low 用 low 列、n_high 用 high 列（不是 close）"""
    closes = [15.0] * 10
    highs = [20.0] * 9 + [15.0]
    lows = [10.0] * 9 + [15.0]
    df = _make_df(closes, highs=highs, lows=lows)
    result = scan_stock(df, "000001", "测试股")
    p10 = next(p for p in result.periods if p.period == 10)
    assert p10.n_low == 10.0
    assert p10.n_high == 20.0
    assert p10.position_pct == 50.0


# --- save_snapshot 按日归档 ---


@pytest.fixture
def temp_snapshot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "SNAPSHOT_PATH", tmp_path / "last_scan.json")

    import kan.core.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "SNAPSHOT_PATH", tmp_path / "last_scan.json")
    return tmp_path


def _make_scan_result(symbol="600519", name="贵州茅台"):
    return StockScanResult(
        symbol=symbol, name=name, current_price=100.0,
        scan_date=date.today(), periods=[
            PeriodResult(period=5, n_low=95.0, n_high=105.0,
                         position_pct=50.0, at_low=False, at_high=False),
        ],
        low_resonance=0, high_resonance=0,
    )


class TestSaveSnapshot:
    def test_writes_last_scan_json(self, temp_snapshot_dir):
        save_snapshot([_make_scan_result()])
        assert (temp_snapshot_dir / "last_scan.json").exists()

    def test_writes_daily_archive(self, temp_snapshot_dir):
        save_snapshot([_make_scan_result()])
        daily = temp_snapshot_dir / "snapshots" / f"{date.today().isoformat()}.json"
        assert daily.exists()
        data = json.loads(daily.read_text())
        assert len(data) == 1
        assert data[0]["symbol"] == "600519"

    def test_daily_and_last_scan_have_same_content(self, temp_snapshot_dir):
        save_snapshot([_make_scan_result()])
        last = (temp_snapshot_dir / "last_scan.json").read_text()
        daily = (temp_snapshot_dir / "snapshots" / f"{date.today().isoformat()}.json").read_text()
        assert last == daily

    def test_cleanup_old_snapshots(self, temp_snapshot_dir):
        snapshots_dir = temp_snapshot_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        old_date = date.today() - timedelta(days=300)
        old_file = snapshots_dir / f"{old_date.isoformat()}.json"
        old_file.write_text("[]")

        recent_date = date.today() - timedelta(days=100)
        recent_file = snapshots_dir / f"{recent_date.isoformat()}.json"
        recent_file.write_text("[]")

        save_snapshot([_make_scan_result()])

        assert not old_file.exists()
        assert recent_file.exists()

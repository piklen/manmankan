"""排序逻辑回归测试

排序契约：
  1. scan 排序：共振优先 → 3日→5日→7日 字典序 tie-break
  2. trend 排序：天数 abs 降序 → 同天数按累计 abs 降序
  3. scan -p N 不提供（用户视角设计：默认全周期 + 自适应宽度更直观）

测试策略：直接构造 StockScanResult / TrendResult 列表，调用排序函数验证顺序。
不走 fetcher / scan_stock 完整管道，专注排序 contract。
"""

from __future__ import annotations

from datetime import date

import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import PeriodResult, StockScanResult
from kan.core.scanner import PERIODS, TrendResult, _period_pct_key

# --- _period_pct_key 纯函数测试 ---


def _make_result(
    name: str,
    period_pcts: dict[int, float],
    *,
    insufficient: set[int] | None = None,
    low_resonance: int = 0,
    high_resonance: int = 0,
) -> StockScanResult:
    insufficient = insufficient or set()
    periods = []
    for p in PERIODS:
        if p in insufficient:
            periods.append(PeriodResult(
                period=p, n_low=0.0, n_high=0.0, position_pct=0.0,
                at_low=False, at_high=False, insufficient=True,
            ))
        else:
            pct = period_pcts.get(p, 50.0)
            periods.append(PeriodResult(
                period=p, n_low=10.0, n_high=20.0, position_pct=pct,
                at_low=pct <= 5.0, at_high=pct >= 95.0,
            ))
    return StockScanResult(
        symbol="600519",
        name=name,
        current_price=100.0,
        scan_date=date(2026, 5, 8),
        periods=periods,
        low_resonance=low_resonance,
        high_resonance=high_resonance,
    )


def test_period_pct_key_returns_tuple_in_periods_order() -> None:
    """_period_pct_key 按 PERIODS 顺序生成 tuple"""
    r = _make_result("A", {3: 10.0, 5: 20.0, 7: 30.0})
    key = _period_pct_key(r, sentinel=100.0)
    assert key[0] == 10.0  # 3 日
    assert key[1] == 20.0  # 5 日
    assert key[2] == 30.0  # 7 日
    assert len(key) == len(PERIODS)


def test_period_pct_key_uses_sentinel_for_insufficient() -> None:
    """insufficient 周期用 sentinel 占位"""
    r = _make_result("A", {3: 10.0}, insufficient={5, 7, 10, 15, 30, 60, 90, 120, 180})
    key = _period_pct_key(r, sentinel=999.0)
    assert key[0] == 10.0
    assert all(k == 999.0 for k in key[1:])


# --- scan_batch 排序测试（共振优先 + PERIODS 字典序 tie-break）---


def test_scan_low_resonance_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """低点模式：共振多的在前 · 不管 pct"""
    from kan.core.scanner import scan_batch

    r_high_res = _make_result("HighRes", {3: 50.0, 5: 50.0, 7: 50.0}, low_resonance=5)
    r_low_pct = _make_result("LowPct", {3: 1.0, 5: 1.0, 7: 1.0}, low_resonance=2)

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _sym: object())
    monkeypatch.setattr(
        "kan.core.scanner.scan_stock",
        lambda _df, sym, name: r_high_res if name == "HighRes" else r_low_pct,
    )
    sorted_results = scan_batch([("HighRes", "HighRes"), ("LowPct", "LowPct")], mode="low")
    assert sorted_results[0].name == "HighRes"
    assert sorted_results[1].name == "LowPct"


def test_scan_low_periods_lex_tie_break(monkeypatch: pytest.MonkeyPatch) -> None:
    """同共振下，3日 pct 最低的在前 · 同 3日则比 5日"""
    from kan.core.scanner import scan_batch

    # 两只共振都为 1，A 的 3 日 10%，B 的 3 日 40% → A 在前
    a = _make_result("A", {3: 10.0, 5: 40.0, 7: 50.0}, low_resonance=1)
    b = _make_result("B", {3: 40.0, 5: 10.0, 7: 50.0}, low_resonance=1)

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _sym: object())
    monkeypatch.setattr(
        "kan.core.scanner.scan_stock",
        lambda _df, sym, name: a if name == "A" else b,
    )
    sorted_results = scan_batch([("A", "A"), ("B", "B")], mode="low")
    assert sorted_results[0].name == "A", "3日 10% 应在 3日 40% 之前"


def test_scan_low_secondary_break_by_5day(monkeypatch: pytest.MonkeyPatch) -> None:
    """3 日 pct 相同时按 5 日 pct 排"""
    from kan.core.scanner import scan_batch

    a = _make_result("A", {3: 30.0, 5: 10.0, 7: 50.0}, low_resonance=0)
    b = _make_result("B", {3: 30.0, 5: 40.0, 7: 50.0}, low_resonance=0)

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _sym: object())
    monkeypatch.setattr(
        "kan.core.scanner.scan_stock",
        lambda _df, sym, name: a if name == "A" else b,
    )
    sorted_results = scan_batch([("A", "A"), ("B", "B")], mode="low")
    assert sorted_results[0].name == "A", "3 日相同 5 日 10% < 5 日 40% → A 在前"


def test_scan_high_resonance_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """高点模式：共振多的在前"""
    from kan.core.scanner import scan_batch

    r1 = _make_result("HighRes", {3: 99.0, 5: 99.0, 7: 99.0}, high_resonance=10)
    r2 = _make_result("LowRes", {3: 99.5, 5: 99.5, 7: 99.5}, high_resonance=3)

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _sym: object())
    monkeypatch.setattr(
        "kan.core.scanner.scan_stock",
        lambda _df, sym, name: r1 if name == "HighRes" else r2,
    )
    sorted_results = scan_batch([("HighRes", "HighRes"), ("LowRes", "LowRes")], mode="high")
    assert sorted_results[0].name == "HighRes"


def test_scan_high_periods_lex_tie_break(monkeypatch: pytest.MonkeyPatch) -> None:
    """高点模式：同共振下 3 日 pct 高的在前"""
    from kan.core.scanner import scan_batch

    a = _make_result("A", {3: 100.0, 5: 60.0, 7: 50.0}, high_resonance=1)
    b = _make_result("B", {3: 60.0, 5: 100.0, 7: 50.0}, high_resonance=1)

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _sym: object())
    monkeypatch.setattr(
        "kan.core.scanner.scan_stock",
        lambda _df, sym, name: a if name == "A" else b,
    )
    sorted_results = scan_batch([("A", "A"), ("B", "B")], mode="high")
    assert sorted_results[0].name == "A", "3 日 100% 应在 3 日 60% 之前"


# --- trend_batch 排序测试（天数 abs 降序 + 累计 abs 降序 tie-break）---


def test_trend_streak_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """连跌天数多的在前（不论累计幅度）"""
    from kan.core.scanner import trend_batch

    r6 = TrendResult("000001", "6天小跌", 10.0, streak=-6, streak_pct=-2.0, daily_changes=[])
    r5 = TrendResult("000002", "5天大跌", 10.0, streak=-5, streak_pct=-15.0, daily_changes=[])

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _sym: object())
    monkeypatch.setattr(
        "kan.core.scanner.calc_trend",
        lambda _df, sym, name, candle: r6 if "6天" in name else r5,
    )
    sorted_results = trend_batch([("000001", "6天小跌"), ("000002", "5天大跌")])
    assert sorted_results[0].name == "6天小跌", "6 天连跌 > 5 天连跌"


def test_calc_trend_short_series_returns_flat_result() -> None:
    import pandas as pd

    from kan.core.scanner import calc_trend

    df = pd.DataFrame([{"date": "2026-05-01", "open": 10.0, "close": 10.0}])

    result = calc_trend(df, "000001", "短序列")

    assert result.streak == 0
    assert result.streak_pct == 0.0
    assert result.daily_changes == []


def test_calc_trend_flat_days_keep_current_direction() -> None:
    import pandas as pd

    from kan.core.scanner import calc_trend

    df = pd.DataFrame([
        {"date": "2026-05-01", "open": 10.0, "close": 10.0},
        {"date": "2026-05-02", "open": 10.0, "close": 11.0},
        {"date": "2026-05-03", "open": 11.0, "close": 11.0},
    ])

    result = calc_trend(df, "000001", "平盘穿透")

    assert result.streak == 2
    assert result.streak_pct == 10.0


def test_trend_pct_tie_break(monkeypatch: pytest.MonkeyPatch) -> None:
    """同天数下累计幅度大的在前"""
    from kan.core.scanner import trend_batch

    r_big = TrendResult("000001", "5天-15", 10.0, streak=-5, streak_pct=-15.0, daily_changes=[])
    r_small = TrendResult("000002", "5天-3", 10.0, streak=-5, streak_pct=-3.0, daily_changes=[])

    monkeypatch.setattr("kan.data.fetcher.get_cached", lambda _sym: object())
    monkeypatch.setattr(
        "kan.core.scanner.calc_trend",
        lambda _df, sym, name, candle: r_big if "-15" in name else r_small,
    )
    sorted_results = trend_batch([("000001", "5天-15"), ("000002", "5天-3")])
    assert sorted_results[0].name == "5天-15", "5 天 -15% 应在 5 天 -3% 之前"


# --- scan -p N 已移除回归测试 ---


def test_scan_period_option_removed() -> None:
    """kan scan -p 60 应当 typer 报错（选项不提供）"""
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "-p", "60"])
    assert result.exit_code != 0


def test_scan_period_long_option_removed() -> None:
    """kan scan --period 60 应当 typer 报错"""
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--period", "60"])
    assert result.exit_code != 0

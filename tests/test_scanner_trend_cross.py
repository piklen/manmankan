"""scanner_trend 截面路径 + 撞 cap 兜底测试。

覆盖 `trend_batch_cross_section`:
- 基础:panel groupby symbol 算 streak · 与逐股 trend_batch 等价输出
- 空 panel / 缺股票 / 目标池外 symbol → 跳过
- 30 天 cap 与逐股路径同契约,不触发逐股慢路径
- 排序:streak abs 降序 + streak_pct abs 降序 tie-break
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from kan.core.scanner_trend import trend_batch_cross_section


def _bar(symbol: str, d: date, open_: float, close: float) -> dict:
    return {"symbol": symbol, "date": d, "open": open_, "high": close, "low": open_, "close": close, "volume": 100.0, "amount": 1000.0}


def _panel(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_cross_section_empty_panel_returns_empty() -> None:
    """空 panel → 返空 list · 不抛。"""
    out = trend_batch_cross_section([("600519", "茅台")], panel=_panel([]))
    assert out == []


def test_cross_section_none_panel_returns_empty() -> None:
    """panel=None → 返空 list。"""
    out = trend_batch_cross_section([("600519", "茅台")], panel=None)
    assert out == []


def test_cross_section_short_series_returns_flat() -> None:
    """只有 1 行 → len(df) < 2 → streak=0 · 不抛。"""
    panel = _panel([_bar("600519", date(2026, 6, 30), 100.0, 101.0)])
    out = trend_batch_cross_section([("600519", "茅台")], panel=panel)
    assert len(out) == 1
    assert out[0].symbol == "600519"
    assert out[0].streak == 0


def test_cross_section_consecutive_up() -> None:
    """连涨 3 天(4 个收盘点 · 3 个日变化)· streak=3。"""
    panel = _panel([
        _bar("600519", date(2026, 6, 26), 100.0, 100.0),
        _bar("600519", date(2026, 6, 27), 100.0, 101.0),
        _bar("600519", date(2026, 6, 28), 101.0, 102.0),
        _bar("600519", date(2026, 6, 29), 102.0, 103.0),
    ])
    out = trend_batch_cross_section([("600519", "茅台")], panel=panel)
    assert out[0].streak == 3
    # (101-100)/100 + (102-101)/101 + (103-102)/102 ≈ 2.97
    assert out[0].streak_pct == pytest.approx(2.97, abs=0.01)


def test_cross_section_candle_mode() -> None:
    """candle=True · 阳线阴线口径 · close>open=▲。
    4 天 · 第一天无前日对比但 candle 口径只看当日 close vs open · 4 天都是阳线 → streak=4。
    """
    panel = _panel([
        _bar("600519", date(2026, 6, 26), 100.0, 101.0),
        _bar("600519", date(2026, 6, 27), 100.0, 102.0),
        _bar("600519", date(2026, 6, 28), 100.0, 103.0),
        _bar("600519", date(2026, 6, 29), 100.0, 104.0),
    ])
    out = trend_batch_cross_section([("600519", "茅台")], panel=panel, candle=True)
    # calc_trend: range(1, min(len,31)) → 索引 1..3 = 3 个变化 · streak=3
    assert out[0].streak == 3


def test_cross_section_sort_by_abs_streak_desc() -> None:
    """排序:|streak| 降序 · 同 |streak| 下 |streak_pct| 降序 tie-break。"""
    # 600519 连涨 3 天累计 +6% · 000001 连跌 5 天累计 -10%
    panel = _panel([
        _bar("600519", date(2026, 6, 27), 100.0, 102.0),
        _bar("600519", date(2026, 6, 28), 102.0, 104.0),
        _bar("600519", date(2026, 6, 29), 104.0, 106.0),
        _bar("000001", date(2026, 6, 25), 100.0, 98.0),
        _bar("000001", date(2026, 6, 26), 98.0, 96.0),
        _bar("000001", date(2026, 6, 27), 96.0, 94.0),
        _bar("000001", date(2026, 6, 28), 94.0, 92.0),
        _bar("000001", date(2026, 6, 29), 92.0, 90.0),
    ])
    out = trend_batch_cross_section([("600519", "茅台"), ("000001", "平安")], panel=panel)
    # |5| > |3| → 000001 排前
    assert out[0].symbol == "000001"
    assert out[1].symbol == "600519"


def test_cross_section_cap_triggers_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """撞 cap 不触发逐股 get_cached · 保持 --all 截面 fast-path。"""
    # 构造 panel 让某股连涨 30 天(撞 cap)
    rows = []
    for i in range(31):
        d = date(2026, 5, 1 + i)  # 简化 · 不走真实交易日历
        rows.append(_bar("600519", d, 100.0 + i, 101.0 + i))
    panel = _panel(rows)

    monkeypatch.setattr(
        "kan.data.fetcher.get_cached",
        lambda _sym: (_ for _ in ()).throw(AssertionError("不应触发逐股 K 线补查")),
    )

    out = trend_batch_cross_section([("600519", "茅台")], panel=panel)
    assert len(out) == 1
    assert out[0].symbol == "600519"


def test_cross_section_missing_symbol_in_panel_skipped() -> None:
    """watchlist 有股票但 panel 缺该 symbol → 跳过 · 不在结果里。"""
    panel = _panel([_bar("600519", date(2026, 6, 29), 100.0, 101.0)])
    out = trend_batch_cross_section(
        [("600519", "茅台"), ("000001", "平安")],
        panel=panel,
    )
    assert len(out) == 1
    assert out[0].symbol == "600519"


def test_cross_section_extra_symbol_in_panel_skipped() -> None:
    """panel 有目标池外 symbol → 跳过 · 不混入输出。"""
    panel = _panel([
        _bar("600519", date(2026, 6, 29), 100.0, 101.0),
        _bar("999999", date(2026, 6, 29), 1.0, 2.0),
    ])
    out = trend_batch_cross_section([("600519", "茅台")], panel=panel)
    assert [r.symbol for r in out] == ["600519"]

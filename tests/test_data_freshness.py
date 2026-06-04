"""数据时效性判定回归测试 (历史背景)

修复 bug：早期实现的 _is_cache_fresh 用 mtime 判"今日"，
凌晨 02:55 拉昨日数据后 mtime 日期 = 今天，scan 整天显示昨日涨停名单。

新判据基于 K 线 date 列 + 交易日历的 latest_trade_date()：
- 缓存是否新鲜 = K 线最后一行 date ≥ "应有最近交易日"
- "应有最近交易日" = 当日盘后 (≥ 15:30) 即今日 · 否则回退最近交易日
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from kan.core import trading_calendar
from kan.data import fetcher


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def fixed_trade_dates(monkeypatch):
    """注入固定交易日集合 · 避免 akshare 网络请求 + 系统时间解耦。

    覆盖：4 月底正常交易日、五一长假（5/1-5/5 非交易日）、5 月中工作周。
    """
    dates = {
        date(2026, 4, 28), date(2026, 4, 29), date(2026, 4, 30),
        # 五一假期：5/1 ~ 5/5 全部非交易日（4/30 = 节前最后交易日）
        date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8),
        date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 13),
        date(2026, 5, 14), date(2026, 5, 15),
    }
    monkeypatch.setattr(trading_calendar, "_trade_dates_memo", dates)
    yield dates
    trading_calendar.clear_memo()


@pytest.fixture
def parquet_with_date(temp_data_dir):
    """工厂：写一个 parquet 缓存 · K 线最后一行 date 可指定 · mtime 可指定。"""
    def _factory(symbol: str, last_date: date, mtime: datetime | None = None):
        cache = temp_data_dir / f"{symbol}.parquet"
        df = pd.DataFrame({
            "date": [
                last_date - timedelta(days=2),
                last_date - timedelta(days=1),
                last_date,
            ],
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10000.0, 11000.0, 12000.0],
            "amount": [1e6, 1.1e6, 1.2e6],
        })
        df.to_parquet(cache, index=False)
        if mtime is not None:
            ts = mtime.timestamp()
            os.utime(cache, (ts, ts))
        return cache
    return _factory


# ── 核心反模式回归（是这次 bug 的 smoking gun）───────────────────────


def test_stale_data_with_today_mtime_must_be_rejected(
    fixed_trade_dates, parquet_with_date, monkeypatch
):
    """凌晨 02:55 拉到昨日数据：mtime=今天 但 K 线最后一行=昨天 → 必须判 stale。

    这是 早期数据时效性 bug 的 smoking gun · 旧逻辑被 mtime 假象骗，
    新逻辑必须基于 K 线真实 date 判定。
    """
    parquet_with_date(
        "600519",
        last_date=date(2026, 5, 12),  # K 线截止昨日
        mtime=datetime(2026, 5, 13, 2, 55),  # 今天凌晨 02:55 写入
    )
    monkeypatch.setattr(
        trading_calendar, "latest_trade_date",
        lambda *a, **kw: date(2026, 5, 13),
    )
    assert not fetcher.is_fresh("600519"), (
        "K 线最后一行 5/12 < 应有最近交易日 5/13 · 必须 stale · "
        "不能被'今天的 mtime'假象骗"
    )


def test_fresh_data_is_accepted(
    fixed_trade_dates, parquet_with_date, monkeypatch
):
    """K 线最后一行 = 应有最近交易日 → fresh"""
    parquet_with_date("600519", last_date=date(2026, 5, 13))
    monkeypatch.setattr(
        trading_calendar, "latest_trade_date",
        lambda *a, **kw: date(2026, 5, 13),
    )
    assert fetcher.is_fresh("600519")


# ── data_cutoff_date 正确语义 ─────────────────────────────────────────


def test_data_cutoff_reads_kline_last_row_not_mtime(
    fixed_trade_dates, parquet_with_date
):
    """data_cutoff_date 必须读 K 线最后一行 date 而非文件 mtime"""
    parquet_with_date(
        "600519",
        last_date=date(2026, 5, 12),
        mtime=datetime(2026, 5, 13, 2, 55),
    )
    cutoff = fetcher.data_cutoff_date("600519")
    assert cutoff == date(2026, 5, 12), (
        f"应读 K 线 date(5/12) 而非 mtime 日期(5/13) · 实际 {cutoff}"
    )


def test_data_cutoff_returns_none_when_no_cache(temp_data_dir):
    assert fetcher.data_cutoff_date("600519") is None


# ── latest_trade_date 关键时段 ─────────────────────────────────────────


def test_latest_trade_date_post_market_today(fixed_trade_dates):
    """周二 16:00 (盘后阈值 15:30 之后) → 期望当日"""
    as_of = datetime(2026, 5, 13, 16, 0)
    assert trading_calendar.latest_trade_date(as_of) == date(2026, 5, 13)


def test_latest_trade_date_intraday_returns_previous(fixed_trade_dates):
    """周二 14:00 (盘中) → 今日数据未 final · 期望昨日"""
    as_of = datetime(2026, 5, 13, 14, 0)
    assert trading_calendar.latest_trade_date(as_of) == date(2026, 5, 12)


def test_latest_trade_date_premarket(fixed_trade_dates):
    """周二 09:00 (盘前) → 期望昨日"""
    as_of = datetime(2026, 5, 13, 9, 0)
    assert trading_calendar.latest_trade_date(as_of) == date(2026, 5, 12)


def test_latest_trade_date_weekend(fixed_trade_dates):
    """周六 12:00 → 期望周五"""
    as_of = datetime(2026, 5, 9, 12, 0)  # 周六
    assert trading_calendar.latest_trade_date(as_of) == date(2026, 5, 8)


def test_latest_trade_date_after_long_holiday(fixed_trade_dates):
    """五一长假后 5/6 早上 09:00 → 期望节前最后交易日 4/30"""
    as_of = datetime(2026, 5, 6, 9, 0)
    assert trading_calendar.latest_trade_date(as_of) == date(2026, 4, 30)


def test_latest_trade_date_threshold_just_after(fixed_trade_dates):
    """15:30 整 · 已到阈值 → 当日已 final"""
    as_of = datetime(2026, 5, 13, 15, 30)
    assert trading_calendar.latest_trade_date(as_of) == date(2026, 5, 13)


def test_latest_trade_date_threshold_just_before(fixed_trade_dates):
    """15:29 · 差 1 分钟到阈值 → 仍判'今日未 final' → 期望昨日"""
    as_of = datetime(2026, 5, 13, 15, 29)
    assert trading_calendar.latest_trade_date(as_of) == date(2026, 5, 12)


# ── market_phase 各相位 ────────────────────────────────────────────────


def test_market_phase_pre(fixed_trade_dates):
    assert trading_calendar.market_phase(
        datetime(2026, 5, 13, 9, 0),
    ) == trading_calendar.PHASE_PRE


def test_market_phase_intraday(fixed_trade_dates):
    assert trading_calendar.market_phase(
        datetime(2026, 5, 13, 11, 30),
    ) == trading_calendar.PHASE_INTRADAY


def test_market_phase_post(fixed_trade_dates):
    assert trading_calendar.market_phase(
        datetime(2026, 5, 13, 16, 0),
    ) == trading_calendar.PHASE_POST


def test_market_phase_closed_weekend(fixed_trade_dates):
    """周六 → CLOSED_DAY"""
    assert trading_calendar.market_phase(
        datetime(2026, 5, 9, 12, 0),
    ) == trading_calendar.PHASE_CLOSED_DAY


def test_market_phase_closed_holiday(fixed_trade_dates):
    """五一节中 5/3 → CLOSED_DAY"""
    assert trading_calendar.market_phase(
        datetime(2026, 5, 3, 12, 0),
    ) == trading_calendar.PHASE_CLOSED_DAY


# ── 边界 / 健壮性 ──────────────────────────────────────────────────────


def test_is_fresh_on_corrupted_parquet(temp_data_dir, fixed_trade_dates):
    """无 date 列的 parquet → 不应崩 · 返回 False（隐含触发刷新）"""
    cache = temp_data_dir / "600519.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(cache, index=False)
    assert not fetcher.is_fresh("600519")


def test_is_fresh_on_missing_cache(temp_data_dir, fixed_trade_dates):
    """无缓存 → 必返回 False · 不抛"""
    assert not fetcher.is_fresh("600519")


def test_is_trading_day(fixed_trade_dates):
    assert trading_calendar.is_trading_day(date(2026, 5, 13))  # 周三
    assert not trading_calendar.is_trading_day(date(2026, 5, 9))  # 周六
    assert not trading_calendar.is_trading_day(date(2026, 5, 3))  # 五一假

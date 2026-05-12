"""fetcher 测试 · 缓存逻辑 + AKShare mock + 多源 fallback"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from kan import fetcher, trading_calendar


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def force_eastmoney_path(monkeypatch):
    """绕过新的 baostock/sina 主路径 · 让 fetch_kline 走到东财 mock。

    fallback 顺序 2026-05-10 改为 baostock → 新浪 → 东财 → 腾讯。
    旧测试 mock 的是 akshare.stock_zh_a_hist (东财)，需要先把前两个源 mock None
    才能让流程走到东财。新测试应该直接 mock 主路径。
    """
    monkeypatch.setattr(fetcher, "_fetch_baostock", lambda *a, **kw: None)
    monkeypatch.setattr(fetcher, "_fetch_sina", lambda *a, **kw: None)


@pytest.fixture
def fake_akshare_df():
    """模拟 AKShare 返回的 DataFrame"""
    return pd.DataFrame({
        "日期": ["2026-04-28", "2026-04-29", "2026-04-30"],
        "开盘": [100.0, 101.0, 102.0],
        "收盘": [101.0, 102.0, 103.0],
        "最高": [101.5, 102.5, 103.5],
        "最低": [99.5, 100.5, 101.5],
        "成交量": [10000, 11000, 12000],
        "成交额": [1e6, 1.1e6, 1.2e6],
        "其他列": ["x", "y", "z"],
    })


def test_fetch_kline_normalizes_columns(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        df = fetcher.fetch_kline("600519", days=180, force=True)

    assert set(df.columns) == {"date", "open", "high", "low", "close", "volume", "amount"}
    assert len(df) == 3


def test_fetch_kline_writes_cache(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", force=True)
    assert (temp_data_dir / "600519.parquet").exists()


def test_fetch_kline_invalid_symbol_raises(temp_data_dir, force_eastmoney_path):
    empty_df = pd.DataFrame()
    with (
        patch("akshare.stock_zh_a_hist", return_value=empty_df),
        pytest.raises(ValueError, match="无效股票代码或无数据"),
    ):
        fetcher.fetch_kline("999999", force=True)


def test_is_fresh_no_cache(temp_data_dir):
    assert not fetcher.is_fresh("600519")


def test_is_fresh_today_cache(temp_data_dir, force_eastmoney_path, fake_akshare_df, monkeypatch):
    """v0.0.4.5: is_fresh 改为对比 K 线 date ≥ latest_trade_date()。

    fake_akshare_df 最后一行 = 2026-04-30 · mock latest_trade_date 同日返回，
    避免触发 akshare 网络请求 + 让测试与系统时间解耦。
    """
    monkeypatch.setattr(
        trading_calendar, "latest_trade_date",
        lambda *a, **kw: date(2026, 4, 30),
    )
    trading_calendar.clear_memo()

    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", force=True)
    assert fetcher.is_fresh("600519")


def test_is_fresh_yesterday_cache(temp_data_dir):
    cache = temp_data_dir / "600519.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(cache)
    yesterday = (datetime.now() - timedelta(days=1)).timestamp()
    import os
    os.utime(cache, (yesterday, yesterday))
    assert not fetcher.is_fresh("600519")


def test_get_cached_returns_none_when_missing(temp_data_dir):
    assert fetcher.get_cached("600519") is None


def test_get_cached_returns_dataframe(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", force=True)
    df = fetcher.get_cached("600519")
    assert df is not None
    assert len(df) == 3


def test_has_cache(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    assert not fetcher.has_cache("600519")
    with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
        fetcher.fetch_kline("600519", force=True)
    assert fetcher.has_cache("600519")


def test_fetch_batch_continues_on_error(temp_data_dir, force_eastmoney_path, fake_akshare_df):
    """批量拉取中某只失败不应中断其他股票"""
    def side_effect(symbol, **kwargs):
        if symbol == "FAIL":
            return pd.DataFrame()
        return fake_akshare_df

    with patch("akshare.stock_zh_a_hist", side_effect=side_effect), \
         patch("time.sleep"):
        results, errors = fetcher.fetch_batch(["600519", "FAIL", "000858"], force=True)

    assert "600519" in results
    assert "000858" in results
    assert "FAIL" in errors


# --- get_cached 补缺失列 ---


def test_get_cached_fills_missing_optional_columns(temp_data_dir):
    """旧 parquet 缺少 KLINE_OPTIONAL 列时 get_cached 应自动补 NaN"""
    cache = temp_data_dir / "600519.parquet"
    old_df = pd.DataFrame({
        "date": [datetime(2026, 5, 8).date()],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
    })
    old_df.to_parquet(cache, index=False)

    df = fetcher.get_cached("600519")
    assert df is not None
    assert "volume" in df.columns
    assert "amount" in df.columns
    assert pd.isna(df["volume"].iloc[0])
    assert pd.isna(df["amount"].iloc[0])


# --- _normalize_kline ---


class TestNormalizeKline:
    def test_reorders_and_converts_types(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["100.5"], "volume": ["10000"], "amount": ["1e6"],
        })
        df = fetcher._normalize_kline(raw)
        assert list(df.columns) == fetcher.KLINE_COLUMNS
        assert df["close"].dtype == "float64"
        assert df["date"].iloc[0].__class__.__name__ == "date"

    def test_fills_missing_optional_columns(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": [100], "high": [101],
            "low": [99], "close": [100.5],
        })
        df = fetcher._normalize_kline(raw)
        assert "volume" in df.columns
        assert pd.isna(df["volume"].iloc[0])

    def test_raises_on_missing_required_column(self):
        raw = pd.DataFrame({"date": ["2026-05-08"], "open": [100]})
        with pytest.raises(ValueError, match="必需列"):
            fetcher._normalize_kline(raw)

    def test_drops_rows_with_nan_close(self):
        raw = pd.DataFrame({
            "date": ["2026-05-07", "2026-05-08"],
            "open": [100, 101], "high": [101, 102], "low": [99, 100],
            "close": [100.5, None],
        })
        df = fetcher._normalize_kline(raw)
        assert len(df) == 1

    def test_sorts_by_date(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08", "2026-05-06", "2026-05-07"],
            "open": [100, 98, 99], "high": [101, 99, 100], "low": [99, 97, 98],
            "close": [100.5, 98.5, 99.5],
        })
        df = fetcher._normalize_kline(raw)
        dates = list(df["date"])
        assert dates == sorted(dates)


# --- _fetch_baostock mock ---


def test_fetch_baostock_returns_dataframe(temp_data_dir):
    mock_rs = MagicMock()
    mock_rs.error_code = "0"
    mock_rs.next = MagicMock(side_effect=[True, True, False])
    mock_rs.get_row_data = MagicMock(side_effect=[
        ["2026-05-07", "100", "101", "99", "100.5", "10000", "1000000"],
        ["2026-05-08", "101", "102", "100", "101.5", "11000", "1100000"],
    ])

    with patch("baostock.login"), \
         patch("baostock.query_history_k_data_plus", return_value=mock_rs):
        fetcher._bs_logged_in = False
        df = fetcher._fetch_baostock("600519", "20260501")

    assert df is not None
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]


def test_fetch_baostock_returns_none_on_error(temp_data_dir):
    mock_rs = MagicMock()
    mock_rs.error_code = "1"
    mock_rs.error_msg = "error"

    with patch("baostock.login"), \
         patch("baostock.query_history_k_data_plus", return_value=mock_rs):
        fetcher._bs_logged_in = False
        df = fetcher._fetch_baostock("999999", "20260501")

    assert df is None


# --- 熔断器 ---


class TestCircuitBreaker:
    def test_eastmoney_circuit_breaker_trips_on_failure(self, temp_data_dir, monkeypatch):
        monkeypatch.setattr(fetcher, "_eastmoney_ok", None)
        with patch("akshare.stock_zh_a_hist", side_effect=Exception("timeout")):
            result = fetcher._fetch_eastmoney("600519", "20260501")
        assert result is None
        assert fetcher._eastmoney_ok is False

    def test_eastmoney_circuit_breaker_skips_after_trip(self, temp_data_dir, monkeypatch):
        monkeypatch.setattr(fetcher, "_eastmoney_ok", False)
        with patch("akshare.stock_zh_a_hist") as mock:
            result = fetcher._fetch_eastmoney("600519", "20260501")
        assert result is None
        mock.assert_not_called()

    def test_eastmoney_circuit_breaker_resets_on_success(self, temp_data_dir, fake_akshare_df, monkeypatch):
        monkeypatch.setattr(fetcher, "_eastmoney_ok", None)
        with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
            result = fetcher._fetch_eastmoney("600519", "20260501")
        assert result is not None
        assert fetcher._eastmoney_ok is True

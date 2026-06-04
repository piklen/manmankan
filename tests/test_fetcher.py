"""fetcher 测试 · 缓存逻辑 + AKShare mock + 多源 fallback (chain 架构)。

历史背景 fallback 走 KlineSourceChain · `_fetch_<source>` SOT 在各 source module:
- `_fetch_tushare`  在 `kan.data.tushare`
- `_fetch_<其余 4>` 在 `kan.data.sources`

测试 monkeypatch 路径同步迁移 · fetcher namespace 不再持有 `_fetch_*` 别名。
"""

import logging
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from kan.core import trading_calendar
from kan.data import fetcher, sources, tushare
from kan.storage import paths


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def force_eastmoney_path(monkeypatch):
    """绕过 tushare / baostock / 新浪 · 让 chain 落到东财 (priority 30 race · sina None 后只剩 eastmoney)。

    chain 架构 monkeypatch 路径:
    - `_fetch_tushare` SOT 在 `kan.data.tushare` (TushareKlineSource.fetch 调它)
    - `_fetch_baostock/_sina/_tencent` SOT 在 `kan.data.sources` (对应 class 调它)

    sina + eastmoney 同 priority 30 自动并发 race · 把 sina mock 成 None ·
    eastmoney 凭 patched akshare.stock_zh_a_hist 返 fake_akshare_df 中标。
    tushare/baostock 都 mock None 防止用户本地 token / baostock 装好时短路。
    """
    monkeypatch.setattr(tushare, "_fetch_tushare", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_baostock", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: None)


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

    assert set(df.columns) == {
        "date", "open", "high", "low", "close",
        "volume", "amount", "_source", "_adjust",
    }
    assert len(df) == 3
    assert (df["_source"] == "eastmoney").all()  # force_eastmoney_path fixture 走东财路径
    assert (df["_adjust"] == "qfq").all()


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
    """背景: is_fresh 改为对比 K 线 date ≥ latest_trade_date()。

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
    assert not fetcher.is_fresh("600519", min_rows=360)


def test_is_fresh_yesterday_cache(temp_data_dir):
    cache = temp_data_dir / "600519.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(cache)
    yesterday = (datetime.now() - timedelta(days=1)).timestamp()
    import os
    os.utime(cache, (yesterday, yesterday))
    assert not fetcher.is_fresh("600519")


def test_is_fresh_legacy_tushare_raw_cache_is_stale(temp_data_dir):
    """旧版 TuShare daily 缓存没有 _adjust=qfq 标记 · 即使日期新也要重拉。"""
    cache = temp_data_dir / "600519.parquet"
    pd.DataFrame({
        "date": [datetime(2026, 5, 8).date()],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "_source": ["tushare"],
    }).to_parquet(cache, index=False)

    assert not fetcher.is_fresh("600519")


def test_is_fresh_tushare_qfq_cache_can_be_fresh(temp_data_dir, monkeypatch):
    cache = temp_data_dir / "600519.parquet"
    pd.DataFrame({
        "date": [datetime(2026, 5, 8).date()],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "_source": ["tushare"], "_adjust": ["qfq"],
    }).to_parquet(cache, index=False)
    monkeypatch.setattr(
        trading_calendar, "latest_trade_date",
        lambda *a, **kw: date(2026, 5, 8),
    )
    trading_calendar.clear_memo()

    assert fetcher.is_fresh("600519")


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
    """旧 parquet 缺 volume/amount 仍补 NaN · 缺 _source 经 migration 补 unknown."""
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
    assert df["_source"].iloc[0] == "unknown"  # migration 行为
    assert df["_adjust"].iloc[0] == "unknown"


# --- _normalize_kline ---


class TestNormalizeKline:
    def test_reorders_and_converts_types(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["100.5"], "volume": ["10000"], "amount": ["1e6"],
        })
        df = fetcher._normalize_kline(raw, source="test")
        assert list(df.columns) == fetcher.KLINE_COLUMNS
        assert df["close"].dtype == "float64"
        assert df["date"].iloc[0].__class__.__name__ == "date"
        assert df["_source"].iloc[0] == "test"
        assert df["_adjust"].iloc[0] == "unknown"

    def test_fills_missing_optional_columns(self):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": [100], "high": [101],
            "low": [99], "close": [100.5],
        })
        df = fetcher._normalize_kline(raw)
        assert "volume" in df.columns
        assert pd.isna(df["volume"].iloc[0])
        assert df["_adjust"].iloc[0] == "unknown"

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

    def test_clean_data_emits_no_warning(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["100.5"], "volume": ["10000"], "amount": ["1e6"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="baostock")
        assert caplog.records == []

    def test_unparseable_value_warns_with_source_and_column(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-07", "2026-05-08"],
            "open": ["100", "101"], "high": ["101", "102"], "low": ["99", "100"],
            "close": ["100.5", "N/A"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            df = fetcher._normalize_kline(raw, source="baostock")
        assert len(caplog.records) == 1
        msg = caplog.records[0].getMessage()
        assert "baostock" in msg
        assert "close" in msg
        assert len(df) == 1  # 垃圾 close 行被 dropna 丢掉

    def test_unparseable_warning_includes_symbol_when_provided(self, caplog):
        """历史背景 warning 末尾带 `[symbol]` · 调试时定位脏数据源头(批量 fetch 时一连串
        warning 没标 symbol → 用户实测无法判断是哪只股票的脏数据)。
        """
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["100.5"], "volume": ["bad"], "amount": ["1e6"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="baostock", symbol="600519")
        assert any("[600519]" in r.getMessage() for r in caplog.records)

    def test_preexisting_nan_does_not_warn(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-07", "2026-05-08"],
            "open": ["100", "101"], "high": ["101", "102"], "low": ["99", "100"],
            "close": ["100.5", "101.5"], "volume": ["10000", None],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="sina")
        assert caplog.records == []

    def test_multiple_bad_columns_single_warning(self, caplog):
        raw = pd.DataFrame({
            "date": ["2026-05-08"],
            "open": ["bad"], "high": ["101"], "low": ["99"],
            "close": ["100.5"], "volume": ["oops"], "amount": ["1e6"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source="baostock")
        assert len(caplog.records) == 1
        msg = caplog.records[0].getMessage()
        assert "open×1" in msg
        assert "volume×1" in msg

    @pytest.mark.parametrize("source", ["sina", "eastmoney", "tencent"])
    def test_warning_carries_source_name(self, caplog, source):
        raw = pd.DataFrame({
            "date": ["2026-05-08"], "open": ["100"], "high": ["101"],
            "low": ["99"], "close": ["junk"],
        })
        with caplog.at_level(logging.WARNING, logger="kan.data.fetcher"):
            fetcher._normalize_kline(raw, source=source)
        assert len(caplog.records) == 1
        assert source in caplog.records[0].getMessage()


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
        sources._bs_logged_in = False
        df = sources._fetch_baostock("600519", "20260501")

    assert df is not None
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]


def test_fetch_baostock_returns_none_on_error(temp_data_dir):
    mock_rs = MagicMock()
    mock_rs.error_code = "1"
    mock_rs.error_msg = "error"

    with patch("baostock.login"), \
         patch("baostock.query_history_k_data_plus", return_value=mock_rs):
        sources._bs_logged_in = False
        df = sources._fetch_baostock("999999", "20260501")

    assert df is None


# --- 熔断器集成 ---


def test_circuit_skips_breaker_down_source(temp_data_dir, raw_kline_df, isolated_breaker, monkeypatch):
    """breaker 标记 baostock down → chain 跳过 BaostockKlineSource → 走 akshare race 档.

    背景: BaostockKlineSource.is_available() 看熔断器 · down 时返 False · chain skip。
    """
    monkeypatch.setattr(tushare, "_fetch_tushare", lambda *a, **kw: None)
    isolated_breaker.record("baostock", ok=False)
    monkeypatch.setattr(sources, "_fetch_eastmoney", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: raw_kline_df)

    df = fetcher.fetch_kline("600519", force=True)
    assert (df["_source"] == "sina").all()


def test_circuit_records_down_on_source_exception(isolated_breaker):
    """源抛异常 → 被记 down."""
    with patch("akshare.stock_zh_a_hist", side_effect=Exception("timeout")):
        result = sources._fetch_eastmoney("600519", "20260501")
    assert result is None
    assert isolated_breaker.is_down("eastmoney")


def test_circuit_empty_result_not_recorded_down(isolated_breaker):
    """源返回空数据（无效代码/无数据）≠ 源挂 · 不记 down."""
    with patch("akshare.stock_zh_a_hist", return_value=pd.DataFrame()):
        result = sources._fetch_eastmoney("999999", "20260501")
    assert result is None
    assert not isolated_breaker.is_down("eastmoney")


# ── source stamping + migration · _source column ───────────────────────


@pytest.fixture
def raw_kline_df():
    """fetch_xxx 返回的 raw DataFrame (英文列 · normalize 前形态)."""
    return pd.DataFrame({
        "date": ["2026-04-28", "2026-04-29", "2026-04-30"],
        "open": [100.0, 101.0, 102.0],
        "high": [101.5, 102.5, 103.5],
        "low": [99.5, 100.5, 101.5],
        "close": [101.0, 102.0, 103.0],
        "volume": [10000, 11000, 12000],
        "amount": [1e6, 1.1e6, 1.2e6],
    })


@pytest.mark.parametrize("source,mock_target", [
    ("baostock", "_fetch_baostock"),
    ("sina", "_fetch_sina"),
    ("eastmoney", "_fetch_eastmoney"),
    ("tencent", "_fetch_tencent"),
])
def test_fetch_kline_stamps_source(temp_data_dir, raw_kline_df, source, mock_target, monkeypatch):
    """各源 fallback 标记正确 source · 其它源全 mock None 让目标源生效.

    chain monkeypatch 路径:
    - `_fetch_tushare` 在 `kan.data.tushare` namespace
    - `_fetch_baostock / _sina / _eastmoney / _tencent` 在 `kan.data.sources` namespace

    sina + eastmoney 同 priority 30 并发 race · 测试时其中之一 mock None ·
    另一个 mock raw_df 让结果确定 (不受 race 顺序影响)。
    """
    # 全 mock None · 再单独 mock 目标源为 raw_df (顺序覆盖)
    monkeypatch.setattr(tushare, "_fetch_tushare", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_baostock", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_eastmoney", lambda *a, **kw: None)
    monkeypatch.setattr(sources, "_fetch_tencent", lambda *a, **kw: None)

    monkeypatch.setattr(sources, mock_target, lambda *a, **kw: raw_kline_df)

    df = fetcher.fetch_kline("600519", force=True)
    assert (df["_source"] == source).all()


def test_load_with_migration_legacy_adds_unknown(temp_data_dir):
    """旧 parquet 缺 _source 列 · _load_with_migration 自动补 unknown · 行数 zero-loss."""
    cache = temp_data_dir / "600519.parquet"
    old_df = pd.DataFrame({
        "date": [datetime(2026, 5, 7).date(), datetime(2026, 5, 8).date()],
        "open": [100.0, 101.0], "high": [101.0, 102.0],
        "low": [99.0, 100.0], "close": [100.5, 101.5],
        "volume": [10000, 11000], "amount": [1e6, 1.1e6],
    })
    old_df.to_parquet(cache, index=False)

    df = fetcher._load_with_migration(cache)
    assert "_source" in df.columns
    assert "_adjust" in df.columns
    assert (df["_source"] == "unknown").all()
    assert (df["_adjust"] == "unknown").all()
    assert len(df) == len(old_df)  # zero-loss


def test_load_with_migration_writes_back_atomic(temp_data_dir, monkeypatch):
    """migration 触发 atomic write back · 持久化 _source 列到磁盘."""
    cache = temp_data_dir / "600519.parquet"
    old_df = pd.DataFrame({
        "date": [datetime(2026, 5, 8).date()],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
    })
    old_df.to_parquet(cache, index=False)

    calls = []
    original = paths.atomic_write_parquet

    def spy(df, path):
        calls.append(path)
        return original(df, path)

    monkeypatch.setattr("kan.storage.paths.atomic_write_parquet", spy)

    fetcher._load_with_migration(cache)
    assert len(calls) == 1
    reloaded = pd.read_parquet(cache)
    assert "_source" in reloaded.columns
    assert "_adjust" in reloaded.columns


def test_load_with_migration_idempotent(temp_data_dir, monkeypatch):
    """已含 _source 列的 parquet 不重复 migrate · 不触发 atomic write back."""
    cache = temp_data_dir / "600519.parquet"
    df_with_source = pd.DataFrame({
        "date": [datetime(2026, 5, 8).date()],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "volume": [10000.0], "amount": [1e6],
        "_source": ["baostock"], "_adjust": ["qfq"],
    })
    df_with_source.to_parquet(cache, index=False)

    calls = []
    monkeypatch.setattr(
        "kan.storage.paths.atomic_write_parquet", lambda *a, **kw: calls.append(1)
    )
    df = fetcher._load_with_migration(cache)
    assert len(calls) == 0
    assert (df["_source"] == "baostock").all()


def test_get_cached_triggers_migration(temp_data_dir):
    """get_cached 路径走 migration helper · 旧 parquet 自动补 _source = unknown."""
    cache = temp_data_dir / "600519.parquet"
    old_df = pd.DataFrame({
        "date": [datetime(2026, 5, 8).date()],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "volume": [10000.0], "amount": [1e6],
    })
    old_df.to_parquet(cache, index=False)

    df = fetcher.get_cached("600519")
    assert df is not None
    assert df["_source"].iloc[0] == "unknown"
    assert df["_adjust"].iloc[0] == "unknown"


def test_read_cutoff_unaffected_by_migration(temp_data_dir):
    """_read_cutoff_from_parquet 只读 date 列 · 不触发 migration · 文件未改写."""
    cache = temp_data_dir / "600519.parquet"
    old_df = pd.DataFrame({
        "date": [datetime(2026, 5, 7).date(), datetime(2026, 5, 8).date()],
        "open": [100.0, 101.0], "high": [101.0, 102.0],
        "low": [99.0, 100.0], "close": [100.5, 101.5],
    })
    old_df.to_parquet(cache, index=False)

    mtime_before = cache.stat().st_mtime
    last_date = fetcher._read_cutoff_from_parquet(cache)
    mtime_after = cache.stat().st_mtime

    assert last_date == datetime(2026, 5, 8).date()
    assert mtime_before == mtime_after
    reloaded = pd.read_parquet(cache)
    assert "_source" not in reloaded.columns


class TestTushareProDispatch:
    """背景: 配 token 时 tushare 顶替 baostock 作主路径；未配 token 行为不变"""

    @pytest.fixture
    def isolated_env(self, tmp_path, monkeypatch):
        from kan.infra import circuit_breaker
        from kan.storage import config
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(paths, "CIRCUIT_PATH", tmp_path / "circuit.json")
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
        monkeypatch.setattr(circuit_breaker, "_default", None)
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def test_no_token_path_unchanged(self, isolated_env, monkeypatch, fake_akshare_df):
        """未配 token → TushareKlineSource.is_available()=False → chain 跳过 · 走 akshare 档.

        背景: 未配 token 时 chain 直接 skip TushareKlineSource (不调 fetch) ·
        与 历史背景不同 (旧版本 fetch 内部检查 token · 调用一次返 None)。
        新行为更高效 · 不浪费一次 fetch 调用。
        """
        # 把 _fetch_tushare 设 spy 没必要 (chain 不会调它 · is_available 已 False)
        # 仅保留作为 safeguard · 确认 chain 真的没调用
        called = {"tushare": False}
        def spy_tushare(*a, **kw):
            called["tushare"] = True
            return None
        monkeypatch.setattr(tushare, "_fetch_tushare", spy_tushare)
        monkeypatch.setattr(sources, "_fetch_baostock", lambda *a, **kw: None)
        monkeypatch.setattr(sources, "_fetch_sina", lambda *a, **kw: None)
        with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
            df = fetcher.fetch_kline("600519", force=True)
        # 背景: 未配 token 时 chain skip TushareKlineSource · _fetch_tushare 不被调
        assert not called["tushare"]
        assert not df.empty

    def test_with_token_uses_tushare_first(self, isolated_env, monkeypatch):
        """配 token → TushareKlineSource priority=10 顶档命中 → chain 不再走 baostock"""
        from kan.storage import config
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        sample = pd.DataFrame({
            "date": [date(2026, 4, 28), date(2026, 4, 29)],
            "open": [100.0, 101.0],
            "high": [101.5, 102.5],
            "low": [99.5, 100.5],
            "close": [101.0, 102.0],
            "volume": [10000, 11000],
            "amount": [1010000.0, 1122000.0],
        })

        baostock_called = {"hit": False}
        def fake_baostock(*a, **kw):
            baostock_called["hit"] = True
            return None

        monkeypatch.setattr(tushare, "_fetch_tushare", lambda *a, **kw: sample.copy())
        monkeypatch.setattr(sources, "_fetch_baostock", fake_baostock)

        df = fetcher.fetch_kline("600519", force=True)
        assert not baostock_called["hit"]
        assert (df["_source"] == "tushare").all()
        assert (df["_adjust"] == "qfq").all()

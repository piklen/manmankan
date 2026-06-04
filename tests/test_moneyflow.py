"""kan/data/moneyflow.py · 主力资金截面拉取 + 缓存 + 降级 (整合-1)。

隔离 DATA_DIR + 固定 latest_trade_date (历史日永鲜判定确定性 · 仿 test_metrics)。
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from kan.data import moneyflow


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(moneyflow, "DATA_DIR", tmp_path)
    monkeypatch.setattr(moneyflow, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date",
        lambda: datetime.date(2026, 5, 29),
    )
    return tmp_path


def _raw():
    # _fetch_tushare_moneyflow 出口 (已 ts_code→symbol)
    return pd.DataFrame([
        {"symbol": "600519", "trade_date": "20260529",
         "net_amount": 5000.0, "buy_elg_amount": 3000.0, "buy_lg_amount": 2000.0},
        {"symbol": "000001", "trade_date": "20260529",
         "net_amount": -800.0, "buy_elg_amount": -500.0, "buy_lg_amount": -300.0},
    ])


class TestFetchMoneyflow:
    def test_fetch_and_normalize(self, _isolate, monkeypatch):
        monkeypatch.setattr("kan.data.moneyflow._fetch_tushare_moneyflow", lambda td: _raw())
        df = moneyflow.fetch_moneyflow(trade_date="20260101")  # 历史日永鲜
        assert set(df["symbol"]) == {"600519", "000001"}
        row = df[df["symbol"] == "600519"].iloc[0]
        assert row["net_amount"] == 5000.0
        assert row["trade_date"] == datetime.date(2026, 5, 29)  # 来自 raw items 内容
        assert row["_source"] == "tushare_moneyflow"

    def test_symbols_filter(self, _isolate, monkeypatch):
        monkeypatch.setattr("kan.data.moneyflow._fetch_tushare_moneyflow", lambda td: _raw())
        df = moneyflow.fetch_moneyflow(trade_date="20260101", symbols=["600519"])
        assert list(df["symbol"]) == ["600519"]

    def test_no_data_empty_schema(self, _isolate, monkeypatch):
        monkeypatch.setattr("kan.data.moneyflow._fetch_tushare_moneyflow", lambda td: None)
        df = moneyflow.fetch_moneyflow(trade_date="20230101")  # 早期无数据
        assert df.empty
        assert list(df.columns) == moneyflow.MONEYFLOW_COLUMNS

    def test_cache_reused_historical(self, _isolate, monkeypatch):
        calls: list[str] = []

        def _f(td):
            calls.append(td)
            return _raw()
        monkeypatch.setattr("kan.data.moneyflow._fetch_tushare_moneyflow", _f)
        moneyflow.fetch_moneyflow(trade_date="20260101")  # 历史日 < latest → 永鲜
        moneyflow.fetch_moneyflow(trade_date="20260101")
        assert calls == ["20260101"]

    def test_incompatible_current_cache_refetches(self, _isolate, monkeypatch):
        old = pd.DataFrame([
            {
                "symbol": "600519",
                "trade_date": datetime.date(2026, 5, 29),
                "net_amount": 1.0,
                "buy_elg_amount": 1.0,
                "buy_lg_amount": 0.0,
                "_source": "tushare_moneyflow_dc",
            }
        ])
        old.to_parquet(moneyflow._cache_path("20260529"), index=False)
        calls: list[str] = []

        def _f(td):
            calls.append(td)
            return _raw()

        monkeypatch.setattr("kan.data.moneyflow._fetch_tushare_moneyflow", _f)

        df = moneyflow.fetch_moneyflow(trade_date="20260529", symbols=["600519"])

        assert "20260529" in calls
        assert df.iloc[0]["net_amount"] == 5000.0
        assert "buy_md_amount" in df.columns

    def test_bad_trade_date_raises(self, _isolate):
        with pytest.raises(ValueError, match="非法交易日"):
            moneyflow.fetch_moneyflow(trade_date="2026-05-29")

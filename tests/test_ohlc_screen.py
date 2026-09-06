"""严格日线交集、复权基准、数据缺口与 CLI 的回归证据。"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.data import ohlc_history as data
from kan.data.tushare import TushareDataContractError
from kan.service import ohlc_screen_service as service


@pytest.fixture
def sample():
    dates = pd.bdate_range(end="2026-09-04", periods=11).strftime("%Y%m%d").tolist()
    raw = pd.DataFrame({
        "ts_code": ["600001.SH"] * 11, "trade_date": dates,
        "open": [8.0] * 8 + [6.3, 6.3, 6.5],
        "high": [10.0] * 8 + [6.5, 6.6, 6.8],
        "low": [7.0] * 8 + [5.0, 6.1, 6.3],
        "close": [8.0] * 8 + [6.2, 6.4, 6.6],
        "adj_factor": [1.0] * 11, "vol": [100.0] * 10 + [200.0],
        "amount": [65.0] * 11,
    })
    pool = pd.DataFrame([{"symbol": "600001", "name": "样本甲", "industry": "样本行业", "exchange": "SSE"}])
    request = service.OhlcScreenRequest(market="mainboard", as_of=date(2026, 9, 4), period=10,
                                      low_within=3, max_position=35, joint_up_days=2)
    return request, pool, data.adjust_history(raw, dates[-1]), dates


def evaluate(sample):
    return service.evaluate_ohlc_screen(*sample)


def test_evidence_and_coverage_are_reproducible(sample):
    result = evaluate(sample)
    assert result["coverage"]["matched"] == 1
    row = result["rows"][0]
    assert row["joint_up_days"] == 2
    assert row["position_pct"] == pytest.approx(32)
    assert row["from_low_pct"] == pytest.approx(32)
    assert row["low_date"] == sample[3][-3]
    assert row["volume_vs_prev5"] == 2
    assert row["amount_yuan"] == 65000
    assert len(row["daily_evidence"]) == 10
    assert row["daily_evidence"][-1]["previous_close"] == 6.4
    assert row["daily_evidence"][-1]["joint_up"] is True
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(("column", "value"), [("close", 6.4), ("open", 6.6), ("close", 6.35)])
def test_flat_doji_or_gap_down_breaks_joint_streak(sample, column, value):
    sample[2].loc[10, column] = value
    assert evaluate(sample)["rows"] == []


def test_positive_change_below_display_precision_still_counts(sample):
    sample[2].loc[10, ["open", "close", "low"]] = [6.4, 6.4001, 6.3]
    assert evaluate(sample)["rows"][0]["joint_up_days"] == 2


def test_exact_position_and_recent_low_boundaries(sample):
    sample[2].loc[10, "close"] = 6.75
    assert evaluate(sample)["coverage"]["matched"] == 1
    sample[2].loc[10, "close"] = 6.750001
    assert evaluate(sample)["coverage"]["matched"] == 0
    sample[2].loc[10, "close"] = 6.6
    sample[0].low_within = 2
    assert evaluate(sample)["coverage"]["matched"] == 0


def test_repeated_low_uses_latest_occurrence(sample):
    sample[2].loc[2, "low"] = 5
    row = evaluate(sample)["rows"][0]
    assert row["low_dates"] == [sample[3][2], sample[3][8]]
    assert row["low_age"] == 2


@pytest.mark.parametrize(("index", "reason"), [(10, "missing_as_of_bar"), (2, "incomplete_history")])
def test_missing_session_is_not_skipped(sample, index, reason):
    req, pool, panel, dates = sample
    result = evaluate((req, pool, panel.drop(index), dates))
    assert result["coverage"]["evaluated"] == 0
    assert result["excluded"][0]["reason"] == reason


@pytest.mark.parametrize(("column", "value"), [("adj_factor", np.nan), ("base_factor", 0),
                                                   ("high", 1), ("low", 20), ("vol", 0), ("close", np.inf)])
def test_invalid_data_cannot_enter_results(sample, column, value):
    sample[2].loc[3, column] = value
    assert evaluate(sample)["excluded"][0]["reason"] == "invalid_bar_or_factor"


def test_zero_range_and_capped_streak(sample):
    panel = sample[2]
    panel[["open", "high", "low", "close"]] = 5
    assert evaluate(sample)["excluded"][0]["reason"] == "zero_range"
    panel["close"] = np.arange(11) + 5
    panel["open"] = panel["close"] - 0.1
    panel["high"] = panel["close"] + 0.1
    panel["low"] = panel["close"] - 0.2
    sample[0].max_position = 100
    sample[0].low_within = 10
    assert evaluate(sample)["rows"][0]["streak_capped"]


def test_adjustment_uses_one_as_of_denominator_and_excludes_future():
    raw = pd.DataFrame({"ts_code": ["600001.SH"] * 3, "trade_date": ["20260902", "20260903", "20260904"],
                        "open": [10, 5, 5.2], "high": [10, 5, 5.2], "low": [10, 5, 5.2],
                        "close": [10, 5, 5.2], "vol": [100] * 3, "amount": [100] * 3,
                        "adj_factor": [1, 2, 2]})
    adjusted = data.adjust_history(raw, "20260904")
    assert adjusted["close"].tolist() == [5, 5, 5.2]
    assert adjusted["raw_close"].tolist() == [10, 5, 5.2]
    assert adjusted["base_factor"].tolist() == [2, 2, 2]


def test_request_and_calendar_validation(sample):
    with pytest.raises(ValueError, match="日历"):
        evaluate((*sample[:3], sample[3][:-1]))
    with pytest.raises(ValueError, match="窗口"):
        service.OhlcScreenRequest(**{**sample[0].model_dump(), "low_within": 11})


def test_query_errors_are_explicit(monkeypatch):
    monkeypatch.setattr(data, "_resolve_config", lambda: (None, "unused"))
    with pytest.raises(RuntimeError, match="凭证"):
        data._query("daily", {}, "ts_code")
    monkeypatch.setattr(data, "_resolve_config", lambda: ("test-token", "unused"))
    monkeypatch.setattr(data, "_post_tushare_api", lambda **kw: (None, None))
    with pytest.raises(RuntimeError, match="无数据"):
        data._query("daily", {}, "ts_code")
    monkeypatch.setattr(data, "_post_tushare_api", lambda **kw: ({"fields": [], "items": []}, None))
    with pytest.raises(TushareDataContractError):
        data._query("daily", {}, "ts_code")
    monkeypatch.setattr(data, "_post_tushare_api", lambda **kw: ({"fields": ["ts_code"], "items": [["600001.SH"]]}, None))
    assert len(data._query("daily", {}, "ts_code")) == 1


def test_universe_includes_st_and_excludes_other_markets(monkeypatch):
    rows = [{"ts_code": f"{600000+i}.SH", "symbol": str(600000+i), "name": "样本",
             "market": "主板", "exchange": "SSE", "list_status": "L"} for i in range(5000)]
    rows += [{"ts_code": "000001.SZ", "symbol": "000001", "name": "ST样本", "market": "主板", "exchange": "SZSE", "list_status": "L"},
             {"ts_code": "300001.SZ", "symbol": "300001", "name": "样本", "market": "创业板", "exchange": "SZSE", "list_status": "L"},
             {"ts_code": "900001.SH", "symbol": "900001", "name": "样本", "market": "主板", "exchange": "SSE", "list_status": "L"}]
    frame = pd.DataFrame(rows)
    monkeypatch.setattr(data, "_query", lambda *args: frame)
    pool = data.load_mainboard_universe()
    assert len(pool) == 5001 and "ST样本" in pool["name"].tolist()
    frame.loc[5000, "exchange"] = "SSE"
    with pytest.raises(TushareDataContractError, match="缺少"):
        data.load_mainboard_universe()
    frame.loc[1, "symbol"] = frame.loc[0, "symbol"]
    with pytest.raises(TushareDataContractError, match="重复"):
        data.load_mainboard_universe()


def test_calendar_requires_both_exchanges_and_no_missing_day(monkeypatch):
    def query(api, params, fields):
        days = pd.date_range(params["start_date"], params["end_date"])
        return pd.DataFrame({"exchange": params["exchange"], "cal_date": days.strftime("%Y%m%d"), "is_open": (days.weekday < 5).astype(int)})
    monkeypatch.setattr(data, "_query", query)
    assert data.load_session_dates(date(2026, 9, 4), 3) == ["20260902", "20260903", "20260904"]
    with pytest.raises(ValueError, match="交易日"):
        data.load_session_dates(date(2026, 9, 5), 3)
    monkeypatch.setattr(data, "_query", lambda *args: query(*args).iloc[1:])
    with pytest.raises(TushareDataContractError, match="缺日"):
        data.load_session_dates(date(2026, 9, 4), 3)


def test_raw_cache_refresh_and_missing_factor(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    calls = []
    def query(api, params, fields):
        calls.append(api)
        cols = fields.split(",")
        frame = pd.DataFrame(1.0, index=range(3000), columns=cols)
        frame["ts_code"] = [f"{600000+i}.SH" for i in range(3000)]
        frame["trade_date"] = params["trade_date"]
        if api == "adj_factor":
            frame.loc[0, "ts_code"] = "000001.SZ"
        return frame
    monkeypatch.setattr(data, "_query", query)
    panel = data.load_adjusted_history(["20260903", "20260904"])
    assert panel["adj_factor"].isna().sum() == 2
    assert len(calls) == 4
    data.load_adjusted_history(["20260903", "20260904"])
    assert len(calls) == 4
    data.load_adjusted_history(["20260904"], refresh=True)
    assert len(calls) == 6
    monkeypatch.setattr(data, "_query", lambda *args: query(*args).iloc[:2])
    with pytest.raises(TushareDataContractError, match="截面不完整"):
        data._daily_evidence("20260904", refresh=True)


def test_run_and_cli_use_same_service(sample, monkeypatch):
    req, pool, panel, dates = sample
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: req.as_of)
    monkeypatch.setattr(data, "load_mainboard_universe", lambda: pool)
    monkeypatch.setattr(data, "load_session_dates", lambda *a: dates)
    monkeypatch.setattr(data, "load_adjusted_history", lambda *a, **kw: panel)
    result = service.run_ohlc_screen(req)
    assert result["ok"] and result["sources"] and result["disclaimer"]
    runner = CliRunner()
    args = ["screen", "ohlc", "--market", "mainboard", "--as-of", "2026-09-04", "--period", "10",
            "--low-within", "3", "--max-position", "35", "--joint-up-days", "2"]
    output = runner.invoke(app, args)
    assert output.exit_code == 0, output.output
    assert json.loads(output.stdout)["rows"] == result["rows"]
    assert runner.invoke(app, ["screen", "ohlc"]).exit_code == 2
    args[3] = "unknown"
    failure = runner.invoke(app, args)
    assert failure.exit_code == 1
    assert json.loads(failure.stdout)["ok"] is False
    req.as_of = date(2026, 9, 5)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 9, 4))
    with pytest.raises(ValueError, match="晚于"):
        service.run_ohlc_screen(req)
    req.as_of = date(2026, 9, 3)
    with pytest.raises(ValueError, match="历史"):
        service.run_ohlc_screen(req)

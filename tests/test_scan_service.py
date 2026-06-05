"""Unit tests for the render-neutral scan service."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from kan.core.models import Board, BoardMeta, PeriodResult, StockScanResult
from kan.core.pipeline import DataCtx, Freshness
from kan.core.stock_set import CodeListSet
from kan.service.scan_service import ScanRequest, run_scan


def _scan_result(
    symbol: str,
    name: str,
    *,
    low_resonance: int = 0,
    high_resonance: int = 0,
    is_st: bool = False,
) -> StockScanResult:
    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=100.0,
        scan_date=date(2026, 5, 21),
        periods=[
            PeriodResult(
                period=30,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=low_resonance,
        high_resonance=high_resonance,
        is_st=is_st,
    )


def _freshness() -> Freshness:
    return Freshness(
        data_cutoff=date(2026, 5, 21),
        fetched_at="2026-05-21 15:30",
        expected_cutoff=date(2026, 5, 21),
        is_stale=False,
        phase="post",
    )


def test_run_scan_enriches_then_filters_signal_and_st(monkeypatch) -> None:
    raw_results = [
        _scan_result("600519", "Alpha", low_resonance=1),
        _scan_result("000001", "Beta", low_resonance=1, is_st=True),
        _scan_result("000002", "Gamma", low_resonance=0),
    ]
    stock_set = CodeListSet([
        ("600519", "Alpha"),
        ("000001", "Beta"),
        ("000002", "Gamma"),
    ])
    calls: dict[str, Any] = {}

    def fake_scan_batch(targets, *, mode, periods=None):
        raise AssertionError("run_data_pipeline should receive, not call, this function")

    def fake_run_data_pipeline(
        stock_set_arg, *, compute, mode, periods, fetch_days, show_progress, exit_on_resolve_error,
    ):
        calls["stock_set"] = stock_set_arg
        calls["compute"] = compute
        calls["mode"] = mode
        calls["periods"] = periods
        calls["fetch_days"] = fetch_days
        calls["show_progress"] = show_progress
        calls["exit_on_resolve_error"] = exit_on_resolve_error
        return DataCtx(
            targets=stock_set_arg.pairs(),
            meta=None,
            results=raw_results,
            freshness=_freshness(),
            source_name=stock_set_arg.name,
        )

    def fake_enrich_scan_rows(results, *, data_cutoff):
        calls["data_cutoff"] = data_cutoff
        return list(results)

    monkeypatch.setattr("kan.core.scanner.scan_batch", fake_scan_batch)
    monkeypatch.setattr("kan.core.pipeline.run_data_pipeline", fake_run_data_pipeline)
    monkeypatch.setattr("kan.core.enrich.enrich_scan_rows", fake_enrich_scan_rows)

    result = run_scan(ScanRequest(
        stock_set=stock_set,
        mode="low",
        periods=[20, 60],
        signal_only=True,
        exclude_st=True,
        show_progress=False,
    ))

    assert calls == {
        "stock_set": stock_set,
        "compute": fake_scan_batch,
        "mode": "low",
        "periods": [20, 60],
        "fetch_days": 60,
        "show_progress": False,
        "exit_on_resolve_error": False,
        "data_cutoff": date(2026, 5, 21),
    }
    assert result.all_results == raw_results
    assert [r.symbol for r in result.results] == ["600519"]
    assert result.meta is None


def test_run_scan_returns_board_index_result(monkeypatch) -> None:
    board = Board(code="801016", name="Food", level=2, size=2)
    board_meta = BoardMeta(
        board=board,
        index_kline=pd.DataFrame({"close": [100.0, 101.0]}),
        constituents=[("600519", "Alpha")],
        highlight=set(),
    )
    stock_set = CodeListSet([("600519", "Alpha")])

    def fake_run_data_pipeline(
        stock_set_arg, *, compute, mode, periods, fetch_days, show_progress, exit_on_resolve_error,
    ):
        assert exit_on_resolve_error is False
        assert fetch_days == 20
        return DataCtx(
            targets=stock_set_arg.pairs(),
            meta=board_meta,
            results=[_scan_result("600519", "Alpha")],
            freshness=_freshness(),
            source_name=stock_set_arg.name,
        )

    def fake_scan_stock(df, symbol, name, periods=None):
        assert df is board_meta.index_kline
        assert periods == [20]
        return _scan_result(symbol, name)

    monkeypatch.setattr("kan.core.pipeline.run_data_pipeline", fake_run_data_pipeline)
    monkeypatch.setattr(
        "kan.core.enrich.enrich_scan_rows",
        lambda results, *, data_cutoff: list(results),
    )
    monkeypatch.setattr("kan.core.scanner.scan_stock", fake_scan_stock)

    result = run_scan(ScanRequest(stock_set=stock_set, periods=[20]))

    assert result.board_index_result is not None
    assert result.board_index_result.symbol == "801016"
    assert result.board_index_result.name == "Food"
    assert result.meta is board_meta

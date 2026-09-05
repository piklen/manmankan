"""研究证据包的真实计算接缝、质量语义及多入口一致性。"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from kan.cli import app
from kan.core.models import (
    ChipMetrics,
    FundamentalMetrics,
    MoneyflowMetrics,
    SentimentMetrics,
    ShareholderMetrics,
    TechnicalMetrics,
    ValuationMetrics,
)
from kan.domain.research import ResearchDimension, ResearchRequest
from kan.mcp import server
from kan.service.research_service import build_research_bundle

DAY = date(2026, 9, 4)


@pytest.fixture
def research_io(monkeypatch):
    frame = pd.DataFrame({
        "date": pd.bdate_range(end=DAY, periods=361).date,
        "open": [100.0] * 361, "high": [110.0] * 361,
        "low": [90.0] * 361, "close": [100.0] * 361,
        "volume": [1000.0] * 361, "amount": [100000.0] * 361,
        "_source": ["fixture"] * 361,
    })
    fetch = Mock(return_value=({"600519": frame, "000858": frame.copy()}, {}))
    enrich = Mock(side_effect=lambda codes, **kwargs: {symbol: {
        "valuation": ValuationMetrics(
            trade_date=date(2026, 6, 1), pe_ttm=10, pb=2, total_mv=12345.5,
            source="fixture_valuation",
        ),
        "fundamentals": FundamentalMetrics(
            end_date=date(2026, 6, 30), roe=15, netprofit_yoy=0,
            or_yoy=-5, source="fixture_fundamentals",
        ),
        "technical": TechnicalMetrics(trade_date=DAY, close=100, atr=2, source="fixture_technical"),
        "moneyflow": MoneyflowMetrics(trade_date=DAY, net_amount=-2.5, source="fixture_moneyflow"),
        "sentiment": SentimentMetrics(trade_date=DAY, fd_amount=2000, open_times=2, limit="D", source="fixture_limit"),
        "chip": ChipMetrics(trade_date=DAY, winner_rate=5, source="fixture_chip"),
        "shareholder": ShareholderMetrics(
            holder_end_date=date(2026, 6, 30), top10_end_date=date(2026, 3, 31),
            holder_num=1234, north_hold_ratio=0, source="fixture_shareholder",
        ),
    } for symbol in codes})
    holdings = Mock(side_effect=AssertionError("研究不应读取个人账本"))
    monkeypatch.setattr("kan.data.fetcher.fetch_batch", fetch)
    monkeypatch.setattr("kan.data.fetcher.cache_age", lambda code: "2026-09-04 20:00")
    monkeypatch.setattr("kan.storage.watchlist.load_stock_names_cache", lambda **kwargs: {"600519": "样例股份"})
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: DAY)
    monkeypatch.setattr("kan.core.enrich.fetch_enrichments", enrich)
    monkeypatch.setattr("kan.data.financial_statements.fetch_financial_statements", Mock(return_value=({}, {})))
    monkeypatch.setattr("kan.storage.positions.load_positions", holdings)
    return fetch, enrich, holdings, frame


def _section(bundle, dimension):
    return next(item for item in bundle.evidence if item.dimension == dimension)


def test_research_help_shows_statement_dimensions_in_narrow_terminal():
    result = CliRunner().invoke(app, ["research", "--help"], env={"COLUMNS": "80", "TERM": "dumb", "NO_COLOR": "1"})
    assert result.exit_code == 0
    assert all(name in result.output for name in ("income", "balancesheet", "cashflow", "shareholder"))


def test_bundle_keeps_dimension_dates_units_and_resolvable_references(research_io):
    fetch, enrich, holdings, _ = research_io
    request = ResearchRequest(codes=["SH.600519"])
    first = build_research_bundle(request)
    second = build_research_bundle(request)
    assert first.ok and first.status == "partial"
    assert first.bundle_id == second.bundle_id
    assert first.subjects[0].evidence_refs == [item.evidence_ref for item in first.evidence]
    assert first.coverage.available_sections == 3
    assert _section(first, "market").freshness == "fresh"
    valuation = _section(first, "valuation")
    assert valuation.freshness == "stale" and valuation.data_date == date(2026, 6, 1)
    values = {item.field_id: item for item in valuation.facts}
    assert values["valuation.total_mv"].value == 123455000
    assert values["valuation.total_mv"].unit == "元"
    assert values["valuation.dv_ttm"].value is None
    financial = _section(first, "fundamentals")
    assert financial.report_period == date(2026, 6, 30)
    assert financial.announcement_date is None and financial.fetched_at is None
    assert financial.data_date is None and financial.freshness == "unknown"
    assert financial.facts[1].value == 0
    assert not financial.missing_fields
    assert "cash" not in first.model_dump_json()
    holdings.assert_not_called()
    assert enrich.call_args.kwargs["dimensions"] == {"valuation", "fundamentals"}
    from kan.data.fetcher import DEFAULT_KLINE_DAYS
    assert fetch.call_args.kwargs["days"] >= max(181, DEFAULT_KLINE_DAYS)


def test_all_dimensions_preserve_calculated_atr_and_sparse_event_type(research_io):
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=list(ResearchDimension)))
    facts = {fact.field_id: fact for item in bundle.evidence for fact in item.facts}
    assert facts["technical.atr_pct"].value == 2
    assert facts["moneyflow.net_amount"].value == -25000
    assert facts["sentiment.fd_amount"].value == 2000
    assert facts["sentiment.fd_amount"].unit == "源单位未核实"
    assert facts["sentiment.limit"].value == "D"
    assert facts["sentiment.open_times"].label == "开板/炸板次数"
    assert _section(bundle, "technical").adjustment == "qfq"
    shareholder = _section(bundle, "shareholder")
    assert shareholder.data_date is None and shareholder.report_period is None
    assert "holder_end_date=2026-06-30" in shareholder.notes
    assert "top10_end_date=2026-03-31" in shareholder.notes


def test_market_only_is_complete_without_fetching_any_metric(research_io):
    _, enrich, _, _ = research_io
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=["market"]))
    assert bundle.status == "complete" and bundle.coverage.missing_facts == 0
    assert len(bundle.evidence) == 1
    enrich.assert_not_called()


def test_requested_dimensions_do_not_enable_unrequested_metrics(research_io):
    _, enrich, _, _ = research_io
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=["market", "technical"]))
    assert [item.dimension.value for item in bundle.evidence] == ["market", "technical"]
    assert enrich.call_args.kwargs["dimensions"] == {"technical"}
    assert enrich.call_args.kwargs["require_source_dates"] is True


def test_financial_refresh_is_independent_of_market_and_shared_by_cli_mcp(research_io):
    fetch, enrich, holdings, _ = research_io
    enrich.side_effect = None
    enrich.return_value = {"600519": {"fundamentals": FundamentalMetrics(
        end_date=date(2026, 6, 30), ann_date=date(2026, 8, 28),
        fetched_at="2026-09-05T01:00:00+00:00", roe=15, netprofit_yoy=0, or_yoy=-5,
        source="fixture_fundamentals",
    )}}
    payload = {"codes": ["600519"], "dimensions": ["fundamentals"], "refresh": True}
    bundle = build_research_bundle(ResearchRequest.model_validate(payload))
    cli = CliRunner().invoke(app, ["research", "600519", "--dimensions", "fundamentals", "--refresh", "--format", "json"])
    mcp = server._handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kan_research", "arguments": payload}})
    assert cli.exit_code == 0 and not mcp["result"]["isError"]
    assert json.loads(cli.stdout)["evidence"] == bundle.model_dump(mode="json")["evidence"] == mcp["result"]["structuredContent"]["evidence"]
    assert bundle.status == "complete"
    financial = bundle.evidence[0]
    assert financial.report_period == date(2026, 6, 30)
    assert financial.announcement_date == date(2026, 8, 28)
    assert financial.fetched_at == "2026-09-05T01:00:00+00:00"
    assert financial.freshness == "fresh"
    assert enrich.call_args.args == (["600519"],)
    assert enrich.call_args.kwargs["dimensions"] == {"fundamentals"}
    assert enrich.call_args.kwargs["force"] is True
    fetch.assert_not_called()
    holdings.assert_not_called()


def test_unavailable_requested_metrics_are_reported_without_fetching_market(research_io):
    fetch, enrich, _, _ = research_io
    enrich.side_effect = None
    enrich.return_value = {}
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=["fundamentals"]))
    assert bundle.status == "unavailable" and not bundle.ok
    assert bundle.evidence[0].freshness == "unavailable"
    assert bundle.coverage.available_symbols == 0 and not bundle.subjects
    fetch.assert_not_called()


def test_core_enrichment_can_skip_valuation(monkeypatch):
    from kan.core.enrich_results import enrich_results
    from kan.core.models import StockScanResult
    from kan.data import metrics, technical

    valuation = Mock(side_effect=AssertionError("不应额外取估值"))
    tech = Mock(return_value=pd.DataFrame({"symbol": ["600519"], "trade_date": [DAY], "close": [100], "atr": [2]}))
    monkeypatch.setattr(metrics, "fetch_metrics", valuation)
    monkeypatch.setattr(technical, "fetch_technical", tech)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: DAY)
    result = enrich_results([StockScanResult(
        symbol="600519", name="样例", current_price=100, scan_date=DAY,
        periods=[], low_resonance=0, high_resonance=0,
    )], need_valuation=False, need_technical=True)
    assert result[0].valuation is None and result[0].technical is not None
    valuation.assert_not_called()
    tech.assert_called_once()


@pytest.mark.parametrize("raw_date", [None, pd.NaT, "invalid", "missing_column"])
def test_core_strict_dates_do_not_replace_missing_source_date(monkeypatch, raw_date):
    from kan.core.enrich_results import enrich_results
    from kan.core.models import StockScanResult

    row = {"symbol": "600519", "pe_ttm": 10, "_source": "fixture"}
    if raw_date != "missing_column":
        row["trade_date"] = raw_date
    monkeypatch.setattr("kan.data.metrics.fetch_metrics", lambda **kwargs: pd.DataFrame([row]))
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: DAY)
    base = StockScanResult(symbol="600519", name="样例", current_price=100, scan_date=DAY,
                           periods=[], low_resonance=0, high_resonance=0)
    result = enrich_results([base], require_source_dates=True)
    assert result[0].valuation is None


@pytest.mark.parametrize("age,expected", [("old", "stale"), ("future", "unknown"), ("source", "unknown"), ("short", "fresh")])
def test_market_quality_does_not_invent_freshness_or_zeroes(research_io, age, expected):
    fetch, _, _, frame = research_io
    frame = frame.copy()
    if age == "old":
        frame["date"] = pd.bdate_range(end="2026-06-01", periods=361).date
    elif age == "future":
        frame["date"] = pd.bdate_range(end="2026-09-07", periods=361).date
    elif age == "source":
        frame["_source"] = "unknown"
    else:
        frame = frame.tail(5)
    fetch.return_value = ({"600519": frame}, {})
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=["market"]))
    section = bundle.evidence[0]
    assert section.freshness == expected and bundle.status == "partial"
    if age == "short":
        assert all(item.value is None for item in section.facts if item.window)


def test_batch_partial_failure_retains_good_subject_and_mcp_error(research_io):
    fetch, _, _, frame = research_io
    fetch.return_value = ({"600519": frame}, {"000858": "SECRET_RAW_PROVIDER_ERROR"})
    payload = {"codes": ["000858", "600519"], "dimensions": ["market"]}
    bundle = build_research_bundle(ResearchRequest.model_validate(payload))
    assert bundle.status == "partial" and not bundle.ok
    assert bundle.coverage.requested_symbols == 2 and bundle.coverage.available_symbols == 1
    assert [item.symbol for item in bundle.subjects] == ["600519"]
    assert bundle.errors[0].symbol == "000858"
    assert "SECRET" not in bundle.model_dump_json()
    response = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "kan_research", "arguments": payload}})
    assert response["result"]["isError"] is True
    assert len(response["result"]["structuredContent"]["subjects"]) == 1
    cli = CliRunner().invoke(app, ["research", "000858", "600519", "--dimensions", "market", "--format", "json"])
    assert cli.exit_code == 1
    assert json.loads(cli.stdout)["status"] == "partial"


@pytest.mark.parametrize("failure", ["fetch", "invalid", "enrich", "names"])
def test_dependency_failure_is_structured_without_raw_exception(research_io, monkeypatch, failure):
    fetch, enrich, _, frame = research_io
    if failure == "fetch":
        fetch.side_effect = RuntimeError("SECRET_PROVIDER_ENDPOINT")
    elif failure == "invalid":
        fetch.return_value = ({"600519": frame.drop(columns=["close"])}, {})
    elif failure == "enrich":
        enrich.side_effect = RuntimeError("SECRET_PROVIDER_ENDPOINT")
    else:
        monkeypatch.setattr("kan.storage.watchlist.load_stock_names_cache", Mock(side_effect=ValueError("SECRET")))
    bundle = build_research_bundle(ResearchRequest(codes=["600519"]))
    assert "SECRET" not in bundle.model_dump_json()
    if failure in ("fetch", "invalid"):
        assert bundle.status == "partial" and not bundle.ok
        assert bundle.subjects[0].symbol == "600519"
        assert _section(bundle, "fundamentals").facts[0].value == 15
        assert bundle.coverage.available_sections == 2
    elif failure == "enrich":
        assert bundle.status == "partial" and not bundle.ok
        assert _section(bundle, "market").facts[0].value == 100
        assert _section(bundle, "fundamentals").freshness == "unavailable"
    else:
        assert bundle.subjects[0].name == "600519"


@pytest.mark.parametrize("payload", [
    {"codes": []}, {"codes": ["all"]}, {"codes": ["600519"] * 21},
    {"codes": ["600519"], "dimensions": ["market", "unknown"]},
    {"codes": ["600519"], "unexpected": True},
])
def test_invalid_requests_are_rejected_before_io(research_io, payload):
    fetch, _, _, _ = research_io
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate(payload)
    fetch.assert_not_called()


@pytest.mark.parametrize("fmt", ["json", "terminal"])
def test_cli_validation_and_human_output(research_io, fmt):
    invalid = CliRunner().invoke(app, ["research", "not-a-code", "--format", fmt])
    assert invalid.exit_code == 2
    if fmt == "json":
        assert json.loads(invalid.stdout)["error"]["code"] == "invalid_params"
    result = CliRunner().invoke(app, ["research", "600519", "--dimensions", "market,sentiment", "--format", fmt])
    assert result.exit_code == 0, result.output
    if fmt == "terminal":
        assert "研究证据包" in result.output and "样例股份" in result.output
        assert "缺失" in result.output and "evidence:" in result.output


def test_cli_python_mcp_and_discovery_share_one_bundle(research_io):
    from kan.api import build_research_bundle as public_build
    from kan.service.schema_service import build_schema_payload

    expected = public_build(ResearchRequest(codes=["600519"]))
    cli = CliRunner().invoke(app, ["research", "600519", "--format", "json"])
    assert cli.exit_code == 0, cli.output
    payload = json.loads(cli.stdout)
    mcp = server._handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "kan_research", "arguments": {"codes": ["600519"]}}})
    assert not mcp["result"]["isError"]
    assert payload["evidence"] == expected.model_dump(mode="json")["evidence"] == mcp["result"]["structuredContent"]["evidence"]
    tool = next(item for item in server._tool_list() if item["name"] == "kan_research")
    assert tool["inputSchema"]["additionalProperties"] is False
    assert tool["outputSchema"]["title"] == "ResearchBundle"
    commands = build_schema_payload(section="commands")["commands"]
    assert any(item["name"] == "research" for item in commands)

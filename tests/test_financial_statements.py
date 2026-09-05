"""三表从来源、缓存到 CLI/MCP 的研究主路径与报表口径。"""

from __future__ import annotations

import json
import os
from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.data import financial_statements
from kan.data.tushare import TushareApiError
from kan.domain.research import STATEMENT_FIELDS, ResearchDimension, ResearchRequest
from kan.mcp import server
from kan.service.research_service import build_research_bundle


def _response(api, ts_code):
    # 真实接口会返回同一期的重复版本，最新版本不一定排在最后。
    latest = {field: 45_000_000.0 for field, _ in STATEMENT_FIELDS[ResearchDimension(api)]}
    latest.update(ts_code=ts_code, end_date="20260630", ann_date="20260814",
                  f_ann_date="20260815", report_type="1", update_flag="1")
    older_version = dict(latest, update_flag="0", **{field: 10 for field, _ in STATEMENT_FIELDS[ResearchDimension(api)]})
    frame = pd.DataFrame([
        latest, older_version,
        dict(latest, end_date="20251231"),
        dict(latest, end_date="20260930", report_type="6"),
        dict(latest, end_date="20260930", ts_code="000001.SZ"),
    ])
    return {"fields": list(frame.columns), "items": frame.values.tolist()}, None


@pytest.fixture
def financial_io(tmp_path, monkeypatch):
    monkeypatch.setattr(financial_statements, "DATA_DIR", tmp_path)
    monkeypatch.setattr("kan.data.tushare._resolve_config", lambda: ("test-token", "https://data.example.invalid"))
    fetch = Mock(side_effect=lambda **kwargs: _response(kwargs["api_name"], kwargs["params"]["ts_code"]))
    monkeypatch.setattr("kan.data.tushare._post_tushare_api", fetch)
    monkeypatch.setattr("kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 9, 4))
    monkeypatch.setattr("kan.storage.watchlist.load_stock_names_cache", lambda **kwargs: {"600519": "样例股份"})
    market = Mock(side_effect=AssertionError("查财报不应获取行情"))
    metrics = Mock(side_effect=AssertionError("查三表不应额外获取其他指标"))
    monkeypatch.setattr("kan.data.fetcher.fetch_batch", market)
    monkeypatch.setattr("kan.core.enrich.fetch_enrichments", metrics)
    return fetch, market, metrics, tmp_path


def test_latest_consolidated_report_and_revision_are_selected(financial_io):
    fetch, market, metrics, _ = financial_io
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=["income"]))
    assert bundle.status == "complete" and bundle.ok
    section = bundle.evidence[0]
    assert section.report_period == date(2026, 6, 30)
    assert section.announcement_date == date(2026, 8, 14)
    assert section.actual_announcement_date == date(2026, 8, 15)
    assert section.report_type == "1" and section.period_basis == "year_to_date"
    assert section.freshness == "fresh" and section.fetched_at.endswith("+00:00")
    assert all(fact.value == 45_000_000 and fact.unit == "元" for fact in section.facts)
    assert fetch.call_args.kwargs["params"] == {"ts_code": "600519.SH", "report_type": "1"}
    assert {"ann_date", "f_ann_date", "end_date", "update_flag"} <= set(fetch.call_args.kwargs["fields"].split(","))
    assert fetch.call_count == 1
    market.assert_not_called()
    metrics.assert_not_called()


def test_three_statements_cli_python_and_mcp_use_same_facts(financial_io):
    fetch, _, _, _ = financial_io
    payload = {"codes": ["600519"], "dimensions": ["income", "balancesheet", "cashflow"]}
    expected = build_research_bundle(ResearchRequest.model_validate(payload))
    cli = CliRunner().invoke(app, ["research", "600519", "--dimensions", "income,balancesheet,cashflow", "--format", "json"])
    mcp = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "kan_research", "arguments": payload}})
    assert cli.exit_code == 0 and not mcp["result"]["isError"]
    assert json.loads(cli.stdout)["evidence"] == expected.model_dump(mode="json")["evidence"] == mcp["result"]["structuredContent"]["evidence"]
    assert expected.coverage.requested_sections == expected.coverage.fresh_sections == 3
    assert [section.period_basis for section in expected.evidence] == ["year_to_date", "period_end", "year_to_date"]
    assert len({section.evidence_ref for section in expected.evidence}) == 3
    assert fetch.call_count == 3  # 后续入口复用同一批缓存。
    human = CliRunner().invoke(app, ["research", "600519", "--dimensions", "cashflow"])
    assert human.exit_code == 0 and "现金流量表" in human.output
    assert "累计" in human.output and "实际公告日" in human.output
    assert "4,500" in human.output and "万元" in human.output
    assert expected.evidence[-1].facts[0].value == 45_000_000


def test_cache_expiry_and_refresh_do_not_pull_unrequested_statements(financial_io):
    fetch, _, _, path = financial_io
    request = ResearchRequest(codes=["600519"], dimensions=["cashflow"])
    first = build_research_bundle(request)
    cached = build_research_bundle(request)
    assert fetch.call_count == 1 and first.evidence == cached.evidence
    cache = path / "statement_cashflow_600519.parquet"
    old = cache.stat().st_mtime - 25 * 3600
    os.utime(cache, (old, old))
    build_research_bundle(request)
    assert fetch.call_count == 2
    cli = CliRunner().invoke(app, ["research", "600519", "--dimensions", "cashflow", "--refresh", "--format", "json"])
    assert cli.exit_code == 0 and fetch.call_count == 3
    assert {call.kwargs["api_name"] for call in fetch.call_args_list} == {"cashflow"}


def test_failure_of_one_statement_keeps_other_facts_and_reports_dimension(financial_io):
    fetch, _, _, _ = financial_io

    def source(**kwargs):
        if kwargs["api_name"] == "cashflow":
            return None, TushareApiError(code=40004, msg="SECRET_PROVIDER_ENDPOINT", api_name="cashflow")
        return _response(kwargs["api_name"], kwargs["params"]["ts_code"])

    fetch.side_effect = source
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=list(STATEMENT_FIELDS)))
    assert not bundle.ok and bundle.status == "partial"
    assert bundle.coverage.available_sections == 2 and bundle.coverage.available_symbols == 1
    assert bundle.errors[0].dimension == "cashflow" and bundle.errors[0].symbol == "600519"
    assert bundle.evidence[-1].freshness == "unavailable"
    assert "SECRET" not in bundle.model_dump_json()


def test_missing_dates_and_values_are_not_replaced_with_today_or_zero(financial_io):
    fetch, _, _, _ = financial_io

    def source(**kwargs):
        data, _ = _response(kwargs["api_name"], kwargs["params"]["ts_code"])
        frame = pd.DataFrame(data["items"], columns=data["fields"])
        frame["ann_date"] = None
        frame["f_ann_date"] = None
        frame["n_cashflow_act"] = 0
        frame["c_fr_sale_sg"] = None
        return {"fields": list(frame.columns), "items": frame.values.tolist()}, None

    fetch.side_effect = source
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=["cashflow"]))
    section = bundle.evidence[0]
    assert bundle.ok and bundle.status == "partial" and section.freshness == "unknown"
    assert section.announcement_date is None and section.actual_announcement_date is None
    values = {fact.field_id: fact.value for fact in section.facts}
    assert values["cashflow.n_cashflow_act"] == 0 and values["cashflow.c_fr_sale_sg"] is None
    assert section.missing_fields == ["cashflow.c_fr_sale_sg"]


def test_no_config_is_explicitly_unavailable_without_network(financial_io, monkeypatch):
    fetch, _, _, _ = financial_io
    monkeypatch.setattr("kan.data.tushare._resolve_config", lambda: (None, "https://data.example.invalid"))
    bundle = build_research_bundle(ResearchRequest(codes=["600519"], dimensions=["income"]))
    assert not bundle.ok and bundle.status == "unavailable"
    assert bundle.errors[0].dimension == "income"
    fetch.assert_not_called()

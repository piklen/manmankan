from __future__ import annotations

import io
import json
from datetime import date, timedelta

import pandas as pd
from typer.testing import CliRunner

from kan.cli import app


def test_examples_command_runs() -> None:
    result = CliRunner().invoke(app, ["examples"])
    assert result.exit_code == 0
    assert "kan scan --format json" in result.output
    assert "kan mcp install" in result.output


def test_fields_list_json_includes_moneyflow_fields() -> None:
    result = CliRunner().invoke(app, ["fields", "list", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "@moneyflow" in payload["presets"]
    paths = {row["path"] for row in payload["fields"]}
    assert "moneyflow.net_amount_5d" in paths
    assert "sentiment.fd_amount" in paths


def test_mcp_serve_lists_tools() -> None:
    from kan.mcp.server import serve

    inp = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    out = io.StringIO()
    serve(inp, out)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert lines[0]["result"]["serverInfo"]["name"] == "manmankan"
    tools = {t["name"] for t in lines[1]["result"]["tools"]}
    assert {"kan_scan", "kan_find", "kan_info", "kan_index"} <= tools


def test_mcp_install_dry_run_codex_uses_user_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["mcp", "install", "--client", "codex", "--dry-run"])
    assert result.exit_code == 0
    assert "mcp_servers.manmankan" in result.output
    assert not (tmp_path / ".codex" / "config.toml").exists()


def test_index_json_uses_tushare_index_daily_adapter(monkeypatch) -> None:
    from kan.data import index as index_data

    start = date(2026, 1, 1)
    df = pd.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(90)],
            "open": [100 + i for i in range(90)],
            "high": [101 + i for i in range(90)],
            "low": [99 + i for i in range(90)],
            "close": [100 + i for i in range(90)],
            "volume": [1000 + i for i in range(90)],
        }
    )
    monkeypatch.setattr(index_data, "fetch_index_daily", lambda *_args, **_kw: df)

    result = CliRunner().invoke(app, ["index", "sh", "--period", "60", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    row = payload["results"][0]
    assert row["code"] == "000001.SH"
    assert row["data_available"] is True
    assert row["position_pct"] is not None

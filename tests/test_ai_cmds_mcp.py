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


def test_mcp_install_dry_run_default_covers_supported_clients(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(app, ["mcp", "install", "--dry-run"])

    assert result.exit_code == 0
    for client in (
        "codex",
        "claude-code",
        "cursor",
        "windsurf",
        "cline",
        "gemini-cli",
        "opencode",
        "zed",
        "openclaw",
        "amazon-q",
    ):
        assert client in result.output
    assert not (tmp_path / ".cursor" / "mcp.json").exists()


def test_mcp_install_cursor_writes_mcp_servers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(app, ["mcp", "install", "--client", "cursor"])

    assert result.exit_code == 0
    config = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["manmankan"]
    assert server["env"]["KAN_NO_BOOT_BANNER"] == "1"
    assert server["command"]


def test_mcp_install_opencode_writes_local_mcp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    result = CliRunner().invoke(app, ["mcp", "install", "--client", "opencode"])

    assert result.exit_code == 0
    config = json.loads(
        (tmp_path / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    server = config["mcp"]["manmankan"]
    assert server["type"] == "local"
    assert server["command"]
    assert server["environment"]["KAN_NO_BOOT_BANNER"] == "1"
    assert server["enabled"] is True


def test_mcp_install_openclaw_writes_nested_mcp_servers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(app, ["mcp", "install", "--client", "openclaw"])

    assert result.exit_code == 0
    config = json.loads((tmp_path / ".openclaw" / "openclaw.json").read_text(encoding="utf-8"))
    assert "manmankan" in config["mcp"]["servers"]


def test_mcp_install_invalid_json_is_not_overwritten(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text("{invalid", encoding="utf-8")

    result = CliRunner().invoke(app, ["mcp", "install", "--client", "cursor"])

    assert result.exit_code == 0
    assert "failed" in result.output
    assert "invalid JSON" in result.output
    assert path.read_text(encoding="utf-8") == "{invalid"


def test_mcp_install_unknown_client_exits_2() -> None:
    result = CliRunner().invoke(app, ["mcp", "install", "--client", "unknown-client"])

    assert result.exit_code == 2
    assert "unknown-client" in result.output


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


def test_index_json_invalid_code_error_envelope() -> None:
    result = CliRunner().invoke(app, ["index", "missing", "--format", "json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["command"] == "index"
    assert payload["error"]["code"] == "invalid_index"
    assert "例:" in payload["error"]["hint"]

from __future__ import annotations

import http.client
import io
import json
import shlex
import threading
from datetime import date, timedelta

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.cli import app
from kan.core.find_registry import FIND_FIELD_PRESETS


def test_examples_command_runs() -> None:
    from kan.cli.ai_cmds import _EXAMPLES

    result = CliRunner().invoke(app, ["examples"])
    assert result.exit_code == 0
    assert "首次结构 smoke" in result.output
    assert "真实行情坐标 JSON" in result.output
    assert "┏" not in result.output
    commands = {row[1] for row in _EXAMPLES}
    assert "kan find --codes 600519,000858 --format json" in commands
    assert "kan scan --codes 600519,000858 --periods 5,20,60,180 --format json" in commands
    assert "kan mcp install --dry-run" in commands
    assert all("--all --pe lt:20 --roe" not in command for command in commands)
    assert "@fundamentals" in FIND_FIELD_PRESETS


def test_examples_command_json_is_machine_readable() -> None:
    result = CliRunner().invoke(app, ["examples", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "examples"
    assert payload["examples"][0]["command"] == "kan find --codes 600519,000858 --format json"
    assert all(item["command"].startswith("kan ") for item in payload["examples"])


def test_examples_command_markdown_is_copyable() -> None:
    result = CliRunner().invoke(app, ["examples", "--format", "md"])
    assert result.exit_code == 0
    assert result.output.startswith("# manmankan 工作流示例")
    assert "```bash\nkan find --codes 600519,000858 --format json\n```" in result.output
    assert "## 7. 预览 MCP 注册" in result.output


def test_example_find_commands_do_not_use_impossible_field_combinations() -> None:
    from kan.cli.ai_cmds import _EXAMPLES

    for _, command, _ in _EXAMPLES:
        parts = shlex.split(command)
        if parts[:2] == ["kan", "find"]:
            assert not ("--all" in parts and "--roe" in parts)
            for part in parts:
                if part.startswith("@"):
                    for field in part.replace(",", " ").split():
                        if field.startswith("@"):
                            assert field in FIND_FIELD_PRESETS


def test_fields_list_json_includes_moneyflow_fields() -> None:
    result = CliRunner().invoke(app, ["fields", "list", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "@moneyflow" in payload["presets"]
    assert "@fundamentals" in payload["presets"]
    paths = {row["path"] for row in payload["fields"]}
    assert "moneyflow.net_amount_5d" in paths
    assert "fundamentals.roe" in paths
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
    assert {"kan_scan", "kan_find", "kan_info", "kan_index", "kan_hold"} <= tools


def _start_mcp_http_server():
    from kan.mcp.server import make_http_server

    server = make_http_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _http_request(server, method: str, path: str, payload=None, *, origin: str | None = None):
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if origin:
        headers["Origin"] = origin
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read().decode("utf-8")
        return response.status, dict(response.getheaders()), data
    finally:
        conn.close()


def test_mcp_http_post_lists_tools() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, headers, body = _http_request(
            server,
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert headers["MCP-Protocol-Version"] == "2025-06-18"
    payload = json.loads(body)
    tools = {t["name"] for t in payload["result"]["tools"]}
    assert {"kan_scan", "kan_find", "kan_info", "kan_index", "kan_hold"} <= tools


def test_mcp_http_accepts_extra_allowed_origin() -> None:
    from kan.mcp.server import make_http_server

    server = make_http_server("127.0.0.1", 0, allow_origins=["https://agent.example"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _headers, body = _http_request(
            server,
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            origin="https://agent.example",
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert "tools" in json.loads(body)["result"]


def test_mcp_http_rejects_invalid_origin() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, _headers, body = _http_request(
            server,
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            origin="https://evil.example",
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 403
    payload = json.loads(body)
    assert payload["error"]["code"] == -32003
    assert "Origin" in payload["error"]["message"]


def test_mcp_http_post_unknown_path_returns_404() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, _headers, body = _http_request(
            server,
            "POST",
            "/missing",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 404
    assert json.loads(body)["error"]["code"] == -32004


def test_mcp_http_post_rejects_non_object_json() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, _headers, body = _http_request(server, "POST", "/mcp", [])
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 400
    payload = json.loads(body)
    assert payload["error"]["code"] == -32700
    assert "JSON-RPC body" in payload["error"]["message"]


def test_mcp_http_notification_returns_accepted() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, headers, body = _http_request(
            server,
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 202
    assert headers["Content-Length"] == "0"
    assert body == ""


def test_mcp_http_get_returns_405() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, headers, body = _http_request(server, "GET", "/mcp")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 405
    assert headers["Allow"] == "POST"
    assert json.loads(body)["error"]["code"] == -32005


def test_mcp_http_get_unknown_path_returns_404() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, _headers, body = _http_request(server, "GET", "/missing")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 404
    assert json.loads(body)["error"]["code"] == -32004


def test_mcp_http_get_rejects_invalid_origin() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, _headers, body = _http_request(
            server,
            "GET",
            "/mcp",
            origin="https://evil.example",
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 403
    assert json.loads(body)["error"]["code"] == -32003


def test_mcp_http_delete_returns_405() -> None:
    server, thread = _start_mcp_http_server()
    try:
        status, headers, body = _http_request(server, "DELETE", "/mcp")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 405
    assert headers["Allow"] == "POST"
    assert json.loads(body)["error"]["code"] == -32005


def test_mcp_http_cli_rejects_non_localhost_host() -> None:
    result = CliRunner().invoke(app, ["mcp", "http", "--host", "0.0.0.0"])

    assert result.exit_code == 2
    assert "默认只允许绑定" in result.output


def test_mcp_http_cli_starts_with_fake_server(monkeypatch) -> None:
    from kan.mcp import server

    captured = {}

    def fake_serve_http(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(server, "serve_http", fake_serve_http)

    result = CliRunner().invoke(app, ["mcp", "http", "--host", "localhost", "--port", "8765"])

    assert result.exit_code == 0
    assert captured["host"] == "localhost"
    assert captured["port"] == 8765
    assert "MCP HTTP server" in result.output


def test_mcp_http_helpers_cover_origin_and_path_edges() -> None:
    from kan.mcp import server

    with pytest.raises(ValueError, match="必须以 / 开头"):
        server.make_http_server("127.0.0.1", 0, path="mcp")
    assert server._normalize_endpoint_path("/mcp/") == "/mcp"
    assert server._origin_key("http://[::1") is None
    assert server._origin_key("file://agent.example") is None


def test_serve_http_closes_server(monkeypatch) -> None:
    from kan.mcp import server

    class FakeServer:
        served = False
        closed = False

        def serve_forever(self):
            self.served = True
            raise KeyboardInterrupt

        def server_close(self):
            self.closed = True

    fake = FakeServer()
    monkeypatch.setattr(server, "make_http_server", lambda *_args, **_kwargs: fake)

    with pytest.raises(KeyboardInterrupt):
        server.serve_http()

    assert fake.served is True
    assert fake.closed is True


def test_mcp_hold_builds_cli_args(monkeypatch) -> None:
    from kan.mcp import server

    captured = {}

    def fake_run(args):
        captured["args"] = args
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(server, "_run_kan", fake_run)

    result = server._kan_hold({
        "action": "add",
        "code": "600519",
        "cost": 1680,
        "shares": 100,
        "name": "贵州茅台",
    })

    assert result["exit_code"] == 0
    assert captured["args"] == [
        "hold", "add", "600519", "--cost", "1680", "--shares", "100", "--name", "贵州茅台",
    ]


def test_mcp_text_result_redacts_paths_and_tokens() -> None:
    from kan.mcp import server

    result = server._text_result({
        "exit_code": 1,
        "stdout": "path=/Users/alice/.kan/config.json?token=abcdefghi",
        "stderr": '{"Authorization":"Bearer secret-token"}',
    })

    text = result["content"][0]["text"]
    assert result["isError"] is True
    assert "/Users/alice" not in text
    assert "abcdefghi" not in text
    assert "secret-token" not in text
    assert "/Users/<user>" in text
    assert "token=<redacted>" in text
    assert '"Authorization":"<redacted>"' in text


def test_mcp_tool_exception_is_redacted(monkeypatch) -> None:
    from kan.mcp import server

    def raise_private_error(_payload):
        raise ValueError("读取失败: /Users/alice/.kan/config.json token abcdefghi")

    monkeypatch.setitem(
        server.TOOLS,
        "boom",
        server.ToolSpec(
            name="boom",
            description="test",
            input_schema={"type": "object", "properties": {}},
            handler=raise_private_error,
        ),
    )

    response = server._handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "boom", "arguments": {}},
    })

    message = response["error"]["message"]
    assert "/Users/alice" not in message
    assert "abcdefghi" not in message
    assert "/Users/<user>" in message
    assert "token <redacted>" in message


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


def test_callback_routes_subcommand_when_argv_len_one(monkeypatch) -> None:
    """回归: MCP server(kan-mcp 进程)的 sys.argv 恒为长度 1。

    旧 root callback 用 len(sys.argv)==1 误判成"无子命令" → 打印命令速记并
    raise Exit → 所有 in-process invoke(每个 MCP 工具)都塌缩成同一段 help。
    改用 ctx.invoked_subcommand 后,argv 长度 1 仍能正确路由到子命令。

    注: pytest 进程 argv 长度 >1 会掩盖此 bug,故必须 monkeypatch argv 复现。
    """
    import sys
    monkeypatch.setattr(sys, "argv", ["kan-mcp"])

    examples = CliRunner().invoke(app, ["examples"])
    assert examples.exit_code == 0
    assert "命令速记" not in examples.output
    assert "首次结构 smoke" in examples.output
    assert "真实行情坐标 JSON" in examples.output

    fields = CliRunner().invoke(app, ["fields", "list", "--format", "json"])
    assert fields.exit_code == 0
    assert "命令速记" not in fields.output
    assert "@moneyflow" in json.loads(fields.output)["presets"]


def test_run_kan_routes_subcommand_when_argv_len_one(monkeypatch) -> None:
    """回归(MCP 实际路径): _run_kan 经 CliRunner invoke,在 argv 长度 1 下
    仍须路由到目标子命令而非命令速记。覆盖所有 MCP 工具的公共入口。
    """
    import sys
    monkeypatch.setattr(sys, "argv", ["kan-mcp"])
    from kan.mcp.server import _run_kan

    r = _run_kan(["fields", "list", "--format", "json"])
    assert r["exit_code"] == 0
    assert "命令速记" not in r["stdout"]
    assert "@moneyflow" in json.loads(r["stdout"])["presets"]

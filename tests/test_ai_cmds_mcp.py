from __future__ import annotations

import io
import json
import shlex
from datetime import date, timedelta

import pandas as pd
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

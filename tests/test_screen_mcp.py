"""vNext Screen MCP tools 直接应用服务契约测试。"""

from __future__ import annotations

from kan.mcp import server


def _call(name: str, arguments: dict) -> dict:
    response = server._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response is not None
    return response["result"]


def test_tool_list_exposes_typed_screen_lifecycle() -> None:
    tools = {item["name"]: item for item in server._tool_list()}

    expected = {
        "kan_screen_parse",
        "kan_screen_plan",
        "kan_screen_run",
        "kan_screen_get",
        "kan_screen_explain",
    }
    assert expected <= set(tools)
    assert tools["kan_screen_run"]["inputSchema"]["type"] == "object"
    assert tools["kan_screen_run"]["outputSchema"]["title"] == "ScreenRun"


def test_screen_parse_returns_structured_spec_without_cli_invocation() -> None:
    result = _call(
        "kan_screen_parse",
        {"text": "600519 000858 180日位置<30 pe<35 排除ST"},
    )

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["executable"] is True
    assert structured["spec"]["universe"]["codes"] == ["600519", "000858"]
    assert [item["type"] for item in structured["spec"]["conditions"]] == [
        "pos",
        "pe",
    ]


def test_screen_plan_reports_unsupported_full_market_filter() -> None:
    result = _call(
        "kan_screen_plan",
        {
            "spec": {
                "name": "全市场 ROE",
                "universe": {"kind": "all"},
                "conditions": [{"type": "roe", "operator": "gt", "value": 10}],
            }
        },
    )

    structured = result["structuredContent"]
    assert structured["engine_path"] == "cross_section"
    assert structured["unsupported_filters"] == ["roe"]
    assert structured["executable"] is False

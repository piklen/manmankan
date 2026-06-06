"""stdio MCP server for manmankan CLI.

The server intentionally wraps existing CLI commands instead of duplicating
business logic. MCP clients get the same compliance text and data contracts as
terminal users.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from typer.testing import CliRunner

from kan import __version__

SERVER_NAME = "manmankan"
SERVER_VERSION = __version__
PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


def _run_kan(args: list[str]) -> dict[str, Any]:
    """Run kan CLI in-process and return captured output."""
    from kan.cli import app

    runner = CliRunner()
    result = runner.invoke(app, args, env={"KAN_NO_BOOT_BANNER": "1"})
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return list(value)
    raise ValueError("expected string list")


def _bool_flag(args: list[str], flag: str, value: Any) -> None:
    if value:
        args.append(flag)


def _optional_arg(args: list[str], flag: str, value: Any) -> None:
    if value is not None:
        args.extend([flag, str(value)])


def _kan_scan(payload: dict[str, Any]) -> dict[str, Any]:
    args = ["scan", "--format", str(payload.get("format") or "json")]
    codes = payload.get("codes")
    if codes is not None:
        if isinstance(codes, list):
            args.extend(["--codes", ",".join(str(x) for x in codes)])
        else:
            args.extend(["--codes", str(codes)])
    _optional_arg(args, "--industry", payload.get("industry"))
    _optional_arg(args, "--theme", payload.get("theme"))
    _optional_arg(args, "--hot", payload.get("hot"))
    _optional_arg(args, "--group", payload.get("group"))
    _bool_flag(args, "--high", payload.get("high"))
    _bool_flag(args, "--signal", payload.get("signal"))
    _bool_flag(args, "--exclude-st", payload.get("exclude_st"))
    _bool_flag(args, "--only-holdings", payload.get("only_holdings"))
    return _run_kan(args)


def _kan_find(payload: dict[str, Any]) -> dict[str, Any]:
    args = ["find", "--format", str(payload.get("format") or "json")]
    for key, flag in (
        ("codes", "--codes"),
        ("industry", "--industry"),
        ("theme", "--theme"),
        ("hot", "--hot"),
        ("group", "--group"),
        ("sort", "--sort"),
        ("fields", "--fields"),
    ):
        value = payload.get(key)
        if value is None:
            continue
        if key == "codes" and isinstance(value, list):
            value = ",".join(str(x) for x in value)
        if key == "fields" and isinstance(value, list):
            value = ",".join(str(x) for x in value)
        args.extend([flag, str(value)])
    for key, flag in (
        ("pos", "--pos"),
        ("gain", "--gain"),
        ("ma_bias", "--ma-bias"),
        ("moneyflow", "--moneyflow"),
        ("moneyflow_daily", "--moneyflow-daily"),
        ("moneyflow_days", "--moneyflow-days"),
        ("pe", "--pe"),
        ("pb", "--pb"),
        ("roe", "--roe"),
        ("rsi", "--rsi"),
        ("streak", "--streak"),
    ):
        for value in _str_list(payload.get(key)):
            args.extend([flag, value])
    for key, flag in (("limit", "--limit"), ("offset", "--offset")):
        _optional_arg(args, flag, payload.get(key))
    _bool_flag(args, "--all", payload.get("all"))
    _bool_flag(args, "--any", payload.get("any"))
    _bool_flag(args, "--compact", payload.get("compact"))
    _bool_flag(args, "--exclude-st", payload.get("exclude_st"))
    _bool_flag(args, "--only-holdings", payload.get("only_holdings"))
    return _run_kan(args)


def _kan_info(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code is required")
    args = ["info", code, "--format", str(payload.get("format") or "json")]
    return _run_kan(args)


def _kan_examples(_payload: dict[str, Any]) -> dict[str, Any]:
    return _run_kan(["examples"])


def _kan_fields(payload: dict[str, Any]) -> dict[str, Any]:
    args = ["fields", "list", "--format", str(payload.get("format") or "json")]
    return _run_kan(args)


def _kan_index(payload: dict[str, Any]) -> dict[str, Any]:
    args = ["index", "--format", str(payload.get("format") or "json")]
    for code in _str_list(payload.get("codes")):
        args.append(code)
    _optional_arg(args, "--period", payload.get("period"))
    _optional_arg(args, "--days", payload.get("days"))
    return _run_kan(args)


def _kan_hold(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "overview")
    if action in ("overview", "list"):
        args = ["hold", "--format", str(payload.get("format") or "json")]
        _bool_flag(args, "--no-refresh", payload.get("no_refresh"))
        _bool_flag(args, "--mask", payload.get("mask"))
        return _run_kan(args)
    if action == "add":
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code is required for hold add")
        args = ["hold", "add", code]
        _optional_arg(args, "--cost", payload.get("cost"))
        _optional_arg(args, "--shares", payload.get("shares"))
        _optional_arg(args, "--name", payload.get("name"))
        _bool_flag(args, "--add", payload.get("add"))
        return _run_kan(args)
    if action == "reduce":
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code is required for hold reduce")
        args = ["hold", "reduce", code]
        _optional_arg(args, "--shares", payload.get("shares"))
        return _run_kan(args)
    if action == "remove":
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code is required for hold remove")
        return _run_kan(["hold", "remove", code])
    if action == "cash":
        amount = payload.get("amount")
        if amount is None:
            raise ValueError("amount is required for hold cash")
        return _run_kan(["hold", "cash", str(amount)])
    raise ValueError(f"unsupported hold action: {action}")


TOOLS = {
    "kan_scan": ToolSpec(
        name="kan_scan",
        description="Scan watchlist, code pool, industry, theme, or hot list positions.",
        input_schema={
            "type": "object",
            "properties": {
                "codes": {"description": "Comma string or list of 6-digit stock codes"},
                "industry": {"type": "string"},
                "theme": {"type": "string"},
                "hot": {"type": "string", "enum": ["rank", "surge"]},
                "group": {"type": "string"},
                "high": {"type": "boolean"},
                "signal": {"type": "boolean"},
                "exclude_st": {"type": "boolean"},
                "only_holdings": {"type": "boolean"},
                "format": {"type": "string", "enum": ["json", "md"]},
            },
        },
        handler=_kan_scan,
    ),
    "kan_find": ToolSpec(
        name="kan_find",
        description="Run manmankan find DSL and return structured matches.",
        input_schema={
            "type": "object",
            "properties": {
                "codes": {"description": "Comma string or list of 6-digit stock codes"},
                "all": {"type": "boolean"},
                "pos": {"description": "List like 360:lt:10"},
                "gain": {"description": "List like 20:gt:5"},
                "ma_bias": {"description": "List like 20:lt:-3"},
                "moneyflow": {"description": "List like gt:10000"},
                "moneyflow_daily": {"description": "List like gt:1000"},
                "moneyflow_days": {"description": "List like gt:3"},
                "pe": {"description": "List like lt:20"},
                "pb": {"description": "List like lt:2"},
                "roe": {"description": "List like gt:10"},
                "rsi": {"description": "List like lt:30"},
                "streak": {"description": "List like up:gte:2"},
                "fields": {"description": "Field preset/path list, e.g. @core,@moneyflow"},
                "sort": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
                "compact": {"type": "boolean"},
                "any": {"type": "boolean"},
                "exclude_st": {"type": "boolean"},
                "only_holdings": {"type": "boolean"},
                "format": {"type": "string", "enum": ["json", "md"]},
            },
        },
        handler=_kan_find,
    ),
    "kan_info": ToolSpec(
        name="kan_info",
        description="Return one stock's position, valuation, moneyflow, and limit facts.",
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "md"]},
            },
            "required": ["code"],
        },
        handler=_kan_info,
    ),
    "kan_hold": ToolSpec(
        name="kan_hold",
        description="Record or query real holdings facts; outputs objective P/L and position context.",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["overview", "list", "add", "reduce", "remove", "cash"],
                },
                "code": {"type": "string"},
                "cost": {"type": "number"},
                "shares": {"type": "integer"},
                "name": {"type": "string"},
                "add": {"type": "boolean"},
                "amount": {"type": "number"},
                "no_refresh": {"type": "boolean"},
                "mask": {"type": "boolean"},
                "format": {"type": "string", "enum": ["json", "md"]},
            },
        },
        handler=_kan_hold,
    ),
    "kan_examples": ToolSpec(
        name="kan_examples",
        description="Show end-to-end manmankan workflows.",
        input_schema={"type": "object", "properties": {}},
        handler=_kan_examples,
    ),
    "kan_fields": ToolSpec(
        name="kan_fields",
        description="List find JSON field presets and field whitelist.",
        input_schema={
            "type": "object",
            "properties": {"format": {"type": "string", "enum": ["json", "md"]}},
        },
        handler=_kan_fields,
    ),
    "kan_index": ToolSpec(
        name="kan_index",
        description="Return objective index_daily position rows for common A-share indexes.",
        input_schema={
            "type": "object",
            "properties": {
                "codes": {"description": "Index code list, e.g. 000001.SH"},
                "period": {"type": "integer"},
                "days": {"type": "integer"},
                "format": {"type": "string", "enum": ["json", "md"]},
            },
        },
        handler=_kan_index,
    ),
}


def _tool_list() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "inputSchema": spec.input_schema,
        }
        for spec in TOOLS.values()
    ]


def _text_result(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("stdout") or ""
    if payload.get("stderr"):
        text += ("\n" if text else "") + str(payload["stderr"])
    return {
        "content": [{"type": "text", "text": text}],
        "isError": int(payload.get("exit_code") or 0) != 0,
    }


def _handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_list()}}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        spec = TOOLS.get(str(name))
        if spec is None:
            return _error(req_id, -32602, f"unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(req_id, -32602, "arguments must be an object")
        try:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _text_result(spec.handler(arguments)),
            }
        except Exception as e:
            return _error(req_id, -32603, f"{type(e).__name__}: {e}")
    return _error(req_id, -32601, f"method not found: {method}")


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def serve(infile=None, outfile=None) -> None:
    """Run newline-delimited JSON-RPC over stdio."""
    if infile is None:
        infile = sys.stdin
    if outfile is None:
        outfile = sys.stdout
    for line in infile:
        raw = line.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
            resp = _handle_request(req)
        except Exception as e:
            resp = _error(None, -32700, f"{type(e).__name__}: {e}")
        if resp is None:
            continue
        outfile.write(json.dumps(resp, ensure_ascii=False, separators=(",", ":")) + "\n")
        outfile.flush()


def main() -> None:
    serve()


if __name__ == "__main__":  # pragma: no cover
    main()

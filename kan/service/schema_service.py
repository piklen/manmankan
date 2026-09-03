"""Agent-facing schema discovery for manmankan."""
from __future__ import annotations

from typing import Any

from kan import __version__
from kan.core.find_registry import (
    DATA_DIMENSIONS,
    DIMENSION_DATA_FIELDS,
    DIMENSIONS_UNSUPPORTED_IN_ALL,
    FILTER_SPECS,
    FIND_FIELD_PRESETS,
    FIND_FIELD_SPECS,
    FIND_FILTER_HELP_GROUPS,
)
from kan.storage.export import FIND_SCHEMA_VERSION, HOLD_SCHEMA_VERSION, md_table

SCHEMA_DISCOVERY_VERSION = 1
VALID_SCHEMA_SECTIONS = ("all", "commands", "find", "mcp", "errors")


def build_schema_payload(*, section: str = "all", compact: bool = False) -> dict[str, Any]:
    """Build the machine-readable schema discovery payload."""
    normalized = section.strip().lower()
    if normalized not in VALID_SCHEMA_SECTIONS:
        valid = ", ".join(VALID_SCHEMA_SECTIONS)
        raise ValueError(f"不支持的 --section: {section} · 支持: {valid}")

    payload: dict[str, Any] = {
        "ok": True,
        "command": "schema",
        "schema_version": SCHEMA_DISCOVERY_VERSION,
        "package_version": __version__,
        "section": normalized,
        "compact": compact,
    }
    if normalized in ("all", "commands"):
        payload["commands"] = _command_schemas(compact=compact)
    if normalized in ("all", "find"):
        payload["find"] = _find_schema(compact=compact)
    if normalized in ("all", "mcp"):
        payload["mcp"] = _mcp_schema(compact=compact)
    if normalized in ("all", "errors"):
        payload["errors"] = _error_schema(compact=compact)
    return payload


def _command_schemas(*, compact: bool) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = [
        {
            "name": "schema",
            "purpose": "Discover CLI JSON contracts, find DSL, MCP tools, and error envelopes.",
            "formats": ["terminal", "md", "json"],
            "success_keys": ["ok", "command", "schema_version", "package_version", "section"],
            "examples": [
                "kan schema --format json",
                "kan schema --format json --section find --compact",
            ],
        },
        {
            "name": "examples",
            "purpose": "Show copyable end-to-end workflows.",
            "formats": ["terminal", "md", "json"],
            "success_keys": ["command", "examples"],
            "examples": ["kan examples --format json"],
        },
        {
            "name": "guide",
            "purpose": "Show copyable commands by user intent.",
            "formats": ["terminal"],
            "success_keys": [],
            "examples": ["kan guide --topic holdings"],
        },
        {
            "name": "daily",
            "purpose": "Summarize the default pool with factual daily context.",
            "formats": ["terminal", "md", "json"],
            "schema_version": "0.1",
            "success_keys": ["ok", "schema_version", "command", "pool", "facts"],
            "examples": ["kan daily --format json"],
        },
        {
            "name": "fields list",
            "purpose": "List kan find JSON field presets and exact field whitelist.",
            "formats": ["terminal", "md", "json"],
            "success_keys": ["command", "presets", "fields"],
            "examples": ["kan fields list --format json"],
        },
        {
            "name": "find",
            "purpose": "Run objective A-share stock filters and emit AI-consumable matches.",
            "formats": ["terminal", "md", "json"],
            "schema_version": FIND_SCHEMA_VERSION,
            "success_keys": [
                "ok", "schema_version", "command", "result_schema", "rule",
                "results", "data_availability", "stats",
            ],
            "examples": [
                "kan find --codes 600519,000858 --format json --dry-run",
                "kan find --codes 600519,000858 --fields @core,@valuation,@moneyflow,@technical --format json",
                "kan find --all --pe lt:20 --fields @core,@valuation --format json",
            ],
        },
        {
            "name": "scan",
            "purpose": "Scan watchlist/code pool/industry/theme positions across periods.",
            "formats": ["terminal", "md", "json"],
            "success_keys": [
                "ok", "schema_version", "command", "query_time", "stats", "results",
            ],
            "examples": ["kan scan --codes 600519,000858 --periods 5,20,60 --format json"],
        },
        {
            "name": "info",
            "purpose": "Return one stock's position, valuation, moneyflow, and limit facts.",
            "formats": ["terminal", "md", "json"],
            "success_keys": ["ok", "schema_version", "command", "query_time", "stats", "result"],
            "examples": ["kan info 600519 --format json"],
        },
        {
            "name": "range",
            "purpose": "Return one stock's historical intraday ranges and close outcomes after threshold touches.",
            "formats": ["terminal", "json"],
            "success_keys": [
                "ok", "schema_version", "command", "query_time", "study",
            ],
            "examples": [
                "kan range 600519 --format json",
                "kan range 600519 --down 3 --up 7 --format json",
            ],
        },
        {
            "name": "history",
            "purpose": "Return local scan snapshot history for one stock.",
            "formats": ["terminal", "md", "json"],
            "success_keys": ["ok", "schema_version", "command", "query_time", "stats", "series"],
            "examples": ["kan history 600519 --period 60 --format json"],
        },
        {
            "name": "board rank",
            "purpose": "Return objective board-level moneyflow, gain, or position rows.",
            "formats": ["terminal", "md", "json", "csv"],
            "success_keys": ["ok", "schema_version", "command", "query_time", "stats", "results"],
            "examples": ["kan board rank --kind industry --by moneyflow --format json"],
        },
        {
            "name": "board trend",
            "purpose": "Treat industry or concept indexes as OHLC series and return objective streak rows.",
            "formats": ["terminal", "md", "json", "csv"],
            "success_keys": [
                "ok", "schema_version", "command", "query_time", "kind", "mode",
                "filters", "data_cutoff", "stats", "data_availability", "results",
            ],
            "examples": [
                "kan board trend --kind industry --up 3 --format json",
                "kan board trend --kind theme --up 3 --candle --format json",
            ],
        },
        {
            "name": "hold",
            "purpose": "Query or maintain local holdings facts; supports masking private values.",
            "formats": ["terminal", "md", "json"],
            "schema_version": HOLD_SCHEMA_VERSION,
            "success_keys": ["ok", "command", "schema_version", "masked", "results", "account"],
            "examples": ["kan hold --format json --mask"],
        },
        {
            "name": "index",
            "purpose": "Return common A-share index_daily position rows.",
            "formats": ["terminal", "md", "json"],
            "success_keys": ["ok", "schema_version", "command", "query_time", "period", "results"],
            "examples": ["kan index sh --period 60 --format json"],
        },
        {
            "name": "mcp install",
            "purpose": "Preview or register the local MCP server in user-level AI client configs.",
            "formats": ["terminal", "md", "json"],
            "success_keys": [
                "ok", "command", "dry_run", "selected_clients", "server", "results", "summary",
            ],
            "examples": [
                "kan mcp install --dry-run --format json",
                "kan mcp install --client codex --dry-run --format json",
            ],
        },
    ]
    if not compact:
        return commands
    return [
        {
            "name": item["name"],
            "formats": item["formats"],
            "schema_version": item.get("schema_version"),
            "example": item["examples"][0],
        }
        for item in commands
    ]


def _find_schema(*, compact: bool) -> dict[str, Any]:
    filters = [
        {
            "name": name,
            "flag": spec.flag,
            "dimension": spec.dimension,
            "supports_all": spec.supports_all,
            **({} if compact else {
                "source": spec.source,
                "frequency": spec.frequency,
                "missing_semantics": spec.missing_semantics,
            }),
        }
        for name, spec in FILTER_SPECS.items()
    ]
    fields = [
        {
            "path": path,
            "dimension": spec.dimension,
            **({} if compact else {
                "needs_kline": spec.needs_kline,
                "needs_valuation_context": spec.needs_valuation_context,
            }),
        }
        for path, spec in FIND_FIELD_SPECS.items()
    ]
    dimensions = [
        {
            "name": name,
            "supports_all": name not in DIMENSIONS_UNSUPPORTED_IN_ALL,
            **({} if compact else {"availability_fields": list(DIMENSION_DATA_FIELDS[name])}),
        }
        for name in DATA_DIMENSIONS
    ]
    return {
        "schema_version": FIND_SCHEMA_VERSION,
        "condition_syntax": {
            "numeric": "<operator>:<value>, e.g. lt:20 or gt:1000",
            "windowed": "<window>:<operator>:<value>, e.g. 180:lt:30",
            "streak": "<direction>:<operator>:<days>, e.g. up:gte:2",
            "match_mode": "--any makes filters OR; default is AND",
        },
        "data_dimensions": dimensions,
        "filter_groups": [
            {
                "key": group.key,
                "title": group.title,
                "filters": list(group.filters),
                **({} if compact else {"note": group.note}),
            }
            for group in FIND_FILTER_HELP_GROUPS
        ],
        "filters": filters,
        "field_presets": {k: list(v) for k, v in FIND_FIELD_PRESETS.items()},
        "fields": fields,
        "result_schemas": ["full", "compact", "fields", "agent_summary", "delta"],
        "agent_options": {
            "dry_run": "--dry-run / --explain returns mode=query_plan without fetching data",
            "agent_summary": "--agent-summary returns field coverage, missing counts, distributions, and samples",
            "snapshot_delta": "--snapshot returns snapshot.id; --since <id> returns snapshot_delta",
        },
    }


def _mcp_schema(*, compact: bool) -> dict[str, Any]:
    from kan.mcp.server import PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION, TOOLS

    tools: list[dict[str, Any]] = []
    for spec in TOOLS.values():
        schema = spec.input_schema
        if compact:
            input_schema: dict[str, Any] = {
                "properties": sorted((schema.get("properties") or {}).keys()),
            }
            if schema.get("required"):
                input_schema["required"] = schema["required"]
        else:
            input_schema = schema
        output_schema = spec.output_schema or {"type": "object", "additionalProperties": True}
        tools.append({
            "name": spec.name,
            "description": spec.description,
            "inputSchema": input_schema,
            "outputSchema": (
                {"type": output_schema.get("type", "object")}
                if compact else output_schema
            ),
        })
    return {
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "protocol_version": PROTOCOL_VERSION,
        "tools": tools,
    }


def _error_schema(*, compact: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "json_error_envelope": {
            "ok": False,
            "command": "<command>",
            "error": {
                "code": "<machine_code>",
                "reason": "<machine_code>",
                "message": "<human_readable_message>",
                "hint": "<optional_next_step>",
                "next_command": "<optional_copyable_command>",
            },
            "disclaimer": "<present for stock-data commands>",
        },
        "exit_codes": [
            {"code": 0, "meaning": "success"},
            {"code": 1, "meaning": "runtime/data/config failure"},
            {"code": 2, "meaning": "invalid user input"},
        ],
    }
    if not compact:
        payload["notes"] = [
            "Prefer --format json for agent workflows.",
            "Treat missing metrics as data semantics, not investment advice.",
            "Read data_availability before interpreting empty find results.",
        ]
    return payload


def render_schema_markdown(payload: dict[str, Any]) -> str:
    """Render schema discovery as compact markdown."""
    lines = [
        "# manmankan Agent Schema",
        "",
        f"- schema_version: `{payload['schema_version']}`",
        f"- package_version: `{payload['package_version']}`",
        f"- section: `{payload['section']}`",
        "",
    ]
    if commands := payload.get("commands"):
        rows = [
            [
                f"`{item['name']}`",
                ", ".join(f"`{fmt}`" for fmt in item["formats"]),
                f"`{item.get('example') or item['examples'][0]}`",
            ]
            for item in commands
        ]
        lines.extend(["## Commands", "", md_table(["command", "formats", "example"], rows), ""])
    if find := payload.get("find"):
        lines.extend([
            "## Find",
            "",
            f"- find_schema_version: `{find['schema_version']}`",
            f"- filters: `{len(find['filters'])}`",
            f"- fields: `{len(find['fields'])}`",
            f"- presets: {', '.join(f'`{k}`' for k in find['field_presets'])}",
            "",
        ])
    if mcp := payload.get("mcp"):
        rows = [
            [f"`{tool['name']}`", str(tool["description"])]
            for tool in mcp["tools"]
        ]
        lines.extend(["## MCP Tools", "", md_table(["tool", "description"], rows), ""])
    if payload.get("errors"):
        lines.extend([
            "## Errors",
            "",
            "JSON mode uses `ok:false` with `error.code`, `error.message`, and optional `error.hint`.",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def render_schema_terminal(payload: dict[str, Any]) -> str:
    """Render schema discovery as plain terminal text."""
    lines = [
        "慢慢看 · Agent Schema",
        f"schema_version: {payload['schema_version']}",
        f"package_version: {payload['package_version']}",
        f"section: {payload['section']}",
        "",
    ]
    if commands := payload.get("commands"):
        lines.append("Commands:")
        for item in commands:
            example = item.get("example") or item["examples"][0]
            lines.append(f"  - {item['name']}: {example}")
        lines.append("")
    if find := payload.get("find"):
        lines.extend([
            "Find:",
            f"  schema_version: {find['schema_version']}",
            f"  filters: {len(find['filters'])}",
            f"  fields: {len(find['fields'])}",
            f"  presets: {', '.join(find['field_presets'])}",
            "",
        ])
    if mcp := payload.get("mcp"):
        lines.append("MCP tools:")
        for tool in mcp["tools"]:
            lines.append(f"  - {tool['name']}")
        lines.append("")
    if payload.get("errors"):
        lines.extend([
            "Errors:",
            "  JSON failures use ok:false + error.code/message/hint.",
            "",
        ])
    lines.append("Agent tip: use `kan schema --format json --section find --compact` for low-context discovery.")
    return "\n".join(lines)

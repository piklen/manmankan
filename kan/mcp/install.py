"""User-level MCP client registration helpers."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVER_NAME = "manmankan"
SERVER_ENV = {"KAN_NO_BOOT_BANNER": "1"}

DEFAULT_CLIENTS = (
    "codex",
    "claude-code",
    "claude-desktop",
    "cursor",
    "vscode",
    "windsurf",
    "cline",
    "gemini-cli",
    "opencode",
    "zed",
    "openclaw",
    "amazon-q",
)
SUPPORTED_CLIENTS = DEFAULT_CLIENTS


@dataclass(frozen=True)
class InstallResult:
    client: str
    target: str
    status: str
    detail: str


@dataclass(frozen=True)
class _JsonObject:
    data: dict[str, Any]
    error: str | None = None


def server_command() -> tuple[str, list[str]]:
    """Prefer installed console scripts; editable/dev fallback uses current interpreter."""
    if path := shutil.which("kan-mcp"):
        return path, []
    if path := shutil.which("kan"):
        return path, ["mcp", "serve"]
    return sys.executable, ["-m", "kan.mcp.server"]


def server_config() -> dict[str, Any]:
    command, args = server_command()
    return {"command": command, "args": args, "env": dict(SERVER_ENV)}


def _status(*, dry_run: bool, changed: bool) -> str:
    if not changed:
        return "unchanged"
    return "would-update" if dry_run else "updated"


def _failed(client: str, path: Path, detail: str) -> InstallResult:
    return InstallResult(client=client, target=str(path), status="failed", detail=detail)


def _read_json_object(path: Path) -> _JsonObject:
    if not path.exists():
        return _JsonObject({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return _JsonObject({}, f"invalid JSON: line {e.lineno}, column {e.colno}")
    if not isinstance(data, dict):
        return _JsonObject({}, "top-level JSON value is not an object")
    return _JsonObject(data)


def _write_json(path: Path, data: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_mapping(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | str:
    node: dict[str, Any] = data
    for key in keys:
        value = node.get(key)
        if value is None:
            value = {}
            node[key] = value
        if not isinstance(value, dict):
            return ".".join(keys) + " is not an object"
        node = value
    return node


def _upsert_named_config(
    client: str,
    path: Path,
    *,
    parent_keys: tuple[str, ...],
    config: dict[str, Any],
    detail: str,
    dry_run: bool,
) -> InstallResult:
    loaded = _read_json_object(path)
    if loaded.error is not None:
        return _failed(client, path, loaded.error)

    parent = _ensure_mapping(loaded.data, parent_keys)
    if isinstance(parent, str):
        return _failed(client, path, parent)

    changed = parent.get(SERVER_NAME) != config
    parent[SERVER_NAME] = config
    _write_json(path, loaded.data, dry_run=dry_run)
    return InstallResult(
        client=client,
        target=str(path),
        status=_status(dry_run=dry_run, changed=changed),
        detail=detail,
    )


def _upsert_mcp_servers(client: str, path: Path, *, dry_run: bool) -> InstallResult:
    return _upsert_named_config(
        client,
        path,
        parent_keys=("mcpServers",),
        config=server_config(),
        detail=f"mcpServers.{SERVER_NAME}",
        dry_run=dry_run,
    )


def _upsert_vscode(path: Path, *, dry_run: bool) -> InstallResult:
    return _upsert_named_config(
        "vscode",
        path,
        parent_keys=("servers",),
        config={"type": "stdio", **server_config()},
        detail=f"servers.{SERVER_NAME}",
        dry_run=dry_run,
    )


def _upsert_opencode(path: Path, *, dry_run: bool) -> InstallResult:
    command, args = server_command()
    return _upsert_named_config(
        "opencode",
        path,
        parent_keys=("mcp",),
        config={
            "type": "local",
            "command": [command, *args],
            "environment": dict(SERVER_ENV),
            "enabled": True,
        },
        detail=f"mcp.{SERVER_NAME}",
        dry_run=dry_run,
    )


def _upsert_openclaw(path: Path, *, dry_run: bool) -> InstallResult:
    return _upsert_named_config(
        "openclaw",
        path,
        parent_keys=("mcp", "servers"),
        config=server_config(),
        detail=f"mcp.servers.{SERVER_NAME}",
        dry_run=dry_run,
    )


def _upsert_zed(path: Path, *, dry_run: bool) -> InstallResult:
    return _upsert_named_config(
        "zed",
        path,
        parent_keys=("context_servers",),
        config=server_config(),
        detail=f"context_servers.{SERVER_NAME}",
        dry_run=dry_run,
    )


def _upsert_codex(path: Path, *, dry_run: bool) -> InstallResult:
    command, args = server_command()
    block = [
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {json.dumps(command, ensure_ascii=False)}",
        f"args = {json.dumps(args, ensure_ascii=False)}",
        'env = { KAN_NO_BOOT_BANNER = "1" }',
        "",
    ]
    new_block = "\n".join(block)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = f"[mcp_servers.{SERVER_NAME}]"
    if marker in old:
        lines = old.splitlines()
        out: list[str] = []
        idx = 0
        while idx < len(lines):
            if lines[idx].strip() == marker:
                out.extend(block[:-1])
                idx += 1
                while idx < len(lines) and not lines[idx].startswith("["):
                    idx += 1
                continue
            out.append(lines[idx])
            idx += 1
        updated = "\n".join(out).rstrip() + "\n"
    else:
        updated = old.rstrip() + ("\n\n" if old.strip() else "") + new_block
    changed = updated != old
    if not dry_run and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
    return InstallResult(
        client="codex",
        target=str(path),
        status=_status(dry_run=dry_run, changed=changed),
        detail=f"mcp_servers.{SERVER_NAME}",
    )


def _config_home(name: str) -> Path:
    home = Path.home()
    if platform.system().lower() == "windows":
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return base / name
    base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return base / name


def _claude_desktop_path() -> Path:
    system = platform.system().lower()
    home = Path.home()
    app_dir = "Cl" + "aude"
    if system == "darwin":
        return home / "Library" / "Application Support" / app_dir / "claude_desktop_config.json"
    if system == "windows":
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return base / app_dir / "claude_desktop_config.json"
    return home / ".config" / app_dir / "claude_desktop_config.json"


def _run_claude_cli(*, dry_run: bool) -> InstallResult | None:
    exe = shutil.which("claude")
    if exe is None:
        return None
    command, args = server_command()
    cli_args = [exe, "mcp", "add", SERVER_NAME, "--scope", "user", "--", command, *args]
    if dry_run:
        return InstallResult(
            client="claude-code",
            target="claude mcp add --scope user",
            status="would-run",
            detail=" ".join(cli_args),
        )
    try:
        completed = subprocess.run(
            cli_args,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as e:
        return InstallResult("claude-code", "claude mcp add --scope user", "failed", str(e))
    if completed.returncode == 0:
        return InstallResult("claude-code", "claude mcp add --scope user", "updated", "claude CLI")
    detail = (completed.stderr or completed.stdout).strip()
    return InstallResult("claude-code", "claude mcp add --scope user", "failed", detail[:300])


def _client_installers(home: Path) -> dict[str, Callable[[bool], InstallResult]]:
    return {
        "codex": lambda dry_run: _upsert_codex(home / ".codex" / "config.toml", dry_run=dry_run),
        "claude-code": lambda dry_run: _run_claude_cli(dry_run=dry_run)
        or _upsert_mcp_servers("claude-code", home / ".claude.json", dry_run=dry_run),
        "claude-desktop": lambda dry_run: _upsert_mcp_servers(
            "claude-desktop",
            _claude_desktop_path(),
            dry_run=dry_run,
        ),
        "cursor": lambda dry_run: _upsert_mcp_servers(
            "cursor",
            home / ".cursor" / "mcp.json",
            dry_run=dry_run,
        ),
        "vscode": lambda dry_run: _upsert_vscode(home / ".vscode" / "mcp.json", dry_run=dry_run),
        "windsurf": lambda dry_run: _upsert_mcp_servers(
            "windsurf",
            home / ".codeium" / "windsurf" / "mcp_config.json",
            dry_run=dry_run,
        ),
        "cline": lambda dry_run: _upsert_mcp_servers(
            "cline",
            home / ".cline" / "mcp.json",
            dry_run=dry_run,
        ),
        "gemini-cli": lambda dry_run: _upsert_mcp_servers(
            "gemini-cli",
            home / ".gemini" / "settings.json",
            dry_run=dry_run,
        ),
        "opencode": lambda dry_run: _upsert_opencode(
            _config_home("opencode") / "opencode.json",
            dry_run=dry_run,
        ),
        "zed": lambda dry_run: _upsert_zed(_config_home("zed") / "settings.json", dry_run=dry_run),
        "openclaw": lambda dry_run: _upsert_openclaw(
            home / ".openclaw" / "openclaw.json",
            dry_run=dry_run,
        ),
        "amazon-q": lambda dry_run: _upsert_mcp_servers(
            "amazon-q",
            home / ".aws" / "amazonq" / "agents" / "default.json",
            dry_run=dry_run,
        ),
    }


def _has_path_or_command(paths: list[Path], commands: list[str]) -> bool:
    return any(path.exists() for path in paths) or any(shutil.which(cmd) for cmd in commands)


def detect_clients() -> list[str]:
    """Detect likely installed MCP-capable clients without creating config files."""
    home = Path.home()
    checks: dict[str, bool] = {
        "codex": _has_path_or_command([home / ".codex"], ["codex"]),
        "claude-code": _has_path_or_command([home / ".claude.json"], ["claude"]),
        "claude-desktop": _claude_desktop_path().parent.exists(),
        "cursor": _has_path_or_command([home / ".cursor"], ["cursor", "cursor-agent"]),
        "vscode": _has_path_or_command([home / ".vscode"], ["code"]),
        "windsurf": _has_path_or_command([home / ".codeium" / "windsurf"], ["windsurf"]),
        "cline": _has_path_or_command([home / ".cline"], ["cline"]),
        "gemini-cli": _has_path_or_command([home / ".gemini"], ["gemini"]),
        "opencode": _has_path_or_command([_config_home("opencode")], ["opencode"]),
        "zed": _has_path_or_command([_config_home("zed")], ["zed"]),
        "openclaw": _has_path_or_command([home / ".openclaw"], ["openclaw"]),
        "amazon-q": _has_path_or_command([home / ".aws" / "amazonq"], ["qchat"]),
    }
    return [client for client in DEFAULT_CLIENTS if checks[client]]


def _dedupe_clients(clients: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for client in clients:
        if client in seen:
            continue
        seen.add(client)
        out.append(client)
    return out


def install_clients(clients: list[str] | None = None, *, dry_run: bool = False) -> list[InstallResult]:
    """Install manmankan MCP into supported user-level client configs."""
    selected = _dedupe_clients(clients or list(DEFAULT_CLIENTS))
    installers = _client_installers(Path.home())
    return [installers[client](dry_run) for client in selected]


__all__ = [
    "SUPPORTED_CLIENTS",
    "InstallResult",
    "detect_clients",
    "install_clients",
    "server_command",
    "server_config",
]

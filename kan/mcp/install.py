"""User-level MCP client registration helpers."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InstallResult:
    client: str
    target: str
    status: str
    detail: str


def server_command() -> tuple[str, list[str]]:
    """Prefer installed console scripts; editable/dev fallback uses current interpreter."""
    if path := shutil.which("kan-mcp"):
        return path, []
    if path := shutil.which("kan"):
        return path, ["mcp", "serve"]
    return sys.executable, ["-m", "kan.mcp.server"]


def server_config() -> dict[str, Any]:
    command, args = server_command()
    return {"command": command, "args": args, "env": {"KAN_NO_BOOT_BANNER": "1"}}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _upsert_mcp_servers(path: Path, *, dry_run: bool) -> InstallResult:
    data = _read_json(path)
    servers = data.setdefault("mcpServers", {})
    changed = servers.get("manmankan") != server_config()
    servers["manmankan"] = server_config()
    _write_json(path, data, dry_run=dry_run)
    return InstallResult(
        client=path.name,
        target=str(path),
        status="would-update" if dry_run and changed else ("updated" if changed else "unchanged"),
        detail="mcpServers.manmankan",
    )


def _upsert_vscode(path: Path, *, dry_run: bool) -> InstallResult:
    data = _read_json(path)
    servers = data.setdefault("servers", {})
    config = {"type": "stdio", **server_config()}
    changed = servers.get("manmankan") != config
    servers["manmankan"] = config
    _write_json(path, data, dry_run=dry_run)
    return InstallResult(
        client="vscode",
        target=str(path),
        status="would-update" if dry_run and changed else ("updated" if changed else "unchanged"),
        detail="servers.manmankan",
    )


def _upsert_codex(path: Path, *, dry_run: bool) -> InstallResult:
    command, args = server_command()
    block = [
        "[mcp_servers.manmankan]",
        f"command = {json.dumps(command, ensure_ascii=False)}",
        f"args = {json.dumps(args, ensure_ascii=False)}",
        'env = { KAN_NO_BOOT_BANNER = "1" }',
        "",
    ]
    new_block = "\n".join(block)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = "[mcp_servers.manmankan]"
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
        status="would-update" if dry_run and changed else ("updated" if changed else "unchanged"),
        detail="mcp_servers.manmankan",
    )


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
    cli_args = [exe, "mcp", "add", "manmankan", "--scope", "user", "--", command, *args]
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


def install_clients(clients: list[str] | None = None, *, dry_run: bool = False) -> list[InstallResult]:
    """Install manmankan MCP into supported user-level client configs."""
    selected = set(clients or ["codex", "claude-code", "claude-desktop", "cursor", "vscode"])
    home = Path.home()
    results: list[InstallResult] = []
    if "codex" in selected:
        results.append(_upsert_codex(home / ".codex" / "config.toml", dry_run=dry_run))
    if "claude-code" in selected:
        cli_result = _run_claude_cli(dry_run=dry_run)
        if cli_result is not None:
            results.append(cli_result)
        else:
            results.append(_upsert_mcp_servers(home / ".claude.json", dry_run=dry_run))
    if "claude-desktop" in selected:
        results.append(_upsert_mcp_servers(_claude_desktop_path(), dry_run=dry_run))
    if "cursor" in selected:
        results.append(_upsert_mcp_servers(home / ".cursor" / "mcp.json", dry_run=dry_run))
    if "vscode" in selected:
        results.append(_upsert_vscode(home / ".vscode" / "mcp.json", dry_run=dry_run))
    return results


SUPPORTED_CLIENTS = ("codex", "claude-code", "claude-desktop", "cursor", "vscode")


__all__ = ["SUPPORTED_CLIENTS", "InstallResult", "install_clients", "server_command", "server_config"]

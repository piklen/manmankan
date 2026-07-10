"""Local environment setup helpers for shell completion and MCP."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from kan.cli.helpers import _VALID_SHELLS, _detect_shell_fallback, _safe_error_msg
from kan.storage import config
from kan.storage.paths import BASE_DIR

SETUP_SKIP_DAYS = 7


@dataclass(frozen=True)
class CompletionInstallResult:
    shell: str
    target: str
    status: str
    detail: str


def completion_flag_path() -> Path:
    return BASE_DIR / ".completion_installed"


def completion_done() -> bool:
    cfg = config.load()
    return completion_flag_path().exists() or cfg.get("completion_setup") is True


def mcp_done() -> bool:
    return config.load().get("mcp_setup") is True


def mark_completion_setup(value: bool) -> None:
    if value:
        with contextlib.suppress(OSError):
            completion_flag_path().parent.mkdir(parents=True, exist_ok=True)
            completion_flag_path().touch()
    with contextlib.suppress(OSError):
        config.update(completion_setup=value)


def mark_mcp_setup(value: bool) -> None:
    with contextlib.suppress(OSError):
        config.update(mcp_setup=value)


def mark_setup_skip() -> None:
    with contextlib.suppress(OSError):
        config.update(env_setup_last_skip_date=date.today().isoformat())


def setup_skip_recent() -> bool:
    raw = config.load().get("env_setup_last_skip_date")
    if not isinstance(raw, str):
        return False
    try:
        last = date.fromisoformat(raw)
    except ValueError:
        return False
    return (date.today() - last).days < SETUP_SKIP_DAYS


def install_shell_completion(
    shell: str | None = None,
    *,
    dry_run: bool = False,
) -> CompletionInstallResult:
    selected_shell = shell or _detect_shell_fallback()
    if selected_shell is None:
        return CompletionInstallResult(
            shell="-",
            target="-",
            status="failed",
            detail="无法自动检测 shell",
        )
    if selected_shell not in _VALID_SHELLS:
        return CompletionInstallResult(
            shell=selected_shell,
            target="-",
            status="failed",
            detail=f"不支持的 shell: {selected_shell}",
        )
    if dry_run:
        return CompletionInstallResult(
            shell=selected_shell,
            target="typer completion install",
            status="would-update",
            detail="kan completion install",
        )

    try:
        from typer.completion import install

        installed_shell, path = install(shell=selected_shell, prog_name="kan")
    except Exception as e:
        return CompletionInstallResult(
            shell=selected_shell,
            target="-",
            status="failed",
            detail=_safe_error_msg(e),
        )

    mark_completion_setup(True)
    return CompletionInstallResult(
        shell=installed_shell,
        target=str(path),
        status="updated",
        detail="shell completion",
    )


def parse_mcp_client_selection(raw: str | None, detected: list[str]) -> list[str]:
    from kan.mcp.install import SUPPORTED_CLIENTS

    value = (raw or "auto").strip().lower()
    if value == "auto":
        return detected
    if value == "all":
        return list(SUPPORTED_CLIENTS)
    if value in ("none", "no", "n"):
        return []

    selected = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in selected if item not in SUPPORTED_CLIENTS]
    if unknown:
        raise ValueError(
            "不支持的 MCP client: "
            + ", ".join(unknown)
            + f" · 支持: {', '.join(SUPPORTED_CLIENTS)}"
        )
    return selected


def mcp_install_succeeded(statuses: list[str]) -> bool:
    return bool(statuses) and all(status not in {"failed"} for status in statuses)

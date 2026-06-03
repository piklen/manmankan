#!/usr/bin/env python3
"""Warn when locked runtime dependencies are near configured upper bounds.

This is intentionally warning-only. The hard gate is still `uv lock --check` and
`uv sync --frozen`; this script makes future upper-bound reviews visible in CI.
"""

from __future__ import annotations

import importlib.metadata as metadata
import re
import sys
import tomllib
from pathlib import Path

PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^,;\s]+)")
RANGE_RE = re.compile(r"^([A-Za-z0-9_.-]+).*?<([0-9]+(?:\.[0-9]+)*)")


def _version_parts(raw: str) -> tuple[int, ...]:
    numbers = []
    for part in raw.split("."):
        match = re.match(r"^(\d+)", part)
        if match is None:
            break
        numbers.append(int(match.group(1)))
    return tuple(numbers)


def _near_upper(installed: tuple[int, ...], upper: tuple[int, ...]) -> bool:
    if not installed or not upper:
        return False
    if len(upper) == 1:
        return installed[0] >= upper[0] - 1
    if installed[0] != upper[0]:
        return False
    installed_minor = installed[1] if len(installed) > 1 else 0
    upper_minor = upper[1]
    return installed_minor >= upper_minor - 1


def main() -> int:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]
    warnings: list[str] = []

    for requirement in dependencies:
        if PIN_RE.match(requirement):
            continue
        match = RANGE_RE.match(requirement)
        if match is None:
            warnings.append(f"{requirement}: missing explicit upper bound")
            continue
        name, upper_raw = match.groups()
        try:
            installed_raw = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
        installed = _version_parts(installed_raw)
        upper = _version_parts(upper_raw)
        if _near_upper(installed, upper):
            warnings.append(f"{name} {installed_raw} is near upper bound <{upper_raw}")

    for item in warnings:
        print(f"::warning title=Dependency upper-bound review::{item}")

    if not warnings:
        print("Dependency upper-bound review: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

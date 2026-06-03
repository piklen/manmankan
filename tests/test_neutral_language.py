from __future__ import annotations

from pathlib import Path


def test_user_facing_cli_avoids_judgmental_strength_wording() -> None:
    cli_text = "\n".join(path.read_text() for path in Path("kan/cli").glob("*_cmds.py"))

    assert "强势股" not in cli_text
    assert "量能平稳" in Path("kan/core/scanner.py").read_text()

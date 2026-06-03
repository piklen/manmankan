from __future__ import annotations

from pathlib import Path


def test_user_facing_cli_avoids_judgmental_strength_wording() -> None:
    cli_text = "\n".join(path.read_text() for path in Path("kan/cli").glob("*_cmds.py"))

    assert "强势股" not in cli_text
    assert "量能平稳" in Path("kan/core/scanner.py").read_text()


def test_public_code_and_docs_do_not_reintroduce_internal_stage_labels() -> None:
    banned = (
        "整合-",
        "地基-",
        "估值裸值不对外",
        "绝不出个股估值裸值",
        "PRD §",
        "spec §",
        "MVP",
    )
    paths = [
        *Path("kan").rglob("*.py"),
        *Path("docs").glob("*.md"),
    ]
    hits: list[str] = []
    for path in paths:
        text = path.read_text()
        for term in banned:
            if term in text:
                hits.append(f"{path}: {term}")

    assert hits == []

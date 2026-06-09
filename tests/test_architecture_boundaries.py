"""架构边界回归测试。"""
from __future__ import annotations

import ast
from pathlib import Path


def test_lower_layers_do_not_import_cli_helpers() -> None:
    """core/render/service 不应反向依赖 CLI helper。"""
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for package in ("core", "render", "service"):
        for path in (root / "kan" / package).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "kan.cli.helpers":
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "kan.cli.helpers":
                            offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == []

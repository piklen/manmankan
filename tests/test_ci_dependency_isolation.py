"""CI/offline test dependency isolation invariants."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_offline_tests_use_akshare_test_double():
    """Offline tests must not import the real akshare package."""
    akshare = sys.modules.get("akshare")
    assert akshare is not None
    assert getattr(akshare, "__manmankan_test_double__", False) is True


def test_feature_branches_use_pr_ci_without_duplicate_push_runs():
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    push_block = workflow.split("pull_request:", 1)[0]
    assert "branches: [main]" in push_block
    assert "'feature/**'" not in push_block
    assert "UV_TOOL_DIR=$scope/tools" in workflow

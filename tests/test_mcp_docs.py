from pathlib import Path

from kan.mcp.install import SUPPORTED_CLIENTS

ROOT = Path(__file__).resolve().parents[1]


def test_mcp_docs_list_all_supported_clients() -> None:
    text = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")

    for client in SUPPORTED_CLIENTS:
        assert f"`{client}`" in text


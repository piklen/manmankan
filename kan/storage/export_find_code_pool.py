"""Legacy code-pool JSON/markdown helpers.

Normal `kan find --codes ... --format json` now uses the full enrichment path.
These helpers stay exported for compatibility with direct imports and tests that
exercise the old runner fallback branch.
"""

from __future__ import annotations

from kan.core.find_registry import DATA_DIMENSIONS
from kan.storage.export_base import FIND_SCHEMA_VERSION, md_table


def _find_disclaimer_quote() -> str:
    from kan.render.base import FIND_DISCLAIMER_TEXT

    return "> " + FIND_DISCLAIMER_TEXT


def code_pool_payload(
    pairs: list[tuple[str, str]],
    *,
    query_time: str,
    pools: list[str],
    fields: tuple[str, ...] = (),
) -> dict:
    """Compatibility payload for an explicit code pool without enrichment."""
    from kan.render.base import FIND_DISCLAIMER_TEXT

    allowed = {"code", "name", "market_board", "permission_note"}
    selected = tuple(fields or ("code", "name"))
    unsupported = [f for f in selected if f not in allowed]
    if unsupported:
        raise ValueError(
            "外部代码池无 filter 取数只支持 code/name/market_board/permission_note 字段；"
            f"不支持: {', '.join(unsupported)}"
        )

    def _row(code: str, name: str) -> dict:
        from kan.core.retail_facts import market_board, permission_note

        source = {
            "code": code,
            "name": name.replace(" ", ""),
            "market_board": market_board(code),
            "permission_note": permission_note(code),
        }
        return {k: source[k] for k in selected}

    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "mode": "code_pool",
        "result_schema": "fields" if fields else "code_pool",
        "query_time": query_time,
        "rule": {"pools": pools, "filters": []},
        "results": [_row(code, name) for code, name in pairs],
        "disclaimer": FIND_DISCLAIMER_TEXT,
        "data_availability": {
            dim: {"requested": False, "available": False, "coverage": 0.0}
            for dim in DATA_DIMENSIONS
        },
        "stats": {
            "pool_size": len(pairs),
            "matched": len(pairs),
            "shown": len(pairs),
            "data_cutoff": None,
            "stale": False,
        },
    }


def code_pool_markdown(pairs: list[tuple[str, str]], *, title: str) -> str:
    """Markdown for an explicit code pool without filters."""
    rows = [[name.replace(" ", ""), code] for code, name in pairs]
    table = md_table(["股票", "代码"], rows) if rows else "无代码"
    return f"# {title}\n\n{table}\n\n{_find_disclaimer_quote()}"


__all__ = ["code_pool_markdown", "code_pool_payload"]
